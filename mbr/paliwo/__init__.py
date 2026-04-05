from flask import Blueprint
paliwo_bp = Blueprint('paliwo', __name__)
from mbr.paliwo import routes  # noqa: E402, F401
