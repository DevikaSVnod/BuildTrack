IF COL_LENGTH('dbo.engineering_drawings', 'object_inventory') IS NULL
    ALTER TABLE dbo.engineering_drawings ADD object_inventory NVARCHAR(MAX) NULL;
