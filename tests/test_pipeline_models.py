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


# ---------------------------------------------------------------------------
# Task 5: Migration Script — parametry_etapy -> pipeline tables
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Tasks 1-3: DB Schema changes for operator-driven analytical stages
# ---------------------------------------------------------------------------

def test_ebr_korekta_zlecenie_table_exists(db):
    """ebr_korekta_zlecenie table should exist after init."""
    row = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='ebr_korekta_zlecenie'"
    ).fetchone()
    assert row is not None

def test_ebr_korekta_v2_has_zlecenie_columns(db):
    """ebr_korekta_v2 should have zlecenie_id and ilosc_wyliczona columns."""
    info = db.execute("PRAGMA table_info(ebr_korekta_v2)").fetchall()
    col_names = [r["name"] for r in info]
    assert "zlecenie_id" in col_names
    assert "ilosc_wyliczona" in col_names

def test_etap_parametry_has_spec_value(db):
    """etap_parametry should have spec_value column (not target)."""
    info = db.execute("PRAGMA table_info(etap_parametry)").fetchall()
    col_names = [r["name"] for r in info]
    assert "spec_value" in col_names
    assert "target" not in col_names

def test_produkt_etap_limity_has_spec_value(db):
    """produkt_etap_limity should have spec_value column (not target)."""
    info = db.execute("PRAGMA table_info(produkt_etap_limity)").fetchall()
    col_names = [r["name"] for r in info]
    assert "spec_value" in col_names
    assert "target" not in col_names

def test_ebr_etap_sesja_accepts_new_statuses(db):
    """ebr_etap_sesja should accept nierozpoczety, w_trakcie, zamkniety statuses."""
    db.execute("INSERT INTO etapy_analityczne (kod, nazwa, typ_cyklu) VALUES ('test_ea','Test','jednorazowy')")
    db.execute("""INSERT INTO mbr_templates (mbr_id, produkt, wersja, dt_utworzenia)
                  VALUES (99, 'TEST', 1, '2026-01-01')""")
    db.execute("""INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, dt_start)
                  VALUES (99, 99, 'TST-99', '1/2026', '2026-01-01')""")
    etap_id = db.execute("SELECT id FROM etapy_analityczne WHERE kod='test_ea'").fetchone()["id"]

    for status in ("nierozpoczety", "w_trakcie", "zamkniety"):
        db.execute(
            "INSERT INTO ebr_etap_sesja (ebr_id, etap_id, runda, status) VALUES (?,?,?,?)",
            (99, etap_id, 1, status),
        )
        # clean up for next iteration
        db.execute("DELETE FROM ebr_etap_sesja WHERE ebr_id=99 AND etap_id=? AND runda=1", (etap_id,))
    assert True  # no IntegrityError


# ---------------------------------------------------------------------------
# Task 5/6: Zlecenie korekty CRUD + formula hint — fixture & tests
# ---------------------------------------------------------------------------

@pytest.fixture
def setup_pipeline(db):
    """Seed enough data for zlecenie korekty + resolve_formula tests."""
    from mbr.pipeline.models import (
        create_etap, add_etap_korekta, add_etap_parametr,
        set_produkt_pipeline,
    )

    # Analytical parameter
    param1_id = _seed_param(db, pid=9010, kod="so3", label="SO3", typ="bezposredni")

    # MBR + EBR prerequisite rows (with wielkosc_szarzy_kg)
    db.execute("""INSERT INTO mbr_templates (mbr_id, produkt, wersja, dt_utworzenia)
                  VALUES (1, 'TestProd', 1, '2026-01-01')""")
    db.execute("""INSERT INTO ebr_batches (ebr_id, mbr_id, batch_id, nr_partii, dt_start, wielkosc_szarzy_kg)
                  VALUES (1, 1, 'TP-1', '1/2026', '2026-01-01', 10000)""")

    etap1_id = create_etap(db, kod="amid_t5", nazwa="Amidowanie T5")
    etap2_id = create_etap(db, kod="czwart_t5", nazwa="Czwartorzędowanie T5")

    # Pipeline ordering
    set_produkt_pipeline(db, "TestProd", etap1_id, kolejnosc=1)
    set_produkt_pipeline(db, "TestProd", etap2_id, kolejnosc=2)

    # Add param to etap1 with spec_value (for target: resolution)
    add_etap_parametr(db, etap1_id, param1_id, kolejnosc=1, spec_value=12.5)
    add_etap_parametr(db, etap2_id, param1_id, kolejnosc=1)

    korekta_typ_id_1 = add_etap_korekta(db, etap1_id, substancja="NaOH", jednostka="kg", kolejnosc=1)
    korekta_typ_id_2 = add_etap_korekta(db, etap1_id, substancja="HCl", jednostka="kg", kolejnosc=2)
    db.commit()

    return {
        "ebr_id": 1,
        "etap1_id": etap1_id,
        "etap2_id": etap2_id,
        "param1_id": param1_id,
        "korekta_typ_id_1": korekta_typ_id_1,
        "korekta_typ_id_2": korekta_typ_id_2,
    }


