IF COL_LENGTH('dbo.engineering_drawings', 'sheet_intel') IS NULL
    ALTER TABLE dbo.engineering_drawings ADD sheet_intel NVARCHAR(MAX) NULL;
