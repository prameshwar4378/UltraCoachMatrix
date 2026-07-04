from datetime import timedelta
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from accountant.models import FeeCategory, FeeInvoice, Payment
from student_parent.models import StudentAcademicSession, StudentProfile
from .background_jobs import (
    dispatch_background_job,
    enqueue_background_job,
    enqueue_due_notice_notifications,
    execute_background_job,
    recover_stale_background_jobs,
    redispatch_pending_background_jobs,
    run_background_job,
)
from .models import AcademicYear, BackgroundJob, Notice
from super_admin.models import Institute


class CeleryBackgroundJobTests(TestCase):
    def setUp(self):
        self.institute = Institute.objects.create(
            name="Scheduled Notice Institute",
            code="scheduled-notice",
        )

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

    def test_active_payment_creation_queues_fee_notification_once(self):
        user = User.objects.create_user(username="fee-student")
        student = StudentProfile.objects.create(
            institute=self.institute,
            user=user,
            admission_number="FEE-001",
        )
        academic_year = AcademicYear.objects.create(
            institute=self.institute,
            name="2026-27",
            start_date=date(2026, 4, 1),
            end_date=date(2027, 3, 31),
        )
        academic_session = StudentAcademicSession.objects.create(
            institute=self.institute,
            student=student,
            academic_year=academic_year,
            admission_number="FEE-001",
        )
        category = FeeCategory.objects.create(
            institute=self.institute,
            academic_year=academic_year,
            name="Tuition",
            default_amount=Decimal("1000.00"),
        )
        invoice = FeeInvoice.objects.create(
            institute=self.institute,
            student=student,
            academic_session=academic_session,
            category=category,
            title="Term fees",
            amount=Decimal("1000.00"),
            due_date=date(2026, 6, 30),
        )

        with (
            patch("institute_admin.background_jobs.dispatch_background_job") as dispatch,
            self.captureOnCommitCallbacks(execute=True),
        ):
            payment = Payment.objects.create(
                invoice=invoice,
                amount=Decimal("500.00"),
                paid_on=date(2026, 5, 1),
                receipt_number="RCP-FEE-001",
            )
            from student_parent.notifications import enqueue_fee_paid_notification

            existing_job = enqueue_fee_paid_notification(payment)

        jobs = BackgroundJob.objects.filter(
            job_type=BackgroundJob.JobType.FEE_NOTIFICATION,
            payload__payment_id=payment.pk,
        )
        self.assertEqual(jobs.count(), 1)
        self.assertEqual(existing_job.pk, jobs.get().pk)
        dispatch.assert_called_once_with(jobs.get().pk)

    def test_broker_failure_processes_notice_notification_synchronously_by_default(self):
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

    def test_future_notice_is_queued_once_when_publish_time_arrives(self):
        notice = Notice.objects.create(
            institute=self.institute,
            title="Scheduled notice",
            message="Send this later.",
            publish_at=timezone.now() + timedelta(minutes=10),
            is_published=True,
            push_to_app=True,
        )

        self.assertEqual(enqueue_due_notice_notifications(), [])
        self.assertFalse(
            BackgroundJob.objects.filter(
                job_type=BackgroundJob.JobType.NOTICE_NOTIFICATION
            ).exists()
        )

        Notice.objects.filter(pk=notice.pk).update(
            publish_at=timezone.now() - timedelta(seconds=1)
        )
        with (
            patch(
                "institute_admin.background_jobs.dispatch_background_job"
            ) as dispatch,
            self.captureOnCommitCallbacks(execute=True),
        ):
            jobs = enqueue_due_notice_notifications()

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].payload["notice_id"], notice.pk)
        self.assertEqual(
            jobs[0].payload["notification_version"],
            notice.push_notification_version,
        )
        dispatch.assert_called_once_with(jobs[0].pk)
        notice.refresh_from_db()
        self.assertIsNotNone(notice.push_notification_queued_at)
        self.assertEqual(enqueue_due_notice_notifications(), [])

    def test_edited_notice_skips_an_older_queued_notification(self):
        notice = Notice.objects.create(
            institute=self.institute,
            title="Updated notice",
            message="This is the latest content.",
            is_published=True,
            push_to_app=True,
            push_notification_version=2,
        )
        job = BackgroundJob.objects.create(
            job_type=BackgroundJob.JobType.NOTICE_NOTIFICATION,
            institute=self.institute,
            payload={
                "notice_id": notice.pk,
                "notification_version": 1,
            },
        )

        with patch(
            "student_parent.notifications.notify_notice_published"
        ) as notify_notice:
            result = execute_background_job(job)

        self.assertEqual(result["notification_count"], 0)
        self.assertIn("edited", result["skipped"].lower())
        notify_notice.assert_not_called()

    def test_expired_scheduled_notice_is_not_queued(self):
        Notice.objects.create(
            institute=self.institute,
            title="Expired notice",
            message="Do not send this.",
            publish_at=timezone.now() - timedelta(minutes=2),
            expires_at=timezone.now() - timedelta(minutes=1),
            is_published=True,
            push_to_app=True,
        )

        self.assertEqual(enqueue_due_notice_notifications(), [])
