from __future__ import annotations
from abc import ABC, abstractmethod
from ..models import ProductDraft

class Scraper(ABC):
    @abstractmethod
    def can_handle(self, url: str) -> bool:
        ...

    @abstractmethod
    def parse(self, url: str) -> ProductDraft:
        ...