def test_create_zlecenie_korekty(db, setup_pipeline):
    """Create a correction order with multiple items."""
    from mbr.pipeline.models import create_sesja, create_zlecenie_korekty, get_zlecenie

    sesja_id = create_sesja(db, setup_pipeline["ebr_id"], setup_pipeline["etap1_id"], runda=1, laborant="lab1")
    items = [
        {"korekta_typ_id": setup_pipeline["korekta_typ_id_1"], "ilosc": 5.0, "ilosc_wyliczona": 4.8},
        {"korekta_typ_id": setup_pipeline["korekta_typ_id_2"], "ilosc": 2.0, "ilosc_wyliczona": None},
    ]
    zlecenie_id = create_zlecenie_korekty(db, sesja_id, items, zalecil="lab1", komentarz="test")
    db.commit()

    zlecenie = get_zlecenie(db, zlecenie_id)
    assert zlecenie["status"] == "zalecona"
    assert len(zlecenie["items"]) == 2
    assert zlecenie["items"][0]["ilosc"] == 5.0
    assert zlecenie["items"][0]["ilosc_wyliczona"] == 4.8
    assert zlecenie["items"][1]["ilosc_wyliczona"] is None


def test_wykonaj_zlecenie(db, setup_pipeline):
    """Executing a correction order creates a new session (runda+1)."""
    from mbr.pipeline.models import create_sesja, create_zlecenie_korekty, wykonaj_zlecenie, get_zlecenie

    sesja_id = create_sesja(db, setup_pipeline["ebr_id"], setup_pipeline["etap1_id"], runda=1, laborant="lab1")
    items = [{"korekta_typ_id": setup_pipeline["korekta_typ_id_1"], "ilosc": 5.0, "ilosc_wyliczona": None}]
    zlecenie_id = create_zlecenie_korekty(db, sesja_id, items, zalecil="lab1")
    db.commit()

    new_sesja_id = wykonaj_zlecenie(db, zlecenie_id)
    db.commit()

    zlecenie = get_zlecenie(db, zlecenie_id)
    assert zlecenie["status"] == "wykonana"
    assert zlecenie["dt_wykonania"] is not None

    new_sesja = db.execute("SELECT * FROM ebr_etap_sesja WHERE id=?", (new_sesja_id,)).fetchone()
    assert new_sesja["runda"] == 2


def test_list_zlecenia_for_sesja(db, setup_pipeline):
    """list_zlecenia_for_sesja returns all orders with items for a session."""
    from mbr.pipeline.models import create_sesja, create_zlecenie_korekty, list_zlecenia_for_sesja

    sesja_id = create_sesja(db, setup_pipeline["ebr_id"], setup_pipeline["etap1_id"], runda=1, laborant="lab1")
    items1 = [{"korekta_typ_id": setup_pipeline["korekta_typ_id_1"], "ilosc": 5.0}]
    items2 = [{"korekta_typ_id": setup_pipeline["korekta_typ_id_2"], "ilosc": 3.0}]
    create_zlecenie_korekty(db, sesja_id, items1, zalecil="lab1")
    create_zlecenie_korekty(db, sesja_id, items2, zalecil="lab1")
    db.commit()

    zlecenia = list_zlecenia_for_sesja(db, sesja_id)
    assert len(zlecenia) == 2
    assert all("items" in z for z in zlecenia)


from scripts.migrate_parametry_etapy import migrate_parametry_etapy


