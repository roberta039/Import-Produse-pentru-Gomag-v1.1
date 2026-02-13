from __future__ import annotations
from urllib.parse import urlparse
from .generic import GenericScraper
from .promobox import PromoboxScraper
from .andapresent import AndAPresentScraper
from .xdconnects import XDConnectsScraper
from .pfconcept import PFConceptScraper
from .sipec import SipecScraper
from .stamina import StaminaScraper
from .utteam import UTTeamScraper
from .psiproductfinder import PSIProductFinderScraper
from .clipperinterall import ClipperInterallScraper
from .stricker import StrickerScraper
from .midocean import MidOceanScraper

SCRAPERS = [
    PromoboxScraper(),
    AndAPresentScraper(),
    XDConnectsScraper(),
    PFConceptScraper(),
    SipecScraper(),
    StaminaScraper(),
    UTTeamScraper(),
    PSIProductFinderScraper(),
    ClipperInterallScraper(),
    StrickerScraper(),
    MidOceanScraper(),
    GenericScraper(),
]

def get_scraper(url: str):
    for s in SCRAPERS:
        try:
            if s.can_handle(url):
                return s
        except Exception:
            continue
    return GenericScraper()
