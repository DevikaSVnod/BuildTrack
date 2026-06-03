-- =============================================================================
-- BuildTrack — KPI & dashboard tables (source of truth for indexer)
-- Replaces ad-hoc search_content_items rows for dashboard metrics.
-- =============================================================================

IF OBJECT_ID('dbo.dashboard_milestones', 'U') IS NULL
CREATE TABLE dbo.dashboard_milestones (
    id INT IDENTITY(1,1) PRIMARY KEY,
    title NVARCHAR(500) NOT NULL,
    due_display NVARCHAR(100) NOT NULL,
    priority NVARCHAR(50) NOT NULL DEFAULT 'Medium',
    project_id INT NULL REFERENCES dbo.projects(id),
    project_name NVARCHAR(255) NULL,
    sort_order INT NOT NULL DEFAULT 0,
    created_at DATETIMEOFFSET DEFAULT SYSDATETIMEOFFSET()
);
GO

IF OBJECT_ID('dbo.productivity_monthly', 'U') IS NULL
CREATE TABLE dbo.productivity_monthly (
    id INT IDENTITY(1,1) PRIMARY KEY,
    month_label NVARCHAR(20) NOT NULL,
    tasks_count INT NOT NULL,
    completed_count INT NOT NULL,
    sort_order INT NOT NULL DEFAULT 0
);
GO

IF OBJECT_ID('dbo.site_activity_weekly', 'U') IS NULL
CREATE TABLE dbo.site_activity_weekly (
    id INT IDENTITY(1,1) PRIMARY KEY,
    week_label NVARCHAR(20) NOT NULL,
    completed_count INT NOT NULL,
    open_count INT NOT NULL,
    sort_order INT NOT NULL DEFAULT 0
);
GO

IF OBJECT_ID('dbo.safety_kpi_metrics', 'U') IS NULL
CREATE TABLE dbo.safety_kpi_metrics (
    id INT NOT NULL PRIMARY KEY DEFAULT 1,
    safety_score INT NOT NULL,
    safe_working_days INT NOT NULL,
    ppe_compliance_pct INT NOT NULL,
    pending_inspections INT NOT NULL,
    updated_at DATETIMEOFFSET DEFAULT SYSDATETIMEOFFSET(),
    CONSTRAINT CK_safety_kpi_single_row CHECK (id = 1)
);
GO
