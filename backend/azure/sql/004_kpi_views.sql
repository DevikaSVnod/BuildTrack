-- =============================================================================
-- BuildTrack — KPI SQL views (computed + table-backed)
-- Consumed by vw_global_search_documents for Azure SQL Indexer.
-- =============================================================================

-- Budget rollup from project_financials
CREATE OR ALTER VIEW dbo.vw_kpi_budget_summary AS
SELECT
    SUM(CAST(f.budget_cr AS DECIMAL(18,2))) AS total_budget_cr,
    SUM(CAST(f.spent_cr AS DECIMAL(18,2))) AS total_spent_cr,
    CASE
        WHEN SUM(CAST(f.budget_cr AS DECIMAL(18,2))) > 0
        THEN CAST(ROUND(SUM(CAST(f.spent_cr AS DECIMAL(18,2))) * 100.0 / SUM(CAST(f.budget_cr AS DECIMAL(18,2))), 0) AS INT)
        ELSE 0
    END AS utilization_pct,
    COUNT(*) AS project_count
FROM dbo.project_financials f;
GO

-- Live dashboard overview from core tables
CREATE OR ALTER VIEW dbo.vw_kpi_dashboard_overview AS
SELECT
    (SELECT COUNT(*) FROM dbo.projects WHERE status IN (N'In Progress', N'in_progress')) AS active_projects,
    (SELECT COUNT(*) FROM dbo.projects) AS total_projects,
    (SELECT COUNT(*) FROM dbo.tasks WHERE status NOT IN (N'Done', N'done')) AS open_tasks,
    (SELECT COUNT(*) FROM dbo.tasks WHERE status IN (N'Done', N'done')) AS completed_tasks,
    (SELECT COUNT(*) FROM dbo.tasks) AS total_tasks,
    (SELECT COUNT(DISTINCT tm.user_id) FROM dbo.team_members tm) AS workforce_count,
    (SELECT COUNT(*) FROM dbo.documents) AS documents_count,
    ISNULL((SELECT safety_score FROM dbo.safety_kpi_metrics WHERE id = 1), 0) AS safety_score,
    ISNULL(b.utilization_pct, 0) AS budget_utilization_pct,
    ISNULL(b.total_budget_cr, 0) AS total_budget_cr,
    ISNULL(b.total_spent_cr, 0) AS total_spent_cr
FROM dbo.vw_kpi_budget_summary b;
GO

-- Safety KPI + open incident count
CREATE OR ALTER VIEW dbo.vw_kpi_safety_summary AS
SELECT
    m.safety_score,
    m.safe_working_days,
    m.ppe_compliance_pct,
    m.pending_inspections,
    (SELECT COUNT(*) FROM dbo.safety_incidents si WHERE si.status = N'Open') AS open_incidents
FROM dbo.safety_kpi_metrics m
WHERE m.id = 1;
GO

-- Flatten KPI rows into search-index shape (id, title, content, content_type, url, metadata)
CREATE OR ALTER VIEW dbo.vw_search_kpi_rows AS

-- Budget utilisation summary (computed)
SELECT
    N'budget-summary' AS id,
    N'Budget Utilisation Summary' AS title,
    CONCAT(
        N'Budget Utilisation Summary overall total budget ₹',
        CAST(b.total_budget_cr AS NVARCHAR(20)), N'Cr spent ₹',
        CAST(b.total_spent_cr AS NVARCHAR(20)), N'Cr utilisation ',
        CAST(b.utilization_pct AS NVARCHAR(10)), N'% on track financial overview reports'
    ) AS content,
    N'report' AS content_type,
    N'/dashboard' AS url,
    (
        SELECT
            b.total_budget_cr AS total_budget_cr,
            b.total_spent_cr AS total_spent_cr,
            b.utilization_pct AS utilization_pct,
            N'Budget Summary' AS category
        FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
    ) AS metadata
FROM dbo.vw_kpi_budget_summary b

UNION ALL

-- Safety KPI summary
SELECT
    N'safety-kpi-summary' AS id,
    N'Site Safety Score & HSE Metrics' AS title,
    CONCAT(
        N'Safety score ', CAST(ISNULL(m.safety_score, 0) AS NVARCHAR(10)), N' out of 100 HSE ',
        N'safe working days ', CAST(ISNULL(m.safe_working_days, 0) AS NVARCHAR(10)),
        N' open incidents ', CAST(ISNULL(inc.open_incidents, 0) AS NVARCHAR(10)),
        N' PPE compliance ', CAST(ISNULL(m.ppe_compliance_pct, 0) AS NVARCHAR(10)), N'% ',
        N'pending inspections ', CAST(ISNULL(m.pending_inspections, 0) AS NVARCHAR(10))
    ) AS content,
    N'safety' AS content_type,
    N'/safety' AS url,
    (
        SELECT
            ISNULL(m.safety_score, 0) AS safety_score,
            ISNULL(m.safe_working_days, 0) AS safe_working_days,
            ISNULL(inc.open_incidents, 0) AS open_incidents,
            ISNULL(m.ppe_compliance_pct, 0) AS ppe_compliance_pct,
            ISNULL(m.pending_inspections, 0) AS pending_inspections,
            N'KPI' AS category
        FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
    ) AS metadata
FROM (SELECT 1 AS anchor) a
LEFT JOIN dbo.safety_kpi_metrics m ON m.id = 1
CROSS JOIN (
    SELECT COUNT(*) AS open_incidents FROM dbo.safety_incidents si WHERE si.status = N'Open'
) inc

UNION ALL

