from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from .base import Scraper
from ..models import ProductDraft
from ..utils import clean_text, domain_of, ensure_sku


LOGIN_URL = "https://psiproductfinder.de/login"


def _pw_writable_browsers_path() -> str:
    home = os.path.expanduser("~")
    return os.path.join(home, ".cache", "ms-playwright")


def _ensure_playwright_chromium_installed() -> None:
    """Ensure Playwright Chromium exists (Streamlit Cloud safe path)."""
    if os.environ.get("PW_CHROMIUM_READY") == "1":
        return
    browsers_path = _pw_writable_browsers_path()
    os.makedirs(browsers_path, exist_ok=True)
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = browsers_path

    proc = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"playwright_install_failed (code={proc.returncode}):\n{proc.stdout}")
    os.environ["PW_CHROMIUM_READY"] = "1"


def _meta(soup: BeautifulSoup, key: str) -> str:
    el = soup.select_one(f'meta[property="{key}"]') or soup.select_one(f'meta[name="{key}"]')
    if el and el.get("content"):
        return clean_text(el.get("content"))
    return ""


def _extract_images(soup: BeautifulSoup, base_url: str) -> list[str]:
    urls: list[str] = []
    for m in soup.select('meta[property="og:image"], meta[property="og:image:secure_url"], meta[name="twitter:image"]'):
        c = m.get("content")
        if c:
            urls.append(urljoin(base_url, c))

    for img in soup.select("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-original") or img.get("data-lazy")
        if not src:
            srcset = img.get("srcset") or img.get("data-srcset")
            if srcset:
                src = srcset.split(",")[-1].strip().split(" ")[0]
        if not src:
            continue
        src = urljoin(base_url, src)
        if src.lower().startswith("data:"):
            continue
        if any(x in src.lower() for x in ["logo", "icon", "sprite"]):
            continue
        urls.append(src)

    seen = set()
    out = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:12]


def _find_first(obj: Any, keys: set[str]) -> str | None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys and isinstance(v, str) and clean_text(v):
                return clean_text(v)
        for v in obj.values():
            r = _find_first(v, keys)
            if r:
                return r
    elif isinstance(obj, list):
        for it in obj:
            r = _find_first(it, keys)
            if r:
                return r
    return None


