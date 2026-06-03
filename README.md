# BuildTrack — Construction Project Management Platform

A full-stack construction project management platform with AI-powered search using Azure OpenAI and Azure AI Search.

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14 (App Router) + TypeScript + Tailwind CSS |
| Backend | FastAPI (Python) |
| Database | PostgreSQL + SQLAlchemy |
| Auth | JWT (JSON Web Tokens) |
| File Storage | Azure Blob Storage |
| Search | Azure AI Search (hybrid/semantic) |
| AI | Azure OpenAI GPT-4o-mini |
| Charts | Recharts |
| Icons | Lucide React |

## Quick Start

### Prerequisites
- Node.js 18+
- Python 3.11+
- PostgreSQL

### One-command start (Windows)

From the project root, double-click **`start.bat`**, or run:

**PowerShell** (note the `.\` prefix):
```powershell
.\start.bat
# or
.\start.ps1
```

**Command Prompt (cmd)**:
```bat
start.bat
```

This will:
1. Stop any old processes on ports 8000 / 3000 (avoids duplicate backends)
2. Open **BuildTrack API** window (backend on port 8000)
3. Open **BuildTrack Web** window (frontend on port 3000)
4. Open http://localhost:3000 in your browser

To stop everything, run **`.\stop.bat`** (PowerShell) or **`stop.bat`** (cmd), or **`.\stop.ps1`**.

### 1. Database Setup

```sql
CREATE DATABASE buildtrack;
```

### 2. Backend Setup

```bash
cd backend
pip install -r requirements.txt
```

Edit `.env` with your credentials:
```env
DATABASE_URL=postgresql://postgres:password@localhost/buildtrack
SECRET_KEY=your-secret-key-here
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_KEY=your-key
AZURE_SEARCH_ENDPOINT=https://your-search.search.windows.net
AZURE_SEARCH_KEY=your-key
```

Start the backend:
```bash
uvicorn app.main:app --reload --port 8000
```

The server seeds the database automatically on first run.

### 3. Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

### Demo Login
- **Email:** devika@buildtrack.com
- **Password:** password123

## Features

### Dashboard
- Stats cards: Total Projects, Active Tasks, Team Members, Documents
- Project Status Pie Chart & Task Completion Bar Chart
- Recent Projects table with progress bars
- Activity feed

### Projects
- Project cards with status, progress, budget, team size
- Kanban-style task management per project
- Project detail with 5 tabs: Overview, Tasks, Team, Documents, Timeline
- Create/Edit/Delete projects

### Tasks
- Kanban board (To Do | In Progress | Review | Done)
- Priority badges (High/Medium/Low)
- Assignee and due date tracking

### Team
- Team member cards with role badges
- Active projects & task count per member
- Add new members (creates user account + team assignment)

### Documents
- File list with type icons (PDF, DWG, XLSX, Images)
- Upload to Azure Blob Storage (falls back to URL path if not configured)
- Filter by project and file type

### Timeline
- Phase/milestone list per project
- Progress bars with status color coding

### Reports
- Budget vs Actual spend charts
- Project status distribution
- Team productivity line chart
- Project summary table

### AI Search (/search)
- Natural language search across all data
- AI answer box powered by GPT-4o-mini
- Suggested follow-up questions
- Recent search history
- Filter by content type (Projects/Tasks/Documents/Team)

## API Endpoints

```
POST /api/auth/register
POST /api/auth/login
GET  /api/auth/me
GET  /api/auth/users

GET  /api/projects/
POST /api/projects/
GET  /api/projects/{id}
PUT  /api/projects/{id}
DELETE /api/projects/{id}

GET  /api/tasks/
POST /api/tasks/
PUT  /api/tasks/{id}
DELETE /api/tasks/{id}

GET  /api/team/
POST /api/team/
PUT  /api/team/{id}
DELETE /api/team/{id}

GET  /api/documents/
POST /api/documents/upload
DELETE /api/documents/{id}

POST /api/search/
POST /api/search/index          ← trigger Azure SQL Indexer (syncs SQL view → search)
GET  /api/search/index/status   ← SQL indexer run status
```

## Azure Services Setup

### Azure AI Search
1. Create an Azure AI Search resource
2. Run `python azure/search/setup_sql_indexer.py` from `backend/` (creates index, SQL view, indexer)
3. The SQL Indexer runs every 15 minutes; uploads/deletes also trigger a debounced run via the API
4. Do **not** use manual Python indexing — all searchable content comes from `vw_global_search_documents`

### Azure OpenAI
1. Create an Azure OpenAI resource
2. Deploy `gpt-4o-mini` model
3. Deploy `text-embedding-3-small` model
4. Add endpoint and key to backend `.env`

### Azure Blob Storage
1. Create a Storage Account
2. Create container `buildtrack-documents`
3. Add connection string to backend `.env`

## Sample Data

The backend seeds the database with realistic construction data on first run:

- **5 Projects:** Highway Bridge Expansion, Commercial Tower Phase 2, Metro Station Renovation, Industrial Warehouse Build, Residential Complex A
- **15 Tasks:** Site surveys, foundation work, steel erection, electrical wiring, etc.
- **8 Team Members:** Admin, Project Managers, Site Engineers, Contractors
- **10 Documents:** PDFs, DWG files, XLSX reports
