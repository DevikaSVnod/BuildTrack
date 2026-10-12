"""Jira worklog Excel: 15 stories, 12–19 Aug 2026 weekdays, 8h/day, component AI/ML."""
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HEADERS = ["Key", "Type", "Component", "Title", "Est. Hours", "Description"]

# 6 weekdays × 8h = 48h across 15 stories
TICKETS = [
    {
        "hours": 2,
        "title": "Unblock Global Search backend startup and local Python 3.13 runtime",
        "description": (
            "Date: 12-Aug-2026 (Wed).\n\n"
            "Backend failed to start with ModuleNotFoundError for jose, then passlib / email-validator. "
            "Installed missing auth packages (python-jose, passlib) and unblocked FastAPI on Python 3.13 "
            "without a full pinned requirements install (aspose-cad / old Pillow/pydantic fail on 3.13).\n\n"
            "Verified app import and uvicorn startup so login and search APIs could run locally."
        ),
    },
    {
        "hours": 6,
        "title": "Fix Global Search relevance for drawing/university-plan queries",
        "description": (
            "Date: 12-Aug-2026 (Wed).\n\n"
            "Query 'Components in university plan' showed a correct AI 'not found' answer but the UI kept "
            "unrelated Phase-1 hits (Traffic Management Plan, Site Master Plan, panels) because of loose "
            "keyword match on 'plan', weak not-found detection, and frontend merging empty /answer results "
            "with previous cards.\n\n"
            "Work: distinctive-term filtering; broader not-found phrases; drawing/component-plan routing; "
            "prefer AM-789-C University Plan over generic Site Master Plan; stop UI from keeping stale results.\n\n"
            "Outcome: result list and AI answer stay consistent for drawing/inventory questions."
        ),
    },
    {
        "hours": 2,
        "title": "Connect SPACE Action SQL (DEV_V1_SPACE_ACTION) as a Global Search source",
        "description": (
            "Date: 13-Aug-2026 (Thu).\n\n"
            "Configured SPACE on-prem SQL (192.168.10.26, DEV_V1_SPACE_ACTION) as Space Action source "
            "alongside BuildTrack and Assets. Verified VPN/network reachability and that connection alone "
            "does not search action.Event_Agenda until tables are indexed.\n\n"
            "Enabled space source in data_sources (Azure index space-action-index) so later indexing can "
            "feed Global Search without replacing the BuildTrack app database."
        ),
    },
    {
        "hours": 3,
        "title": "Implement production search architecture flags, catalog, hydrate, and metrics",
        "description": (
            "Date: 13-Aug-2026 (Thu).\n\n"
            "Implemented production Global Search design: DB/API as source of truth, Azure AI Search as "
            "slim discovery, LLM only over Top-K.\n\n"
            "Delivered: feature flags (hydrate, catalog, incremental sync, security trim, chunk index); "
            "YAML entity catalog; SQL hydrate-by-ID; catalog-aware routing; watermark incremental sync; "
            "ACL query filter; token/latency metrics; admin APIs "
            "(/catalog, /sync/incremental, /sync/status, /metrics); PRODUCTION_SEARCH.md and catalog tests."
        ),
    },
    {
        "hours": 3,
        "title": "Index all SPACE Action schema tables into Azure AI Search (schema-aware)",
        "description": (
            "Date: 13-Aug-2026 (Thu).\n\n"
            "Extended space_indexer beyond Events / Event_Agenda / Event_Information. Discover all "
            "action.* tables via INFORMATION_SCHEMA; exclude OfflineSyncLog and Synonyms_Configuration; "
            "index text columns only (not every numeric/binary/JSON blob); cap rows per table; store "
            "database/table/record_id metadata.\n\n"
            "Added POST /api/search/space-index and GET /api/search/space-index/status for on-demand sync."
        ),
    },
    {
        "hours": 4,
        "title": "Run SPACE Action index sync and validate hybrid search over indexed rows",
        "description": (
            "Date: 13-Aug-2026 (Thu) into 14-Aug.\n\n"
            "Debugged Swagger missing space-index (stale uvicorn on 8000). After VPN, ran "
            "POST /api/search/space-index: embeddings for all Action rows, then "
            "'Indexed 6664 docs OK, 0 failed into space-action-index'.\n\n"
            "Status: configured=true, schema=action, doc_count=6664. Fast Search "
            "'event agenda' + source_ids=space returned real Event_Agenda rows "
            "(e.g. EVT/2026/00130) — data rows indexed, not schema-only. "
            "LLM still sees Top-K only, so token use stays low."
        ),
    },
    {
        "hours": 2,
        "title": "Harden local runbook: Swagger login, port 8000 conflicts, frontend API URL",
        "description": (
            "Date: 14-Aug-2026 (Fri).\n\n"
            "Operational issues while testing: login 422 (username vs email); Swagger timeout vs long "
            "embedding job; SQL session close 500 after successful index (idle connection); "
            "WinError 10048 duplicate uvicorn; frontend .env.local pointed at 8010 so UI login failed "
            "while API on 8000 succeeded.\n\n"
            "Fixed session close to warn instead of 500; pointed NEXT_PUBLIC_API_URL at 8000; "
            "documented one backend on 8000 and frontend on 3001 when 3000 is busy."
        ),
    },
    {
        "hours": 4,
        "title": "E2E test Global Search UI against SPACE Action index",
        "description": (
            "Date: 14-Aug-2026 (Fri).\n\n"
            "Verified search path: SQL → Azure index (once) → hybrid retrieve → Top-K → LLM. "
            "Tested Swagger Fast Search and app search bar with Space queries "
            "(inspection, EVT/2026/00130, event agenda). Confirmed Space hits include "
            "DEV_V1_SPACE_ACTION / action.Event_Agenda in snippet and metadata.\n\n"
            "Aligned frontend with the indexed backend so SPACE Action results appear in the search bar."
        ),
    },
    {
        "hours": 2,
        "title": "Onboard remaining SPACE SQL databases into Global Search source registry",
        "description": (
            "Date: 17-Aug-2026 (Mon).\n\n"
            "Extended beyond Space Action to the SPACE DB series (Project, Common, UM, DMS, Attachment, "
            "LMS, HSE, Incident, Admin, BMS, ChkWP, CMS, Dashboard, Notification, Analytics). "
            "Registry in space_databases + SEARCH_ENABLE_* flags; startup lists sources such as "
            "space-project, space-hse, space-incident, space-lms, space-cms, space-dashboard.\n\n"
            "Schema-first search for sibling DBs so Global Search can query SPACE modules, not only Action."
        ),
    },
    {
        "hours": 2,
        "title": "Design ProjectId as the SPACE cross-database linking hub",
        "description": (
            "Date: 17-Aug-2026 (Mon).\n\n"
            "SPACE modules do not share one SQL JOIN. Designed soft-key linking on numeric ProjectId "
            "(plus UserId/DocumentId where present). Promote those keys from schema-SQL rows onto "
            "search hit metadata so related DBs can hop on the same key.\n\n"
            "Hub DBs: Space Project plus HSE, Incident, LMS, CMS, Dashboard — searchable vs hop-only "
            "documented for planning."
        ),
    },
    {
        "hours": 4,
        "title": "Implement ProjectId hop fetchers across six SPACE databases",
        "description": (
            "Date: 17-Aug-2026 (Mon).\n\n"
            "Implemented hop fetchers in cross_db_links for Space Project, HSE (occupational + "
            "environmental reviews), Incident, LMS Employment, CMS ProjectCM, and Dashboard_Project_Details. "
            "Wired attach into MultiDatabaseConnector (including single Space source when siblings enabled).\n\n"
            "SQL join-key injection: validator injects ProjectId/UserId/DocumentId when LLM SQL omitted them "
            "(e.g. 'list active projects'). Verified ~34 linked results across types."
        ),
    },
    {
        "hours": 4,
        "title": "Show Linked SPACE records in SearchBar without dropping hop hits",
        "description": (
            "Date: 17-Aug-2026 (Mon).\n\n"
            "UI/answer filters dropped related hops. Merged space_project_id related hits after "
            "answer/entity filters; added SearchBar TYPE_CONFIG for space_project, occupational/"
            "environmental review, incident, employment, contract, dashboard_project; Linked badge "
            "for related_via=space_project_id; stopped collapsing Space linked groups.\n\n"
            "Users see related HSE/Incident/LMS/CMS cards with the project, not only the primary hit."
        ),
    },
    {
        "hours": 2,
        "title": "Regression-test SPACE linked search and demo walkthrough",
        "description": (
            "Date: 18-Aug-2026 (Tue).\n\n"
            "E2E /search/results and /search/answer for list-active-projects and Space Action queries. "
            "Confirmed ProjectIds plus Linked HSE/Incident/LMS/CMS. Restarted local stack "
            "(port 8000 already in use, frontend on 3001, login body email vs username, .env.local 8000).\n\n"
            "Documented which of 17 Space DBs are searchable vs ProjectId-linked for manager demos."
        ),
    },
    {
        "hours": 4,
        "title": "Expand SPACE hop coverage and answer/UX quality for linked types",
        "description": (
            "Date: 18-Aug-2026 (Tue) / 19-Aug-2026 (Wed).\n\n"
            "POC hardening: more ProjectId-linked tables where FKs exist; start DocumentId linking "
            "(DMS/Attachment ↔ project); tune AI citations for related_via=space_project_id; "
            "SearchBar grouping for Space types; reduce duplicate schema_sql vs space_project cards.\n\n"
            "Keeps Global Search answers grounded on Top-K + linked hops without dumping full SPACE DBs into the LLM."
        ),
    },
    {
        "hours": 4,
        "title": "Review SPACE search security flags and source toggles for client demo",
        "description": (
            "Date: 19-Aug-2026 (Wed).\n\n"
            "Reviewed SEARCH_SECURITY_TRIMMING for Space SQL results; confirmed SEARCH_ENABLE_* flags; "
            "disable unused sources for demo. Documented which DBs must be on (Action, Project, HSE, "
            "Incident, LMS, CMS, Dashboard) vs later backlog (UserId hops, BMS name match).\n\n"
            "Prepared Global Search Bar as the SPACE integration surface (API + widget), 8h logged for the day."
        ),
    },
]


