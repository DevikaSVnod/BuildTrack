IF COL_LENGTH('dbo.documents', 'body_text') IS NULL
    ALTER TABLE dbo.documents ADD body_text NVARCHAR(MAX) NULL;
GO
