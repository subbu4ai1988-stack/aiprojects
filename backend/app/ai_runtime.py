import logging
from collections import deque
from datetime import UTC, datetime
from threading import Lock
from time import monotonic
from typing import Callable, TypeVar

from sqlalchemy import func, select

from .config import settings
from .database import SessionLocal
from .models import AIRequestLog

logger = logging.getLogger(__name__)
T = TypeVar("T")


class AIRuntimeLimit(RuntimeError):
    pass


class AIGuard:
    def __init__(self, max_calls: int, failure_threshold: int, reset_seconds: int) -> None:
        self.max_calls = max_calls
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self.calls: deque[float] = deque()
        self.failures = 0
        self.opened_at: float | None = None
        self.lock = Lock()

    def before_call(self) -> None:
        now = monotonic()
        with self.lock:
            while self.calls and now - self.calls[0] >= 60:
                self.calls.popleft()
            if self.opened_at is not None:
                if now - self.opened_at < self.reset_seconds:
                    raise AIRuntimeLimit("AI circuit breaker is open")
                self.opened_at = None
                self.failures = 0
            if len(self.calls) >= self.max_calls:
                raise AIRuntimeLimit("AI application rate limit reached")
            self.calls.append(now)

    def success(self) -> None:
        with self.lock:
            self.failures = 0
            self.opened_at = None

    def failure(self) -> None:
        with self.lock:
            self.failures += 1
            if self.failures >= self.failure_threshold:
                self.opened_at = monotonic()


guard = AIGuard(
    settings.ai_max_calls_per_minute,
    settings.ai_circuit_failure_threshold,
    settings.ai_circuit_reset_seconds,
)


def _monthly_tokens() -> int:
    if settings.ai_monthly_token_budget <= 0:
        return 0
    start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)
    with SessionLocal() as db:
        return int(db.scalar(select(func.coalesce(func.sum(AIRequestLog.total_tokens), 0)).where(AIRequestLog.created_at >= start)) or 0)


def _record(operation: str, provider, status: str, duration_ms: int, input_chars: int, error: str = "") -> None:
    usage = provider.usage_snapshot() if hasattr(provider, "usage_snapshot") else {}
    row = AIRequestLog(
        operation=operation,
        provider="openai",
        model=getattr(provider, "model", "unknown"),
        status=status,
        duration_ms=duration_ms,
        input_chars=input_chars,
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
        total_tokens=int(usage.get("total_tokens", 0)),
        request_id=str(usage.get("request_id", ""))[:160],
        error=error[:500],
    )
    try:
        with SessionLocal() as db:
            db.add(row)
            db.commit()
    except Exception:
        logger.exception("Unable to persist AI telemetry")


def run_ai_operation(operation: str, provider, callback: Callable[[], T], input_chars: int) -> T:
    started = monotonic()
    try:
        guard.before_call()
        if settings.ai_monthly_token_budget and _monthly_tokens() >= settings.ai_monthly_token_budget:
            raise AIRuntimeLimit("AI monthly token budget reached")
        result = callback()
        guard.success()
        _record(operation, provider, "success", round((monotonic() - started) * 1000), input_chars)
        return result
    except Exception as exc:
        if not isinstance(exc, AIRuntimeLimit):
            guard.failure()
        _record(operation, provider, "limited" if isinstance(exc, AIRuntimeLimit) else "error", round((monotonic() - started) * 1000), input_chars, type(exc).__name__)
        raise
