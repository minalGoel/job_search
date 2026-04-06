from __future__ import annotations

from html import escape
from string import Template
from typing import Any

import structlog

from config.settings import Settings
from outreach.models import OutreachEmail

log = structlog.get_logger(__name__)

# -----------------------------------------------------------------------
# Template definitions (3-step sequence, direct & professional)
# -----------------------------------------------------------------------

TEMPLATES: dict[str, dict[str, str]] = {
    "intro": {
        "name": "intro",
        "subject": "PM role at ${company} — quick note from a fellow product person",
        "body": """Hi ${first_name},

I noticed ${company} is hiring for a ${job_title} role${funding_context}. I'm a Senior PM with ${experience} years building ${domain} products — ${one_line_pitch}.

I'd love to chat if you're still looking. Happy to share more context on my background.

Best,
${sender_name}
${sender_linkedin}""",
    },
    "followup_day3": {
        "name": "followup_day3",
        "subject": "Re: PM role at ${company} — quick note from a fellow product person",
        "body": """Hi ${first_name},

Just bumping this up — I know inboxes get busy. Would love 15 min to discuss the ${job_title} role if it's still open.

Best,
${sender_name}""",
    },
    "followup_day7": {
        "name": "followup_day7",
        "subject": "Re: PM role at ${company} — quick note from a fellow product person",
        "body": """Hi ${first_name},

Last follow-up from my end. If the timing isn't right, no worries at all. I'll keep following ${company}'s journey — really like what you're building.

Best,
${sender_name}""",
    },
}


def _build_funding_context(funding_series: str, funding_amount: str) -> str:
    """Build the funding mention snippet if available."""
    if funding_series and funding_amount:
        return f" — congrats on the {funding_series} raise ({funding_amount})"
    if funding_series:
        return f" — congrats on the {funding_series} raise"
    return ""


def render_email(
    template_name: str,
    contact: dict,
    settings: Settings,
) -> OutreachEmail | None:
    """Render an email template with contact + settings variables.

    Returns an OutreachEmail with both plain text and HTML body.
    """
    tmpl = TEMPLATES.get(template_name)
    if not tmpl:
        log.error("templates.unknown", name=template_name)
        return None

    # Build variable map
    first_name = (contact.get("contact_name") or "").split()[0] if contact.get("contact_name") else "there"
    job_title = contact.get("source_job_title") or "Product Manager"
    funding_context = _build_funding_context(
        contact.get("funding_series", ""),
        contact.get("funding_amount", ""),
    )

    variables = {
        "first_name": first_name,
        "company": contact.get("company", ""),
        "job_title": job_title,
        "funding_context": funding_context,
        "experience": settings.OUTREACH_EXPERIENCE_YEARS,
        "domain": settings.OUTREACH_DOMAIN_EXPERTISE,
        "one_line_pitch": settings.OUTREACH_ONE_LINE_PITCH,
        "sender_name": settings.OUTREACH_SENDER_NAME,
        "sender_linkedin": settings.OUTREACH_SENDER_LINKEDIN,
    }

    try:
        subject = Template(tmpl["subject"]).safe_substitute(variables)
        body_plain = Template(tmpl["body"]).safe_substitute(variables)
    except Exception:
        log.exception("templates.render_failed", template=template_name)
        return None

    # Convert plain text to simple HTML
    body_html = "<p>" + escape(body_plain).replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"

    # Determine sequence step
    step_map = {"intro": 1, "followup_day3": 2, "followup_day7": 3}
    step = step_map.get(template_name, 1)

    return OutreachEmail(
        contact_id=contact.get("id", ""),
        sequence_step=step,
        subject=subject,
        body_html=body_html,
        body_plain=body_plain,
        template_name=template_name,
        status="draft",
    )


def generate_sequence(contact: dict, settings: Settings) -> list[OutreachEmail]:
    """Generate the full 3-step email sequence for a contact."""
    emails = []
    for tmpl_name in ["intro", "followup_day3", "followup_day7"]:
        email = render_email(tmpl_name, contact, settings)
        if email:
            emails.append(email)
    return emails