def _parse_next_data(soup: BeautifulSoup) -> dict | None:
    sc = soup.select_one("script#__NEXT_DATA__")
    if not sc:
        return None
    raw = (sc.string or sc.get_text() or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


_UNWANTED_RE = re.compile(
    r"\b(previous|next|angebot\s+anfragen|kontakt|anmelden|login|preise?|produktfinder|men[üu]|suche|produkt\s*details|konfigurieren|warenkorb)\b",
    flags=re.I,
)


def _clean_paragraphs(paras: list[str]) -> list[str]:
    out: list[str] = []
    for p in paras:
        p = re.sub(r"\s+", " ", p).strip()
        if not p or len(p) < 40:
            continue
        if _UNWANTED_RE.search(p):
            continue
        if sum(ch.isalpha() for ch in p) < 25:
            continue
        out.append(p)
    seen = set()
    dedup = []
    for p in out:
        key = p.lower()
        if key not in seen:
            seen.add(key)
            dedup.append(p)
    return dedup


def _best_description_html(soup: BeautifulSoup) -> str:
    s2 = BeautifulSoup(str(soup), "lxml")
    for sel in [
        "nav", "header", "footer", "aside", "form", "button",
        ".breadcrumb", ".breadcrumbs", ".pagination", ".pager", ".nav",
        ".header", ".footer", ".sidebar", ".cookie", ".consent", ".modal",
    ]:
        for el in s2.select(sel):
            el.decompose()

    selectors = [
        "[itemprop=description]",
        ".description",
        ".product-description",
        ".product__description",
        ".productDetail",
        ".product-detail",
        ".content",
        "main",
        "article",
        "[role=main]",
    ]

    paras: list[str] = []
    for sel in selectors:
        for root in s2.select(sel):
            for p in root.select("p, li"):
                txt = p.get_text(" ", strip=True)
                if txt:
                    paras.append(txt)
        if len(paras) >= 5:
            break

    paras = _clean_paragraphs(paras)

    if not paras:
        text = s2.get_text("\n", strip=True)
        chunks = [c.strip() for c in text.split("\n") if c.strip()]
        paras = _clean_paragraphs(chunks)

    if not paras:
        return ""

    out_paras = []
    total = 0
    for p in paras:
        if total > 1200:
            break
        out_paras.append(p)
        total += len(p)

    return "".join([f"<p>{p}</p>" for p in out_paras])


async def _auto_scroll(page, steps: int = 10, step_px: int = 900, wait_ms: int = 200):
    for _ in range(steps):
        await page.mouse.wheel(0, step_px)
        await page.wait_for_timeout(wait_ms)


async def _accept_cookies_if_any(page):
    candidates = [
        'button:has-text("Accept")',
        'button:has-text("Allow all")',
        'button:has-text("Accept all")',
        'button:has-text("OK")',
        'button:has-text("I agree")',
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


async def _fetch_with_login(url: str, user: str, password: str, wait_ms: int = 1600) -> tuple[str, str]:
    try:
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
                locale="de-DE",
                extra_http_headers={"Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"},
                viewport={"width": 1366, "height": 768},
            )
            page = await context.new_page()
            await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")

            note_parts = ["psi_pw=YES"]

            if user and password:
                await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(600)
                await _accept_cookies_if_any(page)

                await page.fill('input[name="username"], input[id*="user" i], input[placeholder*="Benutzername" i], input[type="text"]', user)
                await page.fill('input[name="password"], input[id*="pass" i], input[placeholder*="Passwort" i], input[type="password"]', password)

                try:
                    await page.click('button:has-text("LOGIN"), button[type="submit"], input[type="submit"]', timeout=8000)
                except Exception:
                    await page.keyboard.press("Enter")

                await page.wait_for_timeout(1200)
                await _accept_cookies_if_any(page)
                note_parts.append("psi_login=YES")
            else:
                note_parts.append("psi_login=NO")

            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(wait_ms)
            await _auto_scroll(page, steps=10, step_px=900, wait_ms=180)
            await page.wait_for_timeout(500)

            html = await page.content()
            await context.close()
            await browser.close()
            return html, " ".join(note_parts)
    except Exception as e:
        msg = str(e)
        if "Executable doesn't exist" in msg or "playwright install" in msg:
            _ensure_playwright_chromium_installed()
            # retry once
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
                    locale="de-DE",
                    extra_http_headers={"Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"},
                    viewport={"width": 1366, "height": 768},
                )
                page = await context.new_page()
                await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")

                note_parts = ["psi_pw=YES", "psi_retry_install=1"]

                if user and password:
                    await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
                    await page.wait_for_timeout(600)
                    await _accept_cookies_if_any(page)
                    await page.fill('input[name="username"], input[id*="user" i], input[placeholder*="Benutzername" i], input[type="text"]', user)
                    await page.fill('input[name="password"], input[id*="pass" i], input[placeholder*="Passwort" i], input[type="password"]', password)
                    try:
                        await page.click('button:has-text("LOGIN"), button[type="submit"], input[type="submit"]', timeout=8000)
                    except Exception:
                        await page.keyboard.press("Enter")
                    await page.wait_for_timeout(1200)
                    await _accept_cookies_if_any(page)
                    note_parts.append("psi_login=YES")
                else:
                    note_parts.append("psi_login=NO")

                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(wait_ms)
                await _auto_scroll(page, steps=10, step_px=900, wait_ms=180)
                await page.wait_for_timeout(500)

                html = await page.content()
                await context.close()
                await browser.close()
                return html, " ".join(note_parts)
        raise


class PSIProductFinderScraper(Scraper):
    def can_handle(self, url: str) -> bool:
        return domain_of(url).endswith("psiproductfinder.de")

    def parse(self, url: str) -> ProductDraft:
        domain = domain_of(url)
        user = os.getenv("PSI_USER", "").strip()
        password = os.getenv("PSI_PASS", "").strip()

        html, note = asyncio.run(_fetch_with_login(url, user, password, wait_ms=1700))
        soup = BeautifulSoup(html, "lxml")

        state = _parse_next_data(soup)
        title = None
        desc = None

        if state:
            title = _find_first(state, {"name", "title", "productName", "product_title"})
            desc = _find_first(state, {"description", "longDescription", "shortDescription", "productDescription", "text"})

        if not title:
            title = _meta(soup, "og:title") or _meta(soup, "twitter:title") or (clean_text(soup.title.get_text()) if soup.title else "Produs")

        desc_html = ""
        if desc and len(desc) > 80:
            desc_html = f"<p>{clean_text(desc)}</p>"
        else:
            desc_html = _best_description_html(soup)

        images = _extract_images(soup, url)
        abs_imgs = []
        for u in images:
            if isinstance(u, str) and u:
                abs_imgs.append(urljoin(url, u))
        seen = set()
        out_imgs = []
        for u in abs_imgs:
            if u not in seen:
                seen.add(u)
                out_imgs.append(u)

        return ProductDraft(
            source_url=url,
            domain=domain,
            sku=ensure_sku(url, None),
            title=title,
            description_html=desc_html,
            short_description=clean_text(BeautifulSoup(desc_html or "", "lxml").get_text())[:200],
            images=out_imgs[:12],
            price=None,
            currency="RON",
            needs_translation=False,
            notes=f"psi_scraper=login_v4_clean_installfix parsed_with=playwright {note}",
        )
