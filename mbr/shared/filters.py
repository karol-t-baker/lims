"""
filters.py — Jinja2 template filters for MBR/EBR webapp.
"""

from datetime import datetime


def pl_date_filter(value):
    """Format ISO date to Polish: DD.MM.YYYY HH:MM"""
    if not value:
        return '\u2014'
    try:
        dt = datetime.fromisoformat(str(value))
        return dt.strftime('%d.%m.%Y %H:%M')
    except Exception:
        return str(value)[:16]


def pl_date_short_filter(value):
    """Format ISO date to Polish short: DD.MM.YYYY"""
    if not value:
        return '\u2014'
    try:
        dt = datetime.fromisoformat(str(value))
        return dt.strftime('%d.%m.%Y')
    except Exception:
        return str(value)[:10]


def fmt_kg_filter(value):
    """Format kg: 23444.0 -> 23 444"""
    if not value:
        return '\u2014'
    try:
        v = int(float(value))
        return f'{v:,}'.replace(',', ' ')
    except Exception:
        return str(value)


def short_product_filter(value):
    """Chegina_K40GLOL -> K40GLOL, Chegina_K7 -> K7"""
    if not value:
        return ''
    return str(value).replace('Chegina_', '').replace('Chegina ', '')


def register_filters(app):
    app.add_template_filter(pl_date_filter, 'pl_date')
    app.add_template_filter(pl_date_short_filter, 'pl_date_short')
    app.add_template_filter(fmt_kg_filter, 'fmt_kg')
    app.add_template_filter(short_product_filter, 'short_product')
