"""Fuel reimbursement form generator (wniosek o zwrot kosztów paliwa)."""

import calendar
import io
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from mbr.shared.timezone import app_now_iso

import requests
from docxtpl import DocxTemplate
from num2words import num2words

# ---------------------------------------------------------------------------
# Configuration (global constants — easy to change)
# ---------------------------------------------------------------------------
RYCZALT = 345.00
STAWKA_DZIENNA = 15.68  # 345/22
LIMIT_KM = 300

GOTENBERG_URL = "http://localhost:3000"
_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "paliwo_temp.docx"

MIESIACE = {
    1: 'styczeń', 2: 'luty', 3: 'marzec', 4: 'kwiecień',
    5: 'maj', 6: 'czerwiec', 7: 'lipiec', 8: 'sierpień',
    9: 'wrzesień', 10: 'październik', 11: 'listopad', 12: 'grudzień'
}


# ---------------------------------------------------------------------------
# Database — osoby
# ---------------------------------------------------------------------------
def init_paliwo_tables(db: sqlite3.Connection):
    db.execute("""
        CREATE TABLE IF NOT EXISTS paliwo_osoby (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            imie_nazwisko TEXT NOT NULL,
            stanowisko TEXT NOT NULL,
            nr_rejestracyjny TEXT NOT NULL,
            aktywny INTEGER DEFAULT 1,
            dt_dodania TEXT
        )
    """)
    db.commit()


def list_osoby(db: sqlite3.Connection, only_active=True) -> list[dict]:
    sql = "SELECT * FROM paliwo_osoby"
    if only_active:
        sql += " WHERE aktywny = 1"
    sql += " ORDER BY imie_nazwisko"
    return [dict(r) for r in db.execute(sql).fetchall()]


def get_osoba(db: sqlite3.Connection, osoba_id: int) -> dict | None:
    row = db.execute("SELECT * FROM paliwo_osoby WHERE id = ?", (osoba_id,)).fetchone()
    return dict(row) if row else None


def add_osoba(db: sqlite3.Connection, imie_nazwisko: str, stanowisko: str, nr_rejestracyjny: str) -> int:
    cur = db.execute(
        "INSERT INTO paliwo_osoby (imie_nazwisko, stanowisko, nr_rejestracyjny, dt_dodania) VALUES (?, ?, ?, ?)",
        (imie_nazwisko, stanowisko, nr_rejestracyjny, app_now_iso())
    )
    db.commit()
    return cur.lastrowid


def update_osoba(db: sqlite3.Connection, osoba_id: int, imie_nazwisko: str, stanowisko: str, nr_rejestracyjny: str):
    db.execute(
        "UPDATE paliwo_osoby SET imie_nazwisko=?, stanowisko=?, nr_rejestracyjny=? WHERE id=?",
        (imie_nazwisko, stanowisko, nr_rejestracyjny, osoba_id)
    )
    db.commit()


def delete_osoba(db: sqlite3.Connection, osoba_id: int):
    db.execute("UPDATE paliwo_osoby SET aktywny = 0 WHERE id = ?", (osoba_id,))
    db.commit()


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def last_workday(year: int, month: int) -> date:
    """Last Mon-Fri day of the given month."""
    last_day = date(year, month, calendar.monthrange(year, month)[1])
    while last_day.weekday() >= 5:
        last_day -= timedelta(days=1)
    return last_day


def kwota_slownie(amount: float) -> str:
    """Convert amount to Polish words: '313,64' → 'trzysta trzynaście złotych sześćdziesiąt cztery grosze'."""
    zlote = int(amount)
    grosze = round((amount - zlote) * 100)
    parts = []
    if zlote > 0:
        zl_words = num2words(zlote, lang='pl')
        zl_label = 'złotych' if zlote >= 5 or zlote == 0 else 'złote' if 2 <= zlote <= 4 else 'złoty'
        parts.append(f"{zl_words} {zl_label}")
    else:
        parts.append("zero złotych")
    if grosze > 0:
        gr_words = num2words(grosze, lang='pl')
        gr_label = 'groszy' if grosze >= 5 or grosze == 0 else 'grosze' if 2 <= grosze <= 4 else 'grosz'
        parts.append(f"{gr_words} {gr_label}")
    return " ".join(parts)


