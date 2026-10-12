"""
Create and seed the Site Assets & Procurement database on Azure SQL.

Creates database `buildtrack_assets` on the same Azure SQL server as DATABASE_URL,
with vendors / equipment / material_deliveries + flattened search_documents.

Usage (from backend/):
  python -m scripts.setup_assets_db
  python -m scripts.setup_assets_db --force
"""
from __future__ import annotations

import json
import logging
import sys
import time
from typing import Optional

from sqlalchemy import Column, Float, Integer, String, Text, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger(__name__)

ASSETS_DB_NAME = "buildtrack_assets"

Base = declarative_base()


class Vendor(Base):
    __tablename__ = "vendors"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    category = Column(String(80), nullable=False)
    contact_email = Column(String(200))
    phone = Column(String(40))
    rating = Column(Float, default=4.0)
    status = Column(String(40), default="Active")
    notes = Column(Text)


class Equipment(Base):
    __tablename__ = "equipment"

    id = Column(Integer, primary_key=True)
    asset_tag = Column(String(40), unique=True, nullable=False)
    name = Column(String(200), nullable=False)
    category = Column(String(80), nullable=False)
    project_name = Column(String(200))
    status = Column(String(40), default="On Site")
    vendor_name = Column(String(200))
    location = Column(String(200))
    last_service_date = Column(String(20))
    notes = Column(Text)


class MaterialDelivery(Base):
    __tablename__ = "material_deliveries"

    id = Column(Integer, primary_key=True)
    delivery_ref = Column(String(40), unique=True, nullable=False)
    material_name = Column(String(200), nullable=False)
    quantity = Column(Float, nullable=False)
    unit = Column(String(40), nullable=False)
    project_name = Column(String(200))
    vendor_name = Column(String(200))
    status = Column(String(40), default="Ordered")
    expected_date = Column(String(20))
    delivered_date = Column(String(20))
    notes = Column(Text)


class SearchDocument(Base):
    """Flattened rows pushed into Azure AI Search (buildtrack-assets-index)."""

    __tablename__ = "search_documents"

    id = Column(String(80), primary_key=True)
    title = Column(String(300), nullable=False)
    content = Column(Text, nullable=False)
    content_type = Column(String(40), nullable=False)
    url = Column(String(300), default="")
    metadata_json = Column(Text, default="{}")


def resolve_assets_database_url(primary_url: Optional[str] = None):
    """
    Return a SQLAlchemy URL object for the assets DB
    (never stringify — passwords with # break URL strings).
    """
    from app.core.config import settings

    if settings.ASSETS_DATABASE_URL:
        return make_url(settings.ASSETS_DATABASE_URL)
    primary = primary_url or settings.DATABASE_URL
    url = make_url(primary) if isinstance(primary, str) else primary
    if not url.database:
        raise RuntimeError("DATABASE_URL has no database name to derive assets URL from")
    return url.set(database=ASSETS_DB_NAME)


def _as_url(sqlalchemy_url):
    if hasattr(sqlalchemy_url, "host"):
        return sqlalchemy_url
    return make_url(sqlalchemy_url)


def _query_value(u, key: str, default: str) -> str:
    if not u.query or not u.query.get(key):
        return default
    val = u.query.get(key)
    return val[0] if isinstance(val, (list, tuple)) else str(val)


def _odbc_connect_string(sqlalchemy_url) -> str:
    """Build a raw ODBC connection string (handles passwords with @ / #).

    Encrypt/TrustServerCertificate default to Azure SQL's expectations (encrypted,
    real CA cert) but can be overridden via the DATABASE_URL query string — e.g. for
    a local SQL Server container with a self-signed cert, add
    "&TrustServerCertificate=yes" to DATABASE_URL.
    """
    u = _as_url(sqlalchemy_url)
    driver = (u.query.get("driver") if u.query else None) or "ODBC Driver 18 for SQL Server"
    if isinstance(driver, (list, tuple)):
        driver = driver[0]
    encrypt = _query_value(u, "Encrypt", "yes")
    trust_cert = _query_value(u, "TrustServerCertificate", "no")

    return (
        f"Driver={{{driver}}};"
        f"Server=tcp:{u.host},{u.port or 1433};"
        f"Database={u.database};"
        f"Uid={u.username};"
        f"Pwd={{{u.password}}};"
        f"Encrypt={encrypt};"
        f"TrustServerCertificate={trust_cert};"
        f"Connection Timeout=60;"
    )