def main() -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Jira Stories"

    header_fill = PatternFill("solid", fgColor="1F4E79")
    header_font = Font(bold=True, color="FFFFFF", name="Calibri", size=11)
    thin = Border(
        left=Side(style="thin", color="B0B0B0"),
        right=Side(style="thin", color="B0B0B0"),
        top=Side(style="thin", color="B0B0B0"),
        bottom=Side(style="thin", color="B0B0B0"),
    )
    wrap = Alignment(wrap_text=True, vertical="top")
    center = Alignment(horizontal="center", vertical="top", wrap_text=True)

    for col, h in enumerate(HEADERS, 1):
        cell = ws.cell(1, col, h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for i, t in enumerate(TICKETS, 2):
        ws.cell(i, 1, "").border = thin
        type_cell = ws.cell(i, 2, "Story")
        type_cell.border = thin
        type_cell.alignment = center
        comp = ws.cell(i, 3, "AI/ML")
        comp.border = thin
        comp.alignment = wrap
        title = ws.cell(i, 4, t["title"])
        title.border = thin
        title.alignment = wrap
        hours = ws.cell(i, 5, t["hours"])
        hours.border = thin
        hours.alignment = center
        desc = ws.cell(i, 6, t["description"])
        desc.border = thin
        desc.alignment = wrap
        ws.row_dimensions[i].height = 88

    widths = [10, 12, 14, 64, 12, 80]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[1].height = 22
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:F{len(TICKETS) + 1}"

    ws2 = wb.create_sheet("Hours by day")
    ws2["A1"] = "Worklog 12–19 Aug 2026 (Sat/Sun excluded) — 8 hours per weekday"
    ws2["A1"].font = Font(bold=True, size=13, color="1F4E79")
    ws2.merge_cells("A1:C1")
    for c, h in enumerate(["Date", "Day", "Hours"], 1):
        cell = ws2.cell(3, c, h)
        cell.fill = header_fill
        cell.font = header_font
        cell.border = thin
    days = [
        ("12-Aug-2026", "Wed", 8),
        ("13-Aug-2026", "Thu", 8),
        ("14-Aug-2026", "Fri", 8),
        ("17-Aug-2026", "Mon", 8),
        ("18-Aug-2026", "Tue", 8),
        ("19-Aug-2026", "Wed", 8),
    ]
    for r, row in enumerate(days, 4):
        for c, val in enumerate(row, 1):
            cell = ws2.cell(r, c, val)
            cell.border = thin
            cell.alignment = center if c > 1 else wrap
    ws2["A11"] = f"Stories: {len(TICKETS)}  |  Total hours: {sum(t['hours'] for t in TICKETS)}  |  Component: AI/ML  |  Type: Story  |  Key: blank"
    ws2["A11"].font = Font(bold=True)
    ws2.column_dimensions["A"].width = 16
    ws2.column_dimensions["B"].width = 10
    ws2.column_dimensions["C"].width = 10

    out = "jira-worklog-12-19-aug-aiml.xlsx"
    wb.save(out)
    print(f"Wrote {out}")
    print(f"Tickets: {len(TICKETS)} hours: {sum(t['hours'] for t in TICKETS)}")


if __name__ == "__main__":
    main()
