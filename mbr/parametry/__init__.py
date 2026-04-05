from flask import Blueprint
parametry_bp = Blueprint('parametry', __name__)
from mbr.parametry import routes  # noqa: E402, F401
