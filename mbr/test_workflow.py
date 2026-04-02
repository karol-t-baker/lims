"""End-to-end test: seed -> create EBR -> enter results -> complete -> verify v4 sync."""
from mbr.models import (get_db, init_mbr_tables, get_active_mbr, create_ebr,
                         save_wyniki, complete_ebr, sync_ebr_to_v4, get_ebr, get_ebr_wyniki)

def test_full_workflow():
    db = get_db()
    init_mbr_tables(db)

    # 1. Verify seed data exists
    count = db.execute("SELECT COUNT(*) FROM mbr_templates").fetchone()[0]
    assert count >= 4, f"Expected 4+ MBR templates, got {count}. Run seed_mbr.py first."
    print(f"  [OK] {count} MBR templates found")

    # 2. Create EBR
    ebr_id = create_ebr(db, "Chegina_K7", "99/2026", "8", "25", 5000.0, "test")
    ebr = get_ebr(db, ebr_id)
    assert ebr is not None
    assert ebr["batch_id"] == "Chegina_K7__99_2026"
    assert ebr["status"] == "open"
    print(f"  [OK] EBR created: {ebr['batch_id']}")

    # 3. Save przed_standaryzacja results
    save_wyniki(db, ebr_id, "przed_standaryzacja", {
        "ph_10proc": {"wartosc": 5.5, "komentarz": ""},
        "nd20": {"wartosc": 1.4050, "komentarz": ""},
        "procent_so3": {"wartosc": 0.008, "komentarz": ""},
    }, "test_laborant")
    wyniki = get_ebr_wyniki(db, ebr_id)
    assert "przed_standaryzacja" in wyniki
    assert wyniki["przed_standaryzacja"]["ph_10proc"]["w_limicie"] == 1
    print("  [OK] przed_standaryzacja saved, limits checked")

    # 4. Save analiza_koncowa results
    save_wyniki(db, ebr_id, "analiza_koncowa", {
        "ph_10proc": {"wartosc": 5.2, "komentarz": ""},
        "nd20": {"wartosc": 1.4050, "komentarz": ""},
        "procent_sm": {"wartosc": 45.0, "komentarz": ""},
        "procent_sa": {"wartosc": 38.5, "komentarz": ""},
        "procent_nacl": {"wartosc": 5.8, "komentarz": ""},
        "procent_aa": {"wartosc": 0.12, "komentarz": ""},
        "procent_so3": {"wartosc": 0.008, "komentarz": ""},
        "procent_h2o2": {"wartosc": 0.003, "komentarz": ""},
        "le_liczba_kwasowa": {"wartosc": 3.4, "komentarz": ""},
    }, "test_laborant")
    wyniki = get_ebr_wyniki(db, ebr_id)
    assert "analiza_koncowa" in wyniki
    print("  [OK] analiza_koncowa saved")

    # 5. Sync to v4 (before complete)
    sync_ebr_to_v4(db, ebr_id)
    events = db.execute(
        "SELECT * FROM events WHERE batch_id = 'Chegina_K7__99_2026' AND _source = 'digital'"
    ).fetchall()
    assert len(events) >= 2, f"Expected 2+ events, got {len(events)}"
    print(f"  [OK] v4 events synced: {len(events)} rows")

    # 6. Complete + final sync
    complete_ebr(db, ebr_id)
    sync_ebr_to_v4(db, ebr_id)

    # 7. Verify v4 batch ak_ fields
    batch = db.execute("SELECT * FROM batch WHERE batch_id = 'Chegina_K7__99_2026'").fetchone()
    assert batch is not None, "batch row not found in v4"
    assert batch["_source"] == "digital"
    # Check specific ak_ values
    assert batch["ak_procent_sa"] == 38.5, f"ak_procent_sa = {batch['ak_procent_sa']}"
    assert batch["ak_nd20"] == 1.405, f"ak_nd20 = {batch['ak_nd20']}"
    print(f"  [OK] v4 batch synced: ak_procent_sa = {batch['ak_procent_sa']}")

    # 8. Verify completed status
    ebr = get_ebr(db, ebr_id)
    assert ebr["status"] == "completed"
    assert ebr["dt_end"] is not None
    print("  [OK] EBR completed with dt_end set")

    # 9. Cleanup test data
    db.execute("DELETE FROM ebr_wyniki WHERE ebr_id = ?", (ebr_id,))
    db.execute("DELETE FROM ebr_batches WHERE ebr_id = ?", (ebr_id,))
    db.execute("DELETE FROM events WHERE batch_id = 'Chegina_K7__99_2026' AND _source = 'digital'")
    db.execute("DELETE FROM batch WHERE batch_id = 'Chegina_K7__99_2026'")
    db.commit()
    db.close()
    print("\n✓ All tests passed!")

if __name__ == "__main__":
    test_full_workflow()
