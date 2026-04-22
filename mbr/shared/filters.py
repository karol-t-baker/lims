"""
filters.py — Jinja2 template filters for MBR/EBR webapp.
"""

import re as _re
from datetime import datetime

from markupsafe import Markup, escape

from mbr.shared.timezone import to_app_tz


_RT_MARKUP_RE = _re.compile(r'(\^\{[^}]*\}|_\{[^}]*\})')


def rt_html_filter(value):
    """Render ^{sup}/_{sub} markup in parameter labels as HTML <sup>/<sub>.

    Mirrors rtHtml() in static/lab_common.js and _md_to_richtext in
    mbr/certs/generator.py — same markup across editor, laborant UI, PDF
    cards, and certificates. All surrounding text is escaped; only the
    marker pairs produce HTML tags.
    """
    if value is None or value == "":
        return Markup("")
    s = str(value)
    out = []
    last = 0
    for m in _RT_MARKUP_RE.finditer(s):
        if m.start() > last:
            out.append(str(escape(s[last:m.start()])))
        inner = m.group()[2:-1]
        tag = "sup" if m.group()[0] == "^" else "sub"
        out.append(f"<{tag}>{escape(inner)}</{tag}>")
        last = m.end()
    if last < len(s):
        out.append(str(escape(s[last:])))
    return Markup("".join(out))


def parse_decimal(value, default=0.0):
    """Parse numeric string accepting both comma and dot as decimal separator."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return default
    s = s.replace(",", ".")
    try:
        return float(s)
    except (ValueError, TypeError):
        return default


def fmt_decimal_filter(value, places=None):
    """Format number with Polish decimal comma: 3.14 → '3,14'.

    places=None preserves original precision, places=N forces N decimal places.
    """
    if value is None or value == "":
        return "—"
    try:
        v = float(str(value).replace(",", "."))
    except (ValueError, TypeError):
        return str(value)
    if places is not None:
        return f"{v:.{int(places)}f}".replace(".", ",")
    return str(v).replace(".", ",")


def pl_date_filter(value):
    """Format ISO date to Polish: DD.MM.YYYY HH:MM (Europe/Warsaw)."""
    if not value:
        return '\u2014'
    try:
        dt = to_app_tz(value)
        return dt.strftime('%d.%m.%Y %H:%M') if dt else '—'
    except Exception:
        return str(value)[:16]


def pl_date_short_filter(value):
    """Format ISO date to Polish short: DD.MM.YYYY (Europe/Warsaw)."""
    if not value:
        return '\u2014'
    try:
        dt = to_app_tz(value)
        return dt.strftime('%d.%m.%Y') if dt else '—'
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
    app.add_template_filter(fmt_decimal_filter, 'fmt_decimal')
    app.add_template_filter(short_product_filter, 'short_product')
    app.add_template_filter(audit_actors_filter, 'audit_actors')
    app.add_template_filter(rt_html_filter, 'rt_html')
