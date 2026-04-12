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


def audit_actors_filter(audit_row):
    """Render actors with full name on hover.

    Shows nickname/inicjaly as text, full imie+nazwisko as title tooltip.
    """
    from markupsafe import Markup
    actors = audit_row.get("actors") or []
    if not actors:
        return Markup("\u2014")
    parts = []
    for a in actors:
        login = a["actor_login"]
        name = a.get("actor_name")
        if name:
            parts.append(f'<span title="{name}">{login}</span>')
        else:
            parts.append(login)
    return Markup(", ".join(parts))


def register_filters(app):
    app.add_template_filter(pl_date_filter, 'pl_date')
    app.add_template_filter(pl_date_short_filter, 'pl_date_short')
    app.add_template_filter(fmt_kg_filter, 'fmt_kg')
    app.add_template_filter(short_product_filter, 'short_product')
    app.add_template_filter(audit_actors_filter, 'audit_actors')
