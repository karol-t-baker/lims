from flask import Blueprint

admin_bp = Blueprint("admin", __name__)

from mbr.admin import routes  # noqa: E402, F401
from mbr.admin import audit_routes  # noqa: E402, F401
