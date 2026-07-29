import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import engine, Base, ping_database
from app.api.routes import auth, projects, tasks, team, documents, search, operational, files, assets

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def _db_keepalive_loop():
    interval = max(settings.DB_KEEPALIVE_MINUTES, 1) * 60
    while True:
        await asyncio.sleep(interval)
        ok = await asyncio.to_thread(ping_database)
        if ok:
            logger.debug("Database keepalive ping OK")
        else:
            logger.warning("Database keepalive ping failed")


def _init_database_sync():
    import app.models.user
    import app.models.project
    import app.models.task
    import app.models.team
    import app.models.document
    import app.models.operational

    Base.metadata.create_all(bind=engine)
    logger.info("Database tables ready")


@asynccontextmanager
async def lifespan(app: FastAPI):
    keepalive_task = None

    if settings.SKIP_DB_INIT:
        logger.info("Skipping DB init (SKIP_DB_INIT=true)")
    else:
        asyncio.create_task(asyncio.to_thread(_init_database_sync))
        asyncio.create_task(_run_seed_tasks())

    from app.plugins import register_all_plugins

    register_all_plugins()
    logger.info("Global Search plugins registered")

    # Second Global Search database on Azure SQL: buildtrack_assets
    try:
        from app.core.data_sources import clear_data_source_caches, ensure_assets_database

        db_name = await asyncio.to_thread(ensure_assets_database)
        clear_data_source_caches()
        logger.info("Site Assets Azure SQL database ready: %s", db_name)
    except Exception as exc:
        logger.warning("Could not initialize Site Assets Azure SQL database: %s", exc)

    # Push assets into Azure AI Search when the dedicated index is empty/missing docs
    if settings.AZURE_SEARCH_ENDPOINT and settings.AZURE_SEARCH_KEY:
        async def _sync_assets_index():
            try:
                from app.search.assets_indexer import (
                    assets_index_doc_count,
                    sync_assets_to_azure_search,
                )

                count = await asyncio.to_thread(assets_index_doc_count)
                if count is None or count == 0:
                    stats = await asyncio.to_thread(
                        lambda: sync_assets_to_azure_search(embed=True)
                    )
                    logger.info("Assets Azure index sync: %s", stats.get("message"))
                else:
                    logger.info("Assets Azure index already has %s docs", count)
            except Exception as exc:
                logger.warning("Assets Azure index sync skipped: %s", exc)

        asyncio.create_task(_sync_assets_index())

    if settings.DATABASE_URL.startswith("mssql"):
        keepalive_task = asyncio.create_task(_db_keepalive_loop())
        asyncio.create_task(asyncio.to_thread(ping_database))

    # Warm Azure Search list caches so Documents/Drawings/Projects open quickly.
    if settings.AZURE_SEARCH_ENDPOINT and settings.AZURE_SEARCH_KEY:
        async def _warm_page_indexes():
            try:
                from app.search import index_reader

                for ctype in ("document", "drawing", "project", "team", "task"):
                    await asyncio.to_thread(index_reader.list_indexed, ctype)
                logger.info("Page index caches warmed (document/drawing/project/team/task)")
            except Exception as exc:
                logger.warning("Page index warm-up skipped: %s", exc)

        asyncio.create_task(_warm_page_indexes())

    yield

    if keepalive_task:
        keepalive_task.cancel()
        try:
            await keepalive_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="BuildTrack API",
    description="Construction Project Management Platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(team.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(search.router, prefix="/api")
app.include_router(operational.router, prefix="/api")
app.include_router(files.router, prefix="/api")
app.include_router(assets.router, prefix="/api")


def seed_kpi_if_needed_sync():
    from app.core.database import SessionLocal
    from app.seed_kpi import seed_kpi_tables
    from app.models.operational import SafetyKpiMetrics

    db = SessionLocal()
    try:
        if db.query(SafetyKpiMetrics).count() == 0:
            seed_kpi_tables(db)
    finally:
        db.close()


async def _run_seed_tasks():
    await asyncio.to_thread(seed_database_sync)
    await asyncio.to_thread(seed_operational_if_needed_sync)
    await asyncio.to_thread(seed_kpi_if_needed_sync)


def seed_operational_if_needed_sync():
    from app.core.database import SessionLocal
    from app.seed_operational import seed_operational_data
    from app.models.operational import HandoverDocument

    db = SessionLocal()
    try:
        if db.query(HandoverDocument).count() == 0:
            seed_operational_data(db)
    finally:
        db.close()


