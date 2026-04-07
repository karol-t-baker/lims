from flask import Blueprint
zbiorniki_bp = Blueprint('zbiorniki', __name__)
from mbr.zbiorniki import routes  # noqa: E402, F401
