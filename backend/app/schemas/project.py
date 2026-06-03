from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime
from app.models.project import ProjectStatus
from app.schemas.user import UserResponse


class ProjectBase(BaseModel):
    name: str
    description: Optional[str] = None
    status: ProjectStatus = ProjectStatus.planning
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    budget: Optional[float] = None
    location: Optional[str] = None
    progress: int = 0
    project_manager_id: Optional[int] = None


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[ProjectStatus] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    budget: Optional[float] = None
    location: Optional[str] = None
    progress: Optional[int] = None
    project_manager_id: Optional[int] = None


class ProjectResponse(ProjectBase):
    id: int
    created_at: datetime
    project_manager: Optional[UserResponse] = None
    task_count: Optional[int] = 0
    team_size: Optional[int] = 0

    class Config:
        from_attributes = True
