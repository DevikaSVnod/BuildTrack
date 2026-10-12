"""Quick smoke test for newly added Space cross-DB hops."""
from collections import Counter

from app.core.data_sources import get_enabled_sources
from app.search.cross_db_links import attach_space_project_id_hits, clear_cross_db_cache


def main() -> None:
    clear_cross_db_cache()
    enabled = {s.id for s in get_enabled_sources()}
    seed = [
        {
            "id": "seed-project-15",
            "title": "Ahmedabad",
            "snippet": "Code: P_AHMPR",
            "content_type": "schema_sql",
            "url": "",
            "score": 1.0,
            "metadata": {
                "database_id": "space-project",
                "database_label": "Space Project",
                "space_project_id": "15",
                "project_id": "15",
                "project": "Ahmedabad",
                "project_name": "Ahmedabad",
                "row": {"ProjectId": 15, "Code": "P_AHMPR", "Name": "Ahmedabad"},
            },
        }
    ]
    out = attach_space_project_id_hits(seed, enabled=enabled, max_related=40, per_hop_limit=2)
    print("total", len(out))
    print(Counter(h.get("content_type") for h in out))
    for h in out[:25]:
        m = h.get("metadata") or {}
        print(
            "-",
            h.get("content_type"),
            (h.get("title") or "")[:40],
            m.get("database_id"),
            m.get("related_via"),
        )


if __name__ == "__main__":
    main()
