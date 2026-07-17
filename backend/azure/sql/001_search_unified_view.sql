-- =============================================================================
-- BuildTrack — Unified search view for Azure AI Search SQL Indexer
-- Target: Azure SQL Database (migrate from PostgreSQL before running this)
-- =============================================================================
-- Azure SQL Indexer reads ONE flattened table/view and pushes rows into the
-- shared search index. Run after schema + seed data exist.
-- =============================================================================

-- Enable change tracking (required for incremental SQL indexer runs)
-- ALTER DATABASE CURRENT SET CHANGE_TRACKING = ON (CHANGE_RETENTION = 2 DAYS, AUTO_CLEANUP = ON);

-- Example per-table (run for each source table the indexer depends on):
-- ALTER TABLE dbo.projects ENABLE CHANGE_TRACKING WITH (TRACK_COLUMNS_UPDATED = ON);
-- ALTER TABLE dbo.tasks ENABLE CHANGE_TRACKING WITH (TRACK_COLUMNS_UPDATED = ON);
-- ALTER TABLE dbo.documents ENABLE CHANGE_TRACKING WITH (TRACK_COLUMNS_UPDATED = ON);
-- ALTER TABLE dbo.users ENABLE CHANGE_TRACKING WITH (TRACK_COLUMNS_UPDATED = ON);
-- ALTER TABLE dbo.team_members ENABLE CHANGE_TRACKING WITH (TRACK_COLUMNS_UPDATED = ON);

-- Optional: operational tables for data currently hardcoded in the frontend
-- (handover, drawings, safety, attendance, timeline, budget KPIs)
-- CREATE TABLE dbo.search_content (...);

GO

CREATE OR ALTER VIEW dbo.vw_global_search_documents AS

-- Projects
SELECT
    CONCAT('project-', p.id) AS id,
    p.name AS title,
    CONCAT(
        p.name, ' ',
        ISNULL(p.description, ''), ' ',
        ISNULL(p.location, ''), ' ',
        ISNULL(u.full_name, ''), ' project manager ',
        CASE WHEN p.budget IS NOT NULL THEN CONCAT('budget ', CAST(p.budget AS NVARCHAR(50))) ELSE '' END,
        ' progress ', CAST(ISNULL(p.progress, 0) AS NVARCHAR(10)), '%'
    ) AS content,
    'project' AS content_type,
    CONCAT('/projects/', p.id) AS url,
    (
        SELECT
            p.status AS status,
            p.location AS location,
            p.progress AS progress,
            p.budget AS budget,
            p.description AS description,
            CONVERT(NVARCHAR(10), p.start_date, 23) AS start_date,
            CONVERT(NVARCHAR(10), p.end_date, 23) AS end_date,
            u.full_name AS project_manager
        FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
    ) AS metadata
FROM dbo.projects p
LEFT JOIN dbo.users u ON u.id = p.project_manager_id

UNION ALL

-- Tasks
SELECT
    CONCAT('task-', t.id) AS id,
    t.title AS title,
    CONCAT(
        t.title, ' ',
        ISNULL(t.description, ''), ' ',
        ISNULL(pr.name, ''), ' ',
        ISNULL(assignee.full_name, ''), ' assigned ',
        CASE WHEN t.due_date IS NOT NULL THEN CONCAT('due ', CONVERT(NVARCHAR(10), t.due_date, 23)) ELSE '' END
    ) AS content,
    'task' AS content_type,
    CASE
        WHEN t.project_id IS NULL THEN CONCAT('/tasks?taskId=', t.id)
        ELSE CONCAT('/projects/', t.project_id, '?tab=Tasks&taskId=', t.id)
    END AS url,
    (
        SELECT
            t.status AS status,
            t.priority AS priority,
            t.project_id AS project_id,
            pr.name AS project_name,
            t.id AS task_id,
            assignee.full_name AS assignee,
            CONVERT(NVARCHAR(10), t.due_date, 23) AS due_date
        FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
    ) AS metadata
