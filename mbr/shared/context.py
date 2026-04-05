"""
context.py — Jinja2 context processors for MBR/EBR webapp.
"""

import time
from datetime import datetime

from mbr.models import PRODUCTS

_CACHE_BUST = str(int(time.time()))


def inject_globals():
    return {
        'today': datetime.now().strftime('%d.%m.%Y'),
        'products': PRODUCTS,
        'main_products': ['Chegina_K7', 'Chegina_K40GL', 'Chegina_K40GLO', 'Chegina_K40GLOL'],
        'v': _CACHE_BUST,
    }


def register_context(app):
    app.context_processor(inject_globals)
