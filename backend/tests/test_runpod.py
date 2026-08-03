import json
from types import SimpleNamespace

import httpx
import pytest

from backend.app import integrations
from backend.app.runpod_client import RunpodClient, RunpodError
from runpod_worker.handler import _assert_safe_media_url, handler


def test_runpod_client_sends_authenticated_transcription_job():
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret-key"
        assert request.url.params["wait"] == "120000"
        body = json.loads(request.content)
        assert body["input"]["operation"] == "transcribe"
        assert body["input"]["media_url"] == "https://recruit.example/api/storage/download?signed=yes"
        return httpx.Response(
            200,
            json={
                "id": "job-1",
                "status": "COMPLETED",
                "output": {
                    "status": "completed",
                    "provider": "runpod-faster-whisper",
                    "text": "A GPU transcript.",
                },
            },
        )

    client = RunpodClient(
        "secret-key",
        "endpoint-1",
        transport=httpx.MockTransport(respond),
    )
    output = client.transcribe("https://recruit.example/api/storage/download?signed=yes", "hint")
    assert output["text"] == "A GPU transcript."


def test_runpod_client_rejects_incomplete_job():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"id": "job-2", "status": "TIMED_OUT"})
    )
    client = RunpodClient("secret-key", "endpoint-1", transport=transport)
    with pytest.raises(RunpodError, match="TIMED_OUT"):
        client.run_sync({"operation": "health"})


def test_transcription_adapter_uses_signed_public_media_url(monkeypatch):
    class FakeRunpodClient:
        def __init__(self, api_key, endpoint_id, **options):
            assert api_key == "secret-key"
            assert endpoint_id == "endpoint-1"
            assert options["wait_ms"] == 120_000

        def transcribe(self, media_url, transcript_hint, language):
            assert media_url == "https://recruit.example/api/storage/download?signed=yes"
            assert transcript_hint == "typed fallback"
            assert language == "en"
            return {"status": "completed", "provider": "runpod-faster-whisper", "text": "GPU result"}

    monkeypatch.setattr(
        integrations,
        "settings",
        SimpleNamespace(
            transcription_provider="runpod",
            public_app_url="https://recruit.example",
            runpod_api_key="secret-key",
            runpod_endpoint_id="endpoint-1",
            runpod_base_url="https://api.runpod.ai/v2",
            runpod_timeout_seconds=150,
            runpod_wait_ms=120_000,
            runpod_transcription_language="en",
        ),
    )
    monkeypatch.setattr(integrations, "RunpodClient", FakeRunpodClient)
    monkeypatch.setattr(
        integrations,
        "signed_download_url",
        lambda reference: "/api/storage/download?signed=yes",
    )

    result = integrations.transcribe_answer("s3://recruitai/interview.webm", " typed fallback ")
    assert result.status == "completed"
    assert result.provider == "runpod-faster-whisper"
    assert result.transcript == "GPU result"

def test_runpod_worker_health_and_stub_contract(monkeypatch):
    monkeypatch.setenv("WORKER_MODE", "stub")
    health = handler({"input": {"operation": "health"}})
    assert health["status"] == "ready"
    assert health["worker_mode"] == "stub"

    result = handler(
        {
            "input": {
                "operation": "transcribe",
                "media_url": "https://recruit.example/signed-media",
                "transcript_hint": "Local test transcript",
            }
        }
    )
    assert result["status"] == "completed"
    assert result["provider"] == "runpod-stub"
    assert result["text"] == "Local test transcript"


def test_runpod_worker_blocks_private_media_urls(monkeypatch):
    monkeypatch.delenv("ALLOW_INSECURE_MEDIA_URLS", raising=False)
    monkeypatch.delenv("ALLOW_PRIVATE_MEDIA_URLS", raising=False)
    with pytest.raises(ValueError, match="HTTPS"):
        _assert_safe_media_url("http://127.0.0.1/private.webm")
    with pytest.raises(ValueError, match="private host"):
        _assert_safe_media_url("https://127.0.0.1/private.webm")


def test_runpod_worker_rejects_unknown_operation():
    with pytest.raises(ValueError, match="health or transcribe"):
        handler({"input": {"operation": "unknown"}})
