-- =============================================================================
-- BuildTrack — Operational tables (formerly static frontend / static_docs.py)
-- Run on Azure SQL after core schema exists.
-- =============================================================================

IF OBJECT_ID('dbo.handover_documents', 'U') IS NULL
CREATE TABLE dbo.handover_documents (
    id INT IDENTITY(1,1) PRIMARY KEY,
    title NVARCHAR(500) NOT NULL,
    category NVARCHAR(100) NULL,
    project_id INT NULL REFERENCES dbo.projects(id),
    project_name NVARCHAR(255) NULL,
    status NVARCHAR(50) NULL,
    signed_by NVARCHAR(255) NULL,
    signed_date DATE NULL,
    created_at DATETIMEOFFSET DEFAULT SYSDATETIMEOFFSET()
);
GO

IF OBJECT_ID('dbo.engineering_drawings', 'U') IS NULL
CREATE TABLE dbo.engineering_drawings (
    id INT IDENTITY(1,1) PRIMARY KEY,
    drawing_no NVARCHAR(50) NOT NULL,
    title NVARCHAR(500) NOT NULL,
    discipline NVARCHAR(100) NULL,
    revision NVARCHAR(50) NULL,
    project_id INT NULL REFERENCES dbo.projects(id),
    project_name NVARCHAR(255) NULL,
    status NVARCHAR(50) NULL,
    uploaded_by NVARCHAR(255) NULL,
    created_at DATETIMEOFFSET DEFAULT SYSDATETIMEOFFSET()
);
GO

IF OBJECT_ID('dbo.safety_incidents', 'U') IS NULL
CREATE TABLE dbo.safety_incidents (
    id INT IDENTITY(1,1) PRIMARY KEY,
    incident_type NVARCHAR(100) NOT NULL,
    description NVARCHAR(MAX) NULL,
    project_id INT NULL REFERENCES dbo.projects(id),
    project_name NVARCHAR(255) NULL,
    severity NVARCHAR(50) NULL,
    status NVARCHAR(50) NULL,
    reported_by NVARCHAR(255) NULL,
    incident_date DATE NULL,
    created_at DATETIMEOFFSET DEFAULT SYSDATETIMEOFFSET()
);
GO

IF OBJECT_ID('dbo.attendance_records', 'U') IS NULL
CREATE TABLE dbo.attendance_records (
    id INT IDENTITY(1,1) PRIMARY KEY,
    person_name NVARCHAR(255) NOT NULL,
    role NVARCHAR(100) NULL,
    status NVARCHAR(50) NULL,
    project_id INT NULL REFERENCES dbo.projects(id),
    project_name NVARCHAR(255) NULL,
    record_date DATE NULL,
    created_at DATETIMEOFFSET DEFAULT SYSDATETIMEOFFSET()
);
GO

IF OBJECT_ID('dbo.timeline_phases', 'U') IS NULL
CREATE TABLE dbo.timeline_phases (
    id INT IDENTITY(1,1) PRIMARY KEY,
    project_id INT NULL REFERENCES dbo.projects(id),
    project_name NVARCHAR(255) NULL,
    phase_name NVARCHAR(255) NOT NULL,
    start_date DATE NULL,
    end_date DATE NULL,
    status NVARCHAR(50) NULL,
    progress INT DEFAULT 0,
    created_at DATETIMEOFFSET DEFAULT SYSDATETIMEOFFSET()
);
GO

IF OBJECT_ID('dbo.project_financials', 'U') IS NULL
CREATE TABLE dbo.project_financials (
    id INT IDENTITY(1,1) PRIMARY KEY,
    project_id INT NULL REFERENCES dbo.projects(id),
    project_name NVARCHAR(255) NULL,
    budget_cr INT NOT NULL,
    spent_cr INT NOT NULL,
    created_at DATETIMEOFFSET DEFAULT SYSDATETIMEOFFSET()
);
GO

IF OBJECT_ID('dbo.search_content_items', 'U') IS NULL
CREATE TABLE dbo.search_content_items (
    id NVARCHAR(100) PRIMARY KEY,
    title NVARCHAR(500) NOT NULL,
    content NVARCHAR(MAX) NOT NULL,
    content_type NVARCHAR(50) NOT NULL,
    url NVARCHAR(500) NULL,
    metadata_json NVARCHAR(MAX) NULL,
    updated_at DATETIMEOFFSET DEFAULT SYSDATETIMEOFFSET()
);
GO
