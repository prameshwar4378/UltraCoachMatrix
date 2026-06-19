from django.conf import settings
from django.core.cache import cache

from .models import AcademicYear, Batch


def _timeout():
    return int(getattr(settings, "LOOKUP_CACHE_TIMEOUT", 300))


def academic_years_cache_key(institute_id):
    return f"academic-years:{institute_id}"


def lookup_data_cache_key(institute_id, academic_year_id, lookup_name):
    return f"lookup:{lookup_name}:{institute_id}:{academic_year_id or 'all'}"


def get_cached_academic_years(institute_id):
    key = academic_years_cache_key(institute_id)
    academic_years = cache.get(key)
    if academic_years is None:
        academic_years = list(
            AcademicYear.objects.filter(institute_id=institute_id).order_by(
                "-start_date",
                "-pk",
            )
        )
        cache.set(key, academic_years, timeout=_timeout())
    return academic_years


def get_cached_batch_course_data(institute_id, academic_year_id=None):
    key = lookup_data_cache_key(institute_id, academic_year_id, "batch-courses")
    data = cache.get(key)
    if data is None:
        batches = Batch.objects.filter(institute_id=institute_id).prefetch_related("courses")
        if academic_year_id:
            batches = batches.filter(academic_year_id=academic_year_id)
        data = {
            str(batch.pk): [
                {
                    "id": str(course.pk),
                    "name": course.name,
                    "fee": str(course.fee_amount),
                }
                for course in batch.courses.all()
            ]
            for batch in batches
        }
        cache.set(key, data, timeout=_timeout())
    return data


def get_cached_course_batch_data(institute_id, academic_year_id=None):
    key = lookup_data_cache_key(institute_id, academic_year_id, "course-batches-v2")
    data = cache.get(key)
    if data is None:
        batches = Batch.objects.filter(
            institute_id=institute_id,
            is_active=True,
        ).prefetch_related("courses")
        if academic_year_id:
            batches = batches.filter(academic_year_id=academic_year_id)
        data = {}
        for batch in batches:
            for course in batch.courses.all():
                data.setdefault(str(course.pk), []).append(
                    {
                        "id": str(batch.pk),
                        "name": batch.name,
                        "fee": str(course.fee_amount),
                    }
                )
        cache.set(key, data, timeout=_timeout())
    return data


def invalidate_academic_years_cache(institute_id):
    if institute_id:
        cache.delete(academic_years_cache_key(institute_id))


def invalidate_lookup_data_cache(institute_id, academic_year_id=None):
    if not institute_id:
        return
    keys = []
    for lookup_name in ("batch-courses", "course-batches", "course-batches-v2"):
        keys.append(lookup_data_cache_key(institute_id, academic_year_id, lookup_name))
        if academic_year_id:
            keys.append(lookup_data_cache_key(institute_id, None, lookup_name))
    cache.delete_many(keys)
