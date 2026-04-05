"""
context.py — Jinja2 context processors for MBR/EBR webapp.
"""

from datetime import datetime

from mbr.models import PRODUCTS


def inject_globals():
    return {
        'today': datetime.now().strftime('%d.%m.%Y'),
        'products': PRODUCTS,
        'main_products': ['Chegina_K7', 'Chegina_K40GL', 'Chegina_K40GLO', 'Chegina_K40GLOL'],
    }


def register_context(app):
    app.context_processor(inject_globals)
