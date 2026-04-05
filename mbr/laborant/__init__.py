from flask import Blueprint
laborant_bp = Blueprint('laborant', __name__)
from mbr.laborant import routes  # noqa: E402, F401
