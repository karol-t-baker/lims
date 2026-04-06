from flask import Blueprint

admin_bp = Blueprint("admin", __name__)

from mbr.admin import routes  # noqa: E402, F401
