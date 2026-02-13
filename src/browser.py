from __future__ import annotations

import asyncio
import os
import subprocess
import sys

from playwright.async_api import async_playwright


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
        raise RuntimeError(f"playwright_install_failed (code={proc.returncode}):\n{proc.stdout}")

    os.environ["PW_CHROMIUM_READY"] = "1"


async def _auto_scroll(page, steps: int = 10, step_px: int = 900, wait_ms: int = 200):
    for _ in range(steps):
        await page.mouse.wheel(0, step_px)
        await page.wait_for_timeout(wait_ms)


async def render_html(url: str, wait_ms: int = 1500) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="ro-RO",
            extra_http_headers={
                "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7",
                "DNT": "1",
                "Upgrade-Insecure-Requests": "1",
            },
            viewport={"width": 1366, "height": 768},
        )

        page = await context.new_page()

        # Hide webdriver flag (basic)
        await page.add_init_script(
            """Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"""
        )

        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(wait_ms)

        # Scroll a bit to trigger lazy-loaded images
        await _auto_scroll(page, steps=12, step_px=900, wait_ms=200)
        await page.wait_for_timeout(600)

        html = await page.content()
        await context.close()
        await browser.close()
        return html


def render_html_sync(url: str, wait_ms: int = 1500) -> str:
    try:
        return asyncio.run(render_html(url, wait_ms=wait_ms))
    except Exception as e:
        msg = str(e)
        if "Executable doesn't exist" in msg or "playwright install" in msg:
            _ensure_playwright_chromium_installed()
            return asyncio.run(render_html(url, wait_ms=wait_ms))
        raise
