from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload
from typing import List
from app.core.database import get_db
from app.models.team import TeamMember
from app.models.task import Task
from app.models.user import User
from app.schemas.document import TeamMemberCreate, TeamMemberUpdate, TeamMemberResponse
from app.api.deps import get_current_user
from app.search import content_service

router = APIRouter(prefix="/team", tags=["team"])


def _batch_counts(db: Session, user_ids: set[int]) -> tuple[dict[int, int], dict[int, int]]:
    if not user_ids:
        return {}, {}
    project_counts = dict(
        db.query(TeamMember.user_id, func.count(TeamMember.id))
        .filter(TeamMember.user_id.in_(user_ids))
        .group_by(TeamMember.user_id)
        .all()
    )
    task_counts = dict(
        db.query(Task.assignee_id, func.count(Task.id))
        .filter(Task.assignee_id.in_(user_ids))
        .group_by(Task.assignee_id)
        .all()
    )
    return project_counts, task_counts


def enrich_member(
    member: TeamMember,
    project_counts: dict[int, int],
    task_counts: dict[int, int],
) -> dict:
    return {
        "id": member.id,
        "user_id": member.user_id,
        "project_id": member.project_id,
        "role": member.role,
        "joined_at": member.joined_at,
        "user": member.user,
        "project_name": member.project.name if member.project else None,
        "active_projects_count": project_counts.get(member.user_id, 0),
        "tasks_count": task_counts.get(member.user_id, 0),
    }


@router.get("/", response_model=List[TeamMemberResponse])
def list_members(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return content_service.team_members()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/", response_model=TeamMemberResponse, status_code=status.HTTP_201_CREATED)
def add_member(
    member_data: TeamMemberCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = db.query(User).filter(User.id == member_data.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    member = TeamMember(**member_data.model_dump())
    db.add(member)
    db.commit()
    member = (
        db.query(TeamMember)
        .options(joinedload(TeamMember.user), joinedload(TeamMember.project))
        .filter(TeamMember.id == member.id)
        .first()
    )
    project_counts, task_counts = _batch_counts(db, {member.user_id})
    return TeamMemberResponse(**enrich_member(member, project_counts, task_counts))


@router.put("/{member_id}", response_model=TeamMemberResponse)
def update_member(
    member_id: int,
    update_data: TeamMemberUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    member = db.query(TeamMember).filter(TeamMember.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Team member not found")
    for field, value in update_data.model_dump(exclude_none=True).items():
        setattr(member, field, value)
    db.commit()
    member = (
        db.query(TeamMember)
        .options(joinedload(TeamMember.user), joinedload(TeamMember.project))
        .filter(TeamMember.id == member.id)
        .first()
    )
    project_counts, task_counts = _batch_counts(db, {member.user_id})
    return TeamMemberResponse(**enrich_member(member, project_counts, task_counts))


@router.delete("/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    member_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    member = db.query(TeamMember).filter(TeamMember.id == member_id).first()
    if not member:
        raise HTTPException(status_code=404, detail="Team member not found")
    db.delete(member)
    db.commit()
