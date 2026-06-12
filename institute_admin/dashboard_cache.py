from django.conf import settings
from django.core.cache import cache
from django.utils import timezone


def dashboard_summary_cache_key(institute_id, academic_year_id, day=None):
    day = day or timezone.localdate()
    return f"dashboard-summary:{institute_id}:{academic_year_id}:{day.isoformat()}"


def get_dashboard_summary(institute_id, academic_year_id):
    return cache.get(dashboard_summary_cache_key(institute_id, academic_year_id))


def set_dashboard_summary(institute_id, academic_year_id, summary):
    timeout = int(getattr(settings, "DASHBOARD_CACHE_TIMEOUT", 180))
    cache.set(
        dashboard_summary_cache_key(institute_id, academic_year_id),
        summary,
        timeout=timeout,
    )


def invalidate_dashboard_summary(institute_id, academic_year_id):
    if institute_id and academic_year_id:
        cache.delete(dashboard_summary_cache_key(institute_id, academic_year_id))
