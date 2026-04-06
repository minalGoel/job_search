from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

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

    # Gmail OAuth (outreach sending)
    GMAIL_CREDENTIALS_PATH: str = "credentials/gmail_credentials.json"
    GMAIL_TOKEN_PATH: str = "credentials/gmail_token.json"

    # Outreach settings
    OUTREACH_DAILY_LIMIT: int = 25
    OUTREACH_SENDER_NAME: str = ""
    OUTREACH_SENDER_LINKEDIN: str = ""
    OUTREACH_EXPERIENCE_YEARS: str = "6"
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
