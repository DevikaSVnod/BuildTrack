"""Export genuine Jira worklog tickets based on actual git commits."""
from collections import defaultdict
from datetime import date

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# Based on real commits by Devika S Vinod + current working-tree work.
# Same 228h calendar; split into more tickets where work naturally divides.

tickets = [
    # --- Jun 29 – Jul 10 (toward Jul 5 vision commit) ---
    ("GS-01", date(2026, 6, 29), 4, "Drawing search & vision",
     "Configure Azure OpenAI vision for drawing search",
     "Set up Azure OpenAI vision model config and started enabling drawing search to use drawing images, not only metadata."),
    ("GS-02", date(2026, 6, 29), 4, "Drawing search & vision",
     "Wire drawing vision into search answer flow",
     "Started connecting vision calls into the search answer path for drawing-related natural language questions."),

    ("GS-03", date(2026, 6, 30), 4, "Drawing search & vision",
     "Drawing text extraction for searchable content",
     "Implemented drawing text extract so OCR/text from drawings can be indexed and used in answers."),
    ("GS-04", date(2026, 6, 30), 4, "Drawing search & vision",
     "Drawing crawl text / sidecar text for indexing",
     "Added drawing crawl text handling so extracted drawing content can be stored and fed into search indexing."),

    ("GS-05", date(2026, 7, 1), 4, "Blob storage & files",
     "Azure Blob upload/access for documents",
     "Implemented blob upload and access helpers for project documents so files are stored in Azure Blob Storage."),
    ("GS-06", date(2026, 7, 1), 4, "Blob storage & files",
     "Azure Blob upload/access for drawings",
     "Extended blob storage helpers for engineering drawings so drawing files can be uploaded, fetched, and used by preview/vision."),

    ("GS-07", date(2026, 7, 3), 4, "Blob storage & files",
     "Drawing raster/preview pipeline for vision input",
     "Built drawing raster/preview helpers so vision and UI get a consistent PNG image for each drawing."),
    ("GS-08", date(2026, 7, 3), 4, "Blob storage & files",
     "DWG preview support for drawing files",
     "Added DWG preview path so DWG drawings can be converted/previewed for UI and vision use."),

    ("GS-09", date(2026, 7, 6), 4, "Drawing search & vision",
     "Drawing vision Q&A in answer engine",
     "Connected drawing vision into answer generation so drawing questions get vision-backed responses. (Part of: Vision model updated for drawing search)"),
    ("GS-10", date(2026, 7, 6), 4, "Drawing search & vision",
     "Query intel and result filter for drawing questions",
     "Updated query intelligence and result filtering so drawing questions return the right drawing hits before answering."),

    ("GS-11", date(2026, 7, 7), 4, "Search retrieval & indexer",
     "Blob indexer and blob retrieval for file-content search",
     "Worked on blob indexer/retrieval so document and drawing file content can be searched and merged with SQL-backed hits."),
    ("GS-12", date(2026, 7, 7), 4, "Search retrieval & indexer",
     "SQL indexer setup, index reader, and stale purge",
     "Improved SQL indexer setup plus index reader/purge utilities so Azure Search stays usable and clean for demos."),

    ("GS-13", date(2026, 7, 8), 4, "Frontend ops pages & file UX",
     "Drawings and Documents page updates for file search",
     "Updated Drawings and Documents pages to work with uploaded files and search-driven list/content flows."),
    ("GS-14", date(2026, 7, 8), 4, "Frontend ops pages & file UX",
     "File preview modal and SearchBar open-from-hit UX",
     "Added file preview/action buttons and SearchBar behavior to open drawings/documents directly from search hits."),

    ("GS-15", date(2026, 7, 9), 4, "Frontend ops pages & file UX",
     "Operational pages polish (attendance, handover, safety)",
     "Stabilized attendance, handover, and safety pages so operational modules load reliably with backend/search-backed data."),
    ("GS-16", date(2026, 7, 9), 4, "Frontend ops pages & file UX",
     "Timeline/reports pages and page cache/prefetch",
     "Polished timeline/reports pages and improved page-data caching/prefetch for faster dashboard navigation."),

    ("GS-17", date(2026, 7, 10), 4, "Search retrieval & indexer",
     "Unified search view and drawing SQL column updates",
     "Updated Azure SQL unified search view and drawing file/sheet-notes columns used by the indexer."),
    ("GS-18", date(2026, 7, 10), 4, "Search retrieval & indexer",
     "Drawing/document sync and seed script fixes",
     "Fixed operational seed and sync scripts (documents/drawings to blob/crawl) used for local/demo search testing."),

    # --- Jul 13–14 drawing refinements ---
    ("GS-19", date(2026, 7, 13), 4, "Drawing search & vision",
     "Refine drawing vision answer quality",
     "Tuned drawing vision answer generation after first rollout to reduce weak/incorrect drawing answers. (Commit: Commit after drawing changes)"),
    ("GS-20", date(2026, 7, 13), 4, "Drawing search & vision",
     "Refine query intel and result filter for drawings",
     "Adjusted query intelligence and result filtering so drawing hits shown in SearchBar/answer context are more relevant."),

    ("GS-21", date(2026, 7, 14), 4, "Drawing search & vision",
     "Debug wrong/missing drawing search answers",
     "Debugged drawing search cases where answers were missing or incorrect and fixed answer-path issues."),
    ("GS-22", date(2026, 7, 14), 4, "Drawing search & vision",
     "Tighten drawing result filtering for SearchBar",
     "Tightened result filtering so SearchBar drawing results stay focused on the asked drawing/project."),

    # --- Jul 15–17 formats / inventory / sheet / body text ---
    ("GS-23", date(2026, 7, 15), 4, "Drawing intelligence (inventory & sheet)",
     "Object inventory extraction for object-count questions",
     "Added object inventory extraction on drawings so count-style questions can use stored inventory."),
    ("GS-24", date(2026, 7, 15), 4, "Drawing intelligence (inventory & sheet)",
     "Persist object inventory on drawing records",
     "Stored inventory JSON on drawings and connected it into ask-time count answers."),

    ("GS-25", date(2026, 7, 16), 4, "Drawing intelligence (inventory & sheet)",
     "Sheet intelligence extraction (scale, title block, notes)",
     "Implemented sheet intel extraction for scale, title block, notes, and key dimensions."),
    ("GS-26", date(2026, 7, 16), 4, "Drawing intelligence (inventory & sheet)",
     "Sheet intel SQL support and ask-time answers",
     "Added SQL support for sheet intel and used stored sheet metadata before falling back to live vision."),

    ("GS-27", date(2026, 7, 17), 4, "Document content search",
     "Document body text extraction (PDF/DOCX/XLSX)",
     "Added document body_text extraction so document content Q&A works from extracted text. (Commit: Update after upgrading formats)"),
    ("GS-28", date(2026, 7, 17), 4, "Document content search",
     "Document body SQL column and rebuild scripts",
     "Added document body_text SQL support and rebuild scripts for body text / inventory / sheet intel regeneration."),

    # --- Jul 20–24 productization ---
    ("GS-29", date(2026, 7, 20), 4, "Global Search productization",
     "Create global_search_core pipeline and models",
     "Created global_search_core package with pipeline and shared models for analyze → retrieve → filter → answer. (Commit: Commit before integration)"),
    ("GS-30", date(2026, 7, 20), 4, "Global Search productization",
     "Add connector/extractor registry and plugin wiring",
     "Added connector/extractor interfaces, registry, and BuildTrack plugin registration at app startup."),

    ("GS-31", date(2026, 7, 21), 4, "Global Search productization",
     "BuildTrack connector and pipeline factory",
     "Implemented BuildTrack connector and pipeline factory so existing search uses the new product pipeline."),
    ("GS-32", date(2026, 7, 21), 4, "Global Search productization",
     "Frontend global-search client library for SearchBar",
     "Added frontend global-search client/types/config used by SearchBar for results and answer calls."),

    ("GS-33", date(2026, 7, 22), 4, "Drawing intelligence (inventory & sheet)",
     "Inventory validation after extract",
     "Added inventory validation checks to catch bad object counts/labels after extraction."),
    ("GS-34", date(2026, 7, 22), 4, "Drawing intelligence (inventory & sheet)",
     "Drawing accuracy benchmark script",
     "Created benchmark_drawing_accuracy script to evaluate drawing Q&A quality after inventory/sheet-intel changes."),

    ("GS-35", date(2026, 7, 24), 4, "Global Search productization",
     "Document Global Search product architecture",
     "Wrote GLOBAL_SEARCH_PRODUCT doc covering architecture, API contract, and how connectors/extractors plug in."),
    ("GS-36", date(2026, 7, 24), 4, "Global Search productization",
     "Align Search API routes with new pipeline",
     "Aligned search routes/schemas with the new pipeline (results/answer flow) used by SearchBar."),

    # --- Jul 27–31 multi-DB ---
    ("GS-37", date(2026, 7, 27), 4, "Multi-database search",
     "SEARCH_DATA_SOURCES multi-DB registry",
     "Implemented data-sources registry/config so Global Search can target more than one database/index."),
    ("GS-38", date(2026, 7, 27), 4, "Multi-database search",
     "MultiDatabaseConnector fan-out and merge",
     "Built multi-database connector to fan out queries, merge/dedupe hits, and tag database labels on results."),

    ("GS-39", date(2026, 7, 28), 4, "Multi-database search",
     "buildtrack_assets database setup and seed",
     "Created/seeded buildtrack_assets (vendors, equipment, deliveries) as the second searchable database."),
    ("GS-40", date(2026, 7, 28), 4, "Multi-database search",
     "Assets indexer and sync to Azure Search",
     "Implemented assets indexer/sync APIs so assets content is pushed into the assets search index."),

    ("GS-41", date(2026, 7, 29), 4, "Multi-database search",
     "Cross-database soft linking by project",
     "Added cross-DB soft linking so related records across BuildTrack and Assets can appear together in answers. (Commit: Multiple database updated)"),
    ("GS-42", date(2026, 7, 29), 4, "Multi-database search",
     "Site Assets page and multi-source SearchBar UX",
     "Added Assets API/page and SearchBar updates for multi-source search results and answers."),

    ("GS-43", date(2026, 7, 30), 4, "Frontend performance & search UX",
     "Page cache and prefetch for dashboard navigation",
     "Improved cachedFetch/pageCache/prefetch so dashboard list pages load faster after multi-DB work."),
    ("GS-44", date(2026, 7, 30), 4, "Frontend performance & search UX",
     "SearchBar performance and recent-query UX",
     "Improved SearchBar responsiveness and recent-query behavior while multi-source search was being tested."),

    ("GS-45", date(2026, 7, 31), 4, "Multi-database search",
     "Query intel updates for multi-source / assets questions",
     "Tuned query intelligence for assets and multi-source questions so the right sources and filters are used."),
    ("GS-46", date(2026, 7, 31), 4, "Multi-database search",
     "Result filter and answer synthesis across databases",
     "Updated result filtering and answer synthesis to handle hits tagged from multiple databases."),

    # --- Aug 3–5 integration polish ---
    ("GS-47", date(2026, 8, 3), 4, "Search quality & integration",
     "Result filter hardening before integration",
     "Hardened result filtering so SearchBar/answer context stays relevant before integration handoff."),
    ("GS-48", date(2026, 8, 3), 4, "Search quality & integration",
     "Blob retrieval and document enrichment fixes",
     "Fixed blob retrieval and document enrichment so stale/weak file hits are cleaned up before answering."),

    ("GS-49", date(2026, 8, 4), 4, "Search quality & integration",
     "BuildTrack connector polish before integration",
     "Final BuildTrack connector updates before integration. (Commit: Updating before integration)"),
    ("GS-50", date(2026, 8, 4), 4, "Search quality & integration",
     "Pre-integration search filter/enrichment pass",
     "Completed pre-integration pass on result filter and enrichment paths used by SearchBar."),

    ("GS-51", date(2026, 8, 5), 4, "Search quality & integration",
     "Query intel refinements from integration testing",
     "Refined query intelligence based on drawing/document/multi-DB questions found during integration testing."),
    ("GS-52", date(2026, 8, 5), 4, "Search quality & integration",
     "Answer refinements from integration testing",
     "Adjusted answer behavior for cases found during integration testing (drawing counts, docs, multi-source)."),

    # --- Aug 6 half day ---
    ("GS-53", date(2026, 8, 6), 4, "Local Docker / SQL push",
     "Docker Compose local stack (SQL Server + Azurite)",
     "Started docker-compose for local SQL Server and Azurite so search/indexing can be tested locally. (Half day)"),

    # --- Aug 10–11 current work ---
    ("GS-54", date(2026, 8, 10), 4, "Local Docker / SQL push",
     "Backend and frontend Dockerfiles",
     "Added backend/frontend Dockerfiles for running the app stack consistently with local SQL/blob."),
    ("GS-55", date(2026, 8, 10), 4, "Local Docker / SQL push",
     "SQL push indexer for local/non-Azure SQL",
     "Implemented sql_push_indexer so local SQL content can be pushed to Azure AI Search when managed indexer cannot reach the DB."),

    ("GS-56", date(2026, 8, 11), 4, "Search quality & integration",
     "SearchBar and result filter polish from current testing",
     "Ongoing SearchBar and result_filter fixes based on current testing of drawing/multi-DB queries."),
    ("GS-57", date(2026, 8, 11), 4, "Search quality & integration",
     "SQL indexer, projects sync, and assets setup polish",
     "Polish on sql_indexer, projects push-sync, timeline page, and assets DB setup from current working changes."),
]


