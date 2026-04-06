from __future__ import annotations

import asyncio
from typing import Any

import httpx
import structlog

from config.settings import Settings

log = structlog.get_logger(__name__)

ENRICH_URL = "https://api.prospeo.io/api/v1/enrich-person"


class ProspeoClient:
    """Prospeo API client — fallback for email enrichment when Apollo fails."""

    def __init__(self, settings: Settings) -> None:
        self.api_key = settings.PROSPEO_API_KEY
        self._log = log.bind(client="prospeo")

    async def enrich_person(
        self,
        first_name: str,
        last_name: str,
        company_domain: str = "",
        linkedin_url: str = "",
    ) -> dict[str, Any] | None:
        """Find verified email for a person.

        Returns dict with email, confidence, etc. or None.
        """
        if not self.api_key:
            self._log.warning("prospeo.no_api_key")
            return None

        payload: dict[str, Any] = {
            "first_name": first_name,
            "last_name": last_name,
        }
        if company_domain:
            payload["company_domain"] = company_domain
        if linkedin_url:
            payload["linkedin_url"] = linkedin_url

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    ENRICH_URL,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()

                if data.get("error"):
                    self._log.warning("prospeo.error", error=data["error"])
                    return None

                email = data.get("email", "")
                confidence = data.get("confidence", 0)
                self._log.info(
                    "prospeo.enrich",
                    name=f"{first_name} {last_name}",
                    email=email[:3] + "***" if email else "none",
                    confidence=confidence,
                )
                return data
            except httpx.HTTPStatusError as e:
                self._log.error("prospeo.error", status=e.response.status_code)
                return None
            except Exception:
                self._log.exception("prospeo.failed")
                return None
