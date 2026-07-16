import hashlib
import hmac
from pathlib import Path
from secrets import token_urlsafe
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import Base, DATA_DIR, engine, get_db
from .models import Application, Candidate, Feedback, Interview, Job, User
from .schemas import InterviewAnswers, JobIn, JobOut, Login
from .services import analyze_answers, extract_resume, generate_questions, parse_resume, rank_resume

SECRET = "local-development-secret-change-in-production"
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
app = FastAPI(title="RecruitAI API", version="1.0.0")

def hash_password(password: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), b"recruitai-local", 120_000).hex()

def verify_password(password: str, encoded: str) -> bool:
    return hmac.compare_digest(hash_password(password), encoded)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def startup():
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        if not db.scalar(select(User).where(User.email == "recruiter@recruitai.local")):
            db.add(User(email="recruiter@recruitai.local", password_hash=hash_password("recruitai"), role="recruiter"))
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
def health(): return {"status": "ok"}


@app.post("/api/auth/login")
def login(payload: Login, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    return {"access_token": jwt.encode({"sub": user.email, "role": user.role}, SECRET, algorithm="HS256"), "role": user.role}


@app.get("/api/jobs", response_model=list[JobOut])
def list_jobs(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return list(db.scalars(select(Job).order_by(Job.id.desc())))


@app.post("/api/jobs", response_model=JobOut)
def create_job(payload: JobIn, db: Session = Depends(get_db), _: User = Depends(current_user)):
    job = Job(**payload.model_dump()); db.add(job); db.commit(); db.refresh(job); return job


@app.patch("/api/jobs/{job_id}/publish", response_model=JobOut)
def publish_job(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    job = db.get(Job, job_id)
    if not job: raise HTTPException(404, "Job not found")
    job.status = "open"; db.commit(); db.refresh(job); return job


@app.post("/api/jobs/{job_id}/applications")
async def add_application(job_id: int, name: Annotated[str, Form()], email: Annotated[str, Form()], resume: UploadFile = File(), db: Session = Depends(get_db), _: User = Depends(current_user)):
    job = db.get(Job, job_id)
    if not job: raise HTTPException(404, "Job not found")
    suffix = Path(resume.filename or "resume").suffix.lower()
    if suffix not in {".pdf", ".docx"}: raise HTTPException(400, "Resume must be PDF or DOCX")
    upload_dir = DATA_DIR / "uploads"; upload_dir.mkdir(exist_ok=True)
    path = upload_dir / f"{token_urlsafe(8)}{suffix}"; path.write_bytes(await resume.read())
    parsed = parse_resume(extract_resume(path)); parsed["name"] = name; parsed["email"] = email
    candidate = Candidate(name=name, email=email, phone=parsed.get("phone", ""), resume_path=str(path), parsed_resume_data=parsed)
    db.add(candidate); db.flush()
    params = job.ranking_params or {}; score, summary = rank_resume(parsed.get("raw_text", ""), job.description, params.get("required_skills", []))
    application = Application(job_id=job.id, candidate_id=candidate.id, match_score=score, ai_ranking_summary=summary)
    db.add(application); db.commit(); db.refresh(application)
    return {"id": application.id, "match_score": score, "summary": summary}


@app.get("/api/jobs/{job_id}/candidates")
def ranked_candidates(job_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    rows = db.scalars(select(Application).where(Application.job_id == job_id).order_by(Application.match_score.desc())).all()
    return [{"application_id": a.id, "name": a.candidate.name, "email": a.candidate.email, "status": a.status, "match_score": a.match_score, "summary": a.ai_ranking_summary, "skills": a.candidate.parsed_resume_data.get("skills", [])} for a in rows]


@app.post("/api/applications/{application_id}/interview")
def invite(application_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    application = db.get(Application, application_id)
    if not application: raise HTTPException(404, "Application not found")
    interview = application.interview or Interview(application_id=application.id, token=token_urlsafe(24), questions=generate_questions(application.job.title, application.job.description))
    application.status = "interview"; db.add(interview); db.commit(); db.refresh(interview)
    return {"token": interview.token, "url": f"http://127.0.0.1:5173/interview/{interview.token}", "questions": interview.questions}


@app.get("/api/interviews/{token}")
def interview_session(token: str, db: Session = Depends(get_db)):
    interview = db.scalar(select(Interview).where(Interview.token == token))
    if not interview: raise HTTPException(404, "Interview not found")
    return {"candidate": interview.application.candidate.name, "job": interview.application.job.title, "questions": interview.questions, "status": interview.status}


@app.post("/api/interviews/{token}/answers")
def submit_answers(token: str, payload: InterviewAnswers, db: Session = Depends(get_db)):
    interview = db.scalar(select(Interview).where(Interview.token == token))
    if not interview: raise HTTPException(404, "Interview not found")
    interview.answers = [a.model_dump() for a in payload.answers]; interview.status = "analyzed"
    report, recommendation, confidence = analyze_answers(interview.answers, interview.application.job.description)
    feedback = interview.feedback or Feedback(interview_id=interview.id, ai_generated_report=report, recommendation=recommendation, confidence_score=confidence)
    feedback.ai_generated_report, feedback.recommendation, feedback.confidence_score = report, recommendation, confidence
    db.add(feedback); db.commit()
    return {"status": "completed"}


@app.get("/api/applications/{application_id}/feedback")
def get_feedback(application_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    application = db.get(Application, application_id)
    if not application or not application.interview or not application.interview.feedback: raise HTTPException(404, "Feedback not available")
    f = application.interview.feedback
    return {"report": f.ai_generated_report, "recommendation": f.recommendation, "confidence_score": f.confidence_score, "answers": application.interview.answers}

