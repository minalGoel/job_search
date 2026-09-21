from __future__ import annotations

from .base import BaseScraper
from .naukri import NaukriScraper
from .iimjobs import IIMJobsScraper
from .foundit import FounditScraper
from .indeed import IndeedScraper
from .cutshort import CutshortScraper
from .wellfound import WellfoundScraper
from .linkedin import LinkedInScraper
from .instahyre import InstahyreScraper
from .glassdoor import GlassdoorScraper
from .remoteok import RemoteOKScraper
from .hirist import HiristScraper
from .ycombinator import YCombinatorScraper
from .weekday import WeekdayScraper
from .adzuna import AdzunaScraper
from .jooble import JoobleScraper
from .careerjet import CareerjetScraper

SCRAPER_REGISTRY: dict[str, type[BaseScraper]] = {
    # Core Indian platforms
    "naukri": NaukriScraper,
    "iimjobs": IIMJobsScraper,
    "foundit": FounditScraper,
    "indeed": IndeedScraper,
    "cutshort": CutshortScraper,
    "instahyre": InstahyreScraper,
    "hirist": HiristScraper,
    # Global platforms
    "linkedin": LinkedInScraper,
    # "wellfound": WellfoundScraper,  # DISABLED: mostly US startups, not relevant for Delhi NCR targeting
    # "glassdoor": GlassdoorScraper,  # DISABLED: low signal for PM roles, Cloudflare blocking issues
    # Remote-first platforms
    "remoteok": RemoteOKScraper,
    # Startup ecosystem
    "ycombinator": YCombinatorScraper,
    "weekday": WeekdayScraper,
    # Aggregators (API-key based; skipped while the key is blank in .env)
    "adzuna": AdzunaScraper,
    "jooble": JoobleScraper,
    "careerjet": CareerjetScraper,
}

__all__ = ["SCRAPER_REGISTRY"]
