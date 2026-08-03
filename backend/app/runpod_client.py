"""Minimal Runpod Serverless queue client used by RecruitAI adapters."""

from __future__ import annotations

from typing import Any

import httpx


class RunpodError(RuntimeError):
    """Raised when a Runpod job cannot produce a usable result."""


class RunpodClient:
    def __init__(
        self,
        api_key: str,
        endpoint_id: str,
        *,
        base_url: str = "https://api.runpod.ai/v2",
        timeout_seconds: float = 120,
        wait_ms: int = 120_000,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.endpoint_id = endpoint_id
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.wait_ms = min(max(wait_ms, 1_000), 300_000)
        self.transport = transport

    def run_sync(self, job_input: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/{self.endpoint_id}/runsync"
        try:
            with httpx.Client(timeout=self.timeout_seconds, transport=self.transport) as client:
                response = client.post(
                    url,
                    params={"wait": self.wait_ms},
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"input": job_input},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RunpodError(f"Runpod request failed: {exc}") from exc

        if not isinstance(payload, dict):
            raise RunpodError("Runpod returned an invalid response")
        status = str(payload.get("status", "COMPLETED")).upper()
        if status != "COMPLETED":
            job_id = payload.get("id", "unknown")
            error = payload.get("error") or f"job status is {status}"
            raise RunpodError(f"Runpod job {job_id} did not complete: {error}")
        output = payload.get("output", payload)
        if not isinstance(output, dict):
            raise RunpodError("Runpod job output is invalid")
        if output.get("error"):
            raise RunpodError(f"Runpod worker failed: {output['error']}")
        return output

    def transcribe(self, media_url: str, transcript_hint: str = "", language: str = "") -> dict[str, Any]:
        output = self.run_sync(
            {
                "operation": "transcribe",
                "media_url": media_url,
                "transcript_hint": transcript_hint,
                "language": language or None,
            }
        )
        if output.get("status") != "completed":
            raise RunpodError("Runpod transcription was not completed")
        if not isinstance(output.get("text"), str):
            raise RunpodError("Runpod transcription did not return text")
        return output
