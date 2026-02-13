from __future__ import annotations
from typing import List
from .scrapers import get_scraper
from .models import ProductDraft

def scrape_products(urls: List[str]) -> List[ProductDraft]:
    out = []
    for url in urls:
        s = get_scraper(url)
        try:
            out.append(s.parse(url))
        except Exception as e:
            # fallback minimal draft
            out.append(ProductDraft(
                source_url=url,
                domain="",
                sku="",
                title="(EROARE SCRAPING)",
                description_html="",
                short_description="",
                images=[],
                price=None,
                needs_translation=False,
                notes=f"error={type(e).__name__}: {e}"
            ))
    return out
