from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class HandoverDocument(Base):
    __tablename__ = "handover_documents"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(500), nullable=False)
    category = Column(String(100), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    project_name = Column(String(255), nullable=True)
    status = Column(String(50), nullable=True)
    signed_by = Column(String(255), nullable=True)
    signed_date = Column(Date, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    project = relationship("Project", backref="handover_documents")


class EngineeringDrawing(Base):
    __tablename__ = "engineering_drawings"

    id = Column(Integer, primary_key=True, index=True)
    drawing_no = Column(String(50), nullable=False)
    title = Column(String(500), nullable=False)
    discipline = Column(String(100), nullable=True)
    revision = Column(String(50), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    project_name = Column(String(255), nullable=True)
    status = Column(String(50), nullable=True)
    uploaded_by = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    project = relationship("Project", backref="engineering_drawings")


class SafetyIncident(Base):
    __tablename__ = "safety_incidents"

    id = Column(Integer, primary_key=True, index=True)
    incident_type = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    project_name = Column(String(255), nullable=True)
    severity = Column(String(50), nullable=True)
    status = Column(String(50), nullable=True)
    reported_by = Column(String(255), nullable=True)
    incident_date = Column(Date, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    project = relationship("Project", backref="safety_incidents")


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"

    id = Column(Integer, primary_key=True, index=True)
    person_name = Column(String(255), nullable=False)
    role = Column(String(100), nullable=True)
    status = Column(String(50), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    project_name = Column(String(255), nullable=True)
    record_date = Column(Date, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    project = relationship("Project", backref="attendance_records")


class TimelinePhase(Base):
    __tablename__ = "timeline_phases"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    project_name = Column(String(255), nullable=True)
    phase_name = Column(String(255), nullable=False)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    status = Column(String(50), nullable=True)
    progress = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    project = relationship("Project", backref="timeline_phases")


class ProjectFinancial(Base):
    __tablename__ = "project_financials"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    project_name = Column(String(255), nullable=True)
    budget_cr = Column(Integer, nullable=False)
    spent_cr = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    project = relationship("Project", backref="financials")


class SearchContentItem(Base):
    """Deprecated — KPI rows now come from KPI tables + vw_search_kpi_rows."""

    __tablename__ = "search_content_items"

    id = Column(String(100), primary_key=True)
    title = Column(String(500), nullable=False)
    content = Column(Text, nullable=False)
    content_type = Column(String(50), nullable=False)
    url = Column(String(500), nullable=True)
    metadata_json = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DashboardMilestone(Base):
    __tablename__ = "dashboard_milestones"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(500), nullable=False)
    due_display = Column(String(100), nullable=False)
    priority = Column(String(50), nullable=False, default="Medium")
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    project_name = Column(String(255), nullable=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    project = relationship("Project", backref="dashboard_milestones")


class ProductivityMonthly(Base):
    __tablename__ = "productivity_monthly"

    id = Column(Integer, primary_key=True, index=True)
    month_label = Column(String(20), nullable=False)
    tasks_count = Column(Integer, nullable=False)
    completed_count = Column(Integer, nullable=False)
    sort_order = Column(Integer, default=0)


class SiteActivityWeekly(Base):
    __tablename__ = "site_activity_weekly"

    id = Column(Integer, primary_key=True, index=True)
    week_label = Column(String(20), nullable=False)
    completed_count = Column(Integer, nullable=False)
    open_count = Column(Integer, nullable=False)
    sort_order = Column(Integer, default=0)


class SafetyKpiMetrics(Base):
    __tablename__ = "safety_kpi_metrics"

    id = Column(Integer, primary_key=True, default=1)
    safety_score = Column(Integer, nullable=False)
    safe_working_days = Column(Integer, nullable=False)
    ppe_compliance_pct = Column(Integer, nullable=False)
    pending_inspections = Column(Integer, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
