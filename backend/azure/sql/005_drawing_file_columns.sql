-- Add file storage columns to engineering_drawings (for blob content indexing)
IF COL_LENGTH('dbo.engineering_drawings', 'file_url') IS NULL
    ALTER TABLE dbo.engineering_drawings ADD file_url NVARCHAR(1000) NULL;
GO

IF COL_LENGTH('dbo.engineering_drawings', 'file_type') IS NULL
    ALTER TABLE dbo.engineering_drawings ADD file_type NVARCHAR(20) NULL;
GO

IF COL_LENGTH('dbo.engineering_drawings', 'file_size') IS NULL
    ALTER TABLE dbo.engineering_drawings ADD file_size BIGINT NULL;
GO
