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
from .weworkremotely import WeWorkRemotelyScraper
from .hirist import HiristScraper
from .ycombinator import YCombinatorScraper
from .weekday import WeekdayScraper

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
    "wellfound": WellfoundScraper,
    "glassdoor": GlassdoorScraper,
    # Remote-first platforms
    "remoteok": RemoteOKScraper,
    "weworkremotely": WeWorkRemotelyScraper,
    # Startup ecosystem
    "ycombinator": YCombinatorScraper,
    "weekday": WeekdayScraper,
}

__all__ = ["SCRAPER_REGISTRY"]
