import sqlite3
import pytest
from mbr.models import init_mbr_tables


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_mbr_tables(conn)
    yield conn
    conn.close()


def test_new_pipeline_tables_exist(db):
    tables = [r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    for t in [
        "etapy_analityczne", "etap_parametry", "produkt_pipeline",
        "produkt_etap_limity", "etap_warunki", "etap_korekty_katalog",
        "ebr_etap_sesja", "ebr_pomiar", "ebr_korekta_v2",
    ]:
        assert t in tables, f"Missing table: {t}"


def test_etapy_analityczne_columns(db):
    cols = [r[1] for r in db.execute("PRAGMA table_info(etapy_analityczne)").fetchall()]
    assert "kod" in cols
    assert "typ_cyklu" in cols
    assert "aktywny" in cols


def test_etapy_analityczne_unique_kod(db):
    db.execute("INSERT INTO etapy_analityczne (kod, nazwa) VALUES ('test', 'Test')")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO etapy_analityczne (kod, nazwa) VALUES ('test', 'Test2')")


def test_etap_parametry_fk(db):
    db.execute("INSERT INTO etapy_analityczne (id, kod, nazwa) VALUES (1, 'amid', 'Amid')")
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (9999, 'ph_test', 'pH', 'bezposredni')")
    db.execute("INSERT INTO etap_parametry (etap_id, parametr_id, kolejnosc) VALUES (1, 9999, 1)")
    row = db.execute("SELECT * FROM etap_parametry WHERE etap_id=1").fetchone()
    assert row is not None


def test_ebr_etap_sesja_unique_constraint(db):
    db.execute("INSERT INTO etapy_analityczne (id, kod, nazwa) VALUES (1, 'amid', 'Amid')")
    db.execute("""INSERT INTO mbr_templates (mbr_id, produkt, wersja, dt_utworzenia)
                  VALUES (1, 'Test', 1, '2026-01-01')""")
    db.execute("""INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, dt_start)
                  VALUES (1, 1, 'T-1', '1/2026', '2026-01-01')""")
    db.execute("""INSERT INTO ebr_etap_sesja (ebr_id, etap_id, runda) VALUES (1, 1, 1)""")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("""INSERT INTO ebr_etap_sesja (ebr_id, etap_id, runda) VALUES (1, 1, 1)""")


def test_ebr_pomiar_unique_constraint(db):
    db.execute("INSERT INTO etapy_analityczne (id, kod, nazwa) VALUES (1, 'amid', 'Amid')")
    db.execute("INSERT INTO parametry_analityczne (id, kod, label, typ) VALUES (9999, 'ph_test', 'pH', 'bezposredni')")
    db.execute("""INSERT INTO mbr_templates (mbr_id, produkt, wersja, dt_utworzenia)
                  VALUES (1, 'Test', 1, '2026-01-01')""")
    db.execute("""INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, dt_start)
                  VALUES (1, 1, 'T-1', '1/2026', '2026-01-01')""")
    db.execute("INSERT INTO ebr_etap_sesja (id, ebr_id, etap_id, runda) VALUES (1, 1, 1, 1)")
    db.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, dt_wpisu, wpisal) VALUES (1, 9999, 7.5, '2026-01-01', 'lab1')")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO ebr_pomiar (sesja_id, parametr_id, wartosc, dt_wpisu, wpisal) VALUES (1, 9999, 7.6, '2026-01-01', 'lab1')")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _seed_param(db, pid=9001, kod="ph", label="pH", typ="bezposredni"):
    db.execute(
        "INSERT OR IGNORE INTO parametry_analityczne (id, kod, label, typ) VALUES (?,?,?,?)",
        (pid, kod, label, typ),
    )
    return pid


# ---------------------------------------------------------------------------
# Task 2: Catalog CRUD — etapy_analityczne
# ---------------------------------------------------------------------------

def test_create_etap(db):
    from mbr.pipeline.models import create_etap, get_etap
    eid = create_etap(db, kod="amid", nazwa="Amidowanie")
    assert isinstance(eid, int) and eid > 0
    row = get_etap(db, eid)
    assert row is not None
    assert row["kod"] == "amid"
    assert row["nazwa"] == "Amidowanie"
    assert row["typ_cyklu"] == "jednorazowy"
    assert row["aktywny"] == 1


def test_create_etap_duplicate_kod_raises(db):
    from mbr.pipeline.models import create_etap
    create_etap(db, kod="amid", nazwa="Amidowanie")
    with pytest.raises(sqlite3.IntegrityError):
        create_etap(db, kod="amid", nazwa="Dup")


