import os

from celery import Celery


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "UltraCoachMatrix.settings")

app = Celery("UltraCoachMatrix")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
