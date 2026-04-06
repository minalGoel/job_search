from __future__ import annotations

import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import structlog

from config.settings import Settings

log = structlog.get_logger(__name__)


def _get_gmail_service(settings: Settings):
    """Build and return an authenticated Gmail API service object.

    First run will open a browser for OAuth consent.
    Subsequent runs use the cached token.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    SCOPES = ["https://www.googleapis.com/auth/gmail.send",
              "https://www.googleapis.com/auth/gmail.readonly"]

    creds_path = Path(settings.GMAIL_CREDENTIALS_PATH)
    token_path = Path(settings.GMAIL_TOKEN_PATH)

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not creds_path.exists():
                raise FileNotFoundError(
                    f"Gmail credentials not found at {creds_path}. "
                    "Download from Google Cloud Console → APIs & Services → Credentials."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)

        token_path.parent.mkdir(parents=True, exist_ok=True)
        with open(token_path, "w") as f:
            f.write(creds.to_json())
        log.info("gmail.token_saved", path=str(token_path))

    return build("gmail", "v1", credentials=creds)


class GmailSender:
    """Sends emails via Gmail API with threading support."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._service = None
        self._log = log.bind(module="gmail_sender")

    def _ensure_service(self):
        if self._service is None:
            self._service = _get_gmail_service(self.settings)
        return self._service

    def send_email(
        self,
        to: str,
        subject: str,
        body_html: str,
        body_plain: str,
        thread_id: str = "",
    ) -> dict:
        """Send an email and return {message_id, thread_id}.

        If thread_id is provided, the email is added to that thread
        (for follow-ups in the same conversation).
        """
        service = self._ensure_service()

        msg = MIMEMultipart("alternative")
        msg["To"] = to
        msg["From"] = "me"
        msg["Subject"] = subject

        msg.attach(MIMEText(body_plain, "plain"))
        msg.attach(MIMEText(body_html, "html"))

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        body: dict = {"raw": raw}
        if thread_id:
            body["threadId"] = thread_id

        try:
            result = (
                service.users()
                .messages()
                .send(userId="me", body=body)
                .execute()
            )
            message_id = result.get("id", "")
            result_thread_id = result.get("threadId", "")
            self._log.info(
                "gmail.sent",
                to=to[:20] + "...",
                subject=subject[:40],
                message_id=message_id,
                thread_id=result_thread_id,
            )
            return {"message_id": message_id, "thread_id": result_thread_id}
        except Exception:
            self._log.exception("gmail.send_failed", to=to)
            raise

    def check_auth(self) -> bool:
        """Verify Gmail API authentication works."""
        try:
            service = self._ensure_service()
            profile = service.users().getProfile(userId="me").execute()
            email = profile.get("emailAddress", "")
            self._log.info("gmail.authenticated", email=email)
            return True
        except Exception:
            self._log.exception("gmail.auth_failed")
            return False
