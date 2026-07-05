import logging
import threading
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from .models import BackgroundJob


logger = logging.getLogger(__name__)


def enqueue_background_job(job_type, *, institute=None, academic_year=None, created_by=None, payload=None, input_file=None):
    job = BackgroundJob.objects.create(
        job_type=job_type,
        institute=institute,
        academic_year=academic_year,
        created_by=created_by,
        payload=payload or {},
        input_file=input_file,
    )
    transaction.on_commit(lambda job_id=job.pk: process_enqueued_background_job(job_id))
    return job


def process_enqueued_background_job(job_id):
    job = BackgroundJob.objects.filter(pk=job_id).only("job_type").first()
    if job and _should_run_asynchronously(job.job_type):
        thread = threading.Thread(
            target=_run_background_job_in_thread,
            args=(job_id,),
            name=f"ucm-bgjob-{job_id}",
            daemon=True,
        )
        thread.start()
        return True
    if job and _should_run_synchronously(job.job_type):
        try:
            run_background_job(job_id)
        except Exception:
            logger.exception("Could not process notification job %s synchronously.", job_id)
            return False
        return True
    return dispatch_background_job(job_id)


def _run_background_job_in_thread(job_id):
    close_old_connections()
    try:
        run_background_job(job_id)
    except Exception:
        logger.exception("Could not process notification job %s asynchronously.", job_id)
    finally:
        close_old_connections()


def _should_run_asynchronously(job_type):
    if not getattr(settings, "BACKGROUND_JOB_ASYNC_NOTIFICATIONS", True):
        return False
    return job_type in {
        BackgroundJob.JobType.FEE_NOTIFICATION,
        BackgroundJob.JobType.NOTICE_NOTIFICATION,
    }


def _should_run_synchronously(job_type):
    if not getattr(settings, "BACKGROUND_JOB_SYNC_NOTIFICATIONS", True):
        return False
    return job_type in {
        BackgroundJob.JobType.FEE_NOTIFICATION,
        BackgroundJob.JobType.NOTICE_NOTIFICATION,
    }


def enqueue_due_notice_notifications(*, limit=100, notice_ids=None):
    from .models import Notice

    queued_jobs = []
    now = timezone.now()
    limit = max(int(limit), 1)

    while len(queued_jobs) < limit:
        with transaction.atomic():
            queryset = (
                Notice.objects.select_for_update()
                .filter(
                    is_published=True,
                    push_to_app=True,
                    push_notification_queued_at__isnull=True,
                )
                .filter(Q(publish_at__isnull=True) | Q(publish_at__lte=now))
                .filter(Q(expires_at__isnull=True) | Q(expires_at__gte=now))
                .order_by("publish_at", "created_at")
            )
            if notice_ids is not None:
                queryset = queryset.filter(pk__in=notice_ids)
            notice = queryset.first()
            if notice is None:
                break

            notice.push_notification_queued_at = now
            notice.save(update_fields=["push_notification_queued_at"])
            queued_jobs.append(
                enqueue_background_job(
                    BackgroundJob.JobType.NOTICE_NOTIFICATION,
                    institute=notice.institute,
                    created_by=notice.created_by,
                    payload={
                        "notice_id": notice.pk,
                        "notification_version": notice.push_notification_version,
                    },
                )
            )

    return queued_jobs


def dispatch_background_job(job_id):
    from .tasks import process_background_job

    try:
        process_background_job.delay(job_id)
    except Exception:
        # The durable database record remains pending and can be recovered once
        # Redis is available or by the run_background_jobs fallback command.
        logger.exception("Could not dispatch background job %s to Celery.", job_id)
        job = BackgroundJob.objects.filter(pk=job_id).only("job_type").first()
        sync_fallback_types = set()
        if getattr(settings, "BACKGROUND_JOB_SYNC_FEE_FALLBACK", True):
            sync_fallback_types.add(BackgroundJob.JobType.FEE_NOTIFICATION)
        if getattr(settings, "BACKGROUND_JOB_SYNC_NOTICE_FALLBACK", False):
            sync_fallback_types.add(BackgroundJob.JobType.NOTICE_NOTIFICATION)
        if (
            job
            and job.job_type in sync_fallback_types
        ):
            try:
                run_background_job(job_id)
            except Exception:
                logger.exception(
                    "Could not process notification job %s synchronously.",
                    job_id,
                )
                return False
            return True
        return False
    return True


def claim_background_job(job_id):
    with transaction.atomic():
        job = (
            BackgroundJob.objects.select_for_update()
            .filter(pk=job_id, status=BackgroundJob.Status.PENDING)
            .first()
        )
        if not job:
            return None
        job.status = BackgroundJob.Status.RUNNING
        job.started_at = timezone.now()
        job.completed_at = None
        job.error_message = ""
        job.attempts = F("attempts") + 1
        job.save(
            update_fields=[
                "status",
                "started_at",
                "completed_at",
                "error_message",
                "attempts",
            ]
        )
        job.refresh_from_db()
        return job


