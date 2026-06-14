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
```

Retry delays use exponential backoff. A job left in `RUNNING` after a worker
crash is returned to `PENDING` by the periodic recovery task. Old `PENDING`
jobs are redispatched automatically, covering jobs created while Redis was
temporarily unavailable.

If Redis is temporarily unavailable, job creation still succeeds and the
database record remains `PENDING`. After Redis returns, it can be processed by
the worker or by the fallback command:

```powershell
python manage.py run_background_jobs
```
