from flask import Blueprint
etapy_bp = Blueprint('etapy', __name__)
from mbr.etapy import routes  # noqa: E402, F401
