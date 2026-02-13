from __future__ import annotations
from .base import Scraper
from .generic import GenericScraper
from ..utils import domain_of

class PFConceptScraper(Scraper):
    def __init__(self):
        self._g = GenericScraper()

    def can_handle(self, url: str) -> bool:
        d = domain_of(url)
        return any(d.endswith(x) for x in ['pfconcept.com'])

    def parse(self, url: str):
        draft = self._g.parse(url)
        return draft
