from flask import Blueprint

ml_export_bp = Blueprint("ml_export", __name__)

from mbr.ml_export import routes  # noqa: E402, F401
