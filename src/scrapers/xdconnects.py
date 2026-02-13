from __future__ import annotations

import asyncio
import json
import os
import re
from urllib.parse import urlparse, quote, urljoin, parse_qs

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from .base import Scraper
from ..models import ProductDraft
from ..utils import clean_text, domain_of, ensure_sku


def _meta_content(soup: BeautifulSoup, selectors: list[str]) -> str:
    for sel in selectors:
        el = soup.select_one(sel)
        if el and el.get("content") and clean_text(el.get("content")):
            return clean_text(el.get("content"))
    return ""


def _iter_jsonld_objects(soup: BeautifulSoup):
    for sc in soup.select('script[type="application/ld+json"]'):
        raw = (sc.string or sc.get_text() or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        if isinstance(data, dict):
            yield data
        elif isinstance(data, list):
            for obj in data:
                if isinstance(obj, dict):
                    yield obj


def _find_product_jsonld(soup: BeautifulSoup) -> dict | None:
    for obj in _iter_jsonld_objects(soup):
        t = obj.get("@type") or obj.get("type")
        if t == "Product" or (isinstance(t, list) and "Product" in t):
            return obj
        graph = obj.get("@graph")
        if isinstance(graph, list):
            for node in graph:
                if isinstance(node, dict):
                    nt = node.get("@type")
                    if nt == "Product" or (isinstance(nt, list) and "Product" in nt):
                        return node
    return None


def _jsonld_get_images(prod: dict) -> list[str]:
    imgs = prod.get("image")
    if isinstance(imgs, str):
        return [imgs]
    if isinstance(imgs, list):
        return [x for x in imgs if isinstance(x, str)]
    return []


def _jsonld_get_price(prod: dict) -> float | None:
    offers = prod.get("offers")
    if isinstance(offers, dict):
        p = offers.get("price")
        if p is None:
            return None
        try:
            return float(str(p).replace(",", "."))
        except Exception:
            return None
    if isinstance(offers, list):
        for o in offers:
            if isinstance(o, dict) and o.get("price") is not None:
                try:
                    return float(str(o.get("price")).replace(",", "."))
                except Exception:
                    continue
    return None


def _extract_images_dom(soup: BeautifulSoup, base_url: str) -> list[str]:
    imgs = []
    for img in soup.select("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-original")
        if not src:
            continue
        src = urljoin(base_url, src)
        if src.lower().startswith("data:"):
            continue
        if any(x in src.lower() for x in ["logo", "icon", "sprite"]):
            continue
        imgs.append(src)
    seen = set()
    out = []
    for u in imgs:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:16]


def _extract_desc(soup: BeautifulSoup) -> str:
    ogd = _meta_content(
        soup,
        [
            'meta[property="og:description"]',
            'meta[name="description"]',
            'meta[name="twitter:description"]',
        ],
    )
    if ogd and len(ogd) > 40:
        return f"<p>{ogd}</p>"

    for sel in [
        ".product-description",
        '[itemprop="description"]',
        "#description",
        ".description",
    ]:
        el = soup.select_one(sel)
        if el and len(el.get_text(strip=True)) > 50:
            return str(el)
    return ""


def _title_from_url(url: str) -> str:
    p = urlparse(url)
    slug = p.path.rstrip("/").split("/")[-1]
    # remove query variantId etc
    slug = re.sub(r"[-_]?p\d+\.\d+$", "", slug, flags=re.I)
    slug = slug.replace("-", " ").replace("_", " ")
    slug = re.sub(r"\s+", " ", slug).strip()
    if not slug:
        return "Produs"
    # Title case but keep acronyms
    return " ".join([w.upper() if w.isupper() and len(w) <= 4 else w.capitalize() for w in slug.split(" ")])


async def _auto_scroll(page, steps: int = 10, step_px: int = 900, wait_ms: int = 200):
    for _ in range(steps):
        await page.mouse.wheel(0, step_px)
        await page.wait_for_timeout(wait_ms)


async def _accept_cookies_if_any(page):
    candidates = [
        'button:has-text("Accept")',
        'button:has-text("I agree")',
        'button:has-text("Allow all")',
        'button:has-text("Accept all")',
        'button:has-text("OK")',
        'button:has-text("Got it")',
    ]
    for sel in candidates:
        try:
            btn = await page.query_selector(sel)
            if btn:
                await btn.click()
                await page.wait_for_timeout(300)
                return
        except Exception:
            continue


