import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal
from .models import AITask, Application
from .services import extract_resume, parse_resume, rank_resume
from .storage import storage

logger = logging.getLogger(__name__)


def enqueue_application(db: Session, application_id: int) -> AITask:
    task = AITask(task_type="process_application", payload={"application_id": application_id})
    db.add(task)
    db.flush()
    return task


def _process_application(db: Session, task: AITask) -> dict:
    application_id = int(task.payload["application_id"])
    application = db.get(Application, application_id)
    if not application:
        raise RuntimeError("Application no longer exists")
    candidate = application.candidate
    with storage.materialize(candidate.resume_path) as path:
        parsed = parse_resume(extract_resume(path))
    parsed["name"] = candidate.name
    parsed["email"] = candidate.email
    candidate.phone = parsed.get("phone", "")
    candidate.parsed_resume_data = parsed
    params = application.job.ranking_params or {}
    score, summary = rank_resume(parsed.get("raw_text", ""), application.job.description, params.get("required_skills", []))
    application.match_score = score
    application.ai_ranking_summary = summary
    return {"application_id": application.id, "match_score": score}


def run_once() -> bool:
    with SessionLocal() as db:
        task = db.scalar(
            select(AITask)
            .where(AITask.task_type == "process_application", AITask.status.in_(["queued", "retry"]), AITask.attempts < settings.ai_worker_max_attempts)
            .order_by(AITask.id)
            .with_for_update(skip_locked=True)
        )
        if not task:
            return False
        task.status = "running"
        task.attempts += 1
        task.updated_at = datetime.now(UTC).replace(tzinfo=None)
        task_id = task.id
        db.commit()

    try:
        with SessionLocal() as db:
            task = db.get(AITask, task_id)
            result = _process_application(db, task)
            task.status = "completed"
            task.result = result
            task.error = ""
            task.updated_at = datetime.now(UTC).replace(tzinfo=None)
            db.commit()
        return True
    except Exception as exc:
        logger.exception("AI task %s failed", task_id)
        with SessionLocal() as db:
            task = db.get(AITask, task_id)
            if not task:
                return True
            task.status = "retry" if task.attempts < settings.ai_worker_max_attempts else "failed"
            task.error = f"{type(exc).__name__}: {exc}"[:500]
            task.updated_at = datetime.now(UTC).replace(tzinfo=None)
            db.commit()
        return True
