"""ChZT ścieków — sessions, autosave pomiary, historia, finalize."""

from flask import Blueprint

chzt_bp = Blueprint(
    "chzt",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/chzt/static",
)

from mbr.chzt import routes  # noqa: E402, F401