-- Team productivity (monthly table → JSON metadata)
SELECT
    N'reports-productivity' AS id,
    N'Team Productivity – Monthly Task Completion' AS title,
    CONCAT(
        N'Team productivity monthly task completion rate ',
        CAST(CASE WHEN agg.total_tasks > 0
            THEN CAST(ROUND(agg.total_completed * 100.0 / agg.total_tasks, 0) AS INT)
            ELSE 0 END AS NVARCHAR(10)),
        N'% total tasks ', CAST(agg.total_tasks AS NVARCHAR(10)),
        N' completed ', CAST(agg.total_completed AS NVARCHAR(10))
    ) AS content,
    N'report' AS content_type,
    N'/dashboard' AS url,
    CONCAT(
        N'{"total_tasks":', CAST(agg.total_tasks AS NVARCHAR(20)),
        N',"total_completed":', CAST(agg.total_completed AS NVARCHAR(20)),
        N',"completion_rate_pct":',
        CAST(CASE WHEN agg.total_tasks > 0
            THEN CAST(ROUND(agg.total_completed * 100.0 / agg.total_tasks, 0) AS INT)
            ELSE 0 END AS NVARCHAR(10)),
        N',"category":"Productivity","monthly":',
        ISNULL(agg.monthly_json, N'[]'),
        N'}'
    ) AS metadata
FROM (
    SELECT
        SUM(p.tasks_count) AS total_tasks,
        SUM(p.completed_count) AS total_completed,
        (
            SELECT pm.month_label AS [month], pm.tasks_count AS tasks, pm.completed_count AS completed
            FROM dbo.productivity_monthly pm
            ORDER BY pm.sort_order
            FOR JSON PATH
        ) AS monthly_json
    FROM dbo.productivity_monthly p
) agg
WHERE agg.total_tasks IS NOT NULL

UNION ALL

-- Site activity trend (weekly table → JSON metadata)
SELECT
    N'dashboard-site-activity' AS id,
    N'Site Activity Trend – Last 5 Weeks' AS title,
    CONCAT(
        N'Site activity trend total completed ', CAST(agg.total_completed AS NVARCHAR(10)),
        N' total open ', CAST(agg.total_open AS NVARCHAR(10)),
        N' weekly W19 W20 W21 W22 W23 dashboard overview'
    ) AS content,
    N'report' AS content_type,
    N'/dashboard' AS url,
    CONCAT(
        N'{"total_completed":', CAST(agg.total_completed AS NVARCHAR(20)),
        N',"total_open":', CAST(agg.total_open AS NVARCHAR(20)),
        N',"category":"Site Activity","weekly":',
        ISNULL(agg.weekly_json, N'[]'),
        N'}'
    ) AS metadata
FROM (
    SELECT
        SUM(w.completed_count) AS total_completed,
        SUM(w.open_count) AS total_open,
        (
            SELECT sw.week_label AS [week], sw.completed_count AS completed, sw.open_count AS [open]
            FROM dbo.site_activity_weekly sw
            ORDER BY sw.sort_order
            FOR JSON PATH
        ) AS weekly_json
    FROM dbo.site_activity_weekly w
) agg
WHERE agg.total_completed IS NOT NULL

UNION ALL

-- Dashboard overview KPI card (computed live)
SELECT
    N'dashboard-kpi-summary' AS id,
    N'Dashboard Overview – Construction KPIs' AS title,
    CONCAT(
        N'Dashboard overview active projects ', CAST(d.active_projects AS NVARCHAR(10)),
        N' open site activities ', CAST(d.open_tasks AS NVARCHAR(10)),
        N' workforce on roll ', CAST(d.workforce_count AS NVARCHAR(10)),
        N' documents filed ', CAST(d.documents_count AS NVARCHAR(10)),
        N' safety score ', CAST(d.safety_score AS NVARCHAR(10)),
        N' budget utilization ', CAST(d.budget_utilization_pct AS NVARCHAR(10)), N'% ',
        N'₹', CAST(d.total_spent_cr AS NVARCHAR(20)), N'Cr ₹', CAST(d.total_budget_cr AS NVARCHAR(20)), N'Cr'
    ) AS content,
    N'report' AS content_type,
    N'/dashboard' AS url,
    (
        SELECT
            d.active_projects AS active_projects,
            d.total_projects AS total_projects,
            d.open_tasks AS open_tasks,
            d.completed_tasks AS completed_tasks,
            d.total_tasks AS total_tasks,
            d.workforce_count AS workforce_count,
            d.documents_count AS documents_count,
            d.safety_score AS safety_score,
            d.budget_utilization_pct AS budget_utilization_pct,
            d.total_budget_cr AS total_budget_cr,
            d.total_spent_cr AS total_spent_cr,
            N'Dashboard KPI' AS category
        FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
    ) AS metadata
FROM dbo.vw_kpi_dashboard_overview d

UNION ALL

-- Upcoming dashboard milestones (table-backed)
SELECT
    CONCAT(N'dashboard-milestone-', m.id) AS id,
    m.title AS title,
    CONCAT(
        N'Upcoming milestone deadline ', m.title,
        N' due ', m.due_display, N' priority ', m.priority,
        N' schedule review meeting inspection'
    ) AS content,
    N'timeline' AS content_type,
    N'/dashboard' AS url,
    (
        SELECT
            m.due_display AS [due],
            m.priority AS priority,
            m.project_name AS project,
            N'Upcoming Milestone' AS category
        FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
    ) AS metadata
FROM dbo.dashboard_milestones m;
GO
