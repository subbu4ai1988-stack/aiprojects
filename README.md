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
## Phase 7 privacy and compliance

- Every candidate ingestion records consent, legal basis, and a configurable retention deadline.
- Administrators can review privacy status, export a complete candidate data package, apply legal holds, and permanently delete candidate records and stored files.
- Privacy exports, policy updates, and deletions are recorded in a non-PII audit ledger using hashed subject references.
- Retention enforcement supports a safe preview and an explicit administrator run. The worker can also enforce overdue deletion automatically when `PRIVACY_AUTO_DELETE=true`.
- Candidate deletion removes applications, interviews, feedback, communications, queued AI tasks, resumes, and recorded interview media while preserving the privacy audit event.

Privacy configuration:

```dotenv
CANDIDATE_RETENTION_DAYS=365
PRIVACY_AUTO_DELETE=false
PRIVACY_SWEEP_INTERVAL_SECONDS=3600
```

Automatic deletion is disabled by default so administrators can review the retention preview and legal holds before enabling it. The Docker admin console exposes the active policy without exposing secrets.
## Phase 8 integration infrastructure

- Resumes and interview recordings use a storage adapter with local filesystem and S3-compatible implementations. Docker uses a private MinIO bucket by default.
- Candidate video playback and privacy exports receive HMAC-signed download links that expire after STORAGE_SIGNED_URL_SECONDS.
- Existing local resume paths and /media recording references remain supported during migration.
- Interview email delivery supports the local outbox or real SMTP with TLS, authentication, bounded retry attempts, and persisted delivery errors.
- Interview answer transcription now passes through an explicit adapter boundary. Local mode uses the supplied transcript while keeping the workflow ready for a production speech-to-text adapter.
- Storage, email, and transcription operations are recorded in the integration audit ledger and summarized in the administrator console.
- Migration 0003 adds delivery retry/error fields and integration telemetry. Fresh and Phase 7 databases both upgrade with alembic upgrade head.
- Frontend ESLint is configured and runs with npm run lint.

Docker starts MinIO automatically. Use the existing private Docker environment file:

    docker compose --env-file "$env:TEMP\recruitai-docker-local.env" up -d --build

RecruitAI is available at http://localhost:8080 and the local MinIO administration console at http://localhost:9001. MinIO credentials are the MINIO_ROOT_USER and MINIO_ROOT_PASSWORD values in that environment file.

For a production SMTP server, configure EMAIL_PROVIDER=smtp, EMAIL_FROM, SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_USE_TLS, and SMTP_MAX_ATTEMPTS. Keep EMAIL_PROVIDER=local, TRANSCRIPTION_PROVIDER=local, and AI_PROVIDER=local until their live services are intentionally enabled. Secrets are never returned by runtime or integration-audit endpoints.

## Phase 9 Runpod GPU transcription

- RecruitAI can now submit private interview recordings to an optional Runpod Serverless endpoint running Faster-Whisper on a GPU.
- The API sends only a short-lived signed media URL and an optional transcript hint. Runpod credentials are never returned by runtime or audit endpoints.
- The Runpod client uses the authenticated `/runsync` queue endpoint with bounded wait and request timeouts.
- Failed, timed-out, or malformed Runpod jobs are recorded in the integration audit ledger; the candidate's typed transcript remains available as a safe fallback.
- The worker rejects HTTP, localhost, private-network, and credential-bearing media URLs by default to reduce server-side request forgery risk.
- Local development remains unchanged with `TRANSCRIPTION_PROVIDER=local`, so no Runpod charge or GPU is needed while implementing other features.

The deployable worker, job contract, image build commands, endpoint settings, and production activation checklist are in `runpod_worker/README.md`. The key activation values are:

```dotenv
TRANSCRIPTION_PROVIDER=runpod
RUNPOD_API_KEY=your_runpod_api_key
RUNPOD_ENDPOINT_ID=your_serverless_endpoint_id
PUBLIC_APP_URL=https://your-public-recruitai-domain.example
```

Do not enable Runpod while `PUBLIC_APP_URL` points to localhost: the remote worker must be able to reach the signed RecruitAI download route over public HTTPS. Build and test the rest of RecruitAI locally first, publish the worker image when ready, and then enable the provider in the deployment environment.
