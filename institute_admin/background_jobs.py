from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import BackgroundJob


def enqueue_background_job(job_type, *, institute=None, academic_year=None, created_by=None, payload=None, input_file=None):
    return BackgroundJob.objects.create(
        job_type=job_type,
        institute=institute,
        academic_year=academic_year,
        created_by=created_by,
        payload=payload or {},
        input_file=input_file,
    )


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
        job.attempts = F("attempts") + 1
        job.save(update_fields=["status", "started_at", "attempts"])
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
        records = notify_fee_paid(payment)
        return {"notification_count": len(records)}

    if job.job_type == BackgroundJob.JobType.NOTICE_NOTIFICATION:
        from student_parent.notifications import notify_notice_published

        notice = job.institute.notices.get(pk=job.payload["notice_id"])
        records = notify_notice_published(notice)
        return {"notification_count": len(records)}

    if job.job_type == BackgroundJob.JobType.STUDENT_IMPORT:
        from .student_import_service import process_student_import_job

        return process_student_import_job(job)

    raise ValueError(f"Unsupported background job type: {job.job_type}")


def run_next_background_job():
    job = claim_next_background_job()
    if not job:
        return None
    try:
        result = execute_background_job(job)
    except Exception as exc:
        job.status = BackgroundJob.Status.FAILED
        job.error_message = str(exc)
        job.completed_at = timezone.now()
        job.save(update_fields=["status", "error_message", "completed_at"])
        raise
    job.status = BackgroundJob.Status.COMPLETED
    job.result = result or {}
    job.error_message = ""
    job.completed_at = timezone.now()
    job.save(update_fields=["status", "result", "error_message", "completed_at"])
    return job