def create_mssql_engine(sqlalchemy_url, *, autocommit: bool = False):
    """Create an engine using an explicit ODBC connect string (password-safe)."""
    import pyodbc

    odbc = _odbc_connect_string(sqlalchemy_url)

    def _creator():
        return pyodbc.connect(odbc, autocommit=autocommit)

    return create_engine(
        "mssql+pyodbc://",
        creator=_creator,
        pool_pre_ping=True,
    )


def _assets_engine_url(primary_url: Optional[str] = None):
    """URL object for assets DB."""
    return resolve_assets_database_url(primary_url)


def _is_azure_sql_host(host: Optional[str]) -> bool:
    return bool(host) and host.lower().endswith(".database.windows.net")


def ensure_azure_database_exists(primary_url: str, db_name: str = ASSETS_DB_NAME) -> None:
    """CREATE DATABASE on the SQL Server if missing (connects to master).

    Uses Azure SQL's EDITION/SERVICE_OBJECTIVE syntax + ONLINE polling when the
    target is an Azure SQL logical server (*.database.windows.net). Falls back to
    plain CREATE DATABASE for local/on-prem SQL Server (e.g. a Docker container
    used for local development), where those Azure-only options aren't supported
    and the database is available immediately.
    """
    master_url = make_url(primary_url).set(database="master")
    master = create_mssql_engine(master_url, autocommit=True)
    is_azure = _is_azure_sql_host(master_url.host)
    try:
        with master.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM sys.databases WHERE name = :n"),
                {"n": db_name},
            ).scalar()
            if exists:
                print(f"SQL Server database already exists: {db_name}")
                return
            if is_azure:
                print(f"Creating Azure SQL database '{db_name}' (Basic)…")
                # Same tier family as existing buildtrack Basic DB
                conn.execute(
                    text(
                        f"CREATE DATABASE [{db_name}] "
                        f"(EDITION = 'Basic', SERVICE_OBJECTIVE = 'Basic')"
                    )
                )
            else:
                print(f"Creating local SQL Server database '{db_name}'…")
                conn.execute(text(f"CREATE DATABASE [{db_name}]"))
        if not is_azure:
            # Local SQL Server databases are available immediately — no ONLINE poll needed.
            print(f"Local SQL Server database ready: {db_name}")
            return
        # Azure SQL: wait until online
        for _ in range(60):
            time.sleep(3)
            with master.connect() as conn:
                state = conn.execute(
                    text(
                        "SELECT state_desc FROM sys.databases WHERE name = :n"
                    ),
                    {"n": db_name},
                ).scalar()
            if state == "ONLINE":
                print(f"Azure SQL database online: {db_name}")
                return
            print(f"  waiting for ONLINE (state={state})…")
        raise RuntimeError(f"Database {db_name} did not become ONLINE in time")
    finally:
        master.dispose()


def _rebuild_search_documents(session) -> None:
    session.execute(text("DELETE FROM search_documents"))
    docs: list[SearchDocument] = []

    for v in session.query(Vendor).all():
        content = (
            f"{v.name} vendor {v.category} {v.status} "
            f"contact {v.contact_email or ''} {v.phone or ''} "
            f"rating {v.rating} {v.notes or ''}"
        )
        docs.append(
            SearchDocument(
                id=f"vendor-{v.id}",
                title=v.name,
                content=content,
                content_type="vendor",
                url="/assets?tab=vendors",
                metadata_json=json.dumps(
                    {
                        "category": v.category,
                        "status": v.status,
                        "rating": v.rating,
                        "email": v.contact_email,
                        "phone": v.phone,
                    }
                ),
            )
        )

    for e in session.query(Equipment).all():
        content = (
            f"{e.asset_tag} {e.name} {e.category} equipment "
            f"project {e.project_name or ''} status {e.status} "
            f"vendor {e.vendor_name or ''} location {e.location or ''} "
            f"serviced {e.last_service_date or ''} {e.notes or ''}"
        )
        docs.append(
            SearchDocument(
                id=f"equipment-{e.id}",
                title=f"{e.asset_tag} - {e.name}",
                content=content,
                content_type="equipment",
                url="/assets?tab=equipment",
                metadata_json=json.dumps(
                    {
                        "asset_tag": e.asset_tag,
                        "category": e.category,
                        "status": e.status,
                        "project": e.project_name,
                        "vendor": e.vendor_name,
                        "location": e.location,
                    }
                ),
            )
        )

    for m in session.query(MaterialDelivery).all():
        content = (
            f"{m.delivery_ref} {m.material_name} material delivery "
            f"{m.quantity} {m.unit} project {m.project_name or ''} "
            f"vendor {m.vendor_name or ''} status {m.status} "
            f"expected {m.expected_date or ''} delivered {m.delivered_date or ''} "
            f"{m.notes or ''}"
        )
        docs.append(
            SearchDocument(
                id=f"material-{m.id}",
                title=f"{m.delivery_ref} - {m.material_name}",
                content=content,
                content_type="material",
                url="/assets?tab=materials",
                metadata_json=json.dumps(
                    {
                        "delivery_ref": m.delivery_ref,
                        "quantity": m.quantity,
                        "unit": m.unit,
                        "status": m.status,
                        "project": m.project_name,
                        "vendor": m.vendor_name,
                        "expected_date": m.expected_date,
                        "delivered_date": m.delivered_date,
                    }
                ),
            )
        )

    session.add_all(docs)


