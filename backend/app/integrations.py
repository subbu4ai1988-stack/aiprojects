import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from sqlalchemy.orm import Session

from .config import settings
from .integration_models import IntegrationEvent
from .runpod_client import RunpodClient, RunpodError
from .storage import signed_download_url


@dataclass(frozen=True)
class DeliveryResult:
    status: str
    provider: str
    attempts: int
    error: str = ""


@dataclass(frozen=True)
class TranscriptionResult:
    transcript: str
    provider: str
    status: str = "completed"
    error: str = ""


def record_integration(
    db: Session,
    integration: str,
    operation: str,
    provider: str,
    status: str,
    *,
    reference: str = "",
    attempts: int = 1,
    error: str = "",
    details: dict | None = None,
) -> IntegrationEvent:
    event = IntegrationEvent(
        integration=integration,
        operation=operation,
        provider=provider,
        status=status,
        reference=reference,
        attempts=attempts,
        error=error[:500],
        details=details or {},
    )
    db.add(event)
    return event


def send_email(recipient: str, subject: str, body: str) -> DeliveryResult:
    if settings.email_provider == "local":
        return DeliveryResult(status="sent", provider="local-outbox", attempts=1)

    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    last_error = ""
    for attempt in range(1, settings.smtp_max_attempts + 1):
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
                if settings.smtp_use_tls:
                    smtp.starttls()
                if settings.smtp_username:
                    smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(message)
            return DeliveryResult(status="sent", provider="smtp", attempts=attempt)
        except (OSError, smtplib.SMTPException) as exc:
            last_error = str(exc)
    return DeliveryResult(
        status="failed",
        provider="smtp",
        attempts=settings.smtp_max_attempts,
        error=last_error,
    )


def transcribe_answer(video_reference: str, supplied_text: str) -> TranscriptionResult:
    transcript_hint = supplied_text.strip()
    if settings.transcription_provider == "local":
        return TranscriptionResult(
            transcript=transcript_hint,
            provider="local-text",
            status="completed",
        )

    if not video_reference:
        return TranscriptionResult(
            transcript=transcript_hint,
            provider="runpod-faster-whisper",
            status="failed",
            error="No interview media reference was supplied",
        )

    media_url = f"{settings.public_app_url}{signed_download_url(video_reference)}"
    client = RunpodClient(
        settings.runpod_api_key,
        settings.runpod_endpoint_id,
        base_url=settings.runpod_base_url,
        timeout_seconds=settings.runpod_timeout_seconds,
        wait_ms=settings.runpod_wait_ms,
    )
    try:
        output = client.transcribe(
            media_url,
            transcript_hint,
            settings.runpod_transcription_language,
        )
        return TranscriptionResult(
            transcript=output["text"].strip() or transcript_hint,
            provider=str(output.get("provider", "runpod-faster-whisper")),
            status="completed",
        )
    except RunpodError as exc:
        return TranscriptionResult(
            transcript=transcript_hint,
            provider="runpod-faster-whisper",
            status="failed",
            error=str(exc),
        )
