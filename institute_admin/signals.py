from django.core.exceptions import ValidationError
from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver

from accountant.models import FeeInvoice, Payment
from student_parent.models import StudentAcademicSession, StudentEnrollment, StudentProfile
from super_admin.models import UserProfile
from teacher.models import Attendance

from .dashboard_cache import invalidate_dashboard_summary
from .lookup_cache import (
    invalidate_academic_years_cache,
    invalidate_lookup_data_cache,
)
from .models import AcademicYear, Batch, Course, Notice


def _validate_same_scope(queryset, pk_set, institute_id, academic_year_id=None):
    selected = queryset.filter(pk__in=pk_set)
    if selected.exclude(institute_id=institute_id).exists():
        raise ValidationError("Selected records must belong to the same institute.")
    if academic_year_id is not None and selected.exclude(academic_year_id=academic_year_id).exists():
        raise ValidationError("Selected records must belong to the same academic year.")


def invalidate_session(session):
    if session:
        invalidate_dashboard_summary(session.institute_id, session.academic_year_id)


def enrollment_session(enrollment):
    if not enrollment.academic_session_id:
        return None
    return StudentAcademicSession.objects.only("institute_id", "academic_year_id").filter(
        pk=enrollment.academic_session_id
    ).first()


@receiver([post_save, post_delete], sender=StudentAcademicSession)
def invalidate_session_dashboard(sender, instance, **kwargs):
    invalidate_session(instance)


@receiver([post_save, post_delete], sender=StudentEnrollment)
def invalidate_enrollment_dashboard(sender, instance, **kwargs):
    invalidate_session(enrollment_session(instance))


@receiver(m2m_changed, sender=StudentEnrollment.courses.through)
def invalidate_enrollment_courses_dashboard(sender, instance, action, **kwargs):
    if action == "pre_add" and kwargs.get("pk_set"):
        if not instance.academic_session_id:
            raise ValidationError("Enrollment must have an academic session before courses can be assigned.")
        _validate_same_scope(
            Course.objects,
            kwargs["pk_set"],
            instance.academic_session.institute_id,
            instance.academic_session.academic_year_id,
        )
    if action in {"post_add", "post_remove", "post_clear"}:
        invalidate_session(enrollment_session(instance))


@receiver([post_save, post_delete], sender=FeeInvoice)
def invalidate_invoice_dashboard(sender, instance, **kwargs):
    invalidate_dashboard_summary(instance.institute_id, instance.academic_session.academic_year_id)


@receiver([post_save, post_delete], sender=Payment)
def invalidate_payment_dashboard(sender, instance, **kwargs):
    invoice = FeeInvoice.objects.only("institute_id", "academic_session__academic_year_id").select_related(
        "academic_session"
    ).filter(pk=instance.invoice_id).first()
    if invoice:
        invalidate_dashboard_summary(invoice.institute_id, invoice.academic_session.academic_year_id)


@receiver([post_save, post_delete], sender=Attendance)
def invalidate_attendance_dashboard(sender, instance, **kwargs):
    invalidate_session(instance.academic_session)


@receiver([post_save, post_delete], sender=StudentProfile)
def invalidate_student_profile_dashboard(sender, instance, **kwargs):
    for institute_id, academic_year_id in instance.academic_sessions.values_list(
        "institute_id", "academic_year_id"
    ):
        invalidate_dashboard_summary(institute_id, academic_year_id)


@receiver([post_save, post_delete], sender=Course)
@receiver([post_save, post_delete], sender=Batch)
def invalidate_academic_setup_dashboard(sender, instance, **kwargs):
    invalidate_dashboard_summary(instance.institute_id, instance.academic_year_id)
    invalidate_lookup_data_cache(instance.institute_id, instance.academic_year_id)


@receiver([post_save, post_delete], sender=AcademicYear)
def invalidate_academic_year_cache(sender, instance, **kwargs):
    invalidate_academic_years_cache(instance.institute_id)
    invalidate_lookup_data_cache(instance.institute_id, instance.pk)


@receiver(m2m_changed, sender=Batch.courses.through)
def invalidate_batch_courses_dashboard(sender, instance, action, **kwargs):
    if action == "pre_add" and kwargs.get("pk_set"):
        _validate_same_scope(Course.objects, kwargs["pk_set"], instance.institute_id, instance.academic_year_id)
    if action in {"post_add", "post_remove", "post_clear"}:
        invalidate_dashboard_summary(instance.institute_id, instance.academic_year_id)
        invalidate_lookup_data_cache(instance.institute_id, instance.academic_year_id)


@receiver(m2m_changed, sender=Notice.target_batches.through)
def validate_notice_target_batches(sender, instance, action, **kwargs):
    if action == "pre_add" and kwargs.get("pk_set"):
        _validate_same_scope(Batch.objects, kwargs["pk_set"], instance.institute_id, instance.academic_year_id)


@receiver(m2m_changed, sender=Notice.target_courses.through)
def validate_notice_target_courses(sender, instance, action, **kwargs):
    if action == "pre_add" and kwargs.get("pk_set"):
        _validate_same_scope(Course.objects, kwargs["pk_set"], instance.institute_id, instance.academic_year_id)


@receiver(m2m_changed, sender=Notice.target_students.through)
def validate_notice_target_students(sender, instance, action, **kwargs):
    if action == "pre_add" and kwargs.get("pk_set"):
        _validate_same_scope(StudentProfile.objects, kwargs["pk_set"], instance.institute_id)
        if instance.academic_year_id:
            missing_students = StudentProfile.objects.filter(pk__in=kwargs["pk_set"]).exclude(
                academic_sessions__academic_year_id=instance.academic_year_id,
            )
            if missing_students.exists():
                raise ValidationError("Selected students must belong to the notice academic session.")


@receiver([post_save, post_delete], sender=UserProfile)
def invalidate_staff_dashboard(sender, instance, **kwargs):
    if not instance.institute_id:
        return
    for academic_year_id in instance.institute.academic_years.values_list("pk", flat=True):
        invalidate_dashboard_summary(instance.institute_id, academic_year_id)
