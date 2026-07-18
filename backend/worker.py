import logging
from time import monotonic, sleep

from backend.app.config import settings
from backend.app.privacy import enforce_retention
from backend.app.tasks import run_once

logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("recruitai.worker")


def main() -> None:
    logger.info("RecruitAI AI worker started")
    last_privacy_sweep = monotonic()
    while True:
        if settings.privacy_auto_delete and monotonic() - last_privacy_sweep >= settings.privacy_sweep_interval_seconds:
            try:
                result = enforce_retention()
                logger.info("Privacy retention sweep completed: %s candidates deleted", result["deleted"])
            except Exception:
                logger.exception("Privacy retention sweep failed")
            last_privacy_sweep = monotonic()
        if not run_once():
            sleep(settings.ai_worker_poll_seconds)


if __name__ == "__main__":
    main()