def claim_next_background_job():
    with transaction.atomic():
        job = (
            BackgroundJob.objects.select_for_update()
            .filter(status=BackgroundJob.Status.PENDING)
            .order_by("created_at")
            .first()
        )
        if not job:
            return None
        job.status = BackgroundJob.Status.RUNNING
        job.started_at = timezone.now()
        job.completed_at = None
        job.error_message = ""
        job.attempts = F("attempts") + 1
        job.save(
            update_fields=[
                "status",
                "started_at",
                "completed_at",
                "error_message",
                "attempts",
            ]
        )
        job.refresh_from_db()
        return job


def execute_background_job(job):
    if job.job_type == BackgroundJob.JobType.FEE_NOTIFICATION:
        from accountant.models import Payment
        from student_parent.notifications import notify_fee_paid

        payment = Payment.objects.select_related(
            "invoice",
            "invoice__student",
            "invoice__student__user",
        ).get(pk=job.payload["payment_id"])
        notification = notify_fee_paid(payment)
        return {"notification_count": 1 if notification else 0}

    if job.job_type == BackgroundJob.JobType.NOTICE_NOTIFICATION:
        from student_parent.notifications import notify_notice_published

        notice = job.institute.notices.get(pk=job.payload["notice_id"])
        notification_version = job.payload.get("notification_version")
        if (
            notification_version is not None
            and int(notification_version) != notice.push_notification_version
        ):
            return {
                "notification_count": 0,
                "skipped": "Notice was edited after this job was queued.",
            }
        records = notify_notice_published(notice)
        return {"notification_count": len(records)}

    if job.job_type == BackgroundJob.JobType.STUDENT_IMPORT:
        from .student_import_service import process_student_import_job

        return process_student_import_job(job)

    raise ValueError(f"Unsupported background job type: {job.job_type}")


def mark_job_completed(job, result):
    job.status = BackgroundJob.Status.COMPLETED
    job.result = result or {}
    job.error_message = ""
    job.completed_at = timezone.now()
    job.save(update_fields=["status", "result", "error_message", "completed_at"])


def mark_job_failed(job, error):
    job.status = BackgroundJob.Status.FAILED
    job.error_message = str(error)
    job.completed_at = timezone.now()
    job.save(update_fields=["status", "error_message", "completed_at"])


def mark_job_pending_for_retry(job, error):
    job.status = BackgroundJob.Status.PENDING
    job.error_message = str(error)
    job.started_at = None
    job.completed_at = None
    job.save(
        update_fields=["status", "error_message", "started_at", "completed_at"]
    )


def run_background_job(job_id, *, mark_failure=True):
    job = claim_background_job(job_id)
    if not job:
        return None
    try:
        result = execute_background_job(job)
    except Exception as exc:
        if mark_failure:
            mark_job_failed(job, exc)
        raise
    mark_job_completed(job, result)
    return job


def run_next_background_job():
    job = claim_next_background_job()
    if not job:
        return None
    try:
        result = execute_background_job(job)
    except Exception as exc:
        mark_job_failed(job, exc)
        raise
    mark_job_completed(job, result)
    return job


def recover_stale_background_jobs(*, dispatch=True):
    stale_before = timezone.now() - timedelta(
        minutes=int(getattr(settings, "BACKGROUND_JOB_STALE_MINUTES", 30))
    )
    stale_jobs = list(
        BackgroundJob.objects.filter(
            status=BackgroundJob.Status.RUNNING,
            started_at__lt=stale_before,
        ).values_list("pk", flat=True)
    )
    if not stale_jobs:
        return []

    BackgroundJob.objects.filter(pk__in=stale_jobs).update(
        status=BackgroundJob.Status.PENDING,
        started_at=None,
        completed_at=None,
        error_message="Recovered after the previous worker stopped responding.",
    )
    if dispatch:
        for job_id in stale_jobs:
            dispatch_background_job(job_id)
    return stale_jobs


def redispatch_pending_background_jobs():
    pending_before = timezone.now() - timedelta(
        minutes=int(
            getattr(settings, "BACKGROUND_JOB_PENDING_REDISPATCH_MINUTES", 5)
        )
    )
    pending_ids = list(
        BackgroundJob.objects.filter(
            status=BackgroundJob.Status.PENDING,
            created_at__lt=pending_before,
        )
        .order_by("created_at")
        .values_list("pk", flat=True)
    )
    for job_id in pending_ids:
        dispatch_background_job(job_id)
    return pending_ids
