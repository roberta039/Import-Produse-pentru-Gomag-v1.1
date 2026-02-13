from __future__ import annotations
import re
from urllib.parse import urlparse
from slugify import slugify

def detect_url_column(columns):
    # case-insensitive match
    lowered = {c.lower(): c for c in columns}
    for cand in ["url", "link", "product_url", "product link", "productlink"]:
        if cand in lowered:
            return lowered[cand]
    # fallback: first col that looks like url
    for c in columns:
        if "http" in str(c).lower():
            return c
    return None

def domain_of(url: str) -> str:
    return urlparse(url).netloc.lower()

def ensure_sku(url: str, sku: str | None) -> str:
    if sku and str(sku).strip():
        return str(sku).strip()
    # fallback generated
    p = urlparse(url)
    tail = (p.path.strip("/").split("/")[-1] or "produs")
    return slugify(f"{p.netloc}-{tail}")[:64]

def clean_text(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s).strip()
    return s
