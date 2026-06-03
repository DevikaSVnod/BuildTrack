"""
Operational page data — read from Azure AI Search only (SQL indexer output).

Writes still go to Azure SQL; the indexer syncs reads into the search index.
"""
from fastapi import APIRouter, Depends, HTTPException
from app.models.user import User
from app.api.deps import get_current_user
from app.search import content_service

router = APIRouter(prefix="/operational", tags=["operational"])


def _index_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=503, detail=str(exc))


@router.get("/handover")
def list_handover(current_user: User = Depends(get_current_user)):
    try:
        return content_service.handover()
    except RuntimeError as exc:
        raise _index_error(exc) from exc


@router.get("/drawings")
def list_drawings(current_user: User = Depends(get_current_user)):
    try:
        return content_service.drawings()
    except RuntimeError as exc:
        raise _index_error(exc) from exc


@router.get("/safety/incidents")
def list_safety_incidents(current_user: User = Depends(get_current_user)):
    try:
        return content_service.safety_incidents()
    except RuntimeError as exc:
        raise _index_error(exc) from exc


@router.get("/safety/metrics")
def safety_metrics(current_user: User = Depends(get_current_user)):
    try:
        data = content_service.safety_metrics()
        if not data:
            raise HTTPException(status_code=404, detail="Safety KPI not found in search index")
        return data
    except RuntimeError as exc:
        raise _index_error(exc) from exc


@router.get("/attendance")
def list_attendance(current_user: User = Depends(get_current_user)):
    try:
        return content_service.attendance()
    except RuntimeError as exc:
        raise _index_error(exc) from exc


@router.get("/timeline")
def list_timeline(current_user: User = Depends(get_current_user)):
    try:
        return content_service.timeline()
    except RuntimeError as exc:
        raise _index_error(exc) from exc


@router.get("/reports/budget")
def budget_reports(current_user: User = Depends(get_current_user)):
    try:
        return content_service.budget_reports()
    except RuntimeError as exc:
        raise _index_error(exc) from exc


@router.get("/reports/productivity")
def productivity_report(current_user: User = Depends(get_current_user)):
    try:
        data = content_service.productivity()
        if not data:
            raise HTTPException(status_code=404, detail="Productivity report not found in search index")
        return data
    except RuntimeError as exc:
        raise _index_error(exc) from exc


@router.get("/dashboard/milestones")
def dashboard_milestones(current_user: User = Depends(get_current_user)):
    try:
        return content_service.milestones()
    except RuntimeError as exc:
        raise _index_error(exc) from exc


@router.get("/dashboard/site-activity")
def dashboard_site_activity(current_user: User = Depends(get_current_user)):
    try:
        data = content_service.site_activity()
        if not data:
            raise HTTPException(status_code=404, detail="Site activity KPI not found in search index")
        return data
    except RuntimeError as exc:
        raise _index_error(exc) from exc
