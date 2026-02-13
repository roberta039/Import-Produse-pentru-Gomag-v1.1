from __future__ import annotations

import hashlib
import os
from typing import Dict, List

import pandas as pd

from .models import ProductDraft

TEMPLATE_PATH = os.path.join("assets", "modelImport.xlsx")


def _load_template_headers() -> List[str]:
    """Loads the header row from Gomag's 'Model import' template (XLSX)."""
    try:
        import openpyxl  # type: ignore
        wb = openpyxl.load_workbook(TEMPLATE_PATH)
        ws = wb.active
        headers = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
        headers = [h for h in headers if h]
        if headers:
            return headers
    except Exception:
        pass

    return [
        "Cod Produs (SKU)",
        "Denumire Produs",
        "Descriere Produs",
        "Descriere Scurta a Produsului",
        "URL Poza de Produs",
        "Pret",
        "Pretul Include TVA",
        "Cota TVA",
        "Moneda",
        "Stoc Cantitativ",
        "Activ in Magazin",
        "Categorie / Categorii",
    ]


def _shorten_sku(sku: str, max_len: int = 30) -> str:
    """Gomag limita SKU = 30. Pastreaza determinist si unic."""
    sku = (sku or "").strip()
    if len(sku) <= max_len:
        return sku

    h = hashlib.sha1(sku.encode("utf-8")).hexdigest()[:8]
    prefix_len = max_len - 1 - len(h)
    prefix = sku[:prefix_len]
    return f"{prefix}-{h}"


def to_gomag_dataframe(products: List[ProductDraft], category_map: Dict[str, str] | None = None) -> pd.DataFrame:
    headers = _load_template_headers()
    category_map = category_map or {}
    rows: List[dict] = []

    for p in products:
        cat = category_map.get(p.source_url, "") or ""

        row = {h: "" for h in headers}

        row["Cod Produs (SKU)"] = _shorten_sku(p.sku)
        row["Denumire Produs"] = p.title or ""
        row["Descriere Produs"] = p.description_html or ""
        row["Descriere Scurta a Produsului"] = p.short_description or ""

        imgs = p.images or []
        row["URL Poza de Produs"] = "\n".join([i for i in imgs if i])

        row["Pret"] = round(p.price_final(), 2)
        row["Moneda"] = "RON"
        row["Stoc Cantitativ"] = 1
        row["Activ in Magazin"] = "DA"

        # TVA standard (RO): 21%
        # IMPORTANT: nu completam "Pretul Include TVA" (il lasam gol) ca sa evite
        # eroarea "setare diferita fata de varianta parinte" (Gomag mosteneste setarea).
        row["Pretul Include TVA"] = ""
        row["Cota TVA"] = 21

        row["Categorie / Categorii"] = cat

        rows.append(row)

    return pd.DataFrame(rows, columns=headers)


def save_xlsx(df: pd.DataFrame, path: str) -> None:
    df.to_excel(path, index=False)