def seed(session) -> None:
    vendors = [
        Vendor(
            name="Gulf Coast Crane Rentals",
            category="Equipment Rental",
            contact_email="dispatch@gccrane.com",
            phone="+1-305-555-0142",
            rating=4.7,
            status="Active",
            notes="Preferred crane supplier for Highway Bridge Expansion",
        ),
        Vendor(
            name="Midwest Steel Supply",
            category="Materials",
            contact_email="orders@midweststeel.com",
            phone="+1-312-555-0198",
            rating=4.5,
            status="Active",
            notes="Structural steel and rebar for Metro Station Renovation",
        ),
        Vendor(
            name="Houston MEP Partners",
            category="MEP",
            contact_email="projects@houstonmep.com",
            phone="+1-713-555-0110",
            rating=4.2,
            status="Active",
            notes="Electrical and HVAC packages for Commercial Tower Phase 2",
        ),
        Vendor(
            name="Atlas Scaffolding Co",
            category="Equipment Rental",
            contact_email="yard@atlasscaffold.com",
            phone="+1-214-555-0177",
            rating=4.0,
            status="Active",
            notes="Scaffold systems for Industrial Warehouse Build",
        ),
        Vendor(
            name="SafeSite PPE Distributors",
            category="Safety Supplies",
            contact_email="sales@safesiteppe.com",
            phone="+1-404-555-0166",
            rating=4.8,
            status="Active",
            notes="PPE and temporary safety barriers for all active sites",
        ),
    ]
    session.add_all(vendors)
    session.flush()

    equipment = [
        Equipment(
            asset_tag="CRN-220",
            name="220-ton Crawler Crane",
            category="Crane",
            project_name="Highway Bridge Expansion",
            status="On Site",
            vendor_name="Gulf Coast Crane Rentals",
            location="I-95 Miami — Span 2 laydown",
            last_service_date="2026-06-12",
            notes="Assigned to steel erection main span",
        ),
        Equipment(
            asset_tag="EXC-045",
            name="45-ton Hydraulic Excavator",
            category="Earthmoving",
            project_name="Metro Station Renovation",
            status="On Site",
            vendor_name="Gulf Coast Crane Rentals",
            location="Central Metro Station — north pit",
            last_service_date="2026-05-28",
            notes="Utility trench excavation and spoil removal",
        ),
        Equipment(
            asset_tag="GEN-800",
            name="800 kVA Site Generator",
            category="Power",
            project_name="Commercial Tower Phase 2",
            status="Maintenance",
            vendor_name="Houston MEP Partners",
            location="Houston yard — bay 3",
            last_service_date="2026-07-01",
            notes="Awaiting alternator bearing replacement before remobilization",
        ),
        Equipment(
            asset_tag="SCF-1200",
            name="System Scaffold Package 1200 m2",
            category="Scaffolding",
            project_name="Industrial Warehouse Build",
            status="Available",
            vendor_name="Atlas Scaffolding Co",
            location="Dallas Logistics Park — storage yard",
            last_service_date="2026-04-18",
            notes="Released after warehouse completion; available for Residential Complex A",
        ),
        Equipment(
            asset_tag="LIF-012",
            name="Articulating Boom Lift 60 ft",
            category="Access",
            project_name="Metro Station Renovation",
            status="On Site",
            vendor_name="Atlas Scaffolding Co",
            location="Central Metro Station — platform B",
            last_service_date="2026-06-30",
            notes="Used for digital signage and ceiling works",
        ),
        Equipment(
            asset_tag="PMP-Concrete-03",
            name="Concrete Pump Truck",
            category="Concrete",
            project_name="Highway Bridge Expansion",
            status="On Site",
            vendor_name="Midwest Steel Supply",
            location="I-95 Miami — deck pour staging",
            last_service_date="2026-07-08",
            notes="Scheduled for sequential deck pours",
        ),
    ]
    session.add_all(equipment)

    deliveries = [
        MaterialDelivery(
            delivery_ref="MAT-BRG-881",
            material_name="A572 Grade 50 Structural Steel Girders",
            quantity=48,
            unit="pieces",
            project_name="Highway Bridge Expansion",
            vendor_name="Midwest Steel Supply",
            status="Delivered",
            expected_date="2026-05-15",
            delivered_date="2026-05-14",
            notes="Main span girders — inspected and accepted",
        ),
        MaterialDelivery(
            delivery_ref="MAT-MTR-412",
            material_name="Non-slip Platform Tiles",
            quantity=2200,
            unit="m2",
            project_name="Metro Station Renovation",
            vendor_name="Midwest Steel Supply",
            status="Partial",
            expected_date="2026-07-20",
            delivered_date="2026-07-10",
            notes="First 1400 m2 delivered; remainder delayed one week",
        ),
        MaterialDelivery(
            delivery_ref="MAT-TWR-105",
            material_name="LV Switchgear Panels",
            quantity=12,
            unit="panels",
            project_name="Commercial Tower Phase 2",
            vendor_name="Houston MEP Partners",
            status="Ordered",
            expected_date="2026-08-30",
            delivered_date=None,
            notes="Required before electrical distribution rough-in",
        ),
        MaterialDelivery(
            delivery_ref="MAT-WH-220",
            material_name="Insulated Roof Panels",
            quantity=850,
            unit="panels",
            project_name="Industrial Warehouse Build",
            vendor_name="Atlas Scaffolding Co",
            status="Delivered",
            expected_date="2023-10-01",
            delivered_date="2023-09-28",
            notes="Closeout stock remaining in Dallas yard",
        ),
        MaterialDelivery(
            delivery_ref="MAT-PPE-991",
            material_name="Safety Helmets & High-Vis Vests Kit",
            quantity=150,
            unit="kits",
            project_name="Highway Bridge Expansion",
            vendor_name="SafeSite PPE Distributors",
            status="Delivered",
            expected_date="2026-06-01",
            delivered_date="2026-05-30",
            notes="Site induction stock replenishment",
        ),
        MaterialDelivery(
            delivery_ref="MAT-RES-044",
            material_name="ADA Handrail Assemblies",
            quantity=36,
            unit="assemblies",
            project_name="Residential Complex A",
            vendor_name="SafeSite PPE Distributors",
            status="On Hold",
            expected_date="2026-09-15",
            delivered_date=None,
            notes="Paused pending permit approvals for Residential Complex A",
        ),
    ]
    session.add_all(deliveries)
    session.flush()
    _rebuild_search_documents(session)
    session.commit()


