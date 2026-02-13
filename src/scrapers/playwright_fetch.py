from __future__ import annotations

import asyncio
from playwright.async_api import async_playwright

async def _fetch(url: str, wait_ms: int = 2500) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(wait_ms)
        html = await page.content()
        await browser.close()
        return html

def fetch_html_playwright(url: str, wait_ms: int = 2500) -> str:
    return asyncio.run(_fetch(url, wait_ms=wait_ms))
