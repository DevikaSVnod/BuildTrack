"""Seed operational tables (handover, drawings, safety, etc.) from former static_docs data."""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.operational import (
    HandoverDocument,
    EngineeringDrawing,
    SafetyIncident,
    AttendanceRecord,
    TimelinePhase,
    ProjectFinancial,
    DashboardMilestone,
    ProductivityMonthly,
    SiteActivityWeekly,
    SafetyKpiMetrics,
)

logger = logging.getLogger(__name__)


def _project_id(db: Session, name: str) -> Optional[int]:
    p = db.query(Project).filter(Project.name == name).first()
    return p.id if p else None


def seed_operational_data(db: Session) -> int:
    """Insert operational demo data if tables are empty. Returns rows inserted."""
    if db.query(HandoverDocument).count() > 0:
        return 0

    logger.info("Seeding operational tables (handover, drawings, safety, timeline, reports)...")

    for d in [
        {"title": "Project Completion Certificate", "category": "Completion", "project": "Highway Bridge Expansion", "status": "Signed", "signed_by": "Sarah Chen", "signed_date": date(2026, 5, 1)},
        {"title": "As-Built Drawing Package", "category": "Drawings", "project": "Metro Station Renovation", "status": "Pending", "signed_by": None, "signed_date": None},
        {"title": "O&M Manual – HVAC Systems", "category": "O&M Manual", "project": "Commercial Tower Phase 2", "status": "Submitted", "signed_by": "James Okafor", "signed_date": date(2026, 4, 28)},
        {"title": "Structural Inspection Certificate", "category": "Inspection", "project": "Highway Bridge Expansion", "status": "Signed", "signed_by": "Priya Nair", "signed_date": date(2026, 4, 15)},
        {"title": "Defects Liability Schedule", "category": "DLP", "project": "Industrial Warehouse Build", "status": "Pending", "signed_by": None, "signed_date": None},
        {"title": "Warranty & Guarantee Register", "category": "Warranty", "project": "Metro Station Renovation", "status": "Under Review", "signed_by": "Liu Wei", "signed_date": date(2026, 5, 20)},
    ]:
        pname = d.pop("project")
        db.add(HandoverDocument(project_id=_project_id(db, pname), project_name=pname, **d))

    for d in [
        {"drawing_no": "ST-001-A", "title": "Foundation Layout Plan", "discipline": "Structural", "revision": "Rev C", "project": "Highway Bridge Expansion", "status": "Approved", "uploaded_by": "Sarah Chen"},
        {"drawing_no": "AR-005-B", "title": "Site Master Plan", "discipline": "Architectural", "revision": "Rev B", "project": "Metro Station Renovation", "status": "Under Review", "uploaded_by": "Priya Nair"},
        {"drawing_no": "ME-012-A", "title": "HVAC Duct Routing – Level 2", "discipline": "MEP", "revision": "Rev A", "project": "Commercial Tower Phase 2", "status": "Approved", "uploaded_by": "James Okafor"},
        {"drawing_no": "CI-003-C", "title": "Piling & Bored Pile Layout", "discipline": "Civil", "revision": "Rev C", "project": "Highway Bridge Expansion", "status": "Superseded", "uploaded_by": "Sarah Chen"},
        {"drawing_no": "EL-007-A", "title": "Electrical Distribution Board", "discipline": "Electrical", "revision": "Rev A", "project": "Industrial Warehouse Build", "status": "Under Review", "uploaded_by": "Carlos Mendez"},
        {"drawing_no": "ST-009-B", "title": "Roof Truss Detail – Span 24m", "discipline": "Structural", "revision": "Rev B", "project": "Metro Station Renovation", "status": "Approved", "uploaded_by": "Carlos Mendez"},
    ]:
        pname = d.pop("project")
        db.add(EngineeringDrawing(project_id=_project_id(db, pname), project_name=pname, **d))

    for d in [
        {"incident_type": "Near Miss", "description": "Worker slipped on wet surface near crane area", "project": "Highway Bridge Expansion", "severity": "Medium", "status": "Open", "reported_by": "James Okafor", "incident_date": date(2026, 5, 15)},
        {"incident_type": "Minor Injury", "description": "Cut on hand during steel rod handling – no PPE", "project": "Commercial Tower Phase 2", "severity": "Low", "status": "Closed", "reported_by": "Carlos Mendez", "incident_date": date(2026, 5, 10)},
        {"incident_type": "Safety Violation", "description": "Working at height without harness – third floor", "project": "Metro Station Renovation", "severity": "High", "status": "Open", "reported_by": "Sarah Chen", "incident_date": date(2026, 5, 18)},
        {"incident_type": "Near Miss", "description": "Unsecured scaffolding plank fell from second level", "project": "Industrial Warehouse Build", "severity": "High", "status": "Resolved", "reported_by": "David Reyes", "incident_date": date(2026, 5, 12)},
        {"incident_type": "Observation", "description": "Improper storage of flammable materials in site hut", "project": "Highway Bridge Expansion", "severity": "Medium", "status": "Resolved", "reported_by": "Priya Nair", "incident_date": date(2026, 5, 15)},
    ]:
        pname = d.pop("project")
        db.add(SafetyIncident(project_id=_project_id(db, pname), project_name=pname, **d))

    for d in [
        {"person_name": "James Okafor", "role": "Site Engineer", "status": "Present", "project": "Highway Bridge Expansion", "record_date": date.today()},
        {"person_name": "Sarah Chen", "role": "Project Manager", "status": "Present", "project": "Metro Station Renovation", "record_date": date.today()},
        {"person_name": "Aisha Johnson", "role": "Contractor", "status": "Absent", "project": "Commercial Tower Phase 2", "record_date": date.today()},
        {"person_name": "Priya Nair", "role": "Admin", "status": "Present", "project": "Industrial Warehouse Build", "record_date": date.today()},
        {"person_name": "Carlos Mendez", "role": "Site Engineer", "status": "Late", "project": "Highway Bridge Expansion", "record_date": date.today()},
        {"person_name": "David Reyes", "role": "Contractor", "status": "Present", "project": "Metro Station Renovation", "record_date": date.today()},
    ]:
        pname = d.pop("project")
        db.add(AttendanceRecord(project_id=_project_id(db, pname), project_name=pname, **d))

    for d in [
        {"project": "Highway Bridge Expansion", "phase_name": "Site Survey", "start_date": date(2024, 1, 15), "end_date": date(2024, 2, 28), "status": "Completed", "progress": 100},
        {"project": "Highway Bridge Expansion", "phase_name": "Foundation Work", "start_date": date(2024, 3, 1), "end_date": date(2024, 5, 31), "status": "Completed", "progress": 100},
        {"project": "Highway Bridge Expansion", "phase_name": "Steel Erection", "start_date": date(2024, 6, 1), "end_date": date(2024, 9, 30), "status": "In Progress", "progress": 65},
        {"project": "Highway Bridge Expansion", "phase_name": "Deck & Finishing", "start_date": date(2024, 10, 1), "end_date": date(2025, 3, 31), "status": "Planning", "progress": 0},
        {"project": "Commercial Tower Phase 2", "phase_name": "Design & Permits", "start_date": date(2024, 6, 1), "end_date": date(2024, 9, 30), "status": "In Progress", "progress": 40},
        {"project": "Commercial Tower Phase 2", "phase_name": "Foundation", "start_date": date(2024, 10, 1), "end_date": date(2025, 2, 28), "status": "Planning", "progress": 0},
        {"project": "Commercial Tower Phase 2", "phase_name": "Structure", "start_date": date(2025, 3, 1), "end_date": date(2026, 1, 31), "status": "Planning", "progress": 0},
        {"project": "Metro Station Renovation", "phase_name": "Utility Relocation", "start_date": date(2023, 9, 1), "end_date": date(2024, 1, 31), "status": "Completed", "progress": 100},
        {"project": "Metro Station Renovation", "phase_name": "Platform Upgrade", "start_date": date(2024, 2, 1), "end_date": date(2024, 7, 31), "status": "In Progress", "progress": 75},
        {"project": "Metro Station Renovation", "phase_name": "Digital Signage", "start_date": date(2024, 8, 1), "end_date": date(2024, 11, 30), "status": "Planning", "progress": 0},
        {"project": "Metro Station Renovation", "phase_name": "Final Testing", "start_date": date(2024, 12, 1), "end_date": date(2025, 3, 31), "status": "Planning", "progress": 0},
    ]:
        pname = d.pop("project")
        db.add(TimelinePhase(project_id=_project_id(db, pname), project_name=pname, **d))

    budget_rows = [
        {"project": "Highway Bridge Expansion", "budget_cr": 12, "spent_cr": 7},
        {"project": "Metro Station Renovation", "budget_cr": 8, "spent_cr": 6},
        {"project": "Commercial Tower Phase 2", "budget_cr": 15, "spent_cr": 4},
        {"project": "Industrial Warehouse Build", "budget_cr": 22, "spent_cr": 9},
    ]
    for b in budget_rows:
        pname = b.pop("project")
        db.add(ProjectFinancial(project_id=_project_id(db, pname), project_name=pname, **b))

    from app.seed_kpi import seed_kpi_tables
    seed_kpi_tables(db)

    db.commit()
    count = (
        db.query(HandoverDocument).count()
        + db.query(EngineeringDrawing).count()
        + db.query(SafetyIncident).count()
        + db.query(AttendanceRecord).count()
        + db.query(TimelinePhase).count()
        + db.query(ProjectFinancial).count()
        + db.query(DashboardMilestone).count()
        + db.query(ProductivityMonthly).count()
        + db.query(SiteActivityWeekly).count()
        + db.query(SafetyKpiMetrics).count()
    )
    logger.info(f"Operational seed complete — {count} rows")
    return count