def _seed_old_data(db):
    """Seed parametry_analityczne + parametry_etapy like the existing system."""
    db.execute("INSERT OR IGNORE INTO parametry_analityczne (id, kod, label, typ) VALUES (9001, 'ph', 'pH', 'bezposredni')")
    db.execute("INSERT OR IGNORE INTO parametry_analityczne (id, kod, label, typ) VALUES (9002, 'sm', 'SM', 'bezposredni')")
    db.execute("INSERT OR IGNORE INTO parametry_analityczne (id, kod, label, typ) VALUES (9003, 'nacl', 'NaCl', 'titracja')")

    # Shared (produkt=NULL) bindings
    db.execute("""INSERT INTO parametry_etapy (produkt, kontekst, parametr_id, kolejnosc, min_limit, max_limit)
                  VALUES (NULL, 'amidowanie', 9001, 1, 3.0, 9.0)""")
    db.execute("""INSERT INTO parametry_etapy (produkt, kontekst, parametr_id, kolejnosc, min_limit, max_limit)
                  VALUES (NULL, 'amidowanie', 9002, 2, 40.0, 50.0)""")

    # Product-specific binding (overrides shared)
    db.execute("""INSERT INTO parametry_etapy (produkt, kontekst, parametr_id, kolejnosc, min_limit, max_limit)
                  VALUES ('Chegina_K7', 'amidowanie', 9001, 1, 4.0, 8.0)""")

    # analiza_koncowa context
    db.execute("""INSERT INTO parametry_etapy (produkt, kontekst, parametr_id, kolejnosc, min_limit, max_limit)
                  VALUES ('Chegina_K7', 'analiza_koncowa', 9002, 1, 44.0, 48.0)""")
    db.execute("""INSERT INTO parametry_etapy (produkt, kontekst, parametr_id, kolejnosc, min_limit, max_limit)
                  VALUES ('Chegina_K7', 'analiza_koncowa', 9003, 2, 5.0, 8.0)""")


def test_migrate_creates_etapy(db):
    _seed_old_data(db)
    migrate_parametry_etapy(db)
    rows = db.execute(
        "SELECT kod FROM etapy_analityczne ORDER BY kod"
    ).fetchall()
    kody = [r[0] for r in rows]
    assert "amidowanie" in kody
    assert "analiza_koncowa" in kody


def test_migrate_creates_etap_parametry(db):
    _seed_old_data(db)
    migrate_parametry_etapy(db)
    etap = db.execute(
        "SELECT id FROM etapy_analityczne WHERE kod='amidowanie'"
    ).fetchone()
    assert etap is not None
    count = db.execute(
        "SELECT COUNT(*) FROM etap_parametry WHERE etap_id=?", (etap[0],)
    ).fetchone()[0]
    assert count == 2  # two shared rows for amidowanie


def test_migrate_creates_pipeline(db):
    _seed_old_data(db)
    migrate_parametry_etapy(db)
    rows = db.execute(
        "SELECT etap_id FROM produkt_pipeline WHERE produkt='Chegina_K7'"
    ).fetchall()
    assert len(rows) == 2  # amidowanie + analiza_koncowa


def test_migrate_creates_product_limits(db):
    _seed_old_data(db)
    migrate_parametry_etapy(db)
    etap = db.execute(
        "SELECT id FROM etapy_analityczne WHERE kod='amidowanie'"
    ).fetchone()
    row = db.execute(
        """SELECT min_limit FROM produkt_etap_limity
           WHERE produkt='Chegina_K7' AND etap_id=? AND parametr_id=9001""",
        (etap[0],),
    ).fetchone()
    assert row is not None
    assert row[0] == 4.0


def test_migrate_is_idempotent(db):
    _seed_old_data(db)
    migrate_parametry_etapy(db)
    migrate_parametry_etapy(db)  # second run must not fail or duplicate
    count = db.execute(
        "SELECT COUNT(*) FROM etapy_analityczne"
    ).fetchone()[0]
    assert count == 2  # still just amidowanie + analiza_koncowa


# ---------------------------------------------------------------------------
# Task 1: resolve_formula_zmienne tests
# ---------------------------------------------------------------------------

