-- =============================================================================
-- Production incremental indexing: physical staging table for Azure SQL Indexer
-- =============================================================================
-- Views cannot use SQL Change Tracking cleanly. Populate this staging table from
-- source tables (watermark or CT), then point the Azure SQL Indexer at it.
-- =============================================================================

IF OBJECT_ID(N'dbo.search_documents_staging', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.search_documents_staging (
        id               NVARCHAR(128)  NOT NULL PRIMARY KEY,
        entity_id        NVARCHAR(64)   NULL,
        entity_type      NVARCHAR(64)   NOT NULL,
        source_database  NVARCHAR(64)   NOT NULL DEFAULT 'buildtrack',
        title            NVARCHAR(500)  NOT NULL,
        search_text      NVARCHAR(MAX)  NULL,
        content          NVARCHAR(MAX)  NULL,  -- legacy alias of search_text
        content_type     NVARCHAR(64)   NOT NULL,
        url              NVARCHAR(1000) NULL,
        metadata         NVARCHAR(MAX)  NULL,
        search_text_hash NVARCHAR(64)   NULL,
        status           NVARCHAR(100)  NULL,
        location         NVARCHAR(500)  NULL,
        project_id       NVARCHAR(64)   NULL,
        organization_id  NVARCHAR(64)   NULL,
        tenant_id        NVARCHAR(64)   NULL,
        progress_pct     INT            NULL,
        record_status    NVARCHAR(100)  NULL,
        updated_at       DATETIMEOFFSET NULL,
        indexed_at       DATETIMEOFFSET NOT NULL DEFAULT SYSDATETIMEOFFSET()
    );

    CREATE INDEX IX_search_staging_updated
        ON dbo.search_documents_staging (updated_at);
    CREATE INDEX IX_search_staging_type
        ON dbo.search_documents_staging (content_type);
END
GO

-- Example: upsert projects into staging (run by sync job / CT processor)
/*
MERGE dbo.search_documents_staging AS t
USING (
    SELECT
        CONCAT('project-', p.id) AS id,
        CAST(p.id AS NVARCHAR(64)) AS entity_id,
        'project' AS entity_type,
        'buildtrack' AS source_database,
        p.name AS title,
        CONCAT(p.name, ' ', ISNULL(p.description, ''), ' ', ISNULL(p.location, '')) AS search_text,
        p.status AS status,
        p.location AS location,
        CAST(p.id AS NVARCHAR(64)) AS project_id,
        p.progress AS progress_pct,
        p.status AS record_status,
        p.created_at AS updated_at
    FROM dbo.projects p
) AS s
ON t.id = s.id
WHEN MATCHED AND ISNULL(t.search_text, '') <> ISNULL(s.search_text, '') THEN
    UPDATE SET
        title = s.title,
        search_text = s.search_text,
        content = s.search_text,
        status = s.status,
        location = s.location,
        progress_pct = s.progress_pct,
        record_status = s.record_status,
        updated_at = s.updated_at,
        indexed_at = SYSDATETIMEOFFSET()
WHEN NOT MATCHED THEN
    INSERT (id, entity_id, entity_type, source_database, title, search_text, content,
            content_type, status, location, project_id, progress_pct, record_status, updated_at)
    VALUES (s.id, s.entity_id, s.entity_type, s.source_database, s.title, s.search_text, s.search_text,
            s.entity_type, s.status, s.location, s.project_id, s.progress_pct, s.record_status, s.updated_at);
*/
GO
