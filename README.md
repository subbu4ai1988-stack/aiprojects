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

