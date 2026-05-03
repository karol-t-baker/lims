from flask import Blueprint

produkt_pola_bp = Blueprint('produkt_pola', __name__)

from mbr.produkt_pola import routes  # noqa: E402, F401
