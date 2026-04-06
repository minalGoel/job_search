from __future__ import annotations

from html import escape
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path

import structlog

from config.settings import Settings

log = structlog.get_logger(__name__)


def _build_job_table_html(jobs: list[dict]) -> str:
    rows = []
    for j in jobs:
        link = escape(str(j.get("apply_link", "#")), quote=True)
        rows.append(
            f"<tr>"
            f"<td>{escape(str(j.get('platform', '')))}</td>"
            f"<td>{escape(str(j.get('title', '')))}</td>"
            f"<td>{escape(str(j.get('company', '')))}</td>"
            f"<td>{escape(str(j.get('salary', 'N/A')))}</td>"
            f"<td>{escape(str(j.get('location', '')))}</td>"
            f'<td><a href="{link}">Apply</a></td>'
            f"</tr>"
        )
    return (
        "<table border='1' cellpadding='5' cellspacing='0'>"
        "<tr><th>Platform</th><th>Title</th><th>Company</th>"
        "<th>Salary</th><th>Location</th><th>Link</th></tr>"
        + "\n".join(rows)
        + "</table>"
    )


def send_new_jobs_alert(
    new_jobs: list[dict],
    settings: Settings,
    csv_path: Path | None = None,
) -> bool:
    """Send an HTML email with new job listings and optional CSV attachment."""
    if not settings.SMTP_HOST or not settings.alert_recipients_list:
        log.warning("notifier.skipped", reason="SMTP not configured")
        return False

    non_dup = [j for j in new_jobs if not j.get("is_duplicate")]
    subject = f"Job Alert: {len(non_dup)} new PM roles found"

    html = (
        f"<h2>Found {len(non_dup)} new job(s)</h2>"
        f"<p>{len(new_jobs) - len(non_dup)} cross-platform duplicates also captured.</p>"
        + _build_job_table_html(non_dup[:50])  # Cap at 50 rows in email
    )

    msg = MIMEMultipart()
    msg["From"] = settings.SMTP_USER
    msg["To"] = ", ".join(settings.alert_recipients_list)
    msg["Subject"] = subject
    msg.attach(MIMEText(html, "html"))

    if csv_path and csv_path.exists():
        with open(csv_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f"attachment; filename={csv_path.name}")
            msg.attach(part)

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            if settings.SMTP_USE_TLS:
                server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_USER, settings.alert_recipients_list, msg.as_string())
        log.info("notifier.sent", recipients=settings.alert_recipients_list, jobs=len(non_dup))
        return True
    except Exception:
        log.exception("notifier.failed")
        return False


def send_session_expiry_alert(platform: str, settings: Settings) -> bool:
    """Alert user that a platform's session cookies have expired."""
    if not settings.SMTP_HOST or not settings.alert_recipients_list:
        return False

    msg = MIMEMultipart()
    msg["From"] = settings.SMTP_USER
    msg["To"] = ", ".join(settings.alert_recipients_list)
    msg["Subject"] = f"Job Search: {platform} session expired"
    body = (
        f"<p>The saved session for <b>{escape(platform)}</b> has expired.</p>"
        f"<p>Run <code>python main.py login --platform {escape(platform)}</code> to re-login.</p>"
    )
    msg.attach(MIMEText(body, "html"))

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            if settings.SMTP_USE_TLS:
                server.starttls()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_USER, settings.alert_recipients_list, msg.as_string())
        log.info("notifier.session_expiry_sent", platform=platform)
        return True
    except Exception:
        log.exception("notifier.session_expiry_failed")
        return False
