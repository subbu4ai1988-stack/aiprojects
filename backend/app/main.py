import hashlib
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
import hmac
from pathlib import Path
from secrets import token_urlsafe
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from .admin_models import JobAssignment
from .ai_provider import ai_status
from .config import settings
from .database import Base, DATA_DIR, engine, get_db
from .integrations import record_integration, send_email, transcribe_answer
from .models import Application, Candidate, EmailDelivery, Feedback, Interview, Job, JobPosting, User
from .schemas import BoardPublishIn, InterviewAnswers, JobIn, JobOut, Login, QuestionsIn
from .phase4 import accessible_jobs, has_job_access, router as phase4_router
from .phase6 import router as phase6_router
from .privacy import backfill_candidate_privacy, ensure_candidate_privacy, router as privacy_router
from .services import analyze_answers, extract_resume, generate_questions, parse_resume, rank_resume
from .storage import router as storage_router, signed_download_url, storage
from .tasks import enqueue_application

SECRET = settings.jwt_secret
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.auto_create_schema:
        Base.metadata.create_all(engine)
    with Session(engine) as db:
        if settings.bootstrap_demo_users:
            if not db.scalar(select(User).where(User.email == "recruiter@recruitai.local")):
                db.add(User(email="recruiter@recruitai.local", password_hash=hash_password("recruitai"), role="recruiter"))
            if not db.scalar(select(User).where(User.email == "admin@recruitai.local")):
                db.add(User(email="admin@recruitai.local", password_hash=hash_password("recruitai-admin"), role="admin"))
        if settings.bootstrap_admin_email and not db.scalar(select(User).where(User.email == settings.bootstrap_admin_email)):
            db.add(User(email=settings.bootstrap_admin_email, password_hash=hash_password(settings.bootstrap_admin_password), role="admin"))
        backfill_candidate_privacy(db)
        db.commit()
    yield


app = FastAPI(title="RecruitAI API", version="1.5.0", lifespan=lifespan)


def hash_password(password: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), b"recruitai-local", 120_000).hex()


def verify_password(password: str, encoded: str) -> bool:
    return hmac.compare_digest(hash_password(password), encoded)


app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def operational_headers(request: Request, call_next):
    request_id = request.headers.get("x-request-id", token_urlsafe(12))[:160]
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(self), microphone=(self)"
    return response

MEDIA_DIR = DATA_DIR / "media"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")
app.include_router(phase4_router)
app.include_router(phase6_router)
app.include_router(privacy_router)
app.include_router(storage_router)