def test_list_etapy(db):
    from mbr.pipeline.models import create_etap, list_etapy
    create_etap(db, kod="amid", nazwa="Amidowanie", kolejnosc_domyslna=2)
    create_etap(db, kod="czwart", nazwa="Czwartorzędowanie", kolejnosc_domyslna=1)
    rows = list_etapy(db)
    assert len(rows) == 2
    # ordered by kolejnosc_domyslna
    assert rows[0]["kod"] == "czwart"
    assert rows[1]["kod"] == "amid"


def test_list_etapy_only_active(db):
    from mbr.pipeline.models import create_etap, deactivate_etap, list_etapy
    eid1 = create_etap(db, kod="amid", nazwa="Amidowanie")
    create_etap(db, kod="czwart", nazwa="Czwartorzędowanie")
    deactivate_etap(db, eid1)
    active = list_etapy(db, only_active=True)
    kody = [r["kod"] for r in active]
    assert "amid" not in kody
    assert "czwart" in kody


def test_get_etap_missing(db):
    from mbr.pipeline.models import get_etap
    assert get_etap(db, 9999) is None


def test_update_etap(db):
    from mbr.pipeline.models import create_etap, update_etap, get_etap
    eid = create_etap(db, kod="amid", nazwa="Amidowanie")
    update_etap(db, eid, nazwa="Amidowanie v2", typ_cyklu="cykliczny")
    row = get_etap(db, eid)
    assert row["nazwa"] == "Amidowanie v2"
    assert row["typ_cyklu"] == "cykliczny"


def test_deactivate_etap(db):
    from mbr.pipeline.models import create_etap, deactivate_etap, get_etap
    eid = create_etap(db, kod="amid", nazwa="Amidowanie")
    deactivate_etap(db, eid)
    row = get_etap(db, eid)
    assert row["aktywny"] == 0


# ---------------------------------------------------------------------------
# Task 2: Catalog CRUD — etap_parametry
# ---------------------------------------------------------------------------

def test_add_list_remove_etap_parametr(db):
    from mbr.pipeline.models import (
        create_etap, add_etap_parametr, list_etap_parametry, remove_etap_parametr,
    )
    eid = create_etap(db, kod="amid", nazwa="Amidowanie")
    _seed_param(db, pid=9001, kod="ph", label="pH")
    _seed_param(db, pid=9002, kod="nd20", label="nd20")

    ep1 = add_etap_parametr(db, eid, 9002, kolejnosc=10)
    ep2 = add_etap_parametr(db, eid, 9001, kolejnosc=5)

    rows = list_etap_parametry(db, eid)
    # ORDER BY kolejnosc — ep2 (nd20 at 10) comes second, ph (5) first
    assert len(rows) == 2
    assert rows[0]["kod"] == "ph"    # kolejnosc=5
    assert rows[1]["kod"] == "nd20"  # kolejnosc=10

    remove_etap_parametr(db, ep1)
    rows = list_etap_parametry(db, eid)
    assert len(rows) == 1
    assert rows[0]["kod"] == "ph"


def test_list_etap_parametry_joins(db):
    from mbr.pipeline.models import create_etap, add_etap_parametr, list_etap_parametry
    eid = create_etap(db, kod="amid", nazwa="Amidowanie")
    _seed_param(db, pid=9001, kod="ph", label="pH", typ="bezposredni")
    add_etap_parametr(db, eid, 9001, min_limit=6.0, max_limit=8.0)
    rows = list_etap_parametry(db, eid)
    assert rows[0]["label"] == "pH"
    assert rows[0]["typ"] == "bezposredni"
    assert rows[0]["min_limit"] == 6.0
    assert rows[0]["max_limit"] == 8.0


def test_update_etap_parametr(db):
    from mbr.pipeline.models import create_etap, add_etap_parametr, update_etap_parametr, list_etap_parametry
    eid = create_etap(db, kod="amid", nazwa="Amidowanie")
    _seed_param(db, pid=9001, kod="ph", label="pH")
    ep_id = add_etap_parametr(db, eid, 9001, min_limit=5.0)
    update_etap_parametr(db, ep_id, min_limit=6.5, max_limit=8.0)
    rows = list_etap_parametry(db, eid)
    assert rows[0]["min_limit"] == 6.5
    assert rows[0]["max_limit"] == 8.0


# ---------------------------------------------------------------------------
# Task 2: Catalog CRUD — etap_warunki
# ---------------------------------------------------------------------------