async def _fetch_with_login(url: str, email: str, password: str, wait_ms: int = 1500) -> tuple[str, str]:
    p = urlparse(url)
    locale = "en-gb"
    parts = [x for x in p.path.split("/") if x]
    if parts and re.fullmatch(r"[a-z]{2}-[a-z]{2}", parts[0], re.IGNORECASE):
        locale = parts[0].lower()

    login_url = f"https://www.xdconnects.com/{locale}/profile/login?returnurl={quote(p.path)}"

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="ro-RO",
            extra_http_headers={"Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7"},
            viewport={"width": 1366, "height": 768},
        )
        page = await context.new_page()
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")

        await page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(700)
        await _accept_cookies_if_any(page)

        await page.fill('input[type="email"], input[name*="email" i], input[id*="email" i]', email)
        await page.fill('input[type="password"], input[name*="pass" i], input[id*="pass" i]', password)

        try:
            await page.click(
                'button[type="submit"], input[type="submit"], button:has-text("Login"), button:has-text("Log in")',
                timeout=8000,
            )
        except Exception:
            await page.keyboard.press("Enter")

        await page.wait_for_timeout(1200)
        await _accept_cookies_if_any(page)

        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(wait_ms)
        await _auto_scroll(page, steps=12, step_px=900, wait_ms=200)
        await page.wait_for_timeout(600)

        html = await page.content()
        await context.close()
        await browser.close()
        return html, f"xd_login=YES locale={locale}"


class XDConnectsScraper(Scraper):
    def can_handle(self, url: str) -> bool:
        return domain_of(url).endswith("xdconnects.com")

    def parse(self, url: str) -> ProductDraft:
        email = os.getenv("XD_USER", "").strip()
        password = os.getenv("XD_PASS", "").strip()

        if not email or not password:
            return ProductDraft(
                source_url=url,
                domain=domain_of(url),
                sku=ensure_sku(url, None),
                title="(XDConnects) Lipsesc credențialele",
                description_html="<p>Completează XD_USER / XD_PASS în Streamlit Secrets.</p>",
                short_description="Completează XD_USER / XD_PASS în Streamlit Secrets.",
                images=[],
                price=None,
                currency="RON",
                needs_translation=False,
                notes="xd_login=NO (missing creds)",
            )

        html, login_note = asyncio.run(_fetch_with_login(url, email, password, wait_ms=1600))
        soup = BeautifulSoup(html, "lxml")

        page_title = clean_text(soup.title.get_text()) if soup.title else ""
        if "403" in page_title.lower() or "access not allowed" in page_title.lower():
            return ProductDraft(
                source_url=url,
                domain=domain_of(url),
                sku=ensure_sku(url, None),
                title=page_title or "Error 403",
                description_html="<p>XDConnects blochează accesul (403). Chiar și după login. Poate fi blocare pe IP/datacenter.</p>",
                short_description="XDConnects blochează accesul (403).",
                images=[],
                price=None,
                currency="RON",
                needs_translation=False,
                notes=f"parsed_with=playwright | {login_note} | blocked=403",
            )

        prod = _find_product_jsonld(soup)

        title = None
        sku = None
        price = None
        images: list[str] = []

        if prod:
            title = clean_text(str(prod.get("name") or "")) or None
            sku = clean_text(str(prod.get("sku") or "")) or None
            price = _jsonld_get_price(prod)
            images = _jsonld_get_images(prod)

        # Strong DOM fallbacks for title (XDConnects often has H1)
        if not title:
            title = (
                _meta_content(soup, ['meta[property="og:title"]', 'meta[name="twitter:title"]'])
                or clean_text((soup.select_one("h1") or soup.select_one(".page-title") or soup.select_one(".product-title") or soup.select_one(".product__title") or soup.select_one('[data-testid*="title" i]') or soup.select_one('[class*="title" i]')).get_text())
                if (soup.select_one("h1") or soup.select_one(".page-title") or soup.select_one(".product-title") or soup.select_one(".product__title") or soup.select_one('[data-testid*="title" i]') or soup.select_one('[class*="title" i]')) else None
            )

        if not title:
            title = _title_from_url(url)

        desc_html = _extract_desc(soup) or "<p></p>"

        if not images:
            images = _extract_images_dom(soup, url)

        # Extra hint: variantId from query (optional)
        q = parse_qs(urlparse(url).query)
        variant = q.get("variantId", [""])[0]

        notes_extra = f"variantId={variant}" if variant else ""

        return ProductDraft(
            source_url=url,
            domain=domain_of(url),
            sku=ensure_sku(url, sku),
            title=title,
            description_html=desc_html,
            short_description=clean_text(BeautifulSoup(desc_html, "lxml").get_text())[:200],
            images=images,
            price=price,
            currency="RON",
            needs_translation=False,
            notes=f"parsed_with=playwright | {login_note} | xd_scraper=v1.2 | {notes_extra}".strip(),
        )
