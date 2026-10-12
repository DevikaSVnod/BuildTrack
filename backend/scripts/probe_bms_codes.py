"""Compare Space Project codes vs BMS ProjectBD codes."""
from sqlalchemy import text

from app.core.space_databases import get_space_db_config, resolve_space_database_url
from scripts.setup_assets_db import create_mssql_engine


def main() -> None:
    eng = create_mssql_engine(
        resolve_space_database_url(get_space_db_config("space-bms"))
    )
    try:
        with eng.connect() as c:
            rows = c.execute(
                text(
                    "SELECT TOP 10 ProjectBDID, ProjectName, ProjectTempCode, "
                    "ProjectSAPCode FROM bms.ProjectBD WHERE ISNULL(IsActive, 1) = 1"
                )
            ).fetchall()
            print("BMS ProjectBD sample:", rows)
            for code in ("P_AHMPR", "SMK-TEST-01"):
                m = c.execute(
                    text(
                        "SELECT ProjectBDID, ProjectName, ProjectTempCode "
                        "FROM bms.ProjectBD WHERE ProjectTempCode = :c "
                        "OR ProjectSAPCode = :c"
                    ),
                    {"c": code},
                ).fetchall()
                print(f"BMS match {code}:", m)
    finally:
        eng.dispose()

    eng2 = create_mssql_engine(
        resolve_space_database_url(get_space_db_config("space-project"))
    )
    try:
        with eng2.connect() as c:
            r = c.execute(
                text(
                    "SELECT ProjectId, Code, Name FROM project.Project "
                    "WHERE Code IN ('P_AHMPR', 'SMK-TEST-01')"
                )
            ).fetchall()
            print("Space Project:", r)
    finally:
        eng2.dispose()


if __name__ == "__main__":
    main()
