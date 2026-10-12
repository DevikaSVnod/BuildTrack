# Host SPACE header search (POC FastAPI) on 8016 — Gateway proxies /api/search here.
Set-Location $PSScriptRoot
python -m uvicorn app.main:app --host 0.0.0.0 --port 8016 --reload
