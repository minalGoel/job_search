from __future__ import annotations

import json
import webbrowser
from datetime import datetime
from html import escape
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import structlog

from outreach.db import OutreachDB

log = structlog.get_logger(__name__)

REVIEW_PORT = 8899


def _build_review_html(emails: list[dict]) -> str:
    """Generate the HTML review page with approve/edit/skip/snooze buttons."""
    rows = []
    for e in emails:
        email_id = escape(e.get("id", ""))
        company = escape(str(e.get("company", "")))
        contact_name = escape(str(e.get("contact_name", "")))
        contact_title = escape(str(e.get("contact_title", "")))
        contact_email = escape(str(e.get("contact_email", "")))
        source = escape(str(e.get("source", "")))
        subject = escape(str(e.get("subject", "")))
        body = escape(str(e.get("body_plain", "")))
        step = e.get("sequence_step", 1)
        funding = ""
        if e.get("funding_series") or e.get("funding_amount"):
            funding = f"{escape(str(e.get('funding_series', '')))} {escape(str(e.get('funding_amount', '')))}".strip()

        step_badge = {1: "Intro", 2: "Follow-up Day 3", 3: "Final Day 7"}.get(step, f"Step {step}")

        rows.append(f"""
        <tr id="row-{email_id}" class="email-row">
            <td><strong>{company}</strong>{f'<br><small style="color:#888">{funding}</small>' if funding else ''}</td>
            <td>{contact_name}<br><small>{contact_title}</small></td>
            <td><a href="mailto:{contact_email}">{contact_email}</a></td>
            <td><span class="badge badge-step">{step_badge}</span><br><small>{source}</small></td>
            <td>
                <details>
                    <summary style="cursor:pointer;color:#0066cc">{subject}</summary>
                    <div class="email-preview">
                        <textarea id="subject-{email_id}" style="width:100%;margin:4px 0">{escape(str(e.get('subject','')))}</textarea>
                        <textarea id="body-{email_id}" rows="8" style="width:100%">{body}</textarea>
                    </div>
                </details>
            </td>
            <td class="actions">
                <button class="btn btn-approve" onclick="action('{email_id}','approve')">Approve</button>
                <button class="btn btn-edit" onclick="action('{email_id}','edit')">Save Edit</button>
                <button class="btn btn-snooze" onclick="action('{email_id}','snooze')">Snooze</button>
                <button class="btn btn-skip" onclick="action('{email_id}','skip')">Skip</button>
            </td>
        </tr>""")

    return f"""<!DOCTYPE html>
<html>
<head>
    <title>Outreach Review — {len(emails)} drafts</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 20px; background: #f5f5f5; }}
        h1 {{ color: #333; }}
        table {{ border-collapse: collapse; width: 100%; background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        th {{ background: #2c3e50; color: white; padding: 12px 8px; text-align: left; font-size: 13px; }}
        td {{ padding: 10px 8px; border-bottom: 1px solid #eee; vertical-align: top; font-size: 13px; }}
        tr:hover {{ background: #f8f9fa; }}
        .actions {{ white-space: nowrap; }}
        .btn {{ padding: 6px 12px; border: none; border-radius: 4px; cursor: pointer; font-size: 12px; margin: 2px; }}
        .btn-approve {{ background: #27ae60; color: white; }}
        .btn-edit {{ background: #3498db; color: white; }}
        .btn-skip {{ background: #95a5a6; color: white; }}
        .btn-snooze {{ background: #f39c12; color: white; }}
        .btn:hover {{ opacity: 0.85; }}
        .badge {{ padding: 2px 8px; border-radius: 10px; font-size: 11px; }}
        .badge-step {{ background: #eee; color: #555; }}
        .email-preview {{ margin-top: 8px; }}
        textarea {{ font-family: inherit; font-size: 12px; padding: 4px; border: 1px solid #ddd; border-radius: 3px; }}
        .done {{ opacity: 0.3; text-decoration: line-through; }}
        .status-bar {{ background: #2c3e50; color: white; padding: 10px 20px; border-radius: 6px; margin-bottom: 16px; display: flex; justify-content: space-between; }}
        .status-bar span {{ font-size: 14px; }}
        a {{ color: #3498db; }}
    </style>
</head>
<body>
    <h1>Outreach Review</h1>
    <div class="status-bar">
        <span>Drafts: <strong>{len(emails)}</strong></span>
        <span id="approved-count">Approved: 0</span>
        <span id="skipped-count">Skipped: 0</span>
        <span id="snoozed-count">Snoozed: 0</span>
    </div>
    <table>
        <thead>
            <tr><th>Company</th><th>Contact</th><th>Email</th><th>Step / Source</th><th>Email Preview</th><th>Actions</th></tr>
        </thead>
        <tbody>
            {''.join(rows)}
        </tbody>
    </table>

    <script>
        let counts = {{ approved: 0, skipped: 0, snoozed: 0 }};

        async function action(emailId, act) {{
            let body = {{ email_id: emailId, action: act }};
            if (act === 'edit') {{
                body.subject = document.getElementById('subject-' + emailId).value;
                body.body = document.getElementById('body-' + emailId).value;
            }}
            try {{
                const resp = await fetch('/action', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(body)
                }});
                if (resp.ok) {{
                    const row = document.getElementById('row-' + emailId);
                    if (act === 'approve') {{
                        row.classList.add('done');
                        row.style.background = '#e8f5e9';
                        counts.approved++;
                    }} else if (act === 'skip') {{
                        row.classList.add('done');
                        row.style.background = '#eceff1';
                        counts.skipped++;
                    }} else if (act === 'snooze') {{
                        row.classList.add('done');
                        row.style.background = '#fff8e1';
                        counts.snoozed++;
                    }} else if (act === 'edit') {{
                        row.style.background = '#e3f2fd';
                        alert('Saved! Click Approve to finalize.');
                    }}
                    document.getElementById('approved-count').textContent = 'Approved: ' + counts.approved;
                    document.getElementById('skipped-count').textContent = 'Skipped: ' + counts.skipped;
                    document.getElementById('snoozed-count').textContent = 'Snoozed: ' + counts.snoozed;
                }}
            }} catch (err) {{
                alert('Error: ' + err.message);
            }}
        }}
    </script>
</body>
</html>"""


class ReviewHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the review page."""

    db: OutreachDB  # Set by the server factory
    html_content: str = ""

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(self.html_content.encode("utf-8"))

    def do_POST(self) -> None:
        if self.path != "/action":
            self.send_response(404)
            self.end_headers()
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_length))

        email_id = body.get("email_id", "")
        action = body.get("action", "")

        if action == "approve":
            self.db.update_email_status(email_id, "approved")
        elif action == "skip":
            self.db.update_email_status(email_id, "skipped")
        elif action == "snooze":
            self.db.update_email_status(email_id, "snoozed")
        elif action == "edit":
            subject = body.get("subject", "")
            body_text = body.get("body", "")
            body_html = "<p>" + escape(body_text).replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"
            self.db.update_email_content(email_id, subject, body_text, body_html)

        # Sync contact status when all emails reach a terminal state
        if action in ("skip", "snooze"):
            contact_id = self.db.get_contact_id_for_email(email_id)
            if contact_id and self.db.all_emails_terminal_for_contact(contact_id):
                new_status = "skipped" if action == "skip" else "snoozed"
                self.db.update_contact_status(contact_id, new_status)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True}).encode())

    def log_message(self, format, *args) -> None:
        # Suppress default HTTP logs
        pass


def start_review_server(db: OutreachDB) -> None:
    """Start the review HTTP server and open in browser."""
    drafts = db.get_draft_emails()
    if not drafts:
        print("No draft emails to review.")
        return

    print(f"\n  {len(drafts)} draft emails ready for review.")

    html = _build_review_html(drafts)

    # Inject db into handler class
    ReviewHandler.db = db
    ReviewHandler.html_content = html

    server = HTTPServer(("127.0.0.1", REVIEW_PORT), ReviewHandler)
    url = f"http://127.0.0.1:{REVIEW_PORT}"

    print(f"  Review server running at {url}")
    print("  Press Ctrl+C to stop.\n")

    webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
        print("\n  Review server stopped.")
