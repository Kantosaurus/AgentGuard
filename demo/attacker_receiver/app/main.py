"""Existing /exfil and /health routes."""
from __future__ import annotations

from flask import Blueprint, request

bp = Blueprint("main", __name__)


@bp.post("/exfil")
def exfil():
    body = request.get_data(as_text=True)
    print(f"POST /exfil len={len(body)}", flush=True)
    return {"ok": True}


@bp.get("/health")
def health():
    return {"ok": True}
