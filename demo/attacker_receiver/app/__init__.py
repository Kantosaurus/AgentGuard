"""Attacker receiver: /exfil + /health, plus /search + /docs (added later)."""
from flask import Flask

from .docs import bp as docs_bp
from .main import bp as main_bp
from .search import bp as search_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.register_blueprint(main_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(docs_bp)
    return app
