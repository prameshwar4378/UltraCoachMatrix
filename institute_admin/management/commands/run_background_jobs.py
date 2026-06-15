import logging
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from institute_admin.background_jobs import (
    enqueue_due_notice_notifications,
    run_next_background_job,
)


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run durable background jobs for imports and notification fan-out."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Process at most one job and exit.")
        parser.add_argument("--sleep", type=float, default=2.0, help="Idle polling interval in seconds.")

    def handle(self, *args, **options):
        while True:
            close_old_connections()
            try:
                enqueue_due_notice_notifications()
                job = run_next_background_job()
            except Exception:
                logger.exception("Background job failed.")
                job = True
            finally:
                close_old_connections()

            if options["once"]:
                return
            if not job:
                time.sleep(max(options["sleep"], 0.2))
