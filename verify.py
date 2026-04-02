"""
verify.py — Narzędzie weryfikacji i korekty wyników OCR kart szarżowych.

Użycie:
    python verify.py                              # ładuje JSONy z data/output_json/ lub JSONL
    python verify.py --jsonl path/to/file.jsonl   # jawna ścieżka JSONL
    python verify.py --port 5000                  # port (domyślnie 5000)
"""

import argparse
import json
import logging
from pathlib import Path

from flask import Flask, jsonify, request, send_file, abort

from config import QUEUE_DIR, DONE_DIR, OUTPUT_DIR, map_pages
from migrate_v4 import migrate_card, create_db
from schemas.operacje import (
    operacje_pogrupowane,
    mapa_etykiet_surowcow,
    mapa_etykiet_dodatkow,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory state
# ---------------------------------------------------------------------------
CARDS: dict[str, dict] = {}       # card_id → {produkt, nr_partii, sections, images}
VERIFIED_DIR = Path("data/verified")
V4_DB_PATH = Path("data/batch_db_v4.sqlite")


def discover_images(card_id: str) -> dict[str, list[str]]:
    """Find image paths for a card in queue/ or done/."""
    produkt, nr_partii = card_id.split("__", 1)
    for base_dir in [QUEUE_DIR, DONE_DIR]:
        folder = base_dir / produkt / nr_partii
        if folder.exists():
            pages = sorted(
                p for p in folder.iterdir()
                if p.name.startswith("strona_") and p.suffix.lower() in (".png", ".jpg", ".jpeg")
            )
            if pages:
                page_map = map_pages(pages)
                return {
                    section: [str(p) for p in paths]
                    for section, paths in page_map.items()
                }
    return {}


def _ensure_card(card_id: str):
    """Create CARDS entry if it doesn't exist."""
    if card_id not in CARDS:
        parts = card_id.split("__", 1)
        CARDS[card_id] = {
            "produkt": parts[0].replace("_", " "),
            "nr_partii": parts[1].replace("_", "/") if len(parts) > 1 else "",
            "sections": {},
            "images": {},
            "schema_version": "2.0",
        }


def load_jsonl(jsonl_path: Path):
    """Parse JSONL results file into CARDS dict.

    Supports two formats:
    - Legacy: custom_id = produkt__nr_partii__section (3 parts, one result per section)
    - Unified: custom_id = produkt__nr_partii (2 parts, one result with all sections)
    """
    with open(jsonl_path) as f:
        for line in f:
            r = json.loads(line)
            custom_id = r["custom_id"]
            parts = custom_id.split("__")

            # Extract tool_use input
            tool_data = None
            if r["result"]["type"] == "succeeded":
                for block in r["result"]["message"]["content"]:
                    if block["type"] == "tool_use":
                        tool_data = block["input"]
                        break

            if len(parts) >= 3:
                # Legacy format: produkt__nr_partii__section
                card_id = parts[0] + "__" + parts[1]
                section = parts[2]
                _ensure_card(card_id)
                CARDS[card_id]["sections"][section] = tool_data
            elif len(parts) == 2:
                # Unified format: produkt__nr_partii
                card_id = custom_id
                _ensure_card(card_id)
                if tool_data:
                    for section in ["strona1", "proces", "koncowa"]:
                        CARDS[card_id]["sections"][section] = tool_data.get(section)
                else:
                    log.warning("[%s] Brak tool_data w unified result", card_id)
            else:
                log.warning("Pomijam wpis o nieprawidłowym custom_id: %s", custom_id)
                continue

    # Discover images for each card
    for card_id in CARDS:
        CARDS[card_id]["images"] = discover_images(card_id)

    # Load any previously verified data
    for card_id, card in CARDS.items():
        produkt, nr_partii = card_id.split("__", 1)
        for section in ["strona1", "proces", "koncowa"]:
            verified_path = VERIFIED_DIR / produkt / f"{nr_partii}_{section}.json"
            if verified_path.exists():
                card["sections"][section] = json.loads(verified_path.read_text())
                log.info("Załadowano zweryfikowane: %s/%s", card_id, section)

    log.info("Załadowano %d kart z %s", len(CARDS), jsonl_path)


def load_json_files():
    """Load cards from individual JSON files in output_json/{produkt}/{nr_partii}.json."""
    json_files = sorted(OUTPUT_DIR.glob("**/*.json"))
    if not json_files:
        return False

    for json_path in json_files:
        data = json.loads(json_path.read_text())
        produkt = data.get("produkt", "")
        nr_partii = data.get("nr_partii", "")
        if not produkt or not nr_partii:
            log.warning("Pomijam %s — brak produkt/nr_partii", json_path)
            continue

        produkt_folder = produkt.replace(" ", "_")
        nr_partii_folder = nr_partii.replace("/", "_")
        card_id = f"{produkt_folder}__{nr_partii_folder}"

        _ensure_card(card_id)
        CARDS[card_id]["schema_version"] = data.get("_schema_version", "1.0")
        for section in ["strona1", "proces", "koncowa"]:
            if section in data and data[section] is not None:
                CARDS[card_id]["sections"][section] = data[section]

    # Discover images for each card
    for card_id in CARDS:
        CARDS[card_id]["images"] = discover_images(card_id)

    # Load any previously verified data
    for card_id, card in CARDS.items():
        produkt, nr_partii = card_id.split("__", 1)
        for section in ["strona1", "proces", "koncowa"]:
            verified_path = VERIFIED_DIR / produkt / f"{nr_partii}_{section}.json"
            if verified_path.exists():
                card["sections"][section] = json.loads(verified_path.read_text())
                log.info("Załadowano zweryfikowane: %s/%s", card_id, section)

    log.info("Załadowano %d kart z plików JSON w %s", len(CARDS), OUTPUT_DIR)
    return True


def find_jsonl() -> Path | None:
    """Find the most recent JSONL file in output_json/ or done/."""
    for search_dir in [OUTPUT_DIR, DONE_DIR]:
        jsonl_files = sorted(
            search_dir.glob("*.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if jsonl_files:
            return jsonl_files[0]
    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_file("verify_ui.html", max_age=0)


@app.route("/api/kody")
def api_kody():
    return jsonify({
        "operacje": operacje_pogrupowane(),
        "surowce": mapa_etykiet_surowcow(),
        "dodatki": mapa_etykiet_dodatkow(),
    })


@app.route("/api/cards")
def api_cards():
    cards_list = []
    for card_id, card in CARDS.items():
        sections = list(card["sections"].keys())
        # Check which sections have verified files
        produkt, nr_partii = card_id.split("__", 1)
        verified = [
            s for s in ["strona1", "proces", "koncowa"]
            if (VERIFIED_DIR / produkt / f"{nr_partii}_{s}.json").exists()
        ]
        cards_list.append({
            "id": card_id,
            "produkt": card["produkt"],
            "nr_partii": card["nr_partii"],
            "sections": sections,
            "has_images": bool(card["images"]),
            "verified_sections": verified,
        })
    return jsonify(cards_list)


@app.route("/api/cards/<card_id>/<section>")
def api_card_section(card_id, section):
    card = CARDS.get(card_id)
    if not card:
        abort(404, f"Karta {card_id} nie znaleziona")
    data = card["sections"].get(section)
    if data is None:
        abort(404, f"Sekcja {section} nie znaleziona")
    images = card["images"].get(section, [])
    return jsonify({"data": data, "images": images})


VALID_SECTIONS = {"strona1", "proces", "koncowa"}


def _sync_card_to_v4(card_id: str, card: dict):
    """Re-migrate a single card to v4 DB after verification edit."""
    import sqlite3
    if not V4_DB_PATH.exists():
        return
    try:
        db = sqlite3.connect(str(V4_DB_PATH))
        db.execute("PRAGMA foreign_keys=ON")
        # Delete old data for this card
        db.execute("DELETE FROM events WHERE batch_id = ?", (card_id,))
        db.execute("DELETE FROM materials WHERE batch_id = ?", (card_id,))
        db.execute("DELETE FROM batch WHERE batch_id = ?", (card_id,))
        # Re-insert from current in-memory state
        v3_card = {
            "produkt": card["produkt"],
            "nr_partii": card["nr_partii"],
            "strona1": card["sections"].get("strona1", {}),
            "proces": card["sections"].get("proces", {}),
            "koncowa": card["sections"].get("koncowa", {}),
        }
        migrate_card(db, v3_card)
        db.execute("UPDATE batch SET _verified = 1 WHERE batch_id = ?", (card_id,))
        db.commit()
        db.close()
        log.info("Zsynchronizowano v4 DB: %s", card_id)
    except Exception:
        log.exception("Błąd synchronizacji v4 DB dla %s", card_id)


@app.route("/api/cards/<card_id>/<section>", methods=["PUT"])
def api_save_section(card_id, section):
    if section not in VALID_SECTIONS:
        abort(400, f"Nieznana sekcja: {section}")
    card = CARDS.get(card_id)
    if not card:
        abort(404)
    data = request.get_json()
    card["sections"][section] = data

    # Persist to verified dir
    produkt, nr_partii = card_id.split("__", 1)
    save_dir = VERIFIED_DIR / produkt
    save_dir.mkdir(parents=True, exist_ok=True)
    save_path = save_dir / f"{nr_partii}_{section}.json"
    save_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    log.info("Zapisano: %s/%s → %s", card_id, section, save_path)

    # Sync to v4 SQLite
    _sync_card_to_v4(card_id, card)

    return jsonify({"ok": True, "path": str(save_path)})


@app.route("/api/cards/<card_id>/export", methods=["POST"])
def api_export(card_id):
    card = CARDS.get(card_id)
    if not card:
        abort(404)

    output = {
        "produkt": card["produkt"],
        "nr_partii": card["nr_partii"],
        "_schema_version": card.get("schema_version", "2.0"),
    }
    for section in ["strona1", "proces", "koncowa"]:
        output[section] = card["sections"].get(section)

    produkt, nr_partii = card_id.split("__", 1)
    json_dir = OUTPUT_DIR / produkt
    json_dir.mkdir(parents=True, exist_ok=True)
    json_path = json_dir / f"{nr_partii}.json"
    json_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))

    log.info("Eksport: %s → %s", card_id, json_path)
    return jsonify({"ok": True, "path": str(json_path)})


ALLOWED_IMAGE_ROOTS = [QUEUE_DIR.resolve(), DONE_DIR.resolve()]


@app.route("/api/images/<path:filepath>")
def api_image(filepath):
    p = Path(filepath).resolve()
    if not any(str(p).startswith(str(root)) for root in ALLOWED_IMAGE_ROOTS):
        abort(403)
    if not p.exists():
        abort(404)
    return send_file(p, mimetype="image/jpeg")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Weryfikacja wyników OCR kart szarżowych")
    parser.add_argument("--jsonl", default=None, help="Ścieżka do pliku JSONL z wynikami batcha")
    parser.add_argument("--port", type=int, default=5000, help="Port serwera (domyślnie 5000)")
    args = parser.parse_args()

    if args.jsonl:
        jsonl_path = Path(args.jsonl)
        if not jsonl_path.exists():
            log.error("Plik JSONL nie istnieje: %s", jsonl_path)
            return
        load_jsonl(jsonl_path)
    else:
        # Try individual JSON files first (produced by cmd_collect)
        if load_json_files():
            pass
        else:
            # Fallback to JSONL
            jsonl_path = find_jsonl()
            if jsonl_path:
                load_jsonl(jsonl_path)
            else:
                log.error(
                    "Brak danych. Umieść pliki JSON w %s lub JSONL w %s/%s",
                    OUTPUT_DIR, OUTPUT_DIR, DONE_DIR,
                )
                return

    if not CARDS:
        log.error("Nie załadowano żadnych kart.")
        return

    import socket
    local_ip = socket.gethostbyname(socket.gethostname())
    log.info("Serwer: http://localhost:%d  |  sieć lokalna: http://%s:%d", args.port, local_ip, args.port)
    app.run(host="0.0.0.0", port=args.port, debug=True)


if __name__ == "__main__":
    main()
