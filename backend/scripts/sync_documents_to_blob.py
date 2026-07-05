"""
Upload every document row to Azure Blob Storage and update SQL file_url.

Skips rows that already point at blob.core.windows.net.

Usage (from backend/):
  python scripts/sync_documents_to_blob.py
  python scripts/sync_documents_to_blob.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy.orm import joinedload

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.document import Document
from app.search.sql_indexer import trigger_sql_indexer_run
from app.search.blob_indexer import trigger_blob_indexer_run
from app.storage.blob_access import parse_blob_url
from app.storage.document_blob import (
    blob_name_for_document,
    generate_document_bytes,
    is_blob_url,
    upload_bytes_to_blob,
)


def trigger_blob_indexers() -> None:
    try:
        triggered = trigger_blob_indexer_run()
        for name in triggered:
            print(f"Triggered blob/RAG indexer: {name}")
        if not triggered:
            print("No blob/RAG indexer triggered (debounced or not configured).")
    except Exception as exc:
        print(f"Blob indexer trigger failed: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync all SQL documents to Azure Blob Storage")
    parser.add_argument("--dry-run", action="store_true", help="List actions without uploading")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-upload documents already in blob (refreshes searchable body text)",
    )
    args = parser.parse_args()

    if not settings.AZURE_STORAGE_CONNECTION_STRING:
        raise SystemExit("Set AZURE_STORAGE_CONNECTION_STRING in backend/.env")

    db = SessionLocal()
    uploaded = skipped = failed = 0
    try:
        docs = (
            db.query(Document)
            .options(joinedload(Document.project))
            .order_by(Document.id)
            .all()
        )
        print(f"Found {len(docs)} document row(s) in SQL.")

        for doc in docs:
            if is_blob_url(doc.file_url) and not args.force:
                print(f"  skip id={doc.id} (already in blob): {doc.name}")
                skipped += 1
                continue

            project_name = doc.project.name if doc.project else None
            if is_blob_url(doc.file_url) and args.force:
                _, blob_name = parse_blob_url(doc.file_url)
            else:
                blob_name = blob_name_for_document(doc.id, doc.name)
            content, content_type = generate_document_bytes(
                doc.name, doc.file_type, project_name, doc.id
            )

            if args.dry_run:
                print(f"  would upload id={doc.id} -> {blob_name} ({len(content)} bytes)")
                uploaded += 1
                continue

            try:
                url, size = upload_bytes_to_blob(
                    content,
                    blob_name,
                    content_type,
                    document_id=doc.id,
                    project_id=doc.project_id,
                    original_filename=doc.name,
                )
                doc.file_url = url
                doc.file_size = size
                db.commit()
                print(f"  uploaded id={doc.id}: {doc.name} -> {url}")
                uploaded += 1
            except Exception as exc:
                db.rollback()
                print(f"  FAILED id={doc.id} {doc.name}: {exc}")
                failed += 1

        if not args.dry_run and uploaded:
            try:
                trigger_sql_indexer_run()
                print("SQL indexer triggered.")
            except Exception as exc:
                print(f"SQL indexer trigger failed: {exc}")
            try:
                trigger_blob_indexers()
            except Exception as exc:
                print(f"Blob indexer trigger failed: {exc}")

        print(f"\nDone: uploaded={uploaded}, skipped={skipped}, failed={failed}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
