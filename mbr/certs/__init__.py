from flask import Blueprint
certs_bp = Blueprint('certs', __name__)
from mbr.certs import routes  # noqa: E402, F401
