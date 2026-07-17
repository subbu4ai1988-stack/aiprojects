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
- Resume parsing, matching, question generation, and feedback use deterministic local logic so development requires no cloud account.
- The service boundary in `backend/app/services.py` is ready for OpenAI/Gemini, S3, Transcribe, and job-board adapters.

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
