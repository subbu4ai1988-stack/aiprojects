import hashlib
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import SessionLocal, get_db
from .models import AITask, Application, Candidate, EmailDelivery, Feedback, Interview, User
from .phase4 import require_admin
from .privacy_models import CandidatePrivacy, PrivacyAuditLog
from .storage import signed_download_url, storage

router = APIRouter(prefix="/api/admin/privacy", tags=["privacy"])


class PrivacyUpdate(BaseModel):
    consent_status: str | None = None
    legal_hold: bool | None = None
    retention_days: int | None = Field(default=None, ge=1, le=3650)


class DeleteRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


class RetentionRun(BaseModel):
    dry_run: bool = True


def now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def subject_ref(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def ensure_candidate_privacy(db: Session, candidate_id: int, consent_granted: bool = True) -> CandidatePrivacy:
    row = db.scalar(select(CandidatePrivacy).where(CandidatePrivacy.candidate_id == candidate_id))
    if row:
        return row
    now = now_utc()
    row = CandidatePrivacy(
        candidate_id=candidate_id,
        consent_status="granted" if consent_granted else "withdrawn",
        consent_at=now if consent_granted else None,
        retention_expires_at=now + timedelta(days=settings.candidate_retention_days),
    )
    db.add(row)
    db.flush()
    return row


def backfill_candidate_privacy(db: Session) -> int:
    existing = set(db.scalars(select(CandidatePrivacy.candidate_id)))
    candidate_ids = list(db.scalars(select(Candidate.id)))
    for candidate_id in candidate_ids:
        if candidate_id not in existing:
            ensure_candidate_privacy(db, candidate_id)
    return len(candidate_ids) - len(existing.intersection(candidate_ids))


def audit(db: Session, action: str, email: str, actor_email: str = "system", **details) -> None:
    db.add(PrivacyAuditLog(actor_email=actor_email, action=action, subject_ref=subject_ref(email), details=details))



def _export_answers(answers: list) -> list:
    exported = []
    for answer in answers or []:
        item = dict(answer)
        reference = item.get("video_ref") or item.get("video_url", "")
        if reference:
            item["video_url"] = signed_download_url(reference)
        exported.append(item)
    return exported

def _candidate_export(db: Session, candidate: Candidate) -> dict:
    applications = list(db.scalars(select(Application).where(Application.candidate_id == candidate.id)))
    privacy = db.scalar(select(CandidatePrivacy).where(CandidatePrivacy.candidate_id == candidate.id))
    return {
        "exported_at": now_utc(),
        "candidate": {
            "id": candidate.id,
            "name": candidate.name,
            "email": candidate.email,
            "phone": candidate.phone,
            "parsed_resume_data": candidate.parsed_resume_data,
            "resume_download_url": signed_download_url(candidate.resume_path) if candidate.resume_path else "",
        },
        "privacy": {
            "consent_status": privacy.consent_status if privacy else "unknown",
            "legal_basis": privacy.legal_basis if privacy else "unknown",
            "legal_hold": privacy.legal_hold if privacy else False,
            "consent_at": privacy.consent_at if privacy else None,
            "retention_expires_at": privacy.retention_expires_at if privacy else None,
        },
        "applications": [
            {
                "id": application.id,
                "job": {"id": application.job.id, "title": application.job.title},
                "status": application.status,
                "match_score": application.match_score,
                "ranking_summary": application.ai_ranking_summary,
                "interview": {
                    "status": application.interview.status,
                    "questions": application.interview.questions,
                    "answers": _export_answers(application.interview.answers),
                    "feedback": {
                        "report": application.interview.feedback.ai_generated_report,
                        "recommendation": application.interview.feedback.recommendation,
                        "confidence_score": application.interview.feedback.confidence_score,
                    } if application.interview and application.interview.feedback else None,
                } if application.interview else None,
                "communications": [
                    {"recipient": delivery.recipient, "subject": delivery.subject, "status": delivery.status, "provider": delivery.provider, "attempts": delivery.attempts, "error": delivery.error, "sent_at": delivery.sent_at}
                    for delivery in db.scalars(select(EmailDelivery).where(EmailDelivery.application_id == application.id))
                ],
            }
            for application in applications
        ],
    }


def delete_candidate_data(db: Session, candidate: Candidate, actor_email: str, reason: str, action: str = "candidate_delete") -> dict:
    email = candidate.email
    applications = list(db.scalars(select(Application).where(Application.candidate_id == candidate.id)))
    application_ids = {application.id for application in applications}
    files_removed = int(storage.delete(candidate.resume_path)) if candidate.resume_path else 0
    for task in db.scalars(select(AITask).where(AITask.task_type == "process_application")):
        if int((task.payload or {}).get("application_id", 0)) in application_ids:
            db.delete(task)
    for application in applications:
        for delivery in db.scalars(select(EmailDelivery).where(EmailDelivery.application_id == application.id)):
            db.delete(delivery)
        interview = application.interview
        if interview:
            for answer in interview.answers or []:
                media_reference = answer.get("video_ref") or answer.get("video_url", "")
                if media_reference:
                    files_removed += int(storage.delete(media_reference))
            if interview.feedback:
                db.delete(interview.feedback)
            db.delete(interview)
        db.delete(application)
    privacy = db.scalar(select(CandidatePrivacy).where(CandidatePrivacy.candidate_id == candidate.id))
    if privacy:
        db.delete(privacy)
    candidate_id = candidate.id
    db.delete(candidate)
    audit(db, action, email, actor_email, candidate_id=candidate_id, reason=reason, applications=len(applications), files_removed=files_removed)
    return {"candidate_id": candidate_id, "applications_deleted": len(applications), "files_removed": files_removed}


def due_candidates(db: Session) -> list[Candidate]:
    now = now_utc()
    return list(db.scalars(
        select(Candidate)
        .join(CandidatePrivacy, CandidatePrivacy.candidate_id == Candidate.id)
        .where(CandidatePrivacy.retention_expires_at <= now, CandidatePrivacy.legal_hold.is_(False))
        .order_by(CandidatePrivacy.retention_expires_at)
    ))


def enforce_retention(actor_email: str = "system") -> dict:
    with SessionLocal() as db:
        backfill_candidate_privacy(db)
        candidates = due_candidates(db)
        results = [delete_candidate_data(db, candidate, actor_email, "retention period expired", "retention_delete") for candidate in candidates]
        db.commit()
        return {"deleted": len(results), "results": results}


@router.get("/summary")
def privacy_summary(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    backfill_candidate_privacy(db)
    db.commit()
    now = now_utc()
    rows = list(db.scalars(select(CandidatePrivacy)))
    open_candidates = len(rows)
    return {
        "retention_days": settings.candidate_retention_days,
        "automatic_deletion": settings.privacy_auto_delete,
        "total_candidates": open_candidates,
        "consented": sum(row.consent_status == "granted" for row in rows),
        "legal_holds": sum(row.legal_hold for row in rows),
        "overdue": sum(row.retention_expires_at <= now and not row.legal_hold for row in rows),
        "expiring_soon": sum(now < row.retention_expires_at <= now + timedelta(days=30) and not row.legal_hold for row in rows),
    }


@router.get("/candidates")
def privacy_candidates(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    backfill_candidate_privacy(db)
    db.commit()
    now = now_utc()
    rows = db.execute(
        select(Candidate, CandidatePrivacy)
        .join(CandidatePrivacy, CandidatePrivacy.candidate_id == Candidate.id)
        .order_by(CandidatePrivacy.retention_expires_at)
    ).all()
    return [
        {
            "candidate_id": candidate.id,
            "name": candidate.name,
            "email": candidate.email,
            "consent_status": privacy.consent_status,
            "legal_basis": privacy.legal_basis,
            "legal_hold": privacy.legal_hold,
            "consent_at": privacy.consent_at,
            "retention_expires_at": privacy.retention_expires_at,
            "days_remaining": (privacy.retention_expires_at.date() - now.date()).days,
        }
        for candidate, privacy in rows
    ]


@router.put("/candidates/{candidate_id}")
def update_privacy(candidate_id: int, payload: PrivacyUpdate, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    candidate = db.get(Candidate, candidate_id)
    if not candidate:
        raise HTTPException(404, "Candidate not found")
    privacy = ensure_candidate_privacy(db, candidate_id)
    changes = payload.model_dump(exclude_none=True)
    if payload.consent_status is not None:
        if payload.consent_status not in {"granted", "withdrawn"}:
            raise HTTPException(400, "Unsupported consent status")
        privacy.consent_status = payload.consent_status
        privacy.consent_at = now_utc() if payload.consent_status == "granted" else privacy.consent_at
    if payload.legal_hold is not None:
        privacy.legal_hold = payload.legal_hold
    if payload.retention_days is not None:
        privacy.retention_expires_at = now_utc() + timedelta(days=payload.retention_days)
    privacy.updated_at = now_utc()
    audit(db, "privacy_update", candidate.email, actor.email, candidate_id=candidate.id, changes=changes)
    db.commit()
    return {"candidate_id": candidate.id, **changes}


@router.post("/candidates/{candidate_id}/export")
def export_candidate(candidate_id: int, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    candidate = db.get(Candidate, candidate_id)
    if not candidate:
        raise HTTPException(404, "Candidate not found")
    package = _candidate_export(db, candidate)
    audit(db, "candidate_export", candidate.email, actor.email, candidate_id=candidate.id)
    db.commit()
    return package


@router.delete("/candidates/{candidate_id}")
def delete_candidate(candidate_id: int, payload: DeleteRequest, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    candidate = db.get(Candidate, candidate_id)
    if not candidate:
        raise HTTPException(404, "Candidate not found")
    privacy = ensure_candidate_privacy(db, candidate_id)
    if privacy.legal_hold:
        raise HTTPException(409, "Remove the legal hold before deletion")
    result = delete_candidate_data(db, candidate, actor.email, payload.reason)
    db.commit()
    return result


@router.post("/retention/run")
def run_retention(payload: RetentionRun, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    backfill_candidate_privacy(db)
    candidates = due_candidates(db)
    if payload.dry_run:
        db.rollback()
        return {"dry_run": True, "eligible": len(candidates), "candidate_ids": [candidate.id for candidate in candidates]}
    results = [delete_candidate_data(db, candidate, actor.email, "retention period expired", "retention_delete") for candidate in candidates]
    db.commit()
    return {"dry_run": False, "deleted": len(results), "results": results}


@router.get("/audit")
def privacy_audit(limit: int = 50, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    limit = max(1, min(limit, 200))
    rows = db.scalars(select(PrivacyAuditLog).order_by(PrivacyAuditLog.id.desc()).limit(limit))
    return [
        {"id": row.id, "actor_email": row.actor_email, "action": row.action, "subject_ref": row.subject_ref[:12], "details": row.details, "created_at": row.created_at}
        for row in rows
    ]