FROM dbo.tasks t
LEFT JOIN dbo.projects pr ON pr.id = t.project_id
LEFT JOIN dbo.users assignee ON assignee.id = t.assignee_id

UNION ALL

-- Documents (metadata + extracted body_text; blob RAG still used as supplemental)
SELECT
    CONCAT('document-', d.id) AS id,
    d.name AS title,
    CONCAT(
        d.name, ' ',
        ISNULL(d.file_type, ''), ' ',
        ISNULL(pr.name, ''), ' ',
        ISNULL(uploader.full_name, ''), ' uploaded by ',
        'uploaded on ', CONVERT(NVARCHAR(10), d.created_at, 23), ' ',
        FORMAT(d.created_at, 'MMMM d yyyy'), ' ',
        'file size ', CAST(ISNULL(d.file_size, 0) AS NVARCHAR(20)), ' bytes ',
        CASE
            WHEN ISNULL(d.file_size, 0) >= 1048576
                THEN CONCAT(CAST(CAST(d.file_size AS FLOAT) / 1048576.0 AS DECIMAL(10,2)), ' MB')
            WHEN ISNULL(d.file_size, 0) >= 1024
                THEN CONCAT(CAST(CAST(d.file_size AS FLOAT) / 1024.0 AS DECIMAL(10,1)), ' KB')
            ELSE 'unknown size'
        END, ' ',
        ISNULL(d.body_text, '')
    ) AS content,
    'document' AS content_type,
    CONCAT('/documents?docId=', d.id) AS url,
    (
        SELECT
            d.file_type AS file_type,
            d.project_id AS project_id,
            pr.name AS project_name,
            d.id AS doc_id,
            uploader.full_name AS uploader,
            d.file_url AS file_url,
            d.file_size AS file_size,
            CASE
                WHEN ISNULL(d.file_size, 0) >= 1048576
                    THEN CONCAT(CAST(CAST(d.file_size AS FLOAT) / 1048576.0 AS DECIMAL(10,2)), ' MB')
                WHEN ISNULL(d.file_size, 0) >= 1024
                    THEN CONCAT(CAST(CAST(d.file_size AS FLOAT) / 1024.0 AS DECIMAL(10,1)), ' KB')
                ELSE 'unknown size'
            END AS file_size_display,
            CONVERT(NVARCHAR(10), d.created_at, 23) AS upload_date,
            FORMAT(d.created_at, 'MMMM d yyyy') AS upload_date_display,
            LEFT(ISNULL(d.body_text, ''), 3500) AS body_text
        FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
    ) AS metadata
FROM dbo.documents d
LEFT JOIN dbo.projects pr ON pr.id = d.project_id
LEFT JOIN dbo.users uploader ON uploader.id = d.uploaded_by

UNION ALL

-- Workforce (one row per user, aggregated project names)
SELECT
    CONCAT('workforce-', u.id) AS id,
    u.full_name AS title,
    CONCAT(
        u.full_name, ' ', u.role, ' ', ISNULL(u.company_name, ''), ' ',
        ISNULL(proj_list.project_names, ''), ' workforce personnel team member'
    ) AS content,
    'team' AS content_type,
    CONCAT('/team?userId=', u.id) AS url,
    (
        SELECT
            CASE u.role
                WHEN N'admin' THEN N'Admin'
                WHEN N'project_manager' THEN N'Project Manager'
                WHEN N'site_engineer' THEN N'Site Engineer'
                WHEN N'contractor' THEN N'Contractor'
                ELSE CAST(u.role AS NVARCHAR(50))
            END AS role,
            u.email AS email,
            u.id AS user_id,
            JSON_QUERY(
                CASE
                    WHEN proj_list.project_names IS NULL THEN '[]'
                    ELSE CONCAT('["', REPLACE(proj_list.project_names, ', ', '","'), '"]')
                END
            ) AS projects
        FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
    ) AS metadata
