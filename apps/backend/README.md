# Deep Research Backend

## Overview
This Django REST backend wraps the Open Deep Research LangGraph workflow and adds persistence, continuation, uploads, tracing, and cost tracking without rewriting the core agent logic.

## Architecture (What happens on a request)
1. `POST /api/research/start` creates a `ResearchSession` row and returns `PENDING`.
2. Celery runs the long research job in the background.
3. The LangGraph workflow (from `src/open_deep_research`) performs search + synthesis.
4. The backend stores report, summary, reasoning, sources, token usage, and cost.
5. `GET /api/research/{id}` returns the final result.

Continuation uses the parent summary and uploaded document summaries to avoid repeating topics.

## Requirements
- Python 3.10+
- PostgreSQL
- Redis (Celery broker)
- API keys for your chosen LLM/search providers

## Quickstart (Local)
1. From repo root, install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   python -m pip install -e .
   python -m pip install -r apps/backend/requirements.txt
   ```
2. Create the environment file:
   ```bash
   cd apps/backend
   cp .env.example .env
   ```
3. Start Postgres + Redis (example with Homebrew):
   ```bash
   brew install postgresql@16 redis
   brew services start postgresql@16
   brew services start redis
   ```
4. Create database + user (example defaults from `.env`):
   ```bash
   createdb deep_research
   createuser -s deepresearch
   psql -d postgres -c "ALTER USER deepresearch WITH PASSWORD 'deepresearch';"
   ```
5. Run migrations:
   ```bash
   python manage.py migrate
   ```
6. Start the API (use a non-8000 port if needed):
   ```bash
   python manage.py runserver 8002
   ```
7. Start the Celery worker (new terminal):
   ```bash
   celery -A config worker -l info --concurrency=1 --pool=solo
   ```

## Frontend Test Console
The lightweight test UI lives in `apps/frontend/`.
```bash
cd apps/frontend
python3 -m http.server 5173
```
Open `http://127.0.0.1:5173/` and set Base URL to:
```
http://127.0.0.1:8002/api/research
```

## API Endpoints
- `POST /api/research/start`
- `POST /api/research/{research_id}/continue`
- `POST /api/research/{research_id}/upload`
- `GET /api/research/history`
- `GET /api/research/{research_id}`

## Example Requests (curl)
Start research:
```bash
curl -X POST http://127.0.0.1:8002/api/research/start \
  -H "Content-Type: application/json" \
  -d '{"query":"Summarize AI impacts on drug discovery with sources."}'
```

Upload a file:
```bash
curl -X POST http://127.0.0.1:8002/api/research/<id>/upload \
  -F "file=@/path/to/notes.txt"
```

Fetch details:
```bash
curl http://127.0.0.1:8002/api/research/<id>
```

## Data Models
- `ResearchSession` (status, query, parent, trace_id)
- `ResearchReport` (report + sources)
- `ResearchSummary`
- `ResearchReasoning`
- `ResearchCost` (token usage + estimated cost)
- `UploadedDocument`

## Environment Variables
Core:
- `ODR_SEARCH_API` (tavily, openai, anthropic, none)
- `ODR_RESEARCH_MODEL`, `ODR_COMPRESSION_MODEL`
- `ODR_FINAL_REPORT_MODEL`, `ODR_SUMMARIZATION_MODEL`

Provider keys:
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `GROQ_API_KEY`
- `TAVILY_API_KEY`

LangSmith:
- `LANGCHAIN_TRACING_V2=true`
- `LANGCHAIN_API_KEY=<your key>`
- `LANGCHAIN_PROJECT=<project name>`
  - If you see `403` in worker logs, the key lacks permissions. Update `LANGCHAIN_API_KEY` and restart Celery.

Cost estimation:
- `ODR_MODEL_COSTS_JSON` (per 1K tokens)
- `ODR_COST_MODEL`

Uploads and summaries:
- `ODR_REPORT_SUMMARY_MODEL`, `ODR_REPORT_SUMMARY_MAX_TOKENS`, `ODR_REPORT_SUMMARY_MAX_CHARS`
- `ODR_UPLOAD_SUMMARY_MODEL`, `ODR_UPLOAD_SUMMARY_MAX_TOKENS`
- `ODR_UPLOAD_MAX_CHARS`, `ODR_UPLOAD_STORE_MAX_CHARS`
- `ODR_UPLOAD_WAIT_SECONDS`

Frontend / CORS:
- `CORS_ALLOW_ALL=true` (dev only)
- `CORS_ALLOWED_ORIGINS` (comma-separated)

## Testing Checklist
1. Start research and confirm `COMPLETED` with sources.
2. Upload a TXT/PDF and ensure it influences the report.
3. Continue research and verify parent linkage.
4. Confirm token usage + cost + trace_id in detail response.

## Troubleshooting
- Port in use: `lsof -ti :8002` then `kill <PID>`.
- CORS errors: set `CORS_ALLOW_ALL=true` and restart backend.
- Rate limits from Groq: try a smaller model or retry later.
- LangSmith 403: API key permission issue. Update `LANGCHAIN_API_KEY` and restart the worker.

## Notes
- Uploads are stored under `apps/backend/media/`.
- The demo user in `research/views.py` is a stub (replace with real auth later).
- Postman collection: `apps/backend/postman/deep_research_api.postman_collection.json`.
