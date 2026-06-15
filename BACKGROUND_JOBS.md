# Background Jobs

Large student imports and notification fan-out are stored in the
`BackgroundJob` table and dispatched through Celery. Redis is used only as the
queue; the database record remains the durable status visible to the
application.

## Local setup

1. Start Redis on `127.0.0.1:6379`.
2. Install dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

3. Start the worker from the directory containing `manage.py`:

   ```powershell
   celery -A UltraCoachMatrix worker --loglevel=INFO --pool=solo
   ```

4. Start periodic stale-job recovery:

   ```powershell
   celery -A UltraCoachMatrix beat --loglevel=INFO
   ```

SQLite should use one worker with `--pool=solo`. After moving to PostgreSQL,
worker concurrency can be increased and workers can be separated by queue.

## Environment variables

```text
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/1
BACKGROUND_JOB_MAX_RETRIES=3
BACKGROUND_JOB_RETRY_DELAY=30
BACKGROUND_JOB_STALE_MINUTES=30
BACKGROUND_JOB_PENDING_REDISPATCH_MINUTES=5
BACKGROUND_JOB_RECOVERY_INTERVAL=300
BACKGROUND_JOB_SYNC_FEE_FALLBACK=true
BACKGROUND_JOB_SYNC_NOTICE_FALLBACK=false
SCHEDULED_NOTICE_SCAN_INTERVAL=60
```

Retry delays use exponential backoff. A job left in `RUNNING` after a worker
crash is returned to `PENDING` by the periodic recovery task. Old `PENDING`
jobs are redispatched automatically, covering jobs created while Redis was
temporarily unavailable.

Celery Beat also scans for notices whose `publish_at` time has arrived. Each
notice is atomically marked as queued before its durable notification job is
created, preventing duplicate sends when multiple scheduler processes overlap.

If Redis is temporarily unavailable, job creation still succeeds and the
database record remains `PENDING`. After Redis returns, it can be processed by
the worker or by the fallback command:

```powershell
python manage.py run_background_jobs
```

The fallback worker scans for due scheduled notices before processing jobs. A
cron-only deployment can instead run this command once per minute:

```powershell
python manage.py enqueue_scheduled_notices
```

Fee notifications have an additional safe fallback. When Celery dispatch
fails, the single-student notification is processed synchronously so receiving
a payment can still notify the student on hosts without a continuously running
worker.

On a temporary deployment without a worker, set
`BACKGROUND_JOB_SYNC_NOTICE_FALLBACK=true` to send notices synchronously too.
This can make the notice request slower for large institutes, so disable it
after Redis and Celery are running.