FROM dbo.users u
INNER JOIN (
    SELECT tm.user_id,
           STRING_AGG(p.name, ', ') AS project_names
    FROM dbo.team_members tm
    LEFT JOIN dbo.projects p ON p.id = tm.project_id
    GROUP BY tm.user_id
) proj_list ON proj_list.user_id = u.id

UNION ALL

-- Handover documents
SELECT
    CONCAT('handover-', h.id) AS id,
    h.title AS title,
    CONCAT(
        h.title, ' ', ISNULL(h.category, ''), ' ', ISNULL(h.status, ''), ' ',
        ISNULL(COALESCE(p.name, h.project_name), ''), ' handover closeout document ',
        ISNULL(h.signed_by, '')
    ) AS content,
    'handover' AS content_type,
    '/handover' AS url,
    (
        SELECT
            h.category AS category,
            h.status AS status,
            COALESCE(p.name, h.project_name) AS project,
            h.signed_by AS signed_by,
            h.id AS doc_id
        FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
    ) AS metadata
FROM dbo.handover_documents h
LEFT JOIN dbo.projects p ON p.id = h.project_id

UNION ALL

-- Engineering drawings
SELECT
    CONCAT('drawing-', d.id) AS id,
    CONCAT(d.drawing_no, ' – ', d.title) AS title,
    CONCAT(
        d.drawing_no, ' ', d.title, ' ', ISNULL(d.discipline, ''), ' drawing ',
        ISNULL(d.revision, ''), ' ', ISNULL(d.status, ''), ' ',
        ISNULL(COALESCE(p.name, d.project_name), ''), ' technical specifications ',
        ISNULL(d.sheet_notes, ''), ' ', ISNULL(d.file_url, '')
    ) AS content,
    'drawing' AS content_type,
    '/drawings' AS url,
    (
        SELECT
            d.drawing_no AS drawing_no,
            d.discipline AS discipline,
            d.revision AS revision,
            d.status AS status,
            COALESCE(p.name, d.project_name) AS project,
            d.uploaded_by AS uploaded_by,
            d.id AS drawing_id,
            d.sheet_notes AS sheet_notes,
            d.file_url AS file_url,
            d.file_type AS file_type,
            d.file_size AS file_size,
            CASE
                WHEN ISNULL(d.file_size, 0) >= 1048576
                    THEN CONCAT(CAST(CAST(d.file_size AS FLOAT) / 1048576.0 AS DECIMAL(10,2)), ' MB')
                WHEN ISNULL(d.file_size, 0) >= 1024
                    THEN CONCAT(CAST(CAST(d.file_size AS FLOAT) / 1024.0 AS DECIMAL(10,1)), ' KB')
                ELSE 'unknown size'
            END AS file_size_display
        FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
    ) AS metadata
FROM dbo.engineering_drawings d
LEFT JOIN dbo.projects p ON p.id = d.project_id

UNION ALL

-- Safety incidents
SELECT
    CONCAT('safety-', s.id) AS id,
    CONCAT(s.incident_type, ' – ', COALESCE(p.name, s.project_name)) AS title,
    CONCAT(
        s.incident_type, ' ', ISNULL(s.description, ''), ' ', ISNULL(s.severity, ''), ' severity ',
        ISNULL(s.status, ''), ' ', ISNULL(COALESCE(p.name, s.project_name), ''), ' safety HSE incident ',
        'reported by ', ISNULL(s.reported_by, '')
    ) AS content,
    'safety' AS content_type,
    '/safety' AS url,
    (
        SELECT
            s.incident_type AS incident_type,
            s.severity AS severity,
            s.status AS status,
            COALESCE(p.name, s.project_name) AS project,
            s.reported_by AS reported_by,
            s.id AS inc_id,
            CONVERT(NVARCHAR(10), s.incident_date, 23) AS incident_date
        FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
    ) AS metadata