def test_add_list_remove_etap_warunek(db):
    from mbr.pipeline.models import (
        create_etap, add_etap_warunek, list_etap_warunki, remove_etap_warunek,
    )
    eid = create_etap(db, kod="amid", nazwa="Amidowanie")
    _seed_param(db, pid=9001, kod="ph", label="pH")

    wid = add_etap_warunek(db, eid, 9001, operator=">=", wartosc=7.0, opis_warunku="pH ok")
    rows = list_etap_warunki(db, eid)
    assert len(rows) == 1
    assert rows[0]["operator"] == ">="
    assert rows[0]["wartosc"] == 7.0
    assert rows[0]["kod"] == "ph"

    remove_etap_warunek(db, wid)
    assert list_etap_warunki(db, eid) == []


def test_add_etap_warunek_between(db):
    from mbr.pipeline.models import create_etap, add_etap_warunek, list_etap_warunki
    eid = create_etap(db, kod="amid", nazwa="Amidowanie")
    _seed_param(db, pid=9001, kod="ph", label="pH")
    add_etap_warunek(db, eid, 9001, operator="between", wartosc=6.0, wartosc_max=8.0)
    rows = list_etap_warunki(db, eid)
    assert rows[0]["wartosc"] == 6.0
    assert rows[0]["wartosc_max"] == 8.0


# ---------------------------------------------------------------------------
# Task 2: Catalog CRUD — etap_korekty_katalog
# ---------------------------------------------------------------------------

def test_add_list_remove_etap_korekta(db):
    from mbr.pipeline.models import (
        create_etap, add_etap_korekta, list_etap_korekty, remove_etap_korekta,
    )
    eid = create_etap(db, kod="amid", nazwa="Amidowanie")

    kid = add_etap_korekta(db, eid, substancja="NaOH", jednostka="kg", wykonawca="produkcja", kolejnosc=1)
    rows = list_etap_korekty(db, eid)
    assert len(rows) == 1
    assert rows[0]["substancja"] == "NaOH"
    assert rows[0]["jednostka"] == "kg"
    assert rows[0]["wykonawca"] == "produkcja"

    remove_etap_korekta(db, kid)
    assert list_etap_korekty(db, eid) == []


def test_etap_korekty_order_by_kolejnosc(db):
    from mbr.pipeline.models import create_etap, add_etap_korekta, list_etap_korekty
    eid = create_etap(db, kod="amid", nazwa="Amidowanie")
    add_etap_korekta(db, eid, substancja="B", kolejnosc=2)
    add_etap_korekta(db, eid, substancja="A", kolejnosc=1)
    rows = list_etap_korekty(db, eid)
    assert rows[0]["substancja"] == "A"
    assert rows[1]["substancja"] == "B"


# ---------------------------------------------------------------------------
# Task 3: Product pipeline CRUD
# ---------------------------------------------------------------------------

def test_set_get_remove_produkt_pipeline(db):
    from mbr.pipeline.models import (
        create_etap, set_produkt_pipeline, get_produkt_pipeline, remove_pipeline_etap,
    )
    eid1 = create_etap(db, kod="amid", nazwa="Amidowanie")
    eid2 = create_etap(db, kod="czwart", nazwa="Czwartorzędowanie")

    set_produkt_pipeline(db, "K7", eid1, kolejnosc=1)
    set_produkt_pipeline(db, "K7", eid2, kolejnosc=2)

    rows = get_produkt_pipeline(db, "K7")
    assert len(rows) == 2
    assert rows[0]["kod"] == "amid"
    assert rows[1]["kod"] == "czwart"

    remove_pipeline_etap(db, "K7", eid1)
    rows = get_produkt_pipeline(db, "K7")
    assert len(rows) == 1
    assert rows[0]["kod"] == "czwart"


def test_set_produkt_pipeline_upsert(db):
    from mbr.pipeline.models import create_etap, set_produkt_pipeline, get_produkt_pipeline
    eid = create_etap(db, kod="amid", nazwa="Amidowanie")
    set_produkt_pipeline(db, "K7", eid, kolejnosc=1)
    set_produkt_pipeline(db, "K7", eid, kolejnosc=5)  # update kolejnosc
    rows = get_produkt_pipeline(db, "K7")
    assert rows[0]["kolejnosc"] == 5


