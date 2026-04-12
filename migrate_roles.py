"""One-time migration: rename lab roles.

laborant / laborant_kj → lab
laborant_coa → cert

Recreates mbr_users with updated CHECK constraint, updates login+rola+password.
Idempotent — skips if 'lab' role already exists.
"""
import sqlite3
import bcrypt

DB = "data/batch_db.sqlite"

def migrate():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row

    # Idempotency check
    row = db.execute("SELECT COUNT(*) as c FROM mbr_users WHERE rola='lab'").fetchone()
    if row["c"] > 0:
        print("Already migrated, skipping.")
        db.close()
        return

    db.execute("PRAGMA foreign_keys=OFF")

    db.executescript("""
        CREATE TABLE mbr_users_tmp (
            user_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            login           TEXT UNIQUE NOT NULL,
            password_hash   TEXT NOT NULL,
            rola            TEXT NOT NULL,
            imie_nazwisko   TEXT
        );
        INSERT INTO mbr_users_tmp SELECT * FROM mbr_users;
        DROP TABLE mbr_users;
    """)
    db.execute("UPDATE mbr_users_tmp SET rola='lab' WHERE rola IN ('laborant', 'laborant_kj')")
    db.execute("UPDATE mbr_users_tmp SET rola='cert' WHERE rola='laborant_coa'")
    db.executescript("""
        CREATE TABLE mbr_users (
            user_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            login           TEXT UNIQUE NOT NULL,
            password_hash   TEXT NOT NULL,
            rola            TEXT NOT NULL CHECK(rola IN ('technolog', 'lab', 'cert', 'admin')),
            imie_nazwisko   TEXT
        );
        INSERT INTO mbr_users SELECT * FROM mbr_users_tmp;
        DROP TABLE mbr_users_tmp;
    """)

    lab_hash = bcrypt.hashpw(b"lab", bcrypt.gensalt()).decode()
    cert_hash = bcrypt.hashpw(b"cert", bcrypt.gensalt()).decode()

    db.execute("UPDATE mbr_users SET login='lab', password_hash=?, imie_nazwisko='Laborant KJ' WHERE login='laborant'", (lab_hash,))
    db.execute("UPDATE mbr_users SET login='cert', password_hash=?, imie_nazwisko='Świadectwa KJ' WHERE login='laborant_coa'", (cert_hash,))

    db.commit()

    for row in db.execute("SELECT user_id, login, rola, imie_nazwisko FROM mbr_users").fetchall():
        print(f"  {row['user_id']}: {row['login']} / {row['rola']} / {row['imie_nazwisko']}")

    db.execute("PRAGMA foreign_keys=ON")
    db.close()
    print("Done.")

if __name__ == "__main__":
    migrate()
