from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime
from app.models.task import TaskStatus, TaskPriority
from app.schemas.user import UserResponse


class TaskBase(BaseModel):
    title: str
    description: Optional[str] = None
    status: TaskStatus = TaskStatus.todo
    priority: TaskPriority = TaskPriority.medium
    project_id: Optional[int] = None
    assignee_id: Optional[int] = None
    due_date: Optional[date] = None


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    project_id: Optional[int] = None
    assignee_id: Optional[int] = None
    due_date: Optional[date] = None


class TaskResponse(TaskBase):
    id: int
    created_at: datetime
    assignee: Optional[UserResponse] = None
    project_name: Optional[str] = None

    class Config:
        from_attributes = True
