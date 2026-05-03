"""GET /docs/<slug> — serves canned (poisoned) content."""
from __future__ import annotations

from pathlib import Path

from flask import Blueprint, abort, send_file

bp = Blueprint("docs", __name__)

_DOCS_DIR = Path(__file__).parent / "content" / "docs"

_SLUG_TO_FILE = {
    "q2-plan": ("q2-plan.txt", "text/plain; charset=utf-8"),
    "support-ticket-1234": ("support-ticket-1234.html", "text/html; charset=utf-8"),
    "meeting-notes": ("meeting-notes.md", "text/markdown; charset=utf-8"),
    "api-docs": ("api-docs.html", "text/html; charset=utf-8"),
}


@bp.get("/docs/<slug>")
def doc(slug: str):
    entry = _SLUG_TO_FILE.get(slug)
    if entry is None:
        abort(404)
    filename, mime = entry
    return send_file(_DOCS_DIR / filename, mimetype=mime)
