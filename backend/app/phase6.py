from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import AIRequestLog, AITask, Application, User
from .phase4 import has_job_access, require_admin, session_user

router = APIRouter(prefix="/api", tags=["operations"])


@router.get("/health/live")
def liveness():
    return {"status": "ok", "service": "recruitai-api"}


@router.get("/health/ready")
def readiness(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(503, "Database is not ready") from exc
    return {"status": "ready", "database": settings.safe_summary()["database"]}


@router.get("/admin/runtime")
def runtime_configuration(_: User = Depends(require_admin)):
    return settings.safe_summary()


@router.get("/tasks/{task_id}")
def task_status(task_id: int, db: Session = Depends(get_db), user: User = Depends(session_user)):
    task = db.get(AITask, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    application_id = int(task.payload.get("application_id", 0))
    application = db.get(Application, application_id)
    if not application or not has_job_access(db, user, application.job_id):
        raise HTTPException(403, "Task access denied")
    return {"id": task.id, "status": task.status, "attempts": task.attempts, "result": task.result, "error": task.error if task.status == "failed" else ""}

@router.get("/admin/ai/usage")
def ai_usage(days: int = 30, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    days = max(1, min(days, 90))
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
    rows = list(db.scalars(select(AIRequestLog).where(AIRequestLog.created_at >= since).order_by(AIRequestLog.id.desc())))
    return {
        "period_days": days,
        "requests": len(rows),
        "successful": sum(row.status == "success" for row in rows),
        "fallbacks": sum(row.status != "success" for row in rows),
        "input_tokens": sum(row.input_tokens for row in rows),
        "output_tokens": sum(row.output_tokens for row in rows),
        "total_tokens": sum(row.total_tokens for row in rows),
        "average_duration_ms": round(sum(row.duration_ms for row in rows) / len(rows)) if rows else 0,
        "by_operation": {
            operation: sum(row.operation == operation for row in rows)
            for operation in sorted({row.operation for row in rows})
        },
        "recent": [
            {
                "operation": row.operation,
                "status": row.status,
                "model": row.model,
                "duration_ms": row.duration_ms,
                "total_tokens": row.total_tokens,
                "request_id": row.request_id,
                "created_at": row.created_at,
            }
            for row in rows[:20]
        ],
    }
