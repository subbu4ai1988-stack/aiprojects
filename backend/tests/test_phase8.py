from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from backend.app.config import settings
from backend.app.integrations import send_email, transcribe_answer
from backend.app.main import app
from backend.app.storage import signed_download_url, storage, verify_download

client = TestClient(app)


def admin_auth() -> dict[str, str]:
    with client:
        response = client.post(
            "/api/auth/login",
            json={"email": "admin@recruitai.local", "password": "recruitai-admin"},
        )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_local_storage_round_trip_and_signed_download():
    reference = storage.put_bytes("phase8/test-video.webm", b"phase-8-video", "video/webm")
    try:
        url = signed_download_url(reference, lifetime_seconds=60)
        response = client.get(url)
        assert response.status_code == 200
        assert response.content == b"phase-8-video"
        assert response.headers["content-type"].startswith("video/webm")

        query = parse_qs(urlparse(url).query)
        assert verify_download(reference, int(query["expires"][0]), query["signature"][0])
        assert not verify_download(reference, 1, query["signature"][0])
    finally:
        assert storage.delete(reference)


def test_local_delivery_and_transcription_adapters():
    delivery = send_email("candidate@example.com", "Interview", "Complete your interview")
    assert delivery.status == "sent"
    assert delivery.provider == "local-outbox"
    assert delivery.attempts == 1

    transcription = transcribe_answer("local-video", "  A clear typed transcript.  ")
    assert transcription.transcript == "A clear typed transcript."
    assert transcription.provider == "local-text"


def test_runtime_summary_is_secret_safe_and_integration_audit_is_admin_only():
    summary = settings.safe_summary()
    assert summary["storage_provider"] == "local"
    assert summary["email_provider"] == "local"
    assert "s3_secret_access_key" not in summary
    assert "smtp_password" not in summary

    assert client.get("/api/admin/integrations").status_code == 401
    response = client.get("/api/admin/integrations", headers=admin_auth())
    assert response.status_code == 200
    assert {"total", "successful", "failed", "by_integration", "recent"} <= response.json().keys()
