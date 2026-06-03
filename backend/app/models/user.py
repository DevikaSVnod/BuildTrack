from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum as SAEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.core.database import Base


class UserRole(str, enum.Enum):
    admin = "Admin"
    project_manager = "Project Manager"
    site_engineer = "Site Engineer"
    contractor = "Contractor"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    company_name = Column(String(255), nullable=True)
    role = Column(SAEnum(UserRole), default=UserRole.site_engineer)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    projects_managed = relationship("Project", back_populates="project_manager")
    tasks_assigned = relationship("Task", back_populates="assignee")
    team_memberships = relationship("TeamMember", back_populates="user")
    documents_uploaded = relationship("Document", back_populates="uploader")
