# RecruitAI Platform

Local-first MVP implementing the supplied BRD and TDD: job lifecycle management, resume ingestion and ranking, interview-question generation, candidate interview sessions, and recruiter feedback.

## Run locally

### Backend

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload --port 8000
```

The API is available at `http://127.0.0.1:8000`, with interactive documentation at `/docs`.

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. The Vite development server proxies `/api` to the backend.

## Local behavior

- SQLite stores application data in `backend/data/recruitai.db`.
- Uploaded resumes are stored under `backend/data/uploads`.
- Resume parsing, matching, question generation, and feedback use deterministic local logic by default, so development requires no cloud account.
- The service boundary in `backend/app/services.py` automatically routes to OpenAI when configured and falls back locally if the provider is unavailable.

## Demo login

- Email: `recruiter@recruitai.local`
- Password: `recruitai`

## Test

```powershell
pytest backend/tests
cd frontend
npm run build
```


## Phase 2 interview workflow

- Recruiters can review, edit, add, or remove generated interview questions before sending an invite.
- Candidates record browser-based video answers and may re-record each answer once.
- Local video files are stored under `backend/data/media` and exposed only through the application server.
- Written transcripts or summaries are analyzed into per-question scores, an overall recommendation, and a confidence score.
- Recruiters can review recordings, transcripts, and the consolidated assessment report in one screen.

## Phase 3 distribution and communications

- Open jobs can be distributed to LinkedIn, Indeed, and Glassdoor through local adapter simulations.
- Each job-board operation stores an external reference, confirmation status, and timestamp.
- Interview invitations are delivered through a local outbox adapter with recipient, subject, secure link, provider, and delivery status.
- The adapter boundaries can be replaced with production job-board and SMTP/email-provider integrations without changing the recruiter workflow.

## Phase 4 administration and analytics

- Role-based job access supports administrators, recruiters, and hiring managers.
- New jobs are automatically assigned to their creator; administrators can change assignments.
- Recruiters can move candidates through applied, screening, interview, offer, and rejected stages.
- The analytics dashboard shows job counts, application funnel, interview activity, match score, and offer rate.
- Administrator login: `admin@recruitai.local` / `recruitai-admin`.

## Phase 5 production AI

- OpenAI structured outputs provide typed resume extraction, job-fit assessment, interview questions, and interview feedback.
- Semantic candidate matching combines `text-embedding-3-small` similarity with a structured evidence-based assessment.
- Every OpenAI operation automatically falls back to local deterministic logic if credentials are absent or the provider is unavailable.
- The recruiter header shows the active provider, configured reasoning model, embedding model, and fallback state without exposing credentials.
- Provider tests use fakes and do not make paid API calls.

To enable OpenAI, copy `.env.example` to `.env`, then set:

```dotenv
AI_PROVIDER=openai
OPENAI_API_KEY=your_api_key
OPENAI_MODEL=gpt-5.6-sol
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

Restart the backend after changing environment variables. Keep `.env` out of source control.

## Phase 6 production readiness

- Centralized environment configuration validates production secrets, trusted origins, upload limits, schema strategy, and administrator bootstrapping.
- The database layer accepts `DATABASE_URL` for SQLite or PostgreSQL, with Alembic migrations for production deployments.
- Live AI calls have application rate limits, a circuit breaker, a configurable monthly token budget, automatic local fallback, token/request-ID telemetry, and persistent audit records.
- Production application parsing and ranking run through a durable database task queue and a separately scalable worker; local development stays synchronous by default.
- A versioned local evaluation dataset checks that relevant resumes outrank unrelated resumes before deployment.
- Administrators can view safe runtime configuration and AI usage metrics without access to API keys or prompt content.
- Liveness and database readiness endpoints support container orchestration; API responses include request IDs and security headers.
- Docker Compose provides PostgreSQL, the FastAPI service, and an Nginx-served frontend. GitHub Actions runs Python tests and the frontend build.

### Database migrations

For a new database:

```powershell
alembic upgrade head
```

Existing Phase 1–5 local SQLite databases continue using `AUTO_CREATE_SCHEMA=true`. After starting Phase 6 once, baseline that existing database with `alembic stamp head` before switching it to migration-managed operation.

### Container deployment

Set `POSTGRES_PASSWORD`, a unique `JWT_SECRET` of at least 32 characters, `BOOTSTRAP_ADMIN_EMAIL`, and a bootstrap administrator password of at least 12 characters. Then run:

```powershell
docker compose up --build
```

The production frontend is available at `http://localhost:8080`. OpenAI remains disabled unless `AI_PROVIDER=openai` and `OPENAI_API_KEY` are explicitly supplied.