def test_resolve_formula_zmienne_pomiar_ref(db, setup_pipeline):
    """pomiar:{kod} reference resolves from current session measurement."""
    import json
    from mbr.pipeline.models import create_sesja, save_pomiar, resolve_formula_zmienne

    s = setup_pipeline
    sesja_id = create_sesja(db, s["ebr_id"], s["etap1_id"], runda=1, laborant="lab1")

    # Save a measurement for so3
    save_pomiar(db, sesja_id, s["param1_id"], wartosc=14.2,
                min_limit=None, max_limit=None, wpisal="lab1")

    # Set formula referencing pomiar:so3
    db.execute(
        """UPDATE etap_korekty_katalog
           SET formula_ilosc = '(:C_so3 - 10) * 2',
               formula_zmienne = ?
           WHERE id = ?""",
        (json.dumps({"C_so3": "pomiar:so3"}), s["korekta_typ_id_1"]),
    )
    db.commit()

    result = resolve_formula_zmienne(
        db, s["korekta_typ_id_1"], s["etap1_id"], sesja_id, s["ebr_id"]
    )
    assert result["ok"] is True
    assert result["zmienne"]["C_so3"] == 14.2
    assert "Pomiar" in result["labels"]["C_so3"]
    # (14.2 - 10) * 2 = 8.4
    assert result["wynik"] is not None
    assert abs(result["wynik"] - 8.4) < 0.01


def test_resolve_formula_zmienne_target_ref(db, setup_pipeline):
    """target:{kod} reference resolves spec_value from limity."""
    import json
    from mbr.pipeline.models import create_sesja, resolve_formula_zmienne

    s = setup_pipeline
    sesja_id = create_sesja(db, s["ebr_id"], s["etap1_id"], runda=1, laborant="lab1")

    # Set formula referencing target:so3 (spec_value=12.5 from fixture)
    db.execute(
        """UPDATE etap_korekty_katalog
           SET formula_ilosc = ':target_so3 * 2',
               formula_zmienne = ?
           WHERE id = ?""",
        (json.dumps({"target_so3": "target:so3"}), s["korekta_typ_id_1"]),
    )
    db.commit()

    result = resolve_formula_zmienne(
        db, s["korekta_typ_id_1"], s["etap1_id"], sesja_id, s["ebr_id"]
    )
    assert result["ok"] is True
    assert result["zmienne"]["target_so3"] == 12.5
    assert "Spec" in result["labels"]["target_so3"]
    # 12.5 * 2 = 25.0
    assert result["wynik"] is not None
    assert abs(result["wynik"] - 25.0) < 0.01


def test_resolve_formula_zmienne_redukcja_override(db, setup_pipeline):
    """Meff = masa - redukcja_override when override is provided."""
    import json
    from mbr.pipeline.models import create_sesja, resolve_formula_zmienne

    s = setup_pipeline
    sesja_id = create_sesja(db, s["ebr_id"], s["etap1_id"], runda=1, laborant="lab1")

    db.execute(
        """UPDATE etap_korekty_katalog
           SET formula_ilosc = ':Meff * 0.01',
               formula_zmienne = ?
           WHERE id = ?""",
        (json.dumps({"Meff": "wielkosc_szarzy_kg > 6600 ? wielkosc_szarzy_kg - 500 : wielkosc_szarzy_kg"}),
         s["korekta_typ_id_1"]),
    )
    db.commit()

    result = resolve_formula_zmienne(
        db, s["korekta_typ_id_1"], s["etap1_id"], sesja_id, s["ebr_id"],
        redukcja_override=1500,
    )
    assert result["ok"] is True
    # Meff = 10000 - 1500 = 8500
    assert result["zmienne"]["Meff"] == 8500
    assert result["zmienne"]["redukcja"] == 1500
    # 8500 * 0.01 = 85.0
    assert result["wynik"] is not None
    assert abs(result["wynik"] - 85.0) < 0.01