def test_reorder_pipeline(db):
    from mbr.pipeline.models import (
        create_etap, set_produkt_pipeline, reorder_pipeline, get_produkt_pipeline,
    )
    eid1 = create_etap(db, kod="amid", nazwa="Amidowanie")
    eid2 = create_etap(db, kod="czwart", nazwa="Czwartorzędowanie")
    eid3 = create_etap(db, kod="sulf", nazwa="Sulfonowanie")
    set_produkt_pipeline(db, "K7", eid1, kolejnosc=1)
    set_produkt_pipeline(db, "K7", eid2, kolejnosc=2)
    set_produkt_pipeline(db, "K7", eid3, kolejnosc=3)

    # Reverse order
    reorder_pipeline(db, "K7", [eid3, eid2, eid1])
    rows = get_produkt_pipeline(db, "K7")
    assert rows[0]["kod"] == "sulf"
    assert rows[1]["kod"] == "czwart"
    assert rows[2]["kod"] == "amid"


def test_set_get_remove_produkt_etap_limit(db):
    from mbr.pipeline.models import (
        create_etap, set_produkt_pipeline, set_produkt_etap_limit,
        get_produkt_etap_limity, remove_produkt_etap_limit,
    )
    eid = create_etap(db, kod="amid", nazwa="Amidowanie")
    _seed_param(db, pid=9001, kod="ph", label="pH")
    set_produkt_pipeline(db, "K7", eid, kolejnosc=1)

    set_produkt_etap_limit(db, "K7", eid, 9001, min_limit=6.5, max_limit=7.5)
    rows = get_produkt_etap_limity(db, "K7", eid)
    assert len(rows) == 1
    assert rows[0]["min_limit"] == 6.5
    assert rows[0]["max_limit"] == 7.5
    assert rows[0]["kod"] == "ph"

    remove_produkt_etap_limit(db, "K7", eid, 9001)
    assert get_produkt_etap_limity(db, "K7", eid) == []


def test_set_produkt_etap_limit_upsert(db):
    from mbr.pipeline.models import (
        create_etap, set_produkt_pipeline, set_produkt_etap_limit, get_produkt_etap_limity,
    )
    eid = create_etap(db, kod="amid", nazwa="Amidowanie")
    _seed_param(db, pid=9001, kod="ph", label="pH")
    set_produkt_pipeline(db, "K7", eid, kolejnosc=1)

    set_produkt_etap_limit(db, "K7", eid, 9001, min_limit=6.0, max_limit=8.0)
    set_produkt_etap_limit(db, "K7", eid, 9001, min_limit=6.5)  # partial update
    rows = get_produkt_etap_limity(db, "K7", eid)
    assert rows[0]["min_limit"] == 6.5


def test_resolve_limity_no_overrides(db):
    from mbr.pipeline.models import (
        create_etap, add_etap_parametr, resolve_limity,
    )
    eid = create_etap(db, kod="amid", nazwa="Amidowanie")
    _seed_param(db, pid=9001, kod="ph", label="pH")
    add_etap_parametr(db, eid, 9001, min_limit=6.0, max_limit=8.0)

    rows = resolve_limity(db, "K7", eid)
    assert len(rows) == 1
    assert rows[0]["kod"] == "ph"
    assert rows[0]["min_limit"] == 6.0
    assert rows[0]["max_limit"] == 8.0


def test_resolve_limity_with_overrides(db):
    from mbr.pipeline.models import (
        create_etap, add_etap_parametr, set_produkt_etap_limit, resolve_limity,
    )
    eid = create_etap(db, kod="amid", nazwa="Amidowanie")
    _seed_param(db, pid=9001, kod="ph", label="pH")
    add_etap_parametr(db, eid, 9001, min_limit=6.0, max_limit=8.0)
    set_produkt_etap_limit(db, "K7", eid, 9001, min_limit=6.5, max_limit=7.5)

    rows = resolve_limity(db, "K7", eid)
    assert rows[0]["min_limit"] == 6.5   # product override wins
    assert rows[0]["max_limit"] == 7.5


def test_resolve_limity_partial_override(db):
    """Product override with only min_limit set — max_limit falls back to catalog."""
    from mbr.pipeline.models import (
        create_etap, add_etap_parametr, set_produkt_etap_limit, resolve_limity,
    )
    eid = create_etap(db, kod="amid", nazwa="Amidowanie")
    _seed_param(db, pid=9001, kod="ph", label="pH")
    add_etap_parametr(db, eid, 9001, min_limit=6.0, max_limit=8.0)
    # Set only min override
    set_produkt_etap_limit(db, "K7", eid, 9001, min_limit=6.5)

    rows = resolve_limity(db, "K7", eid)
    assert rows[0]["min_limit"] == 6.5   # override
    assert rows[0]["max_limit"] == 8.0   # falls back to catalog
