from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional

@dataclass
class Variant:
    color: Optional[str] = None
    size: Optional[str] = None
    sku: Optional[str] = None
    price: Optional[float] = None
    images: List[str] = field(default_factory=list)

@dataclass
class ProductDraft:
    source_url: str
    domain: str
    sku: str
    title: str
    description_html: str = ""
    short_description: str = ""
    specs: Dict[str, str] = field(default_factory=dict)
    images: List[str] = field(default_factory=list)
    price: Optional[float] = None
    currency: str = "RON"
    variants: List[Variant] = field(default_factory=list)
    needs_translation: bool = False
    notes: str = ""

    def price_final(self) -> float:
        if self.price is None:
            return 1.0
        try:
            return max(1.0, float(self.price) * 2.0)
        except Exception:
            return 1.0
