"""Company links for the dashboard's Companies page: website, LinkedIn, careers, portal.

The registry only stores careers/listing URLs. The website is derived — from the
``domain`` column of ``discovery_overrides.csv`` when the company has a row, else
from the registrable domain of the careers URL (``careers.hpe.com`` → ``hpe.com``)
unless that host is an ATS vendor's (``*.myworkdayjobs.com`` says nothing about the
company). A handful of entries whose every URL is vendor-hosted are pinned in
``_WEBSITE_OVERRIDES``. LinkedIn is a company-search link: guessing ``/company/<slug>``
is wrong often enough to be worse than a search that always lands.
"""
from __future__ import annotations

import csv
from functools import lru_cache
from urllib.parse import quote_plus, urlsplit

from mnc_careers.discovery import OVERRIDES_CSV
from mnc_careers.registry import MNC

# Hosts that belong to an ATS/job-board vendor, never to the company itself.
_VENDOR_HOSTS = (
    "myworkdayjobs", "greenhouse.io", "lever.co", "smartrecruiters.com", "oraclecloud.com", "avature.net",
    "successfactors", "icims.com", "taleo.net", "eightfold.ai", "phenompeople", "ashbyhq.com", "workable.com",
    "amazon.jobs", "jobvite.com", "teamtailor.com", "eploy", "bamboohr.com", "gr8people.com", "applytojob.com",
    "linkedin.com", "glassdoor", "softgarden", "pearson.jobs", "brassring.com", "csod.com", "ultipro.com",
)
# Sub-hosts that sit in front of the company's own domain.
_STRIP_LABELS = {
    "www", "careers", "career", "jobs", "job", "join", "work", "talent", "recruiting", "recruitment", "apply", "hr",
    "people", "en", "us", "in", "uk", "global", "corporate", "about", "www2", "ww2", "plc", "group", "explore",
}
_WEBSITE_OVERRIDES = {
    "amazon": "amazon.com",
    "linkedin (microsoft)": "linkedin.com",
    "workday": "workday.com",
    "eaton corporation": "eaton.com",
    "factset research": "factset.com",
    "barclays": "barclays.com",          # careers live on the brand TLD (jobs.barclays)
    "lufthansa group": "lufthansagroup.com",  # lufthansagroup.careers
}


@lru_cache(maxsize=1)
def _override_domains() -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        with OVERRIDES_CSV.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                d = (row.get("domain") or "").strip().lower()
                if d and row.get("company"):
                    out.setdefault(row["company"].strip().lower(), d)
    except OSError:
        pass
    return out


def registrable_domain(url: str) -> str:
    """``https://careers.hpe.com/us/en`` → ``hpe.com``; ``""`` for vendor-hosted URLs."""
    host = urlsplit(url or "").netloc.lower().split(":")[0]
    if not host or any(v in host for v in _VENDOR_HOSTS):
        return ""
    parts = host.split(".")
    while len(parts) > 2 and parts[0] in _STRIP_LABELS:
        parts = parts[1:]
    if len(parts) > 2 and parts[-2] in ("co", "com", "org", "net", "ac", "gov") and len(parts[-1]) == 2:
        parts = parts[-3:]  # sc.co.uk style second-level registries
    elif len(parts) > 2:
        parts = parts[-2:]
    return ".".join(parts)


def website_for(mnc: MNC) -> str:
    dom = (_WEBSITE_OVERRIDES.get(mnc.name.lower()) or _override_domains().get(mnc.name.lower())
           or registrable_domain(mnc.careers_url) or registrable_domain(mnc.pm_search_url))
    return f"https://{dom}" if dom else ""


def linkedin_for(mnc: MNC) -> str:
    name = mnc.name.split(" (")[0].split(" / ")[0].strip()
    return f"https://www.linkedin.com/search/results/companies/?keywords={quote_plus(name)}"
