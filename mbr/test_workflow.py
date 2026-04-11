"""End-to-end test: seed -> create EBR -> cyclic standaryzacja -> complete -> verify v4 sync."""
import pytest

from mbr.models import (get_db, init_mbr_tables, get_active_mbr, create_ebr,
                         save_wyniki, complete_ebr, sync_ebr_to_v4, get_ebr,
                         get_ebr_wyniki, get_round_state)


@pytest.mark.skip(reason="integration test — opens real data/batch_db.sqlite and requires seeded mbr_templates. Rewrite with in-memory fixture. See docs/superpowers/todo/2026-04-11-quarantined-tests.md")
def test_cyclic_standaryzacja():
    db = get_db()
    init_mbr_tables(db)

    # 1. Verify seed data
    count = db.execute("SELECT COUNT(*) FROM mbr_templates").fetchone()[0]
    assert count >= 4, f"Expected 4+ MBR templates, got {count}. Run seed_mbr.py first."
    print(f"  [OK] {count} MBR templates found")

    # 2. Create EBR for K7
    ebr_id = create_ebr(db, "Chegina_K7", "99/2026", "8", "25", 5000.0, "test")
    ebr = get_ebr(db, ebr_id)
    assert ebr["batch_id"] == "Chegina_K7__99_2026"
    print(f"  [OK] EBR created: {ebr['batch_id']}")

    # 3. Round state: should start with analiza__1
    wyniki = get_ebr_wyniki(db, ebr_id)
    rs = get_round_state(wyniki)
    assert rs["next_step"] == "analiza"
    assert rs["next_sekcja"] == "analiza__1"
    print("  [OK] Initial round state: analiza__1")

    # 4. Save first analiza (part of standaryzacja etap)
    save_wyniki(db, ebr_id, "analiza__1", {
        "sm": {"wartosc": 45.0, "komentarz": ""},
        "nacl": {"wartosc": 5.8, "komentarz": ""},
        "ph_10proc": {"wartosc": 5.2, "komentarz": ""},
        "nd20": {"wartosc": 1.4050, "komentarz": ""},
        "sa": {"wartosc": 38.6, "komentarz": ""},
        "barwa_fau": {"wartosc": 80, "komentarz": ""},
        "barwa_hz": {"wartosc": 30, "komentarz": ""},
    }, "test_laborant")
    wyniki = get_ebr_wyniki(db, ebr_id)
    assert "analiza__1" in wyniki
    rs = get_round_state(wyniki)
    assert rs["next_step"] == "dodatki"
    assert rs["next_sekcja"] == "dodatki__1"
    print("  [OK] Analiza 1 saved -> next: dodatki__1")

    # 5. Save dodatki (additives)
    save_wyniki(db, ebr_id, "dodatki__1", {
        "kwas_kg": {"wartosc": 2.5, "komentarz": ""},
        "woda_kg": {"wartosc": 15.0, "komentarz": ""},
        "nacl_kg": {"wartosc": 1.2, "komentarz": ""},
    }, "test_laborant")
    wyniki = get_ebr_wyniki(db, ebr_id)
    assert "dodatki__1" in wyniki
    rs = get_round_state(wyniki)
    assert rs["next_step"] == "analiza"
    assert rs["next_sekcja"] == "analiza__2"
    print("  [OK] Dodatki 1 saved -> next: analiza__2 (analiza koncowa)")

    # 6. Save analiza koncowa (analiza__2)
    save_wyniki(db, ebr_id, "analiza__2", {
        "sm": {"wartosc": 44.5, "komentarz": ""},
        "nacl": {"wartosc": 6.0, "komentarz": ""},
        "ph_10proc": {"wartosc": 5.0, "komentarz": ""},
        "nd20": {"wartosc": 1.4020, "komentarz": ""},
        "sa": {"wartosc": 37.9, "komentarz": ""},
        "barwa_fau": {"wartosc": 70, "komentarz": ""},
        "barwa_hz": {"wartosc": 25, "komentarz": ""},
    }, "test_laborant")
    wyniki = get_ebr_wyniki(db, ebr_id)
    assert "analiza__2" in wyniki
    rs = get_round_state(wyniki)
    assert rs["last_analiza"] == 2
    assert rs["is_decision"] is True
    print("  [OK] Analiza koncowa saved -> decision point (Przepompuj/Korekta)")

    # 7. Sync to v4
    sync_ebr_to_v4(db, ebr_id)
    events = db.execute(
        "SELECT * FROM events WHERE batch_id = 'Chegina_K7__99_2026' AND _source = 'digital' ORDER BY seq"
    ).fetchall()
    assert len(events) == 3, f"Expected 3 events, got {len(events)}"
    e1, e2, e3 = [dict(e) for e in events]
    assert e1["stage"] == "analiza" and e1["runda"] == 1
    assert e2["stage"] == "standaryzacja" and e2["runda"] == 1
    assert e2["kwas_kg"] == 2.5
    assert e2["woda_kg"] == 15.0
    assert e3["stage"] == "analiza" and e3["runda"] == 2
    print(f"  [OK] v4 events synced: {len(events)} rows")

    # 8. Complete + final sync -> ak_* from analiza__2 (last analiza)
    complete_ebr(db, ebr_id)
    sync_ebr_to_v4(db, ebr_id)

    batch = db.execute("SELECT * FROM batch WHERE batch_id = 'Chegina_K7__99_2026'").fetchone()
    assert batch is not None
    assert batch["ak_procent_sm"] == 44.5, f"ak_procent_sm = {batch['ak_procent_sm']}"
    assert batch["ak_procent_nacl"] == 6.0
    assert batch["ak_nd20"] == 1.402
    print(f"  [OK] v4 batch ak_* from analiza koncowa: ak_procent_sm={batch['ak_procent_sm']}")

    # 9. Cleanup
    db.execute("DELETE FROM ebr_wyniki WHERE ebr_id = ?", (ebr_id,))
    db.execute("DELETE FROM ebr_batches WHERE ebr_id = ?", (ebr_id,))
    db.execute("DELETE FROM events WHERE batch_id = 'Chegina_K7__99_2026' AND _source = 'digital'")
    db.execute("DELETE FROM batch WHERE batch_id = 'Chegina_K7__99_2026'")
    db.commit()
    db.close()
    print("\n✓ All tests passed!")


if __name__ == "__main__":
    test_cyclic_standaryzacja()
