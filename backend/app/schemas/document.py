from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from app.schemas.user import UserResponse


class DocumentBase(BaseModel):
    name: str
    file_type: Optional[str] = None
    file_url: Optional[str] = None
    project_id: Optional[int] = None
    file_size: Optional[int] = 0


class DocumentCreate(DocumentBase):
    uploaded_by: Optional[int] = None


class DocumentResponse(DocumentBase):
    id: int
    uploaded_by: Optional[int] = None
    created_at: datetime
    uploader: Optional[UserResponse] = None
    project_name: Optional[str] = None

    class Config:
        from_attributes = True


class TeamMemberBase(BaseModel):
    user_id: int
    project_id: Optional[int] = None
    role: Optional[str] = None


class TeamMemberCreate(TeamMemberBase):
    pass


class TeamMemberUpdate(BaseModel):
    role: Optional[str] = None
    project_id: Optional[int] = None


class TeamMemberResponse(TeamMemberBase):
    id: int
    joined_at: datetime
    user: Optional[UserResponse] = None
    project_name: Optional[str] = None
    active_projects_count: Optional[int] = 0
    tasks_count: Optional[int] = 0

    class Config:
        from_attributes = True
