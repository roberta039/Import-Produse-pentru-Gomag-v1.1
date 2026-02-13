import asyncio
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Tuple

import yaml
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# No __future__ import to avoid SyntaxError in patched environments.

def _pw_writable_browsers_path() -> str:
    home = os.path.expanduser("~")
    return os.path.join(home, ".cache", "ms-playwright")


def _ensure_playwright_chromium_installed() -> None:
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
        raise RuntimeError(f"playwright install failed (code={proc.returncode}):\n{proc.stdout}")
    os.environ["PW_CHROMIUM_READY"] = "1"


async def _launch_ctx(p):
    browser = await p.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
            "--ignore-certificate-errors",
        ],
    )
    context = await browser.new_context(ignore_https_errors=True, viewport={"width": 1366, "height": 850})
    page = await context.new_page()
    return browser, context, page


def _load_cfg() -> dict:
    cfg_path = os.path.join("config", "config.yaml")
    if os.path.exists(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {
        "gomag": {
            "login": {
                "email_selector": 'input[name="email"], input[type="email"]',
                "password_selector": 'input[name="password"], input[type="password"]',
                "submit_selector": 'button[type="submit"], button:has-text("Autentificare"), button:has-text("Login")',
            },
            "categories": {"url_path": "/gomag/product/category/list"},
            "import": {"url_path": "/gomag/product/import/add"},
        }
    }


async def _goto_with_fallback(page, url: str):
    if url.startswith("http://"):
        https_url = "https://" + url[len("http://"):]
    elif url.startswith("https://"):
        https_url = url
    else:
        https_url = url
    http_url = https_url.replace("https://", "http://", 1)
    try:
        await page.goto(https_url, wait_until="domcontentloaded", timeout=120000)
        return
    except Exception:
        await page.goto(http_url, wait_until="domcontentloaded", timeout=120000)


async def _wait_render(page, ms: int = 1200):
    await page.wait_for_timeout(ms)


@dataclass
class GomagCreds:
    base_url: str
    email: str
    password: str


async def _login(page, creds: GomagCreds, cfg: dict):
    base = creds.base_url.rstrip("/")
    await _goto_with_fallback(page, base + "/gomag/dashboard")
    await _wait_render(page, 900)

    await page.fill(cfg["gomag"]["login"]["email_selector"], creds.email)
    await page.fill(cfg["gomag"]["login"]["password_selector"], creds.password)
    await page.click(cfg["gomag"]["login"]["submit_selector"])
    await _wait_render(page, 1500)


def _parse_categories(html: str) -> List[Tuple[str, str]]:
    soup = BeautifulSoup(html or "", "lxml")
    out: List[Tuple[str, str]] = []
    # categories list page can be normal table or g2 div table
    for tr in soup.select("table tbody tr"):
        tds = tr.find_all("td")
        if tds:
            name = tds[0].get_text(" ", strip=True)
            if name:
                out.append((name, name))
    for row in soup.select("#content .-g2-table .-g2-table-row:not(.-g2-table-head)"):
        cols = row.select(":scope > .-g2-table-col")
        if cols:
            name = cols[0].get_text(" ", strip=True)
            if name:
                out.append((name, name))
    # de-dup
    seen = set()
    uniq: List[Tuple[str, str]] = []
    for k, v in out:
        if k in seen:
            continue
        seen.add(k)
        uniq.append((k, v))
    return uniq


async def fetch_categories_async(creds: GomagCreds) -> List[Tuple[str, str]]:
    cfg = _load_cfg()
    _ensure_playwright_chromium_installed()
    base = creds.base_url.rstrip("/")
    url = base + cfg["gomag"]["categories"]["url_path"]

    async with async_playwright() as p:
        browser, context, page = await _launch_ctx(p)
        try:
            await _login(page, creds, cfg)
            await _goto_with_fallback(page, url)
            await _wait_render(page, 1600)
            return _parse_categories(await page.content())
        finally:
            await context.close()
            await browser.close()


def fetch_categories(creds: GomagCreds) -> List[Tuple[str, str]]:
    return asyncio.run(fetch_categories_async(creds))


def _extract_first_row(html: str):
    soup = BeautifulSoup(html or "", "lxml")

    # Case A: classic <table>
    tr = soup.select_one("table tbody tr")
    if tr:
        tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        first_text = " | ".join([t for t in tds if t]).strip()
        status_txt = (tds[-1] if tds else "").strip()
        a = tr.select_one("a")
        href = (a.get("href") if a else "") or ""
        # if there is an "err" link, prefer it
        aerr = tr.select_one('a[href*="/gomag/product/import/err"]')
        if aerr and aerr.get("href"):
            href = aerr.get("href")
        return first_text, status_txt, (href or "").strip()

    # Case B: Gomag backend uses div-table (-g2-table)
    row = soup.select_one("#content .-g2-table .-g2-table-row:not(.-g2-table-head)")
    if row:
        cols = row.select(":scope > .-g2-table-col")
        tds = [c.get_text(" ", strip=True) for c in cols]
        first_text = " | ".join([t for t in tds if t]).strip()
        status_txt = tds[-1].strip() if tds else ""
        aerr = row.select_one('a[href*="/gomag/product/import/err"]')
        href = (aerr.get("href") if aerr else "") or ""
        return first_text, status_txt, href.strip()

    return "", "", ""


def _extract_import_errors(html: str) -> List[str]:
    soup = BeautifulSoup(html or "", "lxml")
    errors: List[str] = []

    # Classic table errors
    for tr in soup.select("table tbody tr")[:10]:
        tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if tds:
            errors.append(" | ".join(tds))

    # g2 div-table errors (if used)
    if not errors:
        for row in soup.select("#content .-g2-table .-g2-table-row:not(.-g2-table-head)")[:10]:
            cols = [c.get_text(" ", strip=True) for c in row.select(":scope > .-g2-table-col")]
            cols = [c for c in cols if c]
            if cols:
                errors.append(" | ".join(cols))

    # Sometimes errors are plain list items
    if not errors:
        for li in soup.select("#content li")[:10]:
            t = li.get_text(" ", strip=True)
            if t and len(t) > 5:
                errors.append(t)

    return errors


async def import_file_async(creds: GomagCreds, file_path: str) -> str:
    cfg = _load_cfg()
    _ensure_playwright_chromium_installed()

    base = creds.base_url.rstrip("/")
    add_url = base + cfg["gomag"]["import"]["url_path"]
    list_url = base + "/gomag/product/import/list"

    async with async_playwright() as p:
        browser, context, page = await _launch_ctx(p)
        try:
            await _login(page, creds, cfg)

            # snapshot before
            before_html = ""
            try:
                await _goto_with_fallback(page, list_url)
                await _wait_render(page, 1400)
                before_html = await page.content()
            except Exception:
                before_html = ""
            before_first, _, _ = _extract_first_row(before_html)

            # go add
            await _goto_with_fallback(page, add_url)
            await _wait_render(page, 1400)

            # unhide inputs
            try:
                await page.evaluate("""() => {
                    document.querySelectorAll('input[type=file]').forEach(el => {
                        el.style.display='block';
                        el.style.visibility='visible';
                        el.style.opacity='1';
                        el.removeAttribute('hidden');
                    });
                }""")
            except Exception:
                pass

            async def _try_upload_in(loc) -> bool:
                try:
                    cnt = await loc.count()
                    for i in range(cnt):
                        try:
                            await loc.nth(i).set_input_files(file_path, timeout=60000)
                            return True
                        except Exception:
                            continue
                except Exception:
                    return False
                return False

            uploaded = await _try_upload_in(page.locator('input[type="file"]'))
            if not uploaded:
                for fr in page.frames:
                    if fr == page.main_frame:
                        continue
                    if await _try_upload_in(fr.locator('input[type="file"]')):
                        uploaded = True
                        break
            if not uploaded:
                os.makedirs("debug_artifacts", exist_ok=True)
                await page.screenshot(path="debug_artifacts/gomag_upload_no_file_input.png", full_page=True)
                with open("debug_artifacts/gomag_upload_no_file_input.html", "w", encoding="utf-8") as f:
                    f.write(await page.content())
                raise RuntimeError("Nu am gasit input[type=file] utilizabil pentru upload (vezi debug_artifacts).")

            await _wait_render(page, 1200)

            # click Start Import
            btn = page.locator('button:has-text("Start Import"), a:has-text("Start Import"), [role="button"]:has-text("Start Import")').first
            if await btn.count() == 0:
                os.makedirs("debug_artifacts", exist_ok=True)
                await page.screenshot(path="debug_artifacts/gomag_no_start_import.png", full_page=True)
                with open("debug_artifacts/gomag_no_start_import.html", "w", encoding="utf-8") as f:
                    f.write(await page.content())
                raise RuntimeError("Nu gasesc butonul Start Import (vezi debug_artifacts).")
            await btn.click(timeout=10000, force=True)
            await page.wait_for_timeout(2500)

            # list page after
            await _goto_with_fallback(page, list_url)
            await _wait_render(page, 1600)
            after_html = await page.content()

            # sometimes HTML blank, try reload
            if after_html.strip().replace(" ", "") == "<html><head></head><body></body></html>":
                await page.wait_for_timeout(1200)
                try:
                    await page.reload(wait_until="domcontentloaded", timeout=120000)
                except Exception:
                    pass
                await _wait_render(page, 1600)
                after_html = await page.content()

            first_text, status_txt, href = _extract_first_row(after_html)

            if before_first and first_text and first_text == before_first:
                return "Start Import apasat, dar nu a aparut un import nou in lista."

            if not first_text:
                os.makedirs("debug_artifacts", exist_ok=True)
                await page.screenshot(path="debug_artifacts/gomag_import_list_empty.png", full_page=True)
                with open("debug_artifacts/gomag_import_list_empty.html", "w", encoding="utf-8") as f:
                    f.write(after_html)
                return "Import nou detectat, dar nu am putut extrage randul din lista (nu am gasit randuri in pagina). Am salvat debug_artifacts/gomag_import_list_empty.*"

            # If we have an errors link, fetch it and extract first errors
            if href:
                if href.startswith("/"):
                    err_url = base + href
                elif href.startswith("http"):
                    err_url = href
                else:
                    err_url = base + "/" + href.lstrip("/")

                # If status indicates errors, read details
                if "erori" in (status_txt or "").lower() or "erori" in first_text.lower():
                    await _goto_with_fallback(page, err_url)
                    await _wait_render(page, 1600)
                    err_html = await page.content()
                    errs = _extract_import_errors(err_html)
                    if errs:
                        return "Finalizat cu erori. Primele erori:\n- " + "\n- ".join(errs[:10])

            return f"OK: import nou detectat. Status='{status_txt}'. Primul rand: {first_text[:200]}"
        finally:
            await context.close()
            await browser.close()


def import_file(creds: GomagCreds, file_path: str) -> str:
    return asyncio.run(import_file_async(creds, file_path))
