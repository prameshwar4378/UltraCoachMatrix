from celery import shared_task
from django.conf import settings

from .background_jobs import (
    dispatch_background_job,
    mark_job_failed,
    mark_job_pending_for_retry,
    recover_stale_background_jobs,
    redispatch_pending_background_jobs,
    run_background_job,
)
from .models import BackgroundJob
from UltraCoachMatrix.email_notifications import send_all_scheduled_reminders


@shared_task(
    bind=True,
    name="institute_admin.process_background_job",
    acks_late=True,
    reject_on_worker_lost=True,
    ignore_result=True,
)
def process_background_job(self, job_id):
    try:
        job = run_background_job(job_id, mark_failure=False)
    except Exception as exc:
        job = BackgroundJob.objects.filter(pk=job_id).first()
        max_retries = int(getattr(settings, "BACKGROUND_JOB_MAX_RETRIES", 3))
        if not job:
            raise
        if self.request.retries >= max_retries:
            mark_job_failed(job, exc)
            raise

        mark_job_pending_for_retry(job, exc)
        base_delay = int(getattr(settings, "BACKGROUND_JOB_RETRY_DELAY", 30))
        countdown = base_delay * (2 ** self.request.retries)
        raise self.retry(exc=exc, countdown=countdown, max_retries=max_retries)

    if job is None:
        return {"status": "skipped", "job_id": job_id}
    return {"status": job.status, "job_id": job.pk, "result": job.result}


@shared_task(
    name="institute_admin.recover_stale_background_jobs",
    ignore_result=True,
)
def recover_stale_background_jobs_task():
    recovered_ids = recover_stale_background_jobs(dispatch=False)
    pending_ids = redispatch_pending_background_jobs()
    for job_id in recovered_ids:
        if job_id not in pending_ids:
            dispatch_background_job(job_id)
    return {
        "recovered_job_ids": recovered_ids,
        "redispatched_job_ids": pending_ids,
    }


@shared_task(
    name="institute_admin.send_scheduled_email_reminders",
    ignore_result=True,
)
def send_scheduled_email_reminders_task():
    return send_all_scheduled_reminders()
