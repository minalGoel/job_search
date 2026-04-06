from __future__ import annotations

from datetime import datetime, timedelta

import structlog

from config.settings import Settings
from outreach.db import OutreachDB
from outreach.enricher import OutreachEnricher
from outreach.gmail_sender import GmailSender
from outreach.templates import generate_sequence, render_email

log = structlog.get_logger(__name__)


async def run_enrich(settings: Settings) -> None:
    """Step 1: Find new companies from jobs + funding, enrich contacts, generate drafts."""
    from storage.db import JobDB

    db = OutreachDB()
    job_db = JobDB()

    enricher = OutreachEnricher(settings, db)

    # Source 1: New job listings (all PM roles, one per company)
    all_jobs = job_db.get_all_jobs()
    job_count = await enricher.enrich_from_jobs(all_jobs)
    log.info("pipeline.jobs_enriched", contacts=job_count)

    # Source 2: Funded companies
    # Read from funding export if available
    funded_companies = _load_funded_companies()
    if funded_companies:
        fund_count = await enricher.enrich_from_funding(funded_companies)
        log.info("pipeline.funding_enriched", contacts=fund_count)

    # Generate email drafts for all enriched contacts with verified emails
    enriched = db.get_contacts_by_status("enriched")
    draft_count = 0
    for contact in enriched:
        if not contact.get("contact_email"):
            continue
        emails = generate_sequence(contact, settings)
        for i, email in enumerate(emails):
            # Schedule follow-ups relative to now
            if i == 0:
                email.scheduled_send_at = datetime.now()
            elif i == 1:
                email.scheduled_send_at = datetime.now() + timedelta(days=3)
            elif i == 2:
                email.scheduled_send_at = datetime.now() + timedelta(days=7)

            if db.insert_email(email):
                draft_count += 1

        db.update_contact_status(contact["id"], "queued")

    log.info("pipeline.drafts_generated", count=draft_count)
    print(f"\n  Enriched contacts: {job_count + (fund_count if funded_companies else 0)}")
    print(f"  Email drafts generated: {draft_count}")
    print(f"  Run 'python main.py outreach-review' to review and approve.")

    job_db.close()
    db.close()


def run_send(settings: Settings) -> int:
    """Step 3: Send all approved emails via Gmail API, respecting daily limit."""
    db = OutreachDB()
    sender = GmailSender(settings)

    today_count = db.get_today_send_count()
    remaining = settings.OUTREACH_DAILY_LIMIT - today_count

    if remaining <= 0:
        print(f"  Daily limit reached ({settings.OUTREACH_DAILY_LIMIT} emails). Try again tomorrow.")
        db.close()
        return 0

    approved = db.get_sendable_emails()
    if not approved:
        print("  No approved emails ready to send (check scheduled times).")
        db.close()
        return 0

    to_send = approved[:remaining]
    print(f"  Sending {len(to_send)} of {len(approved)} ready emails (daily limit: {remaining} remaining)...\n")

    sent_count = 0
    for email_data in to_send:
        email_id = email_data["id"]
        contact_id = email_data["contact_id"]
        to_addr = email_data.get("contact_email", "")

        if not to_addr:
            log.warning("pipeline.no_email", email_id=email_id)
            db.update_email_status(email_id, "skipped")
            continue

        # Get thread ID for follow-ups
        thread_id = ""
        if email_data.get("sequence_step", 1) > 1:
            thread_id = db.get_thread_id_for_contact(contact_id)

        try:
            result = sender.send_email(
                to=to_addr,
                subject=email_data.get("subject", ""),
                body_html=email_data.get("body_html", ""),
                body_plain=email_data.get("body_plain", ""),
                thread_id=thread_id,
            )
            db.mark_email_sent(
                email_id,
                result.get("message_id", ""),
                result.get("thread_id", ""),
            )
            db.update_contact_status(contact_id, "sent")
            sent_count += 1
            print(f"    Sent to {to_addr} ({email_data.get('company', '')})")
        except Exception as e:
            error_str = str(e).lower()
            # Permanent failures: invalid address, rejected by server
            is_permanent = any(kw in error_str for kw in [
                "invalid", "not found", "does not exist", "rejected",
                "550", "551", "552", "553", "554",
            ])
            if is_permanent:
                log.error("pipeline.send_bounced", email_id=email_id, error=str(e))
                db.update_email_status(email_id, "bounced")
            else:
                # Transient: auth, network, quota — revert to approved for retry
                log.warning("pipeline.send_transient", email_id=email_id, error=str(e))
                db.update_email_status(email_id, "approved")

    print(f"\n  Sent: {sent_count} emails. Today total: {today_count + sent_count}/{settings.OUTREACH_DAILY_LIMIT}")
    db.close()
    return sent_count


def mark_replied(contact_id: str) -> None:
    """Mark a contact as replied and cancel pending follow-ups."""
    db = OutreachDB()
    contact = db.get_contact(contact_id)
    if not contact:
        print(f"  Contact {contact_id} not found.")
        db.close()
        return

    db.update_contact_status(contact_id, "replied")
    cancelled = db.cancel_pending_followups(contact_id)
    print(f"  Marked {contact.get('contact_name', '')} at {contact.get('company', '')} as REPLIED.")
    if cancelled:
        print(f"  Cancelled {cancelled} pending follow-up(s).")
    db.close()


def show_status(settings: Settings) -> None:
    """Show outreach pipeline status."""
    db = OutreachDB()
    stats = db.get_stats()
    db.close()

    print("\n  Outreach Pipeline Status")
    print("  " + "=" * 40)
    print(f"  Contacts:")
    print(f"    New (no email):    {stats.get('contacts_new', 0)}")
    print(f"    Enriched:          {stats.get('contacts_enriched', 0)}")
    print(f"    Queued:            {stats.get('contacts_queued', 0)}")
    print(f"    Sent:              {stats.get('contacts_sent', 0)}")
    print(f"    Replied:           {stats.get('contacts_replied', 0)}")
    print(f"    Bounced:           {stats.get('contacts_bounced', 0)}")
    print(f"    Skipped:           {stats.get('contacts_skipped', 0)}")
    print(f"\n  Emails:")
    print(f"    Drafts:            {stats.get('emails_draft', 0)}")
    print(f"    Approved:          {stats.get('emails_approved', 0)}")
    print(f"    Sent:              {stats.get('emails_sent', 0)}")
    print(f"    Bounced:           {stats.get('emails_bounced', 0)}")
    print(f"\n  Today:")
    print(f"    Sent today:        {stats.get('today_sent', 0)} / {settings.OUTREACH_DAILY_LIMIT}")
    print(f"\n  Credits (this month):")
    print(f"    Apollo:            {stats.get('apollo_credits_this_month', 0)} / 833")
    print(f"    Prospeo:           {stats.get('prospeo_credits_this_month', 0)} / 75")


def _load_funded_companies() -> list[dict]:
    """Load funded companies from the funding DB/export if available."""
    try:
        import csv
        from pathlib import Path

        output_dir = Path(__file__).resolve().parent.parent / "output"
        # Find latest funded companies CSV
        csvs = sorted(output_dir.glob("funded_companies_*.csv"), reverse=True)
        if not csvs:
            return []

        companies = []
        with open(csvs[0], encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                companies.append({
                    "company": row.get("Company", ""),
                    "amount_raised": row.get("Amt Raised", ""),
                    "last_round_series": row.get("Last Round (Date & Series)", "").split("–")[-1].strip() if "–" in row.get("Last Round (Date & Series)", "") else "",
                    "last_round_date": "",
                })
        return companies
    except Exception:
        log.debug("pipeline.no_funding_data")
        return []
