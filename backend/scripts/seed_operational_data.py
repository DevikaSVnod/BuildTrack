"""Seed operational tables on existing Azure SQL (when core data already exists)."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.database import SessionLocal
from app.seed_operational import seed_operational_data


def main():
    db = SessionLocal()
    try:
        n = seed_operational_data(db)
        if n:
            print(f"Seeded {n} operational rows.")
        else:
            print("Operational tables already have data — skipped.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
