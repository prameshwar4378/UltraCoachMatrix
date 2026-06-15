from django.core.management.base import BaseCommand

from institute_admin.background_jobs import enqueue_due_notice_notifications


class Command(BaseCommand):
    help = "Queue push-notification jobs for notices whose publish time is due."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Maximum due notices to queue in this run.",
        )

    def handle(self, *args, **options):
        jobs = enqueue_due_notice_notifications(limit=options["limit"])
        self.stdout.write(
            self.style.SUCCESS(
                f"Queued {len(jobs)} scheduled notice notification job(s)."
            )
        )