FROM dbo.safety_incidents s
LEFT JOIN dbo.projects p ON p.id = s.project_id

UNION ALL

-- Attendance records
SELECT
    CONCAT('attendance-', a.id) AS id,
    CONCAT(a.person_name, ' – Attendance') AS title,
    CONCAT(
        a.person_name, ' ', ISNULL(a.role, ''), ' attendance register ', ISNULL(a.status, ''), ' ',
        ISNULL(COALESCE(p.name, a.project_name), ''), ' site roll daily check-in'
    ) AS content,
    'attendance' AS content_type,
    '/team?tab=attendance' AS url,
    (
        SELECT
            a.person_name AS name,
            a.role AS role,
            a.status AS status,
            COALESCE(p.name, a.project_name) AS project
        FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
    ) AS metadata
FROM dbo.attendance_records a
LEFT JOIN dbo.projects p ON p.id = a.project_id

UNION ALL

-- Timeline phases
SELECT
    CONCAT('timeline-', t.id) AS id,
    CONCAT(t.phase_name, ' – ', COALESCE(p.name, t.project_name)) AS title,
    CONCAT(
        'Timeline milestone phase ', t.phase_name, ' project ', ISNULL(COALESCE(p.name, t.project_name), ''), ' ',
        'start ', CONVERT(NVARCHAR(10), t.start_date, 23), ' end ', CONVERT(NVARCHAR(10), t.end_date, 23), ' ',
        'status ', ISNULL(t.status, ''), ' progress ', CAST(ISNULL(t.progress, 0) AS NVARCHAR(10)), '% ',
        'schedule construction phases milestones gantt'
    ) AS content,
    'timeline' AS content_type,
    '/timeline' AS url,
    (
        SELECT
            COALESCE(p.name, t.project_name) AS project,
            t.phase_name AS phase,
            CONVERT(NVARCHAR(10), t.start_date, 23) AS start,
            CONVERT(NVARCHAR(10), t.end_date, 23) AS [end],
            t.status AS status,
            t.progress AS progress
        FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
    ) AS metadata
FROM dbo.timeline_phases t
LEFT JOIN dbo.projects p ON p.id = t.project_id

UNION ALL

-- Project budget / financial reports
SELECT
    CONCAT('budget-', LOWER(REPLACE(COALESCE(p.name, f.project_name), ' ', '-'))) AS id,
    CONCAT('Budget – ', COALESCE(p.name, f.project_name)) AS title,
    CONCAT(
        'Budget ', COALESCE(p.name, f.project_name), ' allocated ₹', CAST(f.budget_cr AS NVARCHAR(20)), 'Cr ',
        'spent ₹', CAST(f.spent_cr AS NVARCHAR(20)), 'Cr utilisation ',
        CAST(CASE WHEN f.budget_cr > 0 THEN (f.spent_cr * 100 / f.budget_cr) ELSE 0 END AS NVARCHAR(10)), '% ',
        'financial expenditure cost tracking budget vs spent reports'
    ) AS content,
    'report' AS content_type,
    '/dashboard' AS url,
    (
        SELECT
            COALESCE(p.name, f.project_name) AS project,
            f.budget_cr AS budget_cr,
            f.spent_cr AS spent_cr,
            CASE WHEN f.budget_cr > 0 THEN (f.spent_cr * 100 / f.budget_cr) ELSE 0 END AS utilization_pct,
            'Budget' AS category
        FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
    ) AS metadata
FROM dbo.project_financials f
LEFT JOIN dbo.projects p ON p.id = f.project_id

UNION ALL

-- KPI & dashboard rows (from SQL views + KPI tables — replaces search_content_items)
SELECT
    k.id AS id,
    k.title AS title,
    k.content AS content,
    k.content_type AS content_type,
    k.url AS url,
    k.metadata AS metadata
FROM dbo.vw_search_kpi_rows k;
GO
