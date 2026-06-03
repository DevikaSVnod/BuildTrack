"""One-time: update admin user in existing database."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal
from app.models.user import User

OLD_EMAIL = "michael@buildtrack.com"
NEW_NAME = "Devika S Vinod"
NEW_EMAIL = "devika@buildtrack.com"
NEW_COMPANY = "BuildTrack"


def main():
    db = SessionLocal()
    try:
        user = db.query(User).filter(
            (User.email == OLD_EMAIL) | (User.full_name == "Michael Torres")
        ).first()
        if not user:
            user = db.query(User).filter(User.role == "Admin").first()
        if not user:
            print("No admin user found to update.")
            return
        user.full_name = NEW_NAME
        user.email = NEW_EMAIL
        user.company_name = NEW_COMPANY
        db.commit()
        print(f"Updated admin: {user.full_name} ({user.email})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
