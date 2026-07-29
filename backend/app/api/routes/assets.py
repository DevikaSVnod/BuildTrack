"""
Site Assets & Procurement — browse data from Azure SQL `buildtrack_assets`.

Separate from Global Search: this powers the dedicated /assets page
(equipment, vendors, material deliveries).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from app.api.deps import get_current_user
from app.core.data_sources import get_source, session_for
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/assets", tags=["assets"])


def _require_assets_session():
    if get_source("assets") is None:
        raise HTTPException(
            status_code=503,
            detail="Site Assets database is not configured",
        )
    return session_for("assets")

def _row_dict(row) -> dict[str, Any]:
    return dict(row._mapping)


@router.get("/overview")
def assets_overview(current_user: User = Depends(get_current_user)):
    """Equipment, vendors, material deliveries + summary counts."""
    session = _require_assets_session()
    try:
        equipment = [
            _row_dict(r)
            for r in session.execute(
                text(
                    """
                    SELECT id, asset_tag, name, category, project_name, status,
                           vendor_name, location, last_service_date, notes
                    FROM equipment
                    ORDER BY asset_tag
                    """
                )
            )
        ]
        vendors = [
            _row_dict(r)
            for r in session.execute(
                text(
                    """
                    SELECT id, name, category, contact_email, phone, rating, status, notes
                    FROM vendors
                    ORDER BY name
                    """
                )
            )
        ]
        materials = [
            _row_dict(r)
            for r in session.execute(
                text(
                    """
                    SELECT id, delivery_ref, material_name, quantity, unit,
                           project_name, vendor_name, status, expected_date,
                           delivered_date, notes
                    FROM material_deliveries
                    ORDER BY delivery_ref
                    """
                )
            )
        ]
    except Exception as exc:
        logger.exception("Failed to load assets overview")
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        session.close()

    on_site = sum(1 for e in equipment if (e.get("status") or "").lower() in ("on site", "onsite"))
    active_vendors = sum(1 for v in vendors if (v.get("status") or "").lower() == "active")
    in_transit = sum(
        1
        for m in materials
        if (m.get("status") or "").lower() in ("in transit", "shipped", "ordered")
    )
    delivered = sum(1 for m in materials if (m.get("status") or "").lower() == "delivered")

    return {
        "equipment": equipment,
        "vendors": vendors,
        "materials": materials,
        "metrics": {
            "equipment_total": len(equipment),
            "equipment_on_site": on_site,
            "vendors_total": len(vendors),
            "vendors_active": active_vendors,
            "materials_total": len(materials),
            "materials_open": in_transit,
            "materials_delivered": delivered,
        },
        "source": {
            "id": "assets",
            "label": "Site Assets & Procurement",
            "database": "buildtrack_assets",
        },
    }