def _clear_all(session) -> None:
    session.execute(text("DELETE FROM search_documents"))
    session.execute(text("DELETE FROM material_deliveries"))
    session.execute(text("DELETE FROM equipment"))
    session.execute(text("DELETE FROM vendors"))
    session.commit()


def setup(force: bool = False) -> str:
    """
    Ensure Azure SQL database buildtrack_assets exists, create tables, seed data.
    Returns the assets database name.
    """
    from app.core.config import settings

    primary = settings.DATABASE_URL
    if not primary.startswith("mssql"):
        raise RuntimeError(
            "DATABASE_URL must be Azure SQL (mssql+…) to create buildtrack_assets on the server"
        )

    assets_logical = resolve_assets_database_url(primary)
    ensure_azure_database_exists(primary, ASSETS_DB_NAME)

    engine = create_mssql_engine(assets_logical)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        has_rows = session.execute(text("SELECT COUNT(*) FROM vendors")).scalar() or 0
        if has_rows and not force:
            print(
                f"Assets Azure SQL DB '{ASSETS_DB_NAME}' already seeded "
                f"({has_rows} vendors). Use --force to reseed."
            )
            return ASSETS_DB_NAME
        if has_rows and force:
            print("Clearing existing assets tables (--force)…")
            _clear_all(session)
        seed(session)
        count = session.execute(text("SELECT COUNT(*) FROM search_documents")).scalar()
        print(f"Seeded Azure SQL database '{ASSETS_DB_NAME}' ({count} search_documents)")
    finally:
        session.close()
        engine.dispose()

    host = make_url(primary).host
    print(f"Assets DB ready on Azure SQL server: {host}/{ASSETS_DB_NAME}")
    return ASSETS_DB_NAME


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    force = "--force" in args
    try:
        setup(force=force)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
