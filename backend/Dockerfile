# BuildTrack / Global Search backend (FastAPI)
#
# Includes ODBC Driver 18 for SQL Server so pyodbc can reach Azure SQL Database
# in production or a local SQL Server container in development — only the
# DATABASE_URL / connection strings passed in at runtime change, not this image.
# Pin to bookworm — Microsoft's msodbcsql18 packages target Debian 12.
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ACCEPT_EULA=Y

WORKDIR /app

# System deps: ODBC Driver 18 for SQL Server + build tools for native wheels
# (pyodbc, PyMuPDF, aspose-cad). Uses signed-by keyring (apt-key is removed on
# modern Debian).
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl gnupg2 apt-transport-https ca-certificates build-essential \
        libgl1 libglib2.0-0 \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
        > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 unixodbc-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
