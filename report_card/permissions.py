"""Permission helpers for the Report Card Generator app."""

from super_admin.models import UserProfile

from .models import ReportCardAssessment
from .selectors import (
    get_teacher_accessible_assessment_subjects,
    teacher_has_subject_allocation as selector_teacher_has_subject_allocation,
)


EDIT_BLOCKED_STATUSES = {
    ReportCardAssessment.Status.PUBLISHED,
    ReportCardAssessment.Status.LOCKED,
}
MARKS_ENTRY_STATUSES = {
    ReportCardAssessment.Status.MARKS_ENTRY_OPEN,
    ReportCardAssessment.Status.MARKS_ENTRY_COMPLETED,
    ReportCardAssessment.Status.GENERATED,
}
PUBLISHED_RESULT_STATUSES = {
    ReportCardAssessment.Status.PUBLISHED,
    ReportCardAssessment.Status.LOCKED,
}


def _user_profile(user):
    return getattr(user, "profile", None)


def _user_institute_id(user):
    teacher_profile = getattr(user, "teacher_profile", None)
    if teacher_profile and teacher_profile.institute_id:
        return teacher_profile.institute_id
    assigned_batch = user.assigned_batches.filter(is_active=True).only("institute_id").order_by("pk").first()
    if assigned_batch:
        return assigned_batch.institute_id
    profile = _user_profile(user)
    return profile.institute_id if profile else None


def _same_institute(user, institute_id):
    return bool(_user_institute_id(user) == institute_id)


def _is_teacher(user):
    profile = _user_profile(user)
    return bool(profile and profile.role == UserProfile.Role.TEACHER)


def _is_institute_admin(user):
    profile = _user_profile(user)
    return bool(profile and profile.role == UserProfile.Role.INSTITUTE_ADMIN)


def _is_accountant_manager(user):
    profile = _user_profile(user)
    return bool(profile and profile.role == UserProfile.Role.ACCOUNTANT)


def _is_student_parent(user):
    profile = _user_profile(user)
    return bool(profile and profile.role == UserProfile.Role.STUDENT_PARENT)


def teacher_can_access_assessment(user, assessment):
    if not user or not assessment or not _is_teacher(user):
        return False
    if assessment.is_deleted:
        return False
    if not _same_institute(user, assessment.institute_id):
        return False
    return get_teacher_accessible_assessment_subjects(user, assessment).exists()


def teacher_has_subject_allocation(user, assessment_subject):
    if not user or not assessment_subject or not _is_teacher(user):
        return False
    if not _same_institute(user, assessment_subject.assessment.institute_id):
        return False
    return selector_teacher_has_subject_allocation(user, assessment_subject)


def teacher_can_edit_assessment(user, assessment):
    return False


def teacher_can_enter_marks(user, assessment, assessment_subject=None):
    if not teacher_can_access_assessment(user, assessment):
        return False
    if assessment_subject is not None and not teacher_has_subject_allocation(user, assessment_subject):
        return False
    return assessment.status in MARKS_ENTRY_STATUSES


def admin_can_manage_assessment(user, assessment):
    if not user or not assessment:
        return False
    if getattr(user, "is_superuser", False):
        return True
    if not (_is_institute_admin(user) or _is_accountant_manager(user)):
        return False
    return _same_institute(user, assessment.institute_id)


def student_can_view_result(user, result):
    if not user or not result or not _is_student_parent(user):
        return False
    student = getattr(user, "student_profile", None)
    if not student:
        return False
    if result.assessment.status not in PUBLISHED_RESULT_STATUSES:
        return False
    if result.assessment.is_deleted:
        return False
    if result.is_stale:
        return False
    return result.student_id == student.pk