def current_user(authorization: Annotated[str | None, Header()] = None, db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Authentication required")
    try:
        email = jwt.decode(authorization[7:], SECRET, algorithms=["HS256"])["sub"]
    except (JWTError, KeyError):
        raise HTTPException(401, "Invalid token")
    user = db.scalar(select(User).where(User.email == email))
    if not user:
        raise HTTPException(401, "Unknown user")
    return user


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/ai/status")
def get_ai_status(user: User = Depends(current_user)):
    return ai_status()


@app.post("/api/auth/login")
def login(payload: Login, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    expires = datetime.now(UTC) + timedelta(minutes=settings.access_token_minutes)
    claims = {"sub": user.email, "role": user.role, "exp": expires}
    return {"access_token": jwt.encode(claims, SECRET, algorithm="HS256"), "role": user.role, "expires_at": expires}


@app.get("/api/jobs", response_model=list[JobOut])
def list_jobs(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return accessible_jobs(db, user)


@app.post("/api/jobs", response_model=JobOut)
def create_job(payload: JobIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = Job(**payload.model_dump())
    db.add(job)
    db.flush()
    db.add(JobAssignment(job_id=job.id, user_id=user.id))
    db.commit()
    db.refresh(job)
    return job


@app.patch("/api/jobs/{job_id}/publish", response_model=JobOut)
def publish_job(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if not has_job_access(db, user, job_id): raise HTTPException(403, "Job access denied")
    job.status = "open"
    db.commit()
    db.refresh(job)
    return job



@app.get("/api/jobs/{job_id}/postings")
def list_postings(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not has_job_access(db, user, job_id): raise HTTPException(403, "Job access denied")
    rows = db.scalars(select(JobPosting).where(JobPosting.job_id == job_id).order_by(JobPosting.id.desc())).all()
    return [{"id": row.id, "board": row.board, "external_id": row.external_id, "external_url": row.external_url, "status": row.status, "posted_at": row.posted_at} for row in rows]


@app.post("/api/jobs/{job_id}/postings")
def publish_to_boards(job_id: int, payload: BoardPublishIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if not has_job_access(db, user, job_id): raise HTTPException(403, "Job access denied")
    if job.status != "open":
        raise HTTPException(409, "Publish the job before posting it to job boards")
    allowed = {"linkedin", "indeed", "glassdoor"}
    requested = list(dict.fromkeys(board.lower() for board in payload.boards))
    invalid = [board for board in requested if board not in allowed]
    if invalid:
        raise HTTPException(400, f"Unsupported job boards: {', '.join(invalid)}")
    confirmations = []
    for board in requested:
        existing = db.scalar(select(JobPosting).where(JobPosting.job_id == job.id, JobPosting.board == board))
        posting = existing or JobPosting(job_id=job.id, board=board, external_id=f"{board}-{job.id}-{token_urlsafe(5)}", external_url=f"https://jobs.example.local/{board}/{job.id}")
        db.add(posting)
        db.flush()
        confirmations.append(posting)
    db.commit()
    return [{"id": row.id, "board": row.board, "external_id": row.external_id, "external_url": row.external_url, "status": row.status, "posted_at": row.posted_at} for row in confirmations]


@app.post("/api/jobs/{job_id}/applications")
async def add_application(job_id: int, name: Annotated[str, Form()], email: Annotated[str, Form()], resume: UploadFile = File(), consent: Annotated[bool, Form()] = True, db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if not has_job_access(db, user, job_id): raise HTTPException(403, "Job access denied")
    suffix = Path(resume.filename or "resume").suffix.lower()
    if suffix not in {".pdf", ".docx"}:
        raise HTTPException(400, "Resume must be PDF or DOCX")
    content = await resume.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(413, "Resume exceeds the configured upload limit")
    if not consent:
        raise HTTPException(400, "Candidate consent is required before processing personal data")
    reference = storage.put_bytes(f"uploads/{token_urlsafe(8)}{suffix}", content, resume.content_type or "application/octet-stream")
    record_integration(db, "storage", "resume_upload", storage.provider, "completed", reference=reference, details={"bytes": len(content)})
    if settings.async_ai_jobs:
        candidate = Candidate(name=name, email=email, phone="", resume_path=reference, parsed_resume_data={"skills": [], "_ai_source": "queued"})
        db.add(candidate)
        db.flush()
        ensure_candidate_privacy(db, candidate.id, consent)
        application = Application(job_id=job.id, candidate_id=candidate.id, match_score=0, ai_ranking_summary="AI parsing and ranking queued")
        db.add(application)
        db.flush()
        task = enqueue_application(db, application.id)
        db.commit()
        return {"id": application.id, "match_score": 0, "summary": application.ai_ranking_summary, "processing": True, "task_id": task.id}
    with storage.materialize(reference) as path:
        parsed = parse_resume(extract_resume(path))
    parsed["name"] = name
    parsed["email"] = email
    candidate = Candidate(name=name, email=email, phone=parsed.get("phone", ""), resume_path=reference, parsed_resume_data=parsed)
    db.add(candidate)
    db.flush()
    ensure_candidate_privacy(db, candidate.id, consent)
    params = job.ranking_params or {}
    score, summary = rank_resume(parsed.get("raw_text", ""), job.description, params.get("required_skills", []))
    application = Application(job_id=job.id, candidate_id=candidate.id, match_score=score, ai_ranking_summary=summary)
    db.add(application)
    db.commit()
    db.refresh(application)
    return {"id": application.id, "match_score": score, "summary": summary}

@app.get("/api/jobs/{job_id}/candidates")
def ranked_candidates(job_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not has_job_access(db, user, job_id): raise HTTPException(403, "Job access denied")
    rows = db.scalars(select(Application).where(Application.job_id == job_id).order_by(Application.match_score.desc())).all()
    return [{"application_id": a.id, "name": a.candidate.name, "email": a.candidate.email, "status": a.status, "interview_status": a.interview.status if a.interview else None, "match_score": a.match_score, "summary": a.ai_ranking_summary, "skills": a.candidate.parsed_resume_data.get("skills", [])} for a in rows]


@app.post("/api/applications/{application_id}/interview")
def invite(application_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    application = db.get(Application, application_id)
    if not application:
        raise HTTPException(404, "Application not found")
    if not has_job_access(db, user, application.job_id): raise HTTPException(403, "Job access denied")
    interview = application.interview or Interview(application_id=application.id, token=token_urlsafe(24), questions=generate_questions(application.job.title, application.job.description))
    application.status = "interview"
    db.add(interview)
    db.commit()
    db.refresh(interview)
    return {"token": interview.token, "url": f"{settings.public_app_url}/interview/{interview.token}", "questions": interview.questions, "status": interview.status}


@app.get("/api/applications/{application_id}/interview")
def recruiter_interview(application_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    application = db.get(Application, application_id)
    if not application or not application.interview:
        raise HTTPException(404, "Interview not found")
    if not has_job_access(db, user, application.job_id): raise HTTPException(403, "Job access denied")
    interview = application.interview
    return {"token": interview.token, "url": f"{settings.public_app_url}/interview/{interview.token}", "questions": interview.questions, "status": interview.status}


@app.put("/api/applications/{application_id}/interview/questions")
def update_questions(application_id: int, payload: QuestionsIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    application = db.get(Application, application_id)
    if not application or not application.interview:
        raise HTTPException(404, "Interview not found")
    if not has_job_access(db, user, application.job_id): raise HTTPException(403, "Job access denied")
    if application.interview.status not in {"invited", "prepared"}:
        raise HTTPException(409, "Questions cannot be changed after the interview starts")
    application.interview.questions = [q.model_dump() for q in payload.questions]
    application.interview.status = "prepared"
    db.commit()
    return {"questions": application.interview.questions, "status": application.interview.status}



@app.post("/api/applications/{application_id}/interview/send-invite")
def send_interview_invite(application_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    application = db.get(Application, application_id)
    if not application or not application.interview:
        raise HTTPException(404, "Prepare the interview before sending an invitation")
    if not has_job_access(db, user, application.job_id): raise HTTPException(403, "Job access denied")
    interview = application.interview
    url = f"{settings.public_app_url}/interview/{interview.token}"
    subject = f"Your interview for {application.job.title}"
    body = f"Hello {application.candidate.name},\n\nYou are invited to complete a one-way video interview for {application.job.title}.\n\nSecure interview link: {url}\n\nYou may re-record each answer once."
    result = send_email(application.candidate.email, subject, body)
    delivery = EmailDelivery(
        application_id=application.id, recipient=application.candidate.email, subject=subject, body=body,
        status=result.status, provider=result.provider, attempts=result.attempts, error=result.error,
    )
    db.add(delivery)
    record_integration(
        db, "email", "interview_invite", result.provider, result.status,
        reference=application.candidate.email, attempts=result.attempts, error=result.error,
        details={"application_id": application.id},
    )
    interview.status = "invited" if result.status == "sent" else "delivery_failed"
    db.commit()
    db.refresh(delivery)
    return {"id": delivery.id, "recipient": delivery.recipient, "subject": delivery.subject, "status": delivery.status, "provider": delivery.provider, "attempts": delivery.attempts, "error": delivery.error, "sent_at": delivery.sent_at, "interview_url": url}

@app.get("/api/applications/{application_id}/communications")
def list_communications(application_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    application = db.get(Application, application_id)
    if not application: raise HTTPException(404, "Application not found")
    if not has_job_access(db, user, application.job_id): raise HTTPException(403, "Job access denied")
    rows = db.scalars(select(EmailDelivery).where(EmailDelivery.application_id == application_id).order_by(EmailDelivery.id.desc())).all()
    return [{"id": row.id, "recipient": row.recipient, "subject": row.subject, "body": row.body, "status": row.status, "provider": row.provider, "attempts": row.attempts, "error": row.error, "sent_at": row.sent_at} for row in rows]


@app.get("/api/interviews/{token}")
def interview_session(token: str, db: Session = Depends(get_db)):
    interview = db.scalar(select(Interview).where(Interview.token == token))
    if not interview:
        raise HTTPException(404, "Interview not found")
    return {"candidate": interview.application.candidate.name, "job": interview.application.job.title, "questions": interview.questions, "status": interview.status, "recording_attempts": {str(i): item.get("recording_attempts", 0) for i, item in enumerate(interview.answers or [])}}


@app.post("/api/interviews/{token}/answers/{question_index}/video")
async def upload_video_answer(token: str, question_index: int, video: UploadFile = File(), db: Session = Depends(get_db)):
    interview = db.scalar(select(Interview).where(Interview.token == token))
    if not interview:
        raise HTTPException(404, "Interview not found")
    if interview.status in {"analyzed", "completed"}:
        raise HTTPException(409, "Interview is already complete")
    if question_index < 0 or question_index >= len(interview.questions):
        raise HTTPException(400, "Invalid question index")
    answers = list(interview.answers or [])
    while len(answers) < len(interview.questions):
        answers.append({})
    attempts = int(answers[question_index].get("recording_attempts", 0))
    if attempts >= 2:
        raise HTTPException(409, "Only one re-record is permitted")
    content_type = video.content_type or ""
    if not content_type.startswith("video/"):
        raise HTTPException(400, "A video recording is required")
    suffix = ".webm" if "webm" in content_type else ".mp4"
    filename = f"{token}-{question_index}-{attempts + 1}{suffix}"
    content = await video.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(413, "Video exceeds the configured upload limit")
    previous_reference = answers[question_index].get("video_ref") or answers[question_index].get("video_url", "")
    reference = storage.put_bytes(f"media/{filename}", content, content_type)
    if previous_reference:
        storage.delete(previous_reference)
    video_url = signed_download_url(reference)
    answers[question_index] = {
        **answers[question_index], "question": interview.questions[question_index]["text"],
        "video_ref": reference, "video_url": video_url, "recording_attempts": attempts + 1,
    }
    record_integration(db, "storage", "video_upload", storage.provider, "completed", reference=reference, details={"bytes": len(content)})
    interview.answers = answers
    interview.status = "in_progress"
    db.commit()
    return {"video_url": video_url, "recording_attempts": attempts + 1, "remaining_rerecords": 1 - attempts}

@app.post("/api/interviews/{token}/answers")
def submit_answers(token: str, payload: InterviewAnswers, db: Session = Depends(get_db)):
    interview = db.scalar(select(Interview).where(Interview.token == token))
    if not interview:
        raise HTTPException(404, "Interview not found")
    existing = list(interview.answers or [])
    submitted = []
    for index, answer in enumerate(payload.answers):
        video_data = existing[index] if index < len(existing) else {}
        transcription = transcribe_answer(video_data.get("video_ref", video_data.get("video_url", "")), answer.answer)
        submitted.append({**video_data, **answer.model_dump(), "answer": transcription.transcript, "transcription_provider": transcription.provider})
        record_integration(
            db, "transcription", "interview_answer", transcription.provider, transcription.status,
            reference=video_data.get("video_ref", ""), error=transcription.error,
            details={"interview_id": interview.id, "question_index": index},
        )
    interview.answers = submitted
    interview.status = "analyzed"
    report, recommendation, confidence = analyze_answers(interview.answers, interview.application.job.description)
    feedback = interview.feedback or Feedback(interview_id=interview.id, ai_generated_report=report, recommendation=recommendation, confidence_score=confidence)
    feedback.ai_generated_report, feedback.recommendation, feedback.confidence_score = report, recommendation, confidence
    db.add(feedback)
    db.commit()
    return {"status": "completed"}

@app.get("/api/applications/{application_id}/feedback")
def get_feedback(application_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    application = db.get(Application, application_id)
    if not application or not application.interview or not application.interview.feedback:
        raise HTTPException(404, "Feedback not available")
    if not has_job_access(db, user, application.job_id): raise HTTPException(403, "Job access denied")
    f = application.interview.feedback
    answers = []
    for answer in application.interview.answers or []:
        item = dict(answer)
        reference = item.get("video_ref") or item.get("video_url", "")
        if reference:
            item["video_url"] = signed_download_url(reference)
        answers.append(item)
    return {"report": f.ai_generated_report, "recommendation": f.recommendation, "confidence_score": f.confidence_score, "answers": answers}