def format_pln(amount: float) -> str:
    """Format as Polish currency: 313.64 → '313,64'."""
    return f"{amount:,.2f}".replace(",", " ").replace(".", ",").replace(" ", "")


def calculate(dni_urlopu: int) -> dict:
    """Calculate all amounts for the form."""
    potracenie = round(dni_urlopu * STAWKA_DZIENNA, 2)
    ryczalt_do_wyplaty = round(RYCZALT - potracenie, 2)
    return {
        'ryczalt': format_pln(RYCZALT),
        'stawka_dzienna': format_pln(STAWKA_DZIENNA),
        'limit_km': str(LIMIT_KM),
        'dni_urlopu': str(dni_urlopu),
        'potracenie': format_pln(potracenie),
        'ryczalt_do_wyplaty': format_pln(ryczalt_do_wyplaty),
        'kwota_slownie': kwota_slownie(ryczalt_do_wyplaty),
    }


# ---------------------------------------------------------------------------
# PDF generation
# ---------------------------------------------------------------------------
def _build_person_context(osoba: dict, dni_urlopu: int, year: int, month: int, suffix: str = '') -> dict:
    """Build template context for one person (optionally with _2 suffix for second person)."""
    data_wystawienia = last_workday(year, month)
    miesiac = MIESIACE[month]
    calc = calculate(dni_urlopu)

    ctx = {
        'imie_nazwisko': osoba['imie_nazwisko'],
        'data_wystawienia': data_wystawienia.strftime('%d.%m.%Y'),
        'stanowisko': osoba['stanowisko'],
        'nr_rejestracyjny': osoba['nr_rejestracyjny'],
        'miesiac': miesiac,
        'miesiac_ryczalt': miesiac,
        **calc,
    }
    if suffix:
        return {f"{k}{suffix}": v for k, v in ctx.items()}
    return ctx


def _hide_second_person(doc):
    """Set font color to white for the second person's section.

    The template has two identical halves. After rendering with same data,
    find the midpoint (second occurrence of the rendered date string)
    and set all runs from there onward to white (#FFFFFF).
    """
    from lxml import etree
    WNS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'

    # The first paragraph is always the date (data_wystawienia).
    # Find its rendered text, then locate the second occurrence.
    first_text = doc.paragraphs[0].text.strip() if doc.paragraphs else ''
    start_idx = None
    for i, para in enumerate(doc.paragraphs):
        if i == 0:
            continue
        if para.text.strip() == first_text and first_text:
            start_idx = i
            break

    if start_idx is None:
        return

    for para in doc.paragraphs[start_idx:]:
        for run in para.runs:
            rpr = run._element.find(f'{{{WNS}}}rPr')
            if rpr is None:
                rpr = etree.SubElement(run._element, f'{{{WNS}}}rPr')
                run._element.insert(0, rpr)
            color = rpr.find(f'{{{WNS}}}color')
            if color is None:
                color = etree.SubElement(rpr, f'{{{WNS}}}color')
            color.set(f'{{{WNS}}}val', 'FFFFFF')


def generate_pdf(osoby: list[dict], dni_list: list[int], year: int = None, month: int = None) -> bytes:
    """Generate fuel reimbursement PDF for 1 or 2 persons.

    Uses single template (paliwo_temp.docx) with two person sections.
    When only 1 person, fills second section with same data but white font.

    Args:
        osoby: list of 1 or 2 person dicts
        dni_list: list of leave days per person (same length as osoby)
        year, month: override (default: current month)

    Returns:
        PDF bytes
    """
    today = date.today()
    if year is None:
        year = today.year
    if month is None:
        month = today.month

    context = _build_person_context(osoby[0], dni_list[0], year, month)
    if len(osoby) >= 2:
        context.update(_build_person_context(osoby[1], dni_list[1], year, month, suffix='_2'))
    else:
        # Single person — fill second section with same data (will be hidden with white font)
        context.update(_build_person_context(osoby[0], dni_list[0], year, month, suffix='_2'))

    tpl = DocxTemplate(str(_TEMPLATE_PATH))
    tpl.render(context)

    # When single person, hide second section with white font
    if len(osoby) == 1:
        _hide_second_person(tpl.docx)

    buf = io.BytesIO()
    tpl.save(buf)

    resp = requests.post(
        f"{GOTENBERG_URL}/forms/libreoffice/convert",
        files={"files": ("wniosek.docx", buf.getvalue(),
                         "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.content
