from datetime import date

from django.db.models import Count, Q
from django.utils import timezone
from django.utils.dateparse import parse_date

from institute_admin.models import Notice
from student_parent.models import StudentAcademicSession, StudentEnrollment
from ..models import Exam, ExamAttempt, Homework
from ..views import teacher_batches, teacher_students_for_batches


def teacher_assigned_batches(request):
    return teacher_batches(request)


def assigned_batches_with_counts(request):
    return teacher_assigned_batches(request).annotate(
        active_students=Count(
            "enrollments",
            filter=Q(
                enrollments__status=StudentEnrollment.Status.ACTIVE,
                enrollments__academic_session__status=StudentAcademicSession.Status.ACTIVE,
                enrollments__student__is_active=True,
            ),
            distinct=True,
        ),
        course_total=Count("courses", distinct=True),
    ).prefetch_related("courses").order_by("name")


def teacher_students_for_batch(request, batch):
    return teacher_students_for_batches(teacher_assigned_batches(request).filter(pk=batch.pk))


def homework_queryset(request):
    return Homework.objects.filter(
        batch__in=teacher_assigned_batches(request),
    ).select_related("batch", "course", "subject").prefetch_related("attachments")


def teacher_homework_or_none(request, assignment_id):
    return homework_queryset(request).filter(pk=assignment_id).first()


def exam_queryset(request):
    return Exam.objects.filter(
        batch__in=teacher_assigned_batches(request),
    ).select_related("batch", "course", "subject")


def teacher_exam_or_none(request, exam_id):
    return exam_queryset(request).filter(pk=exam_id).first()


def question_queryset(request):
    from ..models import ExamQuestion

    return ExamQuestion.objects.filter(
        exam__in=exam_queryset(request),
    ).select_related("exam").prefetch_related("options")


def teacher_question_or_none(request, question_id):
    return question_queryset(request).filter(pk=question_id).first()


def submitted_attempts_queryset(request):
    return ExamAttempt.objects.filter(
        exam__in=exam_queryset(request),
        submitted_at__isnull=False,
    ).select_related("exam", "student", "student__user", "academic_session").order_by("-submitted_at")


def attempts_queryset(request):
    return ExamAttempt.objects.filter(
        exam__in=exam_queryset(request),
    ).select_related("exam", "student", "student__user", "academic_session")


def teacher_attempt_or_none(request, attempt_id):
    return attempts_queryset(request).filter(pk=attempt_id).first()


def teacher_notice_queryset(request):
    profile = request.user.profile
    now = timezone.now()
    batches = teacher_assigned_batches(request)
    batch_ids = batches.values_list("pk", flat=True)
    course_ids = batches.values_list("courses__pk", flat=True)
    return Notice.objects.filter(
        institute=profile.institute,
        is_published=True,
    ).filter(
        Q(audience=Notice.Audience.EVERYONE) | Q(audience=Notice.Audience.TEACHERS),
        Q(publish_at__isnull=True) | Q(publish_at__lte=now),
        Q(expires_at__isnull=True) | Q(expires_at__gte=now),
    ).filter(
        Q(target_batches__isnull=True, target_courses__isnull=True, target_students__isnull=True)
        | Q(target_batches__in=batch_ids)
        | Q(target_courses__in=course_ids)
    ).distinct()


def parse_api_date(value, default=None):
    if not value:
        return default
    return parse_date(str(value)) or default


def today_date():
    return date.today()


def student_display_name(student):
    return student.user.get_full_name() or student.user.username
