"""
Add pakowanie_bezposrednie column to ebr_batches.

Run: python -m scripts.migrate_pakowanie_bezposrednie
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mbr.db import get_db

def migrate():
    db = get_db()
    try:
        db.execute("ALTER TABLE ebr_batches ADD COLUMN pakowanie_bezposrednie TEXT")
        db.commit()
        print("Added pakowanie_bezposrednie column.")
    except Exception as e:
        if "duplicate column" in str(e).lower():
            print("Column already exists.")
        else:
            raise
    finally:
        db.close()

if __name__ == "__main__":
    migrate()