def test_resolve_formula_zmienne_previous_stage_pomiar(db, setup_pipeline):
    """pomiar:{kod} walks back through pipeline when not found in current session."""
    import json
    from mbr.pipeline.models import create_sesja, save_pomiar, resolve_formula_zmienne

    s = setup_pipeline

    # Create session in etap1 and save measurement there
    sesja1_id = create_sesja(db, s["ebr_id"], s["etap1_id"], runda=1, laborant="lab1")
    save_pomiar(db, sesja1_id, s["param1_id"], wartosc=14.2,
                min_limit=None, max_limit=None, wpisal="lab1")

    # Create session in etap2 — no measurement here
    sesja2_id = create_sesja(db, s["ebr_id"], s["etap2_id"], runda=1, laborant="lab1")

    # Formula on korekta references pomiar:so3, set on etap1's korekta but resolve from etap2
    # We need a korekta on etap2 for this test
    from mbr.pipeline.models import add_etap_korekta
    korekta_etap2 = add_etap_korekta(db, s["etap2_id"], substancja="Oleum", jednostka="kg", kolejnosc=1)
    db.execute(
        """UPDATE etap_korekty_katalog
           SET formula_ilosc = ':C_so3 * 3',
               formula_zmienne = ?
           WHERE id = ?""",
        (json.dumps({"C_so3": "pomiar:so3"}), korekta_etap2),
    )
    db.commit()

    result = resolve_formula_zmienne(
        db, korekta_etap2, s["etap2_id"], sesja2_id, s["ebr_id"]
    )
    assert result["ok"] is True
    # Should find so3=14.2 from etap1's session via pipeline walkback
    assert result["zmienne"]["C_so3"] == 14.2
    # 14.2 * 3 = 42.6
    assert result["wynik"] is not None
    assert abs(result["wynik"] - 42.6) < 0.01


# ---------------------------------------------------------------------------
# pipeline_has_multi_stage — SSOT for "extended card?" decision
# ---------------------------------------------------------------------------

def test_pipeline_has_multi_stage_true_for_multiple_rows(db):
    from mbr.pipeline.models import pipeline_has_multi_stage
    # Create etapy + pipeline rows for 'TEST_MULTI' product
    db.execute("INSERT OR IGNORE INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) VALUES (901, 'st1', 'S1', 'cykliczny')")
    db.execute("INSERT OR IGNORE INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) VALUES (902, 'st2', 'S2', 'jednorazowy')")
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('TEST_MULTI', 901, 1)")
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('TEST_MULTI', 902, 2)")
    db.commit()
    assert pipeline_has_multi_stage(db, 'TEST_MULTI') is True


def test_pipeline_has_multi_stage_false_for_single_row(db):
    from mbr.pipeline.models import pipeline_has_multi_stage
    db.execute("INSERT OR IGNORE INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) VALUES (903, 'st3', 'S3', 'jednorazowy')")
    db.execute("INSERT INTO produkt_pipeline (produkt, etap_id, kolejnosc) VALUES ('TEST_SINGLE', 903, 1)")
    db.commit()
    assert pipeline_has_multi_stage(db, 'TEST_SINGLE') is False


def test_pipeline_has_multi_stage_false_for_no_rows(db):
    from mbr.pipeline.models import pipeline_has_multi_stage
    assert pipeline_has_multi_stage(db, 'DOES_NOT_EXIST') is False


# ---------------------------------------------------------------------------
# upsert_ebr_korekta — auto-save persistent correction values
# ---------------------------------------------------------------------------

def _seed_korekta_fixture(db):
    """Seed a minimal K7-like pipeline with one etap + one korekta_typ + one open sesja."""
    db.execute(
        "INSERT OR IGNORE INTO etapy_analityczne (id, kod, nazwa, typ_cyklu) "
        "VALUES (904, 'sulfonowanie_t', 'Sulfonowanie (test)', 'cykliczny')"
    )
    db.execute(
        "INSERT INTO etap_korekty_katalog "
        "(id, etap_id, substancja, jednostka, wykonawca, kolejnosc) "
        "VALUES (901, 904, 'Perhydrol 34%', 'kg', 'produkcja', 1)"
    )
    db.execute(
        "INSERT INTO etap_korekty_katalog "
        "(id, etap_id, substancja, jednostka, wykonawca, kolejnosc) "
        "VALUES (902, 904, 'Woda', 'kg', 'produkcja', 2)"
    )
    # Need an ebr_batch for FK on ebr_etap_sesja. Use existing mbr_templates.
    mbr_id = db.execute(
        "INSERT INTO mbr_templates (produkt, wersja, status) "
        "VALUES ('TESTPROD', 1, 'active') RETURNING mbr_id"
    ).fetchone()["mbr_id"]
    ebr_id = db.execute(
        "INSERT INTO ebr_batches (mbr_id, batch_id, nr_partii, dt_start, typ) "
        "VALUES (?, 'B-TEST-1', '1/TEST', datetime('now'), 'szarza') "
        "RETURNING ebr_id",
        (mbr_id,),
    ).fetchone()["ebr_id"]
    from mbr.pipeline.models import create_sesja
    sesja_id = create_sesja(db, ebr_id, 904, runda=1, laborant="lab1")
    db.commit()
    return {"ebr_id": ebr_id, "etap_id": 904, "sesja_id": sesja_id,
            "perhydrol_typ_id": 901, "woda_typ_id": 902}