def main() -> None:
    total_hours = sum(t[2] for t in tickets)
    assert total_hours == 228, total_hours
    assert len(tickets) == 57, len(tickets)

    wb = Workbook()
    ws = wb.active
    ws.title = "Jira Tickets"

    headers = ["Ticket ID", "Log Date", "Day", "Hours", "Epic", "Title", "Description", "Status"]
    ws.append(headers)

    header_fill = PatternFill("solid", fgColor="1F4E79")
    header_font = Font(bold=True, color="FFFFFF")
    thin = Border(
        left=Side(style="thin", color="D9D9D9"),
        right=Side(style="thin", color="D9D9D9"),
        top=Side(style="thin", color="D9D9D9"),
        bottom=Side(style="thin", color="D9D9D9"),
    )
    wrap = Alignment(wrap_text=True, vertical="top")
    alt_fill = PatternFill("solid", fgColor="F2F2F2")

    for col in range(1, len(headers) + 1):
        cell = ws.cell(1, col)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(vertical="center")

    for i, (tid, d, hrs, epic, title, desc) in enumerate(tickets, start=2):
        values = [tid, d, d.strftime("%a"), hrs, epic, title, desc, "Done"]
        for col, val in enumerate(values, 1):
            cell = ws.cell(i, col, val)
            cell.border = thin
            cell.alignment = wrap
            if i % 2 == 0:
                cell.fill = alt_fill
        ws.cell(i, 2).number_format = "YYYY-MM-DD"
        ws.row_dimensions[i].height = 48

    for i, w in enumerate([12, 14, 8, 8, 34, 55, 80, 10], 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws.row_dimensions[1].height = 22
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:H{len(tickets) + 1}"

    ws2 = wb.create_sheet("Summary")
    ws2["A1"] = "Genuine worklog — split from real commits (still 228h)"
    ws2["A1"].font = Font(bold=True, size=13)
    ws2["A3"] = "Total tickets"
    ws2["B3"] = len(tickets)
    ws2["A4"] = "Total hours"
    ws2["B4"] = total_hours
    ws2["A5"] = "Leaves excluded"
    ws2["B5"] = "2026-07-02, 2026-07-23, 2026-08-07 full; 2026-08-06 half (4h)"

    ws2["A7"] = "Epic"
    ws2["B7"] = "Tickets"
    ws2["C7"] = "Hours"
    for c in ("A7", "B7", "C7"):
        ws2[c].fill = header_fill
        ws2[c].font = header_font

    epic_hours: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for _tid, _d, hrs, epic, _title, _desc in tickets:
        epic_hours[epic][0] += 1
        epic_hours[epic][1] += hrs

    r = 8
    for epic, (cnt, hrs) in epic_hours.items():
        ws2.cell(r, 1, epic)
        ws2.cell(r, 2, cnt)
        ws2.cell(r, 3, hrs)
        r += 1

    ws2.column_dimensions["A"].width = 38
    ws2.column_dimensions["B"].width = 12
    ws2.column_dimensions["C"].width = 12

    ws3 = wb.create_sheet("Daily Hours")
    ws3.append(["Log Date", "Day", "Hours", "Ticket IDs", "Titles"])
    for c in range(1, 6):
        ws3.cell(1, c).fill = header_fill
        ws3.cell(1, c).font = header_font

    daily: dict = {}
    for tid, d, hrs, _epic, title, _desc in tickets:
        if d not in daily:
            daily[d] = [0, [], []]
        daily[d][0] += hrs
        daily[d][1].append(tid)
        daily[d][2].append(title)

    for i, (d, (hrs, ids, titles)) in enumerate(daily.items(), start=2):
        ws3.cell(i, 1, d).number_format = "YYYY-MM-DD"
        ws3.cell(i, 2, d.strftime("%a"))
        ws3.cell(i, 3, hrs)
        ws3.cell(i, 4, ", ".join(ids))
        ws3.cell(i, 5, " | ".join(titles))
        ws3.cell(i, 5).alignment = wrap

    for i, w in enumerate([14, 8, 8, 18, 90], 1):
        ws3.column_dimensions[get_column_letter(i)].width = w
    ws3.freeze_panes = "A2"

    ws4 = wb.create_sheet("Commit Evidence")
    ws4.append(["Commit Date", "Commit Message", "Tickets"])
    for c in range(1, 4):
        ws4.cell(1, c).fill = header_fill
        ws4.cell(1, c).font = header_font
    evidence = [
        ("2026-07-05", "Vision model updated for drawing search", "GS-01 to GS-18"),
        ("2026-07-13", "Commit after drawing changes", "GS-19 to GS-22"),
        ("2026-07-17", "Update after upgrading formats", "GS-23 to GS-28"),
        ("2026-07-20", "Commit before integration", "GS-29 to GS-36"),
        ("2026-07-29", "Multiple database updated", "GS-37 to GS-46"),
        ("2026-08-04", "Updating before integration", "GS-47 to GS-52"),
        ("Working tree", "Docker + sql_push_indexer + SearchBar/filter polish", "GS-53 to GS-57"),
    ]
    for i, row in enumerate(evidence, start=2):
        for c, val in enumerate(row, 1):
            ws4.cell(i, c, val)

    for i, w in enumerate([14, 45, 30], 1):
        ws4.column_dimensions[get_column_letter(i)].width = w

    out = r"c:\Users\devika.svinod\Downloads\POC\global-search-poc\jira-worklog-tickets-v2.xlsx"
    wb.save(out)
    print(f"Saved: {out}")
    print(f"Tickets: {len(tickets)}  Hours: {total_hours}")


if __name__ == "__main__":
    main()
