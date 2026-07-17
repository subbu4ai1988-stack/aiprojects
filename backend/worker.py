import logging
from time import sleep

from backend.app.config import settings
from backend.app.tasks import run_once

logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("recruitai.worker")


def main() -> None:
    logger.info("RecruitAI AI worker started")
    while True:
        if not run_once():
            sleep(settings.ai_worker_poll_seconds)


if __name__ == "__main__":
    main()