def seed_database_sync():
    from sqlalchemy.orm import Session
    from app.core.database import SessionLocal
    from app.core.security import get_password_hash
    from app.models.user import User, UserRole
    from app.models.project import Project, ProjectStatus
    from app.models.task import Task, TaskStatus, TaskPriority
    from app.models.team import TeamMember
    from app.models.document import Document
    from datetime import date

    db: Session = SessionLocal()
    try:
        if db.query(User).count() > 0:
            return

        logger.info("Seeding database with sample data...")

        users_data = [
            {"full_name": "Devika S Vinod", "email": "devika@buildtrack.com", "password": "password123", "company_name": "BuildTrack", "role": UserRole.admin},
            {"full_name": "Sarah Chen", "email": "sarah@buildtrack.com", "password": "password123", "company_name": "ChenBuild Corp", "role": UserRole.project_manager},
            {"full_name": "James Okafor", "email": "james@buildtrack.com", "password": "password123", "company_name": "Okafor Engineering", "role": UserRole.site_engineer},
            {"full_name": "Priya Nair", "email": "priya@buildtrack.com", "password": "password123", "company_name": "NairTech Ltd", "role": UserRole.project_manager},
            {"full_name": "David Reyes", "email": "david@buildtrack.com", "password": "password123", "company_name": "Reyes Contractors", "role": UserRole.contractor},
            {"full_name": "Emily Watson", "email": "emily@buildtrack.com", "password": "password123", "company_name": "Watson Build", "role": UserRole.site_engineer},
            {"full_name": "Carlos Mendez", "email": "carlos@buildtrack.com", "password": "password123", "company_name": "Mendez & Sons", "role": UserRole.contractor},
            {"full_name": "Aisha Johnson", "email": "aisha@buildtrack.com", "password": "password123", "company_name": "Johnson Infrastructure", "role": UserRole.site_engineer},
        ]
        users = []
        for u in users_data:
            user = User(
                full_name=u["full_name"],
                email=u["email"],
                hashed_password=get_password_hash(u["password"]),
                company_name=u["company_name"],
                role=u["role"],
            )
            db.add(user)
            users.append(user)
        db.commit()
        for u in users:
            db.refresh(u)

        projects_data = [
            {
                "name": "Highway Bridge Expansion",
                "description": "Expansion of the I-95 highway bridge to add two additional lanes and improve traffic flow. Includes structural reinforcement and modern safety features.",
                "status": ProjectStatus.in_progress,
                "start_date": date(2024, 1, 15),
                "end_date": date(2025, 6, 30),
                "budget": 45000000.00,
                "location": "Interstate I-95, Miami, FL",
                "progress": 62,
                "project_manager_id": users[1].id,
            },
            {
                "name": "Commercial Tower Phase 2",
                "description": "Construction of a 35-story commercial office tower in downtown Houston. Phase 2 includes floors 18-35, parking structure, and rooftop amenities.",
                "status": ProjectStatus.planning,
                "start_date": date(2024, 6, 1),
                "end_date": date(2026, 12, 31),
                "budget": 120000000.00,
                "location": "1200 Main Street, Houston, TX",
                "progress": 15,
                "project_manager_id": users[3].id,
            },
            {
                "name": "Metro Station Renovation",
                "description": "Complete renovation of the Central Metro Station including platform upgrades, accessibility improvements, digital signage installation, and structural repairs.",
                "status": ProjectStatus.in_progress,
                "start_date": date(2023, 9, 1),
                "end_date": date(2025, 3, 31),
                "budget": 18500000.00,
                "location": "Central Metro Station, Chicago, IL",
                "progress": 78,
                "project_manager_id": users[1].id,
            },
            {
                "name": "Industrial Warehouse Build",
                "description": "Construction of a 250,000 sq ft industrial warehouse facility with loading docks, cold storage sections, office spaces, and automated conveyor systems.",
                "status": ProjectStatus.completed,
                "start_date": date(2023, 3, 1),
                "end_date": date(2024, 2, 28),
                "budget": 22000000.00,
                "location": "Logistics Park, Dallas, TX",
                "progress": 100,
                "project_manager_id": users[3].id,
            },
            {
                "name": "Residential Complex A",
                "description": "Development of a 200-unit residential complex with mixed amenities including gym, pool, parking garage, and landscaped common areas. Project currently on hold pending permit approvals.",
                "status": ProjectStatus.on_hold,
                "start_date": date(2024, 4, 1),
                "end_date": date(2026, 8, 31),
                "budget": 65000000.00,
                "location": "Oakwood District, Atlanta, GA",
                "progress": 8,
                "project_manager_id": users[1].id,
            },
        ]
        projects = []
        for p in projects_data:
            project = Project(**p)
            db.add(project)
            projects.append(project)
        db.commit()
        for p in projects:
            db.refresh(p)

        tasks_data = [
            {"title": "Site Survey & Geotechnical Analysis", "description": "Conduct comprehensive soil testing and topographic survey for bridge expansion area", "status": TaskStatus.done, "priority": TaskPriority.high, "project_id": projects[0].id, "assignee_id": users[2].id, "due_date": date(2024, 2, 15)},
            {"title": "Foundation Pile Driving", "description": "Install 48 concrete piles to specified depths per structural engineering drawings", "status": TaskStatus.done, "priority": TaskPriority.high, "project_id": projects[0].id, "assignee_id": users[4].id, "due_date": date(2024, 4, 30)},
            {"title": "Steel Erection - Main Span", "description": "Erect primary steel girders and cross-bracing for the main bridge span", "status": TaskStatus.in_progress, "priority": TaskPriority.high, "project_id": projects[0].id, "assignee_id": users[6].id, "due_date": date(2024, 8, 31)},
            {"title": "Deck Formwork & Concrete Pour", "description": "Set formwork and pour reinforced concrete deck sections in sequential phases", "status": TaskStatus.todo, "priority": TaskPriority.medium, "project_id": projects[0].id, "assignee_id": users[2].id, "due_date": date(2024, 11, 30)},
            {"title": "Architectural Design Review", "description": "Review and finalize architectural drawings for floors 18-35 with the design team", "status": TaskStatus.in_progress, "priority": TaskPriority.high, "project_id": projects[1].id, "assignee_id": users[3].id, "due_date": date(2024, 7, 31)},
            {"title": "Permit & Zoning Approvals", "description": "Submit and track building permits with city planning department for Phase 2", "status": TaskStatus.review, "priority": TaskPriority.high, "project_id": projects[1].id, "assignee_id": users[3].id, "due_date": date(2024, 9, 15)},
            {"title": "Utility Relocation Planning", "description": "Coordinate with utilities for temporary service relocation during metro renovation", "status": TaskStatus.done, "priority": TaskPriority.high, "project_id": projects[2].id, "assignee_id": users[5].id, "due_date": date(2024, 1, 31)},
            {"title": "Platform Surface Replacement", "description": "Remove existing platform tiles and install new non-slip safety-compliant surfaces", "status": TaskStatus.in_progress, "priority": TaskPriority.medium, "project_id": projects[2].id, "assignee_id": users[7].id, "due_date": date(2024, 7, 31)},
            {"title": "Accessibility Ramp Installation", "description": "Install ADA-compliant ramps and elevators at all station entry/exit points", "status": TaskStatus.review, "priority": TaskPriority.high, "project_id": projects[2].id, "assignee_id": users[4].id, "due_date": date(2024, 8, 15)},
            {"title": "Electrical Wiring & Distribution", "description": "Install complete electrical distribution system including emergency lighting and power", "status": TaskStatus.todo, "priority": TaskPriority.medium, "project_id": projects[2].id, "assignee_id": users[6].id, "due_date": date(2024, 10, 31)},
            {"title": "Warehouse Foundation & Slab", "description": "Pour reinforced concrete foundation and 8-inch thick warehouse floor slab", "status": TaskStatus.done, "priority": TaskPriority.high, "project_id": projects[3].id, "assignee_id": users[2].id, "due_date": date(2023, 7, 31)},
            {"title": "Steel Structure Erection", "description": "Erect pre-engineered metal building structure including columns, beams, and roof", "status": TaskStatus.done, "priority": TaskPriority.high, "project_id": projects[3].id, "assignee_id": users[4].id, "due_date": date(2023, 11, 30)},
            {"title": "Residential Permit Application", "description": "Prepare and submit comprehensive permit application to city planning office", "status": TaskStatus.in_progress, "priority": TaskPriority.high, "project_id": projects[4].id, "assignee_id": users[3].id, "due_date": date(2024, 9, 30)},
            {"title": "Environmental Impact Assessment", "description": "Commission and complete environmental impact study for the residential site", "status": TaskStatus.review, "priority": TaskPriority.medium, "project_id": projects[4].id, "assignee_id": users[5].id, "due_date": date(2024, 8, 31)},
            {"title": "Traffic Management Plan", "description": "Develop construction-period traffic management plan for surrounding neighborhood", "status": TaskStatus.todo, "priority": TaskPriority.low, "project_id": projects[4].id, "assignee_id": users[7].id, "due_date": date(2024, 10, 15)},
        ]
        for t in tasks_data:
            task = Task(**t)
            db.add(task)
        db.commit()

        team_data = [
            {"user_id": users[0].id, "project_id": projects[0].id, "role": "Admin"},
            {"user_id": users[1].id, "project_id": projects[0].id, "role": "Project Manager"},
            {"user_id": users[2].id, "project_id": projects[0].id, "role": "Site Engineer"},
            {"user_id": users[4].id, "project_id": projects[0].id, "role": "Contractor"},
            {"user_id": users[3].id, "project_id": projects[1].id, "role": "Project Manager"},
            {"user_id": users[5].id, "project_id": projects[1].id, "role": "Site Engineer"},
            {"user_id": users[1].id, "project_id": projects[2].id, "role": "Project Manager"},
            {"user_id": users[7].id, "project_id": projects[2].id, "role": "Site Engineer"},
            {"user_id": users[4].id, "project_id": projects[2].id, "role": "Contractor"},
            {"user_id": users[6].id, "project_id": projects[2].id, "role": "Contractor"},
            {"user_id": users[3].id, "project_id": projects[3].id, "role": "Project Manager"},
            {"user_id": users[2].id, "project_id": projects[3].id, "role": "Site Engineer"},
            {"user_id": users[1].id, "project_id": projects[4].id, "role": "Project Manager"},
            {"user_id": users[3].id, "project_id": projects[4].id, "role": "Site Engineer"},
        ]
        for m in team_data:
            member = TeamMember(**m)
            db.add(member)
        db.commit()

        documents_data = [
            {"name": "Site Plan - Bridge Expansion.pdf", "file_type": "PDF", "file_url": "/uploads/site-plan-bridge.pdf", "project_id": projects[0].id, "uploaded_by": users[1].id, "file_size": 4500000},
            {"name": "Foundation Drawing Rev3.dwg", "file_type": "DWG", "file_url": "/uploads/foundation-drawing.dwg", "project_id": projects[0].id, "uploaded_by": users[2].id, "file_size": 2800000},
            {"name": "Bridge Budget Report Q2.xlsx", "file_type": "XLSX", "file_url": "/uploads/bridge-budget.xlsx", "project_id": projects[0].id, "uploaded_by": users[1].id, "file_size": 520000},
            {"name": "Commercial Tower Floor Plans.pdf", "file_type": "PDF", "file_url": "/uploads/tower-floor-plans.pdf", "project_id": projects[1].id, "uploaded_by": users[3].id, "file_size": 12000000},
            {"name": "Structural Engineering Report.pdf", "file_type": "PDF", "file_url": "/uploads/structural-report.pdf", "project_id": projects[1].id, "uploaded_by": users[3].id, "file_size": 6700000},
            {"name": "Metro Station Renovation Specs.pdf", "file_type": "PDF", "file_url": "/uploads/metro-specs.pdf", "project_id": projects[2].id, "uploaded_by": users[1].id, "file_size": 8900000},
            {"name": "Accessibility Compliance Checklist.xlsx", "file_type": "XLSX", "file_url": "/uploads/accessibility-checklist.xlsx", "project_id": projects[2].id, "uploaded_by": users[5].id, "file_size": 340000},
            {"name": "Warehouse Layout Drawing.dwg", "file_type": "DWG", "file_url": "/uploads/warehouse-layout.dwg", "project_id": projects[3].id, "uploaded_by": users[2].id, "file_size": 3100000},
            {"name": "Project Completion Certificate.pdf", "file_type": "PDF", "file_url": "/uploads/completion-cert.pdf", "project_id": projects[3].id, "uploaded_by": users[3].id, "file_size": 1200000},
            {"name": "Residential Complex Master Plan.pdf", "file_type": "PDF", "file_url": "/uploads/residential-master-plan.pdf", "project_id": projects[4].id, "uploaded_by": users[1].id, "file_size": 15400000},
        ]
        for d in documents_data:
            doc = Document(**d)
            db.add(doc)
        db.commit()

        if settings.AZURE_STORAGE_CONNECTION_STRING:
            from sqlalchemy.orm import joinedload
            from app.storage.document_blob import (
                blob_name_for_document,
                generate_document_bytes,
                is_blob_url,
                upload_bytes_to_blob,
            )

            for doc in (
                db.query(Document)
                .options(joinedload(Document.project))
                .filter(Document.file_url.like("/uploads/%"))
                .all()
            ):
                try:
                    content, content_type = generate_document_bytes(
                        doc.name,
                        doc.file_type,
                        doc.project.name if doc.project else None,
                        doc.id,
                    )
                    url, size = upload_bytes_to_blob(
                        content,
                        blob_name_for_document(doc.id, doc.name),
                        content_type,
                        document_id=doc.id,
                        project_id=doc.project_id,
                        original_filename=doc.name,
                    )
                    doc.file_url = url
                    doc.file_size = size
                except Exception as blob_err:
                    logger.warning("Seed blob upload failed for %s: %s", doc.name, blob_err)
            db.commit()

        logger.info("Database seeded successfully!")

    except Exception as e:
        logger.error(f"Seeding error: {e}")
        db.rollback()
    finally:
        db.close()


@app.get("/api/health")
async def health_check():
    """Always instant — does not touch the database."""
    return {"status": "healthy", "service": "BuildTrack API"}


@app.get("/api/health/db")
async def health_db_check():
    ok = await asyncio.to_thread(ping_database)
    if ok:
        return {"status": "healthy", "database": "connected"}
    return {"status": "degraded", "database": "unavailable"}
