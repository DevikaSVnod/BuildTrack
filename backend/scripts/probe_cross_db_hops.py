"""Probe Space DimensionType / hop table shapes for pending cross-DB hops."""
from sqlalchemy import text

from app.core.space_databases import get_space_db_config, resolve_space_database_url
from scripts.setup_assets_db import create_mssql_engine


def q(sid: str, sql: str) -> None:
    cfg = get_space_db_config(sid)
    if cfg is None:
        print(sid, "NO CONFIG")
        return
    eng = create_mssql_engine(resolve_space_database_url(cfg))
    try:
        with eng.connect() as c:
            rows = c.execute(text(sql)).fetchall()
            print(sid, "=>", rows[:10])
    except Exception as e:
        print(sid, "ERR", type(e).__name__, e)
    finally:
        eng.dispose()


def main() -> None:
    q(
        "space-dms",
        "SELECT TOP 8 DimensionType, COUNT(1) AS c "
        "FROM dms.Document_MetaData GROUP BY DimensionType ORDER BY c DESC",
    )
    q(
        "space",
        "SELECT TOP 8 DimensionType, COUNT(1) AS c "
        "FROM action.Event_Information GROUP BY DimensionType ORDER BY c DESC",
    )
    q(
        "space-um",
        "SELECT TOP 3 ProjectId, COUNT(1) AS c FROM um.User_Assignment "
        "WHERE IsActive = 1 GROUP BY ProjectId ORDER BY c DESC",
    )
    q(
        "space-chkwp",
        "SELECT TOP 3 ProjectId, COUNT(1) AS c FROM chkwp.Submission "
        "GROUP BY ProjectId ORDER BY c DESC",
    )
    q(
        "space-lms",
        "SELECT TOP 5 name FROM sys.tables WHERE name IN "
        "('Labour_Attendance','Wage_Calculation_Daily_Project_Detail','Employment')",
    )
    q(
        "space-bms",
        "SELECT TOP 3 ProjectBDID, ProjectName, ProjectTempCode, ProjectSAPCode "
        "FROM bms.ProjectBD WHERE IsActive = 1",
    )
    # Sample project ids that have DMS docs via Dimension
    q(
        "space-dms",
        "SELECT TOP 5 DimensionId, COUNT(1) AS c FROM dms.Document_MetaData "
        "WHERE DimensionType IN ('Project','PROJECT','project') "
        "GROUP BY DimensionId ORDER BY c DESC",
    )
    q(
        "space",
        "SELECT TOP 5 DimensionId, COUNT(1) AS c FROM action.Event_Information "
        "WHERE DimensionType IN ('Project','PROJECT','project') "
        "GROUP BY DimensionId ORDER BY c DESC",
    )


if __name__ == "__main__":
    main()
