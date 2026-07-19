import mimetypes
from pathlib import PurePosixPath
from urllib.parse import quote

from django.conf import settings
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404, HttpResponse
from django.utils.encoding import iri_to_uri
from django.views.decorators.http import require_GET

from .media_utils import institute_media_code
from .mobile_auth import bearer_user
from .models import UserProfile


def _request_user(request):
    if request.user.is_authenticated:
        return request.user
    return bearer_user(request)


def _normalized_path(path):
    normalized = PurePosixPath(iri_to_uri(path)).as_posix().lstrip("/")
    if not normalized or normalized.startswith("../") or "/../" in normalized or normalized == "..":
        raise Http404("Media file not found.")
    return normalized


def _profile(user):
    return getattr(user, "profile", None)


def _is_super_admin(user):
    profile = _profile(user)
    return bool(profile and profile.role == UserProfile.Role.SUPER_ADMIN)


def _same_institute(profile, institute_id):
    return bool(profile and profile.institute_id and profile.institute_id == institute_id)


def _student_owns(user, student_id):
    student = getattr(user, "student_profile", None)
    return bool(student and student.pk == student_id)


def _staff_can_access(profile, institute_id):
    return bool(
        _same_institute(profile, institute_id)
        and profile.role
        in {
            UserProfile.Role.INSTITUTE_ADMIN,
            UserProfile.Role.TEACHER,
            UserProfile.Role.ACCOUNTANT,
        }
    )


def _student_can_access_homework(user, homework):
    student = getattr(user, "student_profile", None)
    if not student:
        return False
    from student_parent.models import StudentEnrollment

    return StudentEnrollment.objects.filter(
        academic_session__student=student,
        academic_session__status="ACTIVE",
        status="ACTIVE",
        batch=homework.batch,
    ).exists()


def _student_can_access_exam(user, exam):
    student = getattr(user, "student_profile", None)
    if not student:
        return False
    from student_parent.models import StudentEnrollment

    return StudentEnrollment.objects.filter(
        academic_session__student=student,
        academic_session__academic_year=exam.academic_year,
        academic_session__status="ACTIVE",
        status="ACTIVE",
        batch=exam.batch,
    ).exists()


def _can_access_model_file(user, path):
    if _is_super_admin(user):
        return True

    profile = _profile(user)

    from accountant.models import ExpenseDocument
    from institute_admin.models import BackgroundJob, InstituteGlobalPrintTemplate, InstitutePrintTemplate, Visitor
    from student_parent.models import StudentDocument, StudentProfile
    from teacher.models import ExamAttemptUpload, ExamQuestion, HomeworkAttachment
    from super_admin.models import Institute
    from UCMPartner.models import PartnerSaleClaim

    institute = Institute.objects.filter(logo=path).first()
    if institute:
        return _same_institute(profile, institute.pk)

    sale_claim = (
        PartnerSaleClaim.objects.select_related("partner", "partner__user")
        .filter(payment_screenshot=path)
        .first()
    )
    if sale_claim:
        return bool(
            user.is_staff
            or user.is_superuser
            or sale_claim.partner.user_id == user.pk
        )

    student_doc = (
        StudentDocument.objects.select_related("student")
        .filter(file=path)
        .first()
    )
    if student_doc:
        return _student_owns(user, student_doc.student_id) or _staff_can_access(profile, student_doc.student.institute_id)

    student_profile = StudentProfile.objects.filter(profile_image=path).first()
    if student_profile:
        return _student_owns(user, student_profile.pk) or _staff_can_access(profile, student_profile.institute_id)

    homework_attachment = (
        HomeworkAttachment.objects.select_related("homework", "homework__batch")
        .filter(file=path)
        .first()
    )
    if homework_attachment:
        homework = homework_attachment.homework
        return _staff_can_access(profile, homework.batch.institute_id) or _student_can_access_homework(user, homework)

    expense_document = (
        ExpenseDocument.objects.select_related("expense")
        .filter(file=path)
        .first()
    )
    if expense_document:
        return _staff_can_access(profile, expense_document.expense.institute_id)

    visitor = Visitor.objects.filter(attachment=path).first()
    if visitor:
        return _staff_can_access(profile, visitor.institute_id)

    question = ExamQuestion.objects.select_related("exam", "exam__batch").filter(image=path).first()
    if question:
        exam = question.exam
        return _staff_can_access(profile, exam.batch.institute_id) or _student_can_access_exam(user, exam)

    upload = (
        ExamAttemptUpload.objects.select_related("attempt", "attempt__exam", "attempt__exam__batch")
        .filter(image=path)
        .first()
    )
    if upload:
        exam = upload.attempt.exam
        return _student_owns(user, upload.attempt.student_id) or _staff_can_access(profile, exam.batch.institute_id)

    template = InstitutePrintTemplate.objects.filter(html_file=path).first()
    if template:
        return _staff_can_access(profile, template.institute_id)

    global_template = InstituteGlobalPrintTemplate.objects.filter(html_file=path).first()
    if global_template:
        return bool(profile and profile.role == UserProfile.Role.INSTITUTE_ADMIN and profile.institute_id)

    global_template_preview = InstituteGlobalPrintTemplate.objects.filter(preview_image=path).first()
    if global_template_preview:
        return bool(profile and profile.role == UserProfile.Role.INSTITUTE_ADMIN and profile.institute_id)

    background_job = BackgroundJob.objects.filter(input_file=path).first()
    if background_job:
        return bool(background_job.institute_id and _staff_can_access(profile, background_job.institute_id))

    return _can_access_scoped_fallback(profile, path)


def _can_access_scoped_fallback(profile, path):
    if not profile or not profile.institute_id:
        return False
    prefix = f"institutes/{institute_media_code(profile.institute)}/"
    return path.startswith(prefix)


def _file_response(path):
    content_type, _encoding = mimetypes.guess_type(path)
    content_type = content_type or "application/octet-stream"
    accel_prefix = getattr(settings, "PRIVATE_MEDIA_ACCEL_REDIRECT_PREFIX", "")
    if accel_prefix:
        response = HttpResponse(content_type=content_type)
        response["X-Accel-Redirect"] = accel_prefix.rstrip("/") + "/" + quote(path)
        return response
    return FileResponse(default_storage.open(path, "rb"), content_type=content_type)


@require_GET
def private_media(request, path):
    user = _request_user(request)
    if not user:
        raise Http404("Media file not found.")

    path = _normalized_path(path)
    if not default_storage.exists(path):
        raise Http404("Media file not found.")

    if not _can_access_model_file(user, path):
        raise Http404("Media file not found.")

    return _file_response(path)
