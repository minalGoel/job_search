from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Absolute path so the app behaves the same regardless of CWD
    # (previously ".env" was resolved relative to the working directory).
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parent.parent / ".env"),
        env_file_encoding="utf-8",
    )

    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = True

    ALERT_RECIPIENTS: str = ""
    SCHEDULE_TIMES: str = "09:00,16:00"
    POLL_INTERVAL_MINUTES: int = 0
    LOG_LEVEL: str = "INFO"

    # Apollo.io (contact enrichment)
    APOLLO_API_KEY: str = ""
    APOLLO_RATE_LIMIT_PER_MINUTE: int = 10

    # Prospeo (fallback enrichment)
    PROSPEO_API_KEY: str = ""

    # Job aggregator APIs (free keys; the scraper is skipped when blank)
    ADZUNA_APP_ID: str = ""
    ADZUNA_APP_KEY: str = ""
    JOOBLE_API_KEY: str = ""
    CAREERJET_AFFID: str = ""

    # MNC careers scraping (fetch-everything-then-filter)
    MNC_MAX_POSTINGS: int = 3000        # per-company cap on the full listing fetch
    MNC_API_CONCURRENCY: int = 12       # concurrent companies in the httpx lane
    MNC_PER_HOST_CONCURRENCY: int = 2   # concurrent requests per ATS host
    MNC_HTML_CONCURRENCY: int = 5       # concurrent companies in the Playwright lane
    MNC_HTML_MAX_PAGES: int = 10        # "Next"/"Load more" clicks per company
    MNC_HTTP_TIMEOUT: int = 25          # seconds per HTTP request
    MNC_COMPANY_TIMEOUT: int = 420      # hard wall clock per company (EY: ~120 SF pages at 2/host)

    # Gmail OAuth (outreach sending)
    GMAIL_CREDENTIALS_PATH: str = "credentials/gmail_credentials.json"
    GMAIL_TOKEN_PATH: str = "credentials/gmail_token.json"

    # Outreach settings
    OUTREACH_DAILY_LIMIT: int = 25
    OUTREACH_SENDER_NAME: str = ""
    OUTREACH_SENDER_LINKEDIN: str = ""
    OUTREACH_EXPERIENCE_YEARS: int = 6
    OUTREACH_DOMAIN_EXPERTISE: str = "B2B SaaS"
    OUTREACH_ONE_LINE_PITCH: str = ""

    @property
    def alert_recipients_list(self) -> list[str]:
        return [r.strip() for r in self.ALERT_RECIPIENTS.split(",") if r.strip()]

    @property
    def schedule_times_parsed(self) -> list[tuple[int, int]]:
        result: list[tuple[int, int]] = []
        for t in self.SCHEDULE_TIMES.split(","):
            t = t.strip()
            if t:
                hour, minute = t.split(":")
                result.append((int(hour), int(minute)))
        return result

    @property
    def BASE_DIR(self) -> Path:
        return Path(__file__).resolve().parent.parent

    @property
    def OUTPUT_DIR(self) -> Path:
        return self.BASE_DIR / "output"

    @property
    def COOKIES_DIR(self) -> Path:
        return self.BASE_DIR / "cookies"

    @property
    def LOGS_DIR(self) -> Path:
        return self.BASE_DIR / "logs"