def test_upsert_korekta_inserts_when_missing(db):
    from mbr.pipeline.models import upsert_ebr_korekta, list_ebr_korekty
    s = _seed_korekta_fixture(db)
    kid = upsert_ebr_korekta(
        db, sesja_id=s["sesja_id"], korekta_typ_id=s["perhydrol_typ_id"],
        ilosc=12.5, ilosc_wyliczona=11.8, zalecil="lab1",
    )
    assert isinstance(kid, int) and kid > 0
    rows = list_ebr_korekty(db, s["sesja_id"])
    perhydrol = [r for r in rows if r["korekta_typ_id"] == s["perhydrol_typ_id"]]
    assert len(perhydrol) == 1
    assert perhydrol[0]["ilosc"] == 12.5


def test_upsert_korekta_updates_when_present(db):
    """Calling twice for the same (sesja, korekta_typ) must not duplicate rows."""
    from mbr.pipeline.models import upsert_ebr_korekta
    s = _seed_korekta_fixture(db)
    kid1 = upsert_ebr_korekta(db, s["sesja_id"], s["perhydrol_typ_id"], 10.0, 11.8, "lab1")
    kid2 = upsert_ebr_korekta(db, s["sesja_id"], s["perhydrol_typ_id"], 15.5, 11.8, "lab1")
    assert kid1 == kid2
    n = db.execute(
        "SELECT COUNT(*) AS n FROM ebr_korekta_v2 "
        "WHERE sesja_id=? AND korekta_typ_id=?",
        (s["sesja_id"], s["perhydrol_typ_id"]),
    ).fetchone()["n"]
    assert n == 1
    row = db.execute(
        "SELECT ilosc FROM ebr_korekta_v2 WHERE id=?", (kid1,)
    ).fetchone()
    assert row["ilosc"] == 15.5


def test_upsert_korekta_ilosc_none_clears_manual(db):
    """Passing ilosc=None after a value sets ilosc back to NULL (formula wins again)."""
    from mbr.pipeline.models import upsert_ebr_korekta
    s = _seed_korekta_fixture(db)
    upsert_ebr_korekta(db, s["sesja_id"], s["perhydrol_typ_id"], 12.5, 11.8, "lab1")
    upsert_ebr_korekta(db, s["sesja_id"], s["perhydrol_typ_id"], None, 11.8, "lab1")
    row = db.execute(
        "SELECT ilosc, ilosc_wyliczona FROM ebr_korekta_v2 "
        "WHERE sesja_id=? AND korekta_typ_id=?",
        (s["sesja_id"], s["perhydrol_typ_id"]),
    ).fetchone()
    assert row["ilosc"] is None
    assert row["ilosc_wyliczona"] == 11.8


def test_upsert_korekta_different_sesje_separate_rows(db):
    """Two sesje for the same etap → two separate korekta rows (one per sesja)."""
    from mbr.pipeline.models import upsert_ebr_korekta, create_sesja
    s = _seed_korekta_fixture(db)
    sesja2_id = create_sesja(db, s["ebr_id"], s["etap_id"], runda=2, laborant="lab1")
    db.commit()
    upsert_ebr_korekta(db, s["sesja_id"], s["perhydrol_typ_id"], 10.0, None, "lab1")
    upsert_ebr_korekta(db, sesja2_id, s["perhydrol_typ_id"], 15.0, None, "lab1")
    rows = db.execute(
        "SELECT sesja_id, ilosc FROM ebr_korekta_v2 "
        "WHERE korekta_typ_id=? ORDER BY sesja_id",
        (s["perhydrol_typ_id"],),
    ).fetchall()
    assert len(rows) == 2
    vals = {r["sesja_id"]: r["ilosc"] for r in rows}
    assert vals[s["sesja_id"]] == 10.0
    assert vals[sesja2_id] == 15.0
