IF COL_LENGTH('dbo.engineering_drawings', 'sheet_notes') IS NULL
    ALTER TABLE dbo.engineering_drawings ADD sheet_notes NVARCHAR(MAX) NULL;
GO
