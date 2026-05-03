"""GET /search?q=… — returns 3 fake results, one poisoned."""
from __future__ import annotations

import json
from pathlib import Path

from flask import Blueprint, abort, jsonify, request

bp = Blueprint("search", __name__)

_INDEX_PATH = Path(__file__).parent / "content" / "search_index.json"


def _load_index() -> dict:
    return json.loads(_INDEX_PATH.read_text(encoding="utf-8"))


def _match_key(query: str, index: dict) -> str:
    q = query.lower().strip()
    for key in index:
        if key == "_default":
            continue
        if key.lower() in q:
            return key
    return "_default"


@bp.get("/search")
def search():
    q = request.args.get("q")
    if not q:
        abort(400, "missing query parameter q")
    index = _load_index()
    return jsonify(index[_match_key(q, index)])
