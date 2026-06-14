from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from .background_jobs import (
    dispatch_background_job,
    enqueue_background_job,
    recover_stale_background_jobs,
    redispatch_pending_background_jobs,
    run_background_job,
)
from .models import BackgroundJob


class CeleryBackgroundJobTests(TestCase):
    def test_enqueue_dispatches_only_after_transaction_commit(self):
        with patch(
            "institute_admin.background_jobs.dispatch_background_job"
        ) as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                job = enqueue_background_job(BackgroundJob.JobType.NOTICE_NOTIFICATION)

        dispatch.assert_called_once_with(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, BackgroundJob.Status.PENDING)

    @override_settings(BACKGROUND_JOB_SYNC_NOTICE_FALLBACK=False)
    def test_broker_failure_keeps_notice_pending_when_fallback_is_disabled(self):
        job = BackgroundJob.objects.create(
            job_type=BackgroundJob.JobType.NOTICE_NOTIFICATION
        )

        with patch(
            "institute_admin.tasks.process_background_job.delay",
            side_effect=ConnectionError("Redis unavailable"),
        ):
            dispatched = dispatch_background_job(job.pk)

        self.assertFalse(dispatched)
        job.refresh_from_db()
        self.assertEqual(job.status, BackgroundJob.Status.PENDING)

    def test_broker_failure_processes_fee_notification_synchronously(self):
        job = BackgroundJob.objects.create(
            job_type=BackgroundJob.JobType.FEE_NOTIFICATION
        )

        with (
            patch(
                "institute_admin.tasks.process_background_job.delay",
                side_effect=ConnectionError("Redis unavailable"),
            ),
            patch(
                "institute_admin.background_jobs.run_background_job"
            ) as run_job,
        ):
            dispatched = dispatch_background_job(job.pk)

        self.assertTrue(dispatched)
        run_job.assert_called_once_with(job.pk)

    @override_settings(BACKGROUND_JOB_SYNC_NOTICE_FALLBACK=True)
    def test_broker_failure_processes_notice_notification_synchronously(self):
        job = BackgroundJob.objects.create(
            job_type=BackgroundJob.JobType.NOTICE_NOTIFICATION
        )

        with (
            patch(
                "institute_admin.tasks.process_background_job.delay",
                side_effect=ConnectionError("Redis unavailable"),
            ),
            patch(
                "institute_admin.background_jobs.run_background_job"
            ) as run_job,
        ):
            dispatched = dispatch_background_job(job.pk)

        self.assertTrue(dispatched)
        run_job.assert_called_once_with(job.pk)

    def test_run_background_job_updates_durable_status(self):
        job = BackgroundJob.objects.create(
            job_type=BackgroundJob.JobType.NOTICE_NOTIFICATION
        )

        with patch(
            "institute_admin.background_jobs.execute_background_job",
            return_value={"notification_count": 4},
        ):
            completed = run_background_job(job.pk)

        self.assertEqual(completed.status, BackgroundJob.Status.COMPLETED)
        self.assertEqual(completed.attempts, 1)
        self.assertEqual(completed.result, {"notification_count": 4})
        self.assertIsNotNone(completed.completed_at)

    @override_settings(BACKGROUND_JOB_MAX_RETRIES=1, BACKGROUND_JOB_RETRY_DELAY=0)
    def test_celery_task_retries_then_marks_job_failed(self):
        from .tasks import process_background_job

        job = BackgroundJob.objects.create(
            job_type=BackgroundJob.JobType.NOTICE_NOTIFICATION
        )

        with patch(
            "institute_admin.background_jobs.execute_background_job",
            side_effect=ConnectionError("Temporary provider failure"),
        ):
            with self.assertRaises(ConnectionError):
                process_background_job.apply(args=[job.pk], throw=False)

        job.refresh_from_db()
        self.assertEqual(job.status, BackgroundJob.Status.FAILED)
        self.assertEqual(job.attempts, 2)
        self.assertIn("Temporary provider failure", job.error_message)

    @override_settings(BACKGROUND_JOB_STALE_MINUTES=10)
    def test_stale_running_job_is_returned_to_pending(self):
        job = BackgroundJob.objects.create(
            job_type=BackgroundJob.JobType.STUDENT_IMPORT,
            status=BackgroundJob.Status.RUNNING,
            started_at=timezone.now() - timedelta(minutes=11),
            attempts=1,
        )

        recovered_ids = recover_stale_background_jobs(dispatch=False)

        self.assertEqual(recovered_ids, [job.pk])
        job.refresh_from_db()
        self.assertEqual(job.status, BackgroundJob.Status.PENDING)
        self.assertIsNone(job.started_at)
        self.assertIn("Recovered", job.error_message)

    @override_settings(BACKGROUND_JOB_PENDING_REDISPATCH_MINUTES=5)
    def test_old_pending_jobs_are_redispatched(self):
        job = BackgroundJob.objects.create(
            job_type=BackgroundJob.JobType.FEE_NOTIFICATION
        )
        BackgroundJob.objects.filter(pk=job.pk).update(
            created_at=timezone.now() - timedelta(minutes=6)
        )

        with patch(
            "institute_admin.background_jobs.dispatch_background_job"
        ) as dispatch:
            redispatched_ids = redispatch_pending_background_jobs()

        self.assertEqual(redispatched_ids, [job.pk])
        dispatch.assert_called_once_with(job.pk)
