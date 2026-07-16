import io
import os

os.environ.setdefault("TESTING", "1")
from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)


def token():
    with client:
        response = client.post("/api/auth/login", json={"email": "recruiter@recruitai.local", "password": "recruitai"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_job_workflow():
    headers = token()
    job = client.post("/api/jobs", headers=headers, json={"title": "Python Engineer", "department": "Engineering", "location": "Remote", "description": "Build scalable Python FastAPI services and PostgreSQL systems.", "ranking_params": {"required_skills": ["Python", "FastAPI"]}})
    assert job.status_code == 200
    job_id = job.json()["id"]
    assert client.patch(f"/api/jobs/{job_id}/publish", headers=headers).json()["status"] == "open"
    resume = b"%PDF-1.4 invalid"
    bad = client.post(f"/api/jobs/{job_id}/applications", headers=headers, data={"name": "Ada", "email": "ada@example.com"}, files={"resume": ("resume.txt", io.BytesIO(b"x"), "text/plain")})
    assert bad.status_code == 400
    assert client.get(f"/api/jobs/{job_id}/candidates", headers=headers).status_code == 200
