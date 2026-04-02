"""Generate batch card PDF from MBR template + EBR data."""
import json
from flask import render_template


def generate_pdf(mbr, ebr=None, wyniki=None):
    """Generate PDF bytes for a batch card.
    mbr: dict from mbr_templates (with etapy_json, parametry_lab as JSON strings)
    ebr: dict from ebr_batches (optional — if None, generates empty card)
    wyniki: dict {sekcja: {kod: row_dict}} (optional)
    """
    from weasyprint import HTML

    etapy = json.loads(mbr["etapy_json"])
    parametry = json.loads(mbr["parametry_lab"])
    html = render_template("pdf/karta_base.html",
                           mbr=mbr, ebr=ebr, wyniki=wyniki or {},
                           etapy=etapy, parametry=parametry)
    return HTML(string=html).write_pdf()
