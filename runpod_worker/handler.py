"""Runpod Serverless handler for RecruitAI media transcription."""

from __future__ import annotations

import ipaddress
import os
import socket
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

_MODEL: Any | None = None


def _boolean(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


def _assert_safe_media_url(media_url: str) -> None:
    parsed = urlparse(media_url)
    allow_insecure = _boolean("ALLOW_INSECURE_MEDIA_URLS")
    allowed_schemes = {"https"} | ({"http"} if allow_insecure else set())
    if parsed.scheme not in allowed_schemes or not parsed.hostname:
        raise ValueError("media_url must use HTTPS and include a hostname")
    if parsed.username or parsed.password:
        raise ValueError("media_url must not contain credentials")
    if _boolean("ALLOW_PRIVATE_MEDIA_URLS"):
        return

    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValueError("media_url must not target a private host")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, parsed.port or 443)}
    except socket.gaierror as exc:
        raise ValueError("media_url hostname could not be resolved") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("media_url must not target a private host")


def _download_media(media_url: str) -> Path:
    _assert_safe_media_url(media_url)
    max_bytes = int(os.getenv("MAX_MEDIA_BYTES", str(25 * 1024 * 1024)))
    timeout = float(os.getenv("MEDIA_DOWNLOAD_TIMEOUT_SECONDS", "60"))
    suffix = Path(urlparse(media_url).path).suffix[:12]
    handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    path = Path(handle.name)
    size = 0
    try:
        with handle, httpx.stream("GET", media_url, timeout=timeout, follow_redirects=False) as response:
            response.raise_for_status()
            if 300 <= response.status_code < 400:
                raise ValueError("media_url redirects are not accepted")
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError(f"media file exceeds {max_bytes} bytes")
                handle.write(chunk)
        if size == 0:
            raise ValueError("media file is empty")
        return path
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _get_model():
    global _MODEL
    if _MODEL is None:
        from faster_whisper import WhisperModel

        _MODEL = WhisperModel(
            os.getenv("WHISPER_MODEL", "small"),
            device=os.getenv("WHISPER_DEVICE", "cuda"),
            compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "float16"),
        )
    return _MODEL


def _transcribe(job_input: dict[str, Any]) -> dict[str, Any]:
    media_url = str(job_input.get("media_url", "")).strip()
    transcript_hint = str(job_input.get("transcript_hint", "")).strip()
    if not media_url:
        raise ValueError("media_url is required for transcription")

    if os.getenv("WORKER_MODE", "live").strip().lower() == "stub":
        return {
            "operation": "transcribe",
            "status": "completed",
            "provider": "runpod-stub",
            "text": transcript_hint,
            "language": job_input.get("language"),
            "language_probability": None,
            "duration_seconds": 0,
            "segments": [],
        }

    path = _download_media(media_url)
    try:
        segments, info = _get_model().transcribe(
            str(path),
            language=job_input.get("language") or None,
            vad_filter=True,
            beam_size=int(os.getenv("WHISPER_BEAM_SIZE", "5")),
        )
        rows = [
            {"start": round(segment.start, 3), "end": round(segment.end, 3), "text": segment.text.strip()}
            for segment in segments
        ]
        text = " ".join(row["text"] for row in rows if row["text"]).strip() or transcript_hint
        return {
            "operation": "transcribe",
            "status": "completed",
            "provider": "runpod-faster-whisper",
            "text": text,
            "language": getattr(info, "language", None),
            "language_probability": getattr(info, "language_probability", None),
            "duration_seconds": getattr(info, "duration", None),
            "segments": rows,
        }
    finally:
        path.unlink(missing_ok=True)


def handler(job: dict[str, Any]) -> dict[str, Any]:
    job_input = job.get("input")
    if not isinstance(job_input, dict):
        raise ValueError("job.input must be an object")
    operation = str(job_input.get("operation", "")).strip().lower()
    if operation == "health":
        return {
            "operation": "health",
            "status": "ready",
            "worker_mode": os.getenv("WORKER_MODE", "live").strip().lower(),
            "model": os.getenv("WHISPER_MODEL", "small"),
        }
    if operation == "transcribe":
        return _transcribe(job_input)
    raise ValueError("operation must be health or transcribe")


if __name__ == "__main__":
    import runpod

    runpod.serverless.start({"handler": handler})
