import hashlib
import hmac
from pathlib import Path
from secrets import token_urlsafe
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from .admin_models import JobAssignment
from .database import Base, DATA_DIR, engine, get_db
from .models import Application, Candidate, EmailDelivery, Feedback, Interview, Job, JobPosting, User
from .schemas import BoardPublishIn, InterviewAnswers, JobIn, JobOut, Login, QuestionsIn
from .phase4 import accessible_jobs, has_job_access, router as phase4_router
from .services import analyze_answers, extract_resume, generate_questions, parse_resume, rank_resume

SECRET = "local-development-secret-change-in-production"
app = FastAPI(title="RecruitAI API", version="1.1.0")


def hash_password(password: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), b"recruitai-local", 120_000).hex()


def verify_password(password: str, encoded: str) -> bool:
    return hmac.compare_digest(hash_password(password), encoded)


app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])
MEDIA_DIR = DATA_DIR / "media"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")
app.include_router(phase4_router)


@app.on_event("startup")
def startup():
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        if not db.scalar(select(User).where(User.email == "recruiter@recruitai.local")):
            db.add(User(email="recruiter@recruitai.local", password_hash=hash_password("recruitai"), role="recruiter"))
        if not db.scalar(select(User).where(User.email == "admin@recruitai.local")):
            db.add(User(email="admin@recruitai.local", password_hash=hash_password("recruitai-admin"), role="admin"))
        db.commit()


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


@app.post("/api/auth/login")
def login(payload: Login, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    return {"access_token": jwt.encode({"sub": user.email, "role": user.role}, SECRET, algorithm="HS256"), "role": user.role}


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
async def add_application(job_id: int, name: Annotated[str, Form()], email: Annotated[str, Form()], resume: UploadFile = File(), db: Session = Depends(get_db), user: User = Depends(current_user)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if not has_job_access(db, user, job_id): raise HTTPException(403, "Job access denied")
    suffix = Path(resume.filename or "resume").suffix.lower()
    if suffix not in {".pdf", ".docx"}:
        raise HTTPException(400, "Resume must be PDF or DOCX")
    upload_dir = DATA_DIR / "uploads"
    upload_dir.mkdir(exist_ok=True)
    path = upload_dir / f"{token_urlsafe(8)}{suffix}"
    path.write_bytes(await resume.read())
    parsed = parse_resume(extract_resume(path))
    parsed["name"] = name
    parsed["email"] = email
    candidate = Candidate(name=name, email=email, phone=parsed.get("phone", ""), resume_path=str(path), parsed_resume_data=parsed)
    db.add(candidate)
    db.flush()
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
    return {"token": interview.token, "url": f"http://127.0.0.1:5173/interview/{interview.token}", "questions": interview.questions, "status": interview.status}


@app.get("/api/applications/{application_id}/interview")
def recruiter_interview(application_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    application = db.get(Application, application_id)
    if not application or not application.interview:
        raise HTTPException(404, "Interview not found")
    if not has_job_access(db, user, application.job_id): raise HTTPException(403, "Job access denied")
    interview = application.interview
    return {"token": interview.token, "url": f"http://127.0.0.1:5173/interview/{interview.token}", "questions": interview.questions, "status": interview.status}


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
    url = f"http://127.0.0.1:5173/interview/{interview.token}"
    subject = f"Your interview for {application.job.title}"
    body = f"Hello {application.candidate.name},\n\nYou are invited to complete a one-way video interview for {application.job.title}.\n\nSecure interview link: {url}\n\nYou may re-record each answer once."
    delivery = EmailDelivery(application_id=application.id, recipient=application.candidate.email, subject=subject, body=body, status="sent", provider="local-outbox")
    db.add(delivery)
    interview.status = "invited"
    db.commit()
    db.refresh(delivery)
    return {"id": delivery.id, "recipient": delivery.recipient, "subject": delivery.subject, "status": delivery.status, "provider": delivery.provider, "sent_at": delivery.sent_at, "interview_url": url}


@app.get("/api/applications/{application_id}/communications")
def list_communications(application_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    application = db.get(Application, application_id)
    if not application: raise HTTPException(404, "Application not found")
    if not has_job_access(db, user, application.job_id): raise HTTPException(403, "Job access denied")
    rows = db.scalars(select(EmailDelivery).where(EmailDelivery.application_id == application_id).order_by(EmailDelivery.id.desc())).all()
    return [{"id": row.id, "recipient": row.recipient, "subject": row.subject, "body": row.body, "status": row.status, "provider": row.provider, "sent_at": row.sent_at} for row in rows]


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
    path = MEDIA_DIR / filename
    path.write_bytes(await video.read())
    answers[question_index] = {**answers[question_index], "question": interview.questions[question_index]["text"], "video_url": f"/media/{filename}", "recording_attempts": attempts + 1}
    interview.answers = answers
    interview.status = "in_progress"
    db.commit()
    return {"video_url": f"/media/{filename}", "recording_attempts": attempts + 1, "remaining_rerecords": 1 - attempts}


@app.post("/api/interviews/{token}/answers")
def submit_answers(token: str, payload: InterviewAnswers, db: Session = Depends(get_db)):
    interview = db.scalar(select(Interview).where(Interview.token == token))
    if not interview:
        raise HTTPException(404, "Interview not found")
    existing = list(interview.answers or [])
    submitted = []
    for index, answer in enumerate(payload.answers):
        video_data = existing[index] if index < len(existing) else {}
        submitted.append({**video_data, **answer.model_dump()})
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
    return {"report": f.ai_generated_report, "recommendation": f.recommendation, "confidence_score": f.confidence_score, "answers": application.interview.answers}
