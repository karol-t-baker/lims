from flask import Blueprint
technolog_bp = Blueprint('technolog', __name__)
from mbr.technolog import routes  # noqa: E402, F401
