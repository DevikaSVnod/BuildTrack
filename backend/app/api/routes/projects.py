import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from app.core.database import get_db
from app.models.project import Project, ProjectStatus
from app.models.user import User
from app.schemas.project import ProjectCreate, ProjectUpdate, ProjectResponse
from app.api.deps import get_current_user
from app.search import content_service
from app.search.indexer import build_project_doc
from app.search.sql_indexer import trigger_sql_indexer_async, uses_push_indexing

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["projects"])


def _sync_project_to_search(project: Project) -> None:
    """Push mode: upload this project before the API returns so the list refreshes correctly."""
    if not uses_push_indexing():
        trigger_sql_indexer_async()
        return
    try:
        from app.search.sql_push_indexer import push_docs_now

        push_docs_now([build_project_doc(project)], embed=True)
    except Exception as exc:
        logger.warning("Immediate project push failed, falling back to async sync: %s", exc)
        trigger_sql_indexer_async()


def enrich_project(project: Project) -> dict:
    data = {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "status": project.status,
        "start_date": project.start_date,
        "end_date": project.end_date,
        "budget": project.budget,
        "location": project.location,
        "progress": project.progress,
        "project_manager_id": project.project_manager_id,
        "created_at": project.created_at,
        "project_manager": project.project_manager,
        "task_count": len(project.tasks) if project.tasks else 0,
        "team_size": len(project.team_members) if project.team_members else 0,
    }
    return data


@router.get("/", response_model=List[ProjectResponse])
def list_projects(
    status_filter: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return content_service.projects(status_filter=status_filter)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    project_data: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = Project(**project_data.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    if project.project_manager_id:
        project = (
            db.query(Project)
            .options(joinedload(Project.project_manager))
            .filter(Project.id == project.id)
            .first()
        ) or project
    _sync_project_to_search(project)
    return ProjectResponse(**enrich_project(project))


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        project = content_service.project(project_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectResponse(**project)


@router.put("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: int,
    update_data: ProjectUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    for field, value in update_data.model_dump(exclude_none=True).items():
        setattr(project, field, value)
    db.commit()
    db.refresh(project)
    project = (
        db.query(Project)
        .options(joinedload(Project.project_manager))
        .filter(Project.id == project.id)
        .first()
    ) or project
    _sync_project_to_search(project)
    return ProjectResponse(**enrich_project(project))


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    db.delete(project)
    db.commit()
    trigger_sql_indexer_async()
