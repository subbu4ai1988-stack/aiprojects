import pytest
from fastapi.testclient import TestClient

from backend.app.ai_runtime import AIGuard, AIRuntimeLimit
from backend.app.config import DEVELOPMENT_SECRET, Settings
from backend.app.database import SessionLocal
from backend.app.models import AITask, Application, Candidate, Job
from backend.app.main import app

client = TestClient(app)


def admin_headers():
    with client:
        response = client.post("/api/auth/login", json={"email": "admin@recruitai.local", "password": "recruitai-admin"})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_production_configuration_rejects_development_secret(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET", DEVELOPMENT_SECRET)
    monkeypatch.setenv("BOOTSTRAP_DEMO_USERS", "false")
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings.from_env()


def test_ai_guard_rate_limit_and_circuit_breaker():
    rate_guard = AIGuard(max_calls=1, failure_threshold=3, reset_seconds=60)
    rate_guard.before_call()
    with pytest.raises(AIRuntimeLimit, match="rate limit"):
        rate_guard.before_call()

    circuit_guard = AIGuard(max_calls=10, failure_threshold=2, reset_seconds=60)
    circuit_guard.failure()
    circuit_guard.failure()
    with pytest.raises(AIRuntimeLimit, match="circuit breaker"):
        circuit_guard.before_call()


def test_operational_endpoints_and_security_headers():
    live = client.get("/api/health/live")
    ready = client.get("/api/health/ready")
    assert live.status_code == 200
    assert ready.status_code == 200
    assert live.headers["x-content-type-options"] == "nosniff"
    assert live.headers["x-request-id"]

    usage = client.get("/api/admin/ai/usage", headers=admin_headers())
    runtime = client.get("/api/admin/runtime", headers=admin_headers())
    assert usage.status_code == 200
    assert "total_tokens" in usage.json()
    assert runtime.status_code == 200
    assert "jwt_secret" not in runtime.json()

def test_durable_ai_task_status():
    headers = admin_headers()
    with SessionLocal() as db:
        job = Job(title="Queued role", department="Engineering", location="Remote", description="A queued application processing test role.")
        candidate = Candidate(name="Queue Candidate", email="queue@example.com", parsed_resume_data={})
        db.add_all([job, candidate])
        db.flush()
        application = Application(job_id=job.id, candidate_id=candidate.id)
        db.add(application)
        db.flush()
        task = AITask(task_type="process_application", payload={"application_id": application.id})
        db.add(task)
        db.commit()
        task_id = task.id

    response = client.get(f"/api/tasks/{task_id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "queued"

    with SessionLocal() as db:
        task = db.get(AITask, task_id)
        application = db.get(Application, int(task.payload["application_id"]))
        candidate = application.candidate
        job = application.job
        db.delete(task)
        db.delete(application)
        db.delete(candidate)
        db.delete(job)
        db.commit()
