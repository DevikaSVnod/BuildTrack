"""Seed KPI tables (dashboard milestones, productivity, site activity, safety metrics)."""
from __future__ import annotations

import logging
from sqlalchemy.orm import Session

from app.models.operational import (
    DashboardMilestone,
    ProductivityMonthly,
    SiteActivityWeekly,
    SafetyKpiMetrics,
)

logger = logging.getLogger(__name__)

PRODUCTIVITY_ROWS = [
    {"month_label": "Jan", "tasks_count": 18, "completed_count": 15, "sort_order": 1},
    {"month_label": "Feb", "tasks_count": 22, "completed_count": 19, "sort_order": 2},
    {"month_label": "Mar", "tasks_count": 28, "completed_count": 24, "sort_order": 3},
    {"month_label": "Apr", "tasks_count": 19, "completed_count": 17, "sort_order": 4},
    {"month_label": "May", "tasks_count": 32, "completed_count": 26, "sort_order": 5},
    {"month_label": "Jun", "tasks_count": 25, "completed_count": 22, "sort_order": 6},
]

SITE_ACTIVITY_ROWS = [
    {"week_label": "W19", "completed_count": 12, "open_count": 8, "sort_order": 1},
    {"week_label": "W20", "completed_count": 15, "open_count": 6, "sort_order": 2},
    {"week_label": "W21", "completed_count": 9, "open_count": 11, "sort_order": 3},
    {"week_label": "W22", "completed_count": 18, "open_count": 5, "sort_order": 4},
    {"week_label": "W23", "completed_count": 14, "open_count": 7, "sort_order": 5},
]

MILESTONE_ROWS = [
    {"title": "Metro Station – Steel Erection Review", "due_display": "27 May 2026", "priority": "High", "sort_order": 1},
    {"title": "Highway Bridge – Concrete Pour Phase 3", "due_display": "29 May 2026", "priority": "High", "sort_order": 2},
    {"title": "Tower – MEP Coordination Meeting", "due_display": "02 Jun 2026", "priority": "Medium", "sort_order": 3},
    {"title": "Warehouse – Client Inspection Visit", "due_display": "05 Jun 2026", "priority": "Low", "sort_order": 4},
]


def seed_kpi_tables(db: Session, force: bool = False) -> int:
    """Populate KPI tables if empty (or force replace demo rows)."""
    inserted = 0

    if force or db.query(SafetyKpiMetrics).count() == 0:
        db.query(SafetyKpiMetrics).delete()
        db.add(SafetyKpiMetrics(
            id=1,
            safety_score=87,
            safe_working_days=127,
            ppe_compliance_pct=94,
            pending_inspections=3,
        ))
        inserted += 1

    if force or db.query(ProductivityMonthly).count() == 0:
        db.query(ProductivityMonthly).delete()
        for row in PRODUCTIVITY_ROWS:
            db.add(ProductivityMonthly(**row))
        inserted += len(PRODUCTIVITY_ROWS)

    if force or db.query(SiteActivityWeekly).count() == 0:
        db.query(SiteActivityWeekly).delete()
        for row in SITE_ACTIVITY_ROWS:
            db.add(SiteActivityWeekly(**row))
        inserted += len(SITE_ACTIVITY_ROWS)

    if force or db.query(DashboardMilestone).count() == 0:
        db.query(DashboardMilestone).delete()
        for row in MILESTONE_ROWS:
            db.add(DashboardMilestone(**row))
        inserted += len(MILESTONE_ROWS)

    if inserted:
        db.commit()
        logger.info("KPI tables seeded — %s rows", inserted)
    return inserted


if __name__ == "__main__":
    from app.core.database import SessionLocal

    logging.basicConfig(level=logging.INFO)
    db = SessionLocal()
    try:
        seed_kpi_tables(db, force=True)
    finally:
        db.close()
