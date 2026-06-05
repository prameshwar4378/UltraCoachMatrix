import json
from datetime import date, timedelta

from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_POST

from institute_admin.models import Notice, NoticeRead
from super_admin.decorators import student_parent_required
from super_admin.mobile_auth import bearer_user
from super_admin.models import UserProfile
from teacher.models import (
    Attendance,
    Exam,
    ExamAttempt,
    ExamAttemptActivity,
    ExamAttemptUpload,
    ExamQuestionAttempt,
    ExamResult,
    Homework,
)

from .models import PushNotification, StudentAcademicSession, StudentEnrollment, StudentProfile, UserDevice


def _selected_academic_session(student, request):
    session_id = (request.GET.get("academic_session_id") or "").strip()
    if not session_id:
        return None
    return (
        StudentAcademicSession.objects.filter(student=student, pk=session_id)
        .select_related("academic_year", "institute")
        .first()
    )


@student_parent_required
def download_app(request):
    return render(request, "student_parent/download_app.html")


def _student_from_web_user(request):
    return getattr(request.user, "student_profile", None)


def _student_exam_session(request, student):
    selected = _selected_academic_session(student, request)
    if selected:
        return selected
    return (
        StudentAcademicSession.objects.filter(student=student, status=StudentAcademicSession.Status.ACTIVE)
        .select_related("academic_year", "institute")
        .order_by("-academic_year__start_date", "-pk")
        .first()
    )


def _student_exam_queryset(student, academic_session):
    if not academic_session:
        return Exam.objects.none()
    enrollment_batches = StudentEnrollment.objects.filter(
        academic_session=academic_session,
        status=StudentEnrollment.Status.ACTIVE,
    ).values_list("batch_id", flat=True)
    return (
        Exam.objects.filter(
            batch_id__in=enrollment_batches,
            academic_year=academic_session.academic_year,
            is_published=True,
        )
        .select_related("batch", "academic_year", "subject", "created_by")
        .prefetch_related("questions", "questions__options")
    )


def _student_exam_session_for_exam(student, exam):
    enrollment = (
        StudentEnrollment.objects.filter(
            student=student,
            batch=exam.batch,
            academic_session__academic_year=exam.academic_year,
            academic_session__status=StudentAcademicSession.Status.ACTIVE,
            status=StudentEnrollment.Status.ACTIVE,
        )
        .select_related("academic_session", "academic_session__academic_year")
        .order_by("-academic_session__academic_year__start_date", "-academic_session_id")
        .first()
    )
    return enrollment.academic_session if enrollment else None


@student_parent_required
def exams(request):
    student = _student_from_web_user(request)
    if not student:
        messages.error(request, "No student profile is linked to this account.")
        return redirect("student_parent:download_app")
    sessions = StudentAcademicSession.objects.filter(student=student).select_related("academic_year")
    academic_session = _student_exam_session(request, student)
    exam_list = _student_exam_queryset(student, academic_session)
    attempts = {
        attempt.exam_id: attempt
        for attempt in ExamAttempt.objects.filter(academic_session=academic_session, exam__in=exam_list)
    } if academic_session else {}
    rows = [{"exam": exam, "attempt": attempts.get(exam.pk)} for exam in exam_list]
    return render(
        request,
        "student_parent/exams.html",
        {
            "student": student,
            "sessions": sessions,
            "selected_session": academic_session,
            "rows": rows,
        },
    )


@student_parent_required
def exam_attempt(request, pk):
    student = _student_from_web_user(request)
    if not student:
        messages.error(request, "No student profile is linked to this account.")
        return redirect("student_parent:download_app")
    academic_session = _student_exam_session(request, student)
    exam = get_object_or_404(_student_exam_queryset(student, academic_session), pk=pk)
    attempt, _created = ExamAttempt.objects.get_or_create(
        exam=exam,
        academic_session=academic_session,
        defaults={"student": student, "total_marks": exam.total_marks},
    )
    if attempt.is_submitted:
        return redirect("student_parent:exam_result", pk=attempt.pk)
    questions = list(exam.questions.prefetch_related("options"))
    if request.method == "POST":
        score = 0
        correct_count = 0
        wrong_count = 0
        unattempted_count = 0
        total_marks = sum(question.marks for question in questions)
        for question in questions:
            option_id = request.POST.get(f"question_{question.pk}")
            selected_option = question.options.filter(pk=option_id).first() if option_id else None
            is_correct = bool(selected_option and selected_option.is_correct)
            marks_awarded = question.marks if is_correct else 0
            if selected_option is None:
                unattempted_count += 1
            elif is_correct:
                correct_count += 1
                score += question.marks
            else:
                wrong_count += 1
            ExamQuestionAttempt.objects.update_or_create(
                attempt=attempt,
                question=question,
                defaults={
                    "selected_option": selected_option,
                    "is_correct": is_correct,
                    "marks_awarded": marks_awarded,
                },
            )
            if exam.allow_rough_work_uploads:
                for image in request.FILES.getlist(f"rough_work_{question.pk}"):
                    ExamAttemptUpload.objects.create(attempt=attempt, question=question, image=image)
        attempt.score = score
        attempt.total_marks = total_marks
        attempt.correct_count = correct_count
        attempt.wrong_count = wrong_count
        attempt.unattempted_count = unattempted_count
        attempt.submitted_at = timezone.now()
        attempt.save()
        ExamResult.objects.update_or_create(
            exam=exam,
            student=student,
            defaults={
                "marks_obtained": score,
                "remark": "Generated automatically from MCQ exam.",
            },
        )
        messages.success(request, "Exam submitted successfully.")
        return redirect("student_parent:exam_result", pk=attempt.pk)
    return render(
        request,
        "student_parent/exam_attempt.html",
        {"exam": exam, "attempt": attempt, "questions": questions, "selected_session": academic_session},
    )


@student_parent_required
def exam_result(request, pk):
    student = _student_from_web_user(request)
    attempt = get_object_or_404(
        ExamAttempt.objects.select_related("exam", "exam__batch", "academic_session", "student", "student__user")
        .prefetch_related("question_attempts", "question_attempts__question", "question_attempts__selected_option", "uploads"),
        pk=pk,
        student=student,
    )
    if not attempt.exam.show_result_after_submit:
        messages.info(request, "Result is not available yet.")
        return redirect("student_parent:exams")
    return render(request, "student_parent/exam_result.html", {"attempt": attempt})


def _absolute_media_url(request, field_file):
    if not field_file:
        return ""
    try:
        return request.build_absolute_uri(field_file.url)
    except ValueError:
        return ""


def _mobile_exam_item(exam, attempt=None):
    is_submitted = bool(attempt and attempt.is_submitted)
    return {
        "id": exam.pk,
        "title": exam.title,
        "exam_date": _date(exam.exam_date),
        "duration_minutes": exam.duration_minutes,
        "total_marks": exam.total_marks,
        "question_count": exam.questions.count(),
        "instructions": strip_tags(exam.instructions or "").strip(),
        "allow_rough_work_uploads": exam.allow_rough_work_uploads,
        "show_result_after_submit": exam.show_result_after_submit,
        "batch": {
            "id": exam.batch_id,
            "name": exam.batch.name,
        },
        "subject": {
            "id": exam.subject_id,
            "name": exam.subject.name if exam.subject_id else "General",
        },
        "academic_year": {
            "id": exam.academic_year_id,
            "name": exam.academic_year.name if exam.academic_year_id else "",
        },
        "attempt": {
            "id": attempt.pk if attempt else None,
            "status": "submitted" if is_submitted else "in_progress" if attempt else "not_started",
            "started_at": _datetime(attempt.started_at) if attempt else None,
            "submitted_at": _datetime(attempt.submitted_at) if attempt and attempt.submitted_at else None,
            "score": str(attempt.score) if attempt else None,
            "total_marks": str(attempt.total_marks) if attempt else None,
            "can_view_result": bool(is_submitted and exam.show_result_after_submit),
        },
    }


def _mobile_attempt_payload(request, attempt):
    exam = attempt.exam
    questions = []
    for question in exam.questions.prefetch_related("options"):
        questions.append(
            {
                "id": question.pk,
                "text": question.text,
                "image_url": _absolute_media_url(request, question.image),
                "marks": question.marks,
                "order": question.order,
                "options": [
                    {
                        "id": option.pk,
                        "text": option.text,
                        "order": option.order,
                    }
                    for option in question.options.all()
                ],
            }
        )
    return {
        "attempt": {
            "id": attempt.pk,
            "started_at": _datetime(attempt.started_at),
            "submitted_at": _datetime(attempt.submitted_at) if attempt.submitted_at else None,
        },
        "exam": _mobile_exam_item(exam, attempt),
        "questions": questions,
    }


def _mobile_result_payload(request, attempt):
    question_attempts = {
        item.question_id: item
        for item in attempt.question_attempts.select_related("selected_option", "question").all()
    }
    questions = []
    for question in attempt.exam.questions.prefetch_related("options"):
        question_attempt = question_attempts.get(question.pk)
        correct_option = question.correct_option
        questions.append(
            {
                "id": question.pk,
                "text": question.text,
                "image_url": _absolute_media_url(request, question.image),
                "marks": question.marks,
                "order": question.order,
                "selected_option_id": question_attempt.selected_option_id if question_attempt else None,
                "correct_option_id": correct_option.pk if correct_option else None,
                "is_correct": bool(question_attempt and question_attempt.is_correct),
                "marks_awarded": str(question_attempt.marks_awarded) if question_attempt else "0",
                "options": [
                    {
                        "id": option.pk,
                        "text": option.text,
                        "order": option.order,
                    }
                    for option in question.options.all()
                ],
            }
        )
    return {
        "attempt": {
            "id": attempt.pk,
            "submitted_at": _datetime(attempt.submitted_at) if attempt.submitted_at else None,
            "score": str(attempt.score),
            "total_marks": str(attempt.total_marks),
            "correct_count": attempt.correct_count,
            "wrong_count": attempt.wrong_count,
            "unattempted_count": attempt.unattempted_count,
            "can_view_result": attempt.exam.show_result_after_submit,
        },
        "exam": _mobile_exam_item(attempt.exam, attempt),
        "questions": questions,
    }


def _json_body(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return None


def _request_data(request):
    data = _json_body(request)
    return data if isinstance(data, dict) else {}


@require_GET
def mobile_exams(request):
    student, error = _student_for_request(request)
    if error:
        return error
    academic_session = _student_exam_session(request, student)
    exam_list = _student_exam_queryset(student, academic_session)
    attempts = {
        attempt.exam_id: attempt
        for attempt in ExamAttempt.objects.filter(academic_session=academic_session, exam__in=exam_list)
    } if academic_session else {}
    exams_payload = [_mobile_exam_item(exam, attempts.get(exam.pk)) for exam in exam_list]
    return JsonResponse(
        {
            "student": {
                "id": student.pk,
                "name": student.user.get_full_name() or student.user.username,
                "username": student.user.username,
                "admission_number": student.admission_number,
            },
            "academic_session": {
                "id": academic_session.pk if academic_session else None,
                "admission_number": academic_session.admission_number if academic_session else "",
                "academic_year": academic_session.academic_year.name if academic_session else "",
            },
            "summary": {
                "exam_count": len(exams_payload),
                "submitted_count": sum(1 for item in exams_payload if item["attempt"]["status"] == "submitted"),
                "pending_count": sum(1 for item in exams_payload if item["attempt"]["status"] != "submitted"),
            },
            "exams": exams_payload,
        }
    )


@csrf_exempt
@require_POST
def mobile_exam_start(request, pk):
    student, error = _student_for_request(request)
    if error:
        return error
    payload = _request_data(request)
    exam = (
        Exam.objects.filter(pk=pk, is_published=True)
        .select_related("batch", "academic_year", "subject", "created_by")
        .prefetch_related("questions", "questions__options")
        .first()
    )
    if not exam:
        return JsonResponse({"detail": "Exam is not available."}, status=404)
    academic_session = None
    academic_session_id = payload.get("academic_session_id")
    if academic_session_id:
        academic_session = (
            StudentAcademicSession.objects.filter(
                pk=academic_session_id,
                student=student,
                academic_year=exam.academic_year,
                status=StudentAcademicSession.Status.ACTIVE,
                enrollments__batch=exam.batch,
                enrollments__status=StudentEnrollment.Status.ACTIVE,
            )
            .select_related("academic_year")
            .first()
        )
    academic_session = academic_session or _student_exam_session_for_exam(student, exam)
    if not academic_session:
        return JsonResponse({"detail": "This exam is not assigned to your selected academic session."}, status=404)
    attempt, _created = ExamAttempt.objects.get_or_create(
        exam=exam,
        academic_session=academic_session,
        defaults={"student": student, "total_marks": exam.total_marks},
    )
    if attempt.student_id != student.pk:
        return JsonResponse({"detail": "This attempt belongs to another student."}, status=403)
    if attempt.is_submitted:
        return JsonResponse({"detail": "This exam has already been submitted."}, status=400)
    return JsonResponse(_mobile_attempt_payload(request, attempt))


@csrf_exempt
@require_POST
def mobile_exam_rough_work_upload(request, attempt_id):
    student, error = _student_for_request(request)
    if error:
        return error
    attempt = get_object_or_404(
        ExamAttempt.objects.select_related("exam", "student"),
        pk=attempt_id,
        student=student,
    )
    if attempt.is_submitted:
        return JsonResponse({"detail": "This exam has already been submitted."}, status=400)
    if not attempt.exam.allow_rough_work_uploads:
        return JsonResponse({"detail": "Rough-work uploads are not allowed for this exam."}, status=403)

    image = request.FILES.get("image")
    if not image:
        return JsonResponse({"detail": "Upload an image file."}, status=400)
    if not (image.content_type or "").startswith("image/"):
        return JsonResponse({"detail": "Only image uploads are allowed."}, status=400)

    question = None
    question_id = request.POST.get("question_id")
    if question_id:
        question = attempt.exam.questions.filter(pk=question_id).first()
        if not question:
            return JsonResponse({"detail": "Question does not belong to this exam."}, status=400)

    upload = ExamAttemptUpload.objects.create(attempt=attempt, question=question, image=image)
    return JsonResponse(
        {
            "id": upload.pk,
            "attempt_id": attempt.pk,
            "question_id": upload.question_id,
            "image_url": _absolute_media_url(request, upload.image),
            "uploaded_at": _datetime(upload.uploaded_at),
        },
        status=201,
    )


@csrf_exempt
@require_POST
def mobile_exam_submit(request, attempt_id):
    student, error = _student_for_request(request)
    if error:
        return error
    payload = _json_body(request)
    if payload is None:
        return JsonResponse({"detail": "Invalid JSON payload."}, status=400)
    attempt = get_object_or_404(
        ExamAttempt.objects.select_related("exam", "academic_session", "student"),
        pk=attempt_id,
        student=student,
    )
    if attempt.is_submitted:
        return JsonResponse({"detail": "This exam has already been submitted."}, status=400)

    questions = list(attempt.exam.questions.prefetch_related("options"))
    answer_map = {}
    for answer in payload.get("answers", []):
        if not isinstance(answer, dict):
            continue
        question_id = answer.get("question_id")
        option_id = answer.get("option_id")
        if question_id is not None:
            answer_map[str(question_id)] = option_id

    score = 0
    correct_count = 0
    wrong_count = 0
    unattempted_count = 0
    total_marks = sum(question.marks for question in questions)
    for question in questions:
        option_id = answer_map.get(str(question.pk))
        selected_option = question.options.filter(pk=option_id).first() if option_id else None
        is_correct = bool(selected_option and selected_option.is_correct)
        marks_awarded = question.marks if is_correct else 0
        if selected_option is None:
            unattempted_count += 1
        elif is_correct:
            correct_count += 1
            score += question.marks
        else:
            wrong_count += 1
        ExamQuestionAttempt.objects.update_or_create(
            attempt=attempt,
            question=question,
            defaults={
                "selected_option": selected_option,
                "is_correct": is_correct,
                "marks_awarded": marks_awarded,
            },
        )

    activities = []
    for event in payload.get("activities", []):
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("event_type") or "").strip()[:50]
        if not event_type:
            continue
        occurred_at = parse_datetime(str(event.get("occurred_at") or "")) or timezone.now()
        if timezone.is_naive(occurred_at):
            occurred_at = timezone.make_aware(occurred_at)
        activities.append(
            ExamAttemptActivity(
                attempt=attempt,
                event_type=event_type,
                detail=str(event.get("detail") or "").strip()[:255],
                occurred_at=occurred_at,
            )
        )
    if activities:
        ExamAttemptActivity.objects.bulk_create(activities)

    attempt.score = score
    attempt.total_marks = total_marks
    attempt.correct_count = correct_count
    attempt.wrong_count = wrong_count
    attempt.unattempted_count = unattempted_count
    attempt.submitted_at = timezone.now()
    attempt.save()
    ExamResult.objects.update_or_create(
        exam=attempt.exam,
        student=student,
        defaults={
            "marks_obtained": score,
            "remark": "Generated automatically from MCQ exam.",
        },
    )
    return JsonResponse(
        {
            "attempt": {
                "id": attempt.pk,
                "submitted_at": _datetime(attempt.submitted_at),
                "score": str(attempt.score),
                "total_marks": str(attempt.total_marks),
                "correct_count": attempt.correct_count,
                "wrong_count": attempt.wrong_count,
                "unattempted_count": attempt.unattempted_count,
                "activity_count": len(activities),
                "can_view_result": attempt.exam.show_result_after_submit,
            }
        }
    )


@require_GET
def mobile_exam_result(request, attempt_id):
    student, error = _student_for_request(request)
    if error:
        return error
    attempt = get_object_or_404(
        ExamAttempt.objects.select_related("exam", "exam__batch", "exam__academic_year", "exam__subject", "student")
        .prefetch_related("exam__questions", "exam__questions__options", "question_attempts"),
        pk=attempt_id,
        student=student,
        submitted_at__isnull=False,
    )
    if not attempt.exam.show_result_after_submit:
        return JsonResponse({"detail": "Result is not published yet."}, status=403)
    return JsonResponse(_mobile_result_payload(request, attempt))


def _api_user(request):
    if request.user.is_authenticated:
        return request.user
    return bearer_user(request)


def _unauthorized():
    return JsonResponse({"detail": "Invalid or expired access token."}, status=401)


def _json_request_data(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return None


def _student_for_request(request):
    user = _api_user(request)
    if not user:
        return None, _unauthorized()

    profile = getattr(user, "profile", None)
    role = profile.role if profile else None
    requested_student_id = request.GET.get("student_id")

    if role == UserProfile.Role.STUDENT_PARENT:
        student = getattr(user, "student_profile", None)
        if not student:
            return None, JsonResponse({"detail": "No student profile is linked to this user."}, status=404)
        if requested_student_id and str(student.pk) != str(requested_student_id):
            return None, JsonResponse({"detail": "You can view only your own homework planner."}, status=403)
        return student, None

    if role in [UserProfile.Role.INSTITUTE_ADMIN, UserProfile.Role.TEACHER] or user.is_superuser:
        if not requested_student_id:
            return None, JsonResponse({"detail": "student_id query parameter is required."}, status=400)
        queryset = StudentProfile.objects.select_related("user", "institute")
        if profile and profile.institute_id:
            queryset = queryset.filter(institute=profile.institute)
        return get_object_or_404(queryset, pk=requested_student_id), None

    return None, JsonResponse({"detail": "You are not allowed to view homework planner."}, status=403)


def _date(value):
    return value.isoformat() if value else None


def _datetime(value):
    return value.isoformat() if value else None


def _attendance_payload(student, request):
    today = date.today()
    date_to = parse_date(request.GET.get("date_to", "")) or today
    date_from = parse_date(request.GET.get("date_from", "")) or (date_to - timedelta(days=89))
    if date_from > date_to:
        date_from, date_to = date_to, date_from

    status_filter = (request.GET.get("status") or "").strip().upper()
    batch_id = (request.GET.get("batch_id") or "").strip()
    try:
        limit = min(max(int(request.GET.get("limit", 90)), 1), 180)
    except (TypeError, ValueError):
        limit = 90

    selected_session = _selected_academic_session(student, request)
    sessions = (
        StudentAcademicSession.objects.filter(student=student)
        .select_related("academic_year", "institute")
        .order_by("-academic_year__start_date", "-pk")
    )
    if selected_session:
        sessions = sessions.filter(pk=selected_session.pk)
    records = (
        Attendance.objects.filter(
            academic_session__in=sessions,
            date__gte=date_from,
            date__lte=date_to,
        )
        .select_related(
            "academic_session",
            "academic_session__academic_year",
            "batch",
            "batch__academic_year",
            "marked_by",
        )
        .order_by("-date", "batch__name")
    )
    if status_filter in Attendance.Status.values:
        records = records.filter(status=status_filter)
    else:
        status_filter = ""
    if batch_id:
        records = records.filter(batch_id=batch_id)

    record_list = list(records)
    total = len(record_list)
    present = sum(1 for record in record_list if record.status == Attendance.Status.PRESENT)
    absent = sum(1 for record in record_list if record.status == Attendance.Status.ABSENT)
    late = sum(1 for record in record_list if record.status == Attendance.Status.LATE)
    attended = present + late
    attendance_rate = round((attended / total) * 100, 1) if total else 0
    present_rate = round((present / total) * 100, 1) if total else 0

    batch_groups = {}
    for record in record_list:
        group = batch_groups.setdefault(
            record.batch_id,
            {
                "id": record.batch_id,
                "name": record.batch.name,
                "academic_year": record.batch.academic_year.name if record.batch.academic_year_id else "",
                "total_count": 0,
                "present_count": 0,
                "absent_count": 0,
                "late_count": 0,
                "attendance_rate": 0,
            },
        )
        group["total_count"] += 1
        if record.status == Attendance.Status.PRESENT:
            group["present_count"] += 1
        elif record.status == Attendance.Status.ABSENT:
            group["absent_count"] += 1
        elif record.status == Attendance.Status.LATE:
            group["late_count"] += 1

    for group in batch_groups.values():
        attended_count = group["present_count"] + group["late_count"]
        group["attendance_rate"] = round((attended_count / group["total_count"]) * 100, 1) if group["total_count"] else 0

    return {
        "student": {
            "id": student.pk,
            "username": student.user.username,
            "name": student.user.get_full_name() or student.user.username,
            "admission_number": student.admission_number,
        },
        "filters": {
            "date_from": _date(date_from),
            "date_to": _date(date_to),
            "status": status_filter,
            "batch_id": batch_id,
            "limit": limit,
        },
        "summary": {
            "total_count": total,
            "present_count": present,
            "absent_count": absent,
            "late_count": late,
            "attended_count": attended,
            "attendance_rate": attendance_rate,
            "present_rate": present_rate,
        },
        "status_choices": [{"value": value, "label": label} for value, label in Attendance.Status.choices],
        "batch_wise": list(batch_groups.values()),
        "records": [
            {
                "id": record.pk,
                "date": _date(record.date),
                "status": record.status,
                "status_label": record.get_status_display(),
                "note": record.note,
                "batch": {
                    "id": record.batch_id,
                    "name": record.batch.name,
                    "academic_year": record.batch.academic_year.name if record.batch.academic_year_id else "",
                },
                "academic_session": {
                    "id": record.academic_session_id,
                    "admission_number": record.academic_session.admission_number,
                    "academic_year": record.academic_session.academic_year.name if record.academic_session.academic_year_id else "",
                },
                "marked_by": record.marked_by.get_full_name() or record.marked_by.username if record.marked_by_id else "",
            }
            for record in record_list[:limit]
        ],
    }


@require_GET
def mobile_attendance(request):
    student, error = _student_for_request(request)
    if error:
        return error
    return JsonResponse(_attendance_payload(student, request))


def _notice_payload(notice, read_ids):
    return {
        "id": notice.pk,
        "title": notice.title,
        "message": strip_tags(notice.message or "").strip(),
        "html_message": notice.message,
        "category": notice.category,
        "category_label": notice.get_category_display(),
        "priority": notice.priority,
        "priority_label": notice.get_priority_display(),
        "audience": notice.audience,
        "audience_label": notice.get_audience_display(),
        "publish_at": _datetime(notice.publish_at),
        "expires_at": _datetime(notice.expires_at),
        "created_at": _datetime(notice.created_at),
        "pin_on_top": notice.pin_on_top,
        "is_read": notice.pk in read_ids,
        "created_by": notice.created_by.get_full_name() or notice.created_by.username if notice.created_by_id else "",
    }


def _mobile_notices_payload(student, request):
    selected_session = _selected_academic_session(student, request)
    notices = (
        Notice.for_student(
            student,
            academic_session_id=selected_session.pk if selected_session else None,
        )
        .select_related("created_by")
        .prefetch_related("target_batches", "target_courses", "target_students")
    )
    all_notices = list(notices)
    read_ids = set(
        NoticeRead.objects.filter(user=student.user, notice__in=all_notices).values_list("notice_id", flat=True)
    )

    category = (request.GET.get("category") or "").strip().upper()
    priority = (request.GET.get("priority") or "").strip().upper()
    unread_only = (request.GET.get("unread") or "").strip().lower() in {"1", "true", "yes"}
    search = (request.GET.get("search") or "").strip().lower()
    try:
        limit = min(max(int(request.GET.get("limit", 50)), 1), 100)
    except (TypeError, ValueError):
        limit = 50

    filtered = all_notices
    if category in Notice.Category.values:
        filtered = [notice for notice in filtered if notice.category == category]
    else:
        category = ""
    if priority in Notice.Priority.values:
        filtered = [notice for notice in filtered if notice.priority == priority]
    else:
        priority = ""
    if unread_only:
        filtered = [notice for notice in filtered if notice.pk not in read_ids]
    if search:
        filtered = [
            notice
            for notice in filtered
            if search in notice.title.lower() or search in strip_tags(notice.message or "").lower()
        ]

    urgent_count = sum(1 for notice in all_notices if notice.priority == Notice.Priority.URGENT)
    pinned_count = sum(1 for notice in all_notices if notice.pin_on_top)
    category_counts = {}
    for notice in all_notices:
        row = category_counts.setdefault(
            notice.category,
            {"value": notice.category, "label": notice.get_category_display(), "count": 0},
        )
        row["count"] += 1

    return {
        "student": {
            "id": student.pk,
            "admission_number": student.admission_number,
            "name": student.user.get_full_name() or student.user.username,
            "username": student.user.username,
            "institute": {"id": student.institute_id, "name": student.institute.name},
        },
        "filters": {
            "category": category,
            "priority": priority,
            "unread": unread_only,
            "search": search,
            "limit": limit,
            "academic_session_id": selected_session.pk if selected_session else None,
        },
        "summary": {
            "total_count": len(all_notices),
            "unread_count": len([notice for notice in all_notices if notice.pk not in read_ids]),
            "urgent_count": urgent_count,
            "pinned_count": pinned_count,
        },
        "category_choices": [{"value": value, "label": label} for value, label in Notice.Category.choices],
        "priority_choices": [{"value": value, "label": label} for value, label in Notice.Priority.choices],
        "category_counts": list(category_counts.values()),
        "notices": [_notice_payload(notice, read_ids) for notice in filtered[:limit]],
    }


@require_GET
def mobile_notices(request):
    student, error = _student_for_request(request)
    if error:
        return error
    return JsonResponse(_mobile_notices_payload(student, request))


@csrf_exempt
@require_POST
def mobile_notice_mark_read(request, notice_id):
    student, error = _student_for_request(request)
    if error:
        return error
    notice = get_object_or_404(Notice.for_student(student), pk=notice_id)
    receipt, _created = NoticeRead.objects.get_or_create(notice=notice, user=student.user)
    return JsonResponse({"detail": "Notice marked as read.", "notice_id": notice.pk, "read_at": _datetime(receipt.read_at)})


def _homework_document_url(request):
    session_id = (request.GET.get("academic_session_id") or "").strip()
    path = "/api/mobile/homework/document/download/"
    if session_id:
        path = f"{path}?academic_session_id={session_id}"
    return request.build_absolute_uri(path)


def _student_homework_queryset(student, request):
    enrollments = (
        StudentEnrollment.objects.filter(
            student=student,
            status=StudentEnrollment.Status.ACTIVE,
            academic_session__status="ACTIVE",
        )
        .select_related("batch", "batch__academic_year")
        .prefetch_related("courses")
    )
    selected_session = _selected_academic_session(student, request)
    if selected_session:
        enrollments = enrollments.filter(academic_session=selected_session)
    batch_ids = enrollments.values_list("batch_id", flat=True)
    course_ids = enrollments.values_list("courses__id", flat=True)
    queryset = (
        Homework.objects.filter(batch_id__in=batch_ids)
        .filter(course__isnull=True) | Homework.objects.filter(batch_id__in=batch_ids, course_id__in=course_ids)
    )
    academic_year_id = request.GET.get("academic_year_id")
    batch_id = request.GET.get("batch_id")
    subject_id = request.GET.get("subject_id")
    course_id = request.GET.get("course_id")
    if academic_year_id:
        queryset = queryset.filter(batch__academic_year_id=academic_year_id)
    if batch_id:
        queryset = queryset.filter(batch_id=batch_id)
    if subject_id:
        queryset = queryset.filter(subject_id=subject_id)
    if course_id:
        queryset = queryset.filter(course_id=course_id)
    return (
        queryset.select_related("batch", "batch__academic_year", "subject", "course", "created_by")
        .prefetch_related("attachments")
        .distinct()
        .order_by("due_date", "-created_at")
    )


def _attachment_payload(attachment, request):
    return {
        "id": attachment.pk,
        "file_name": attachment.file.name.rsplit("/", 1)[-1],
        "file_url": request.build_absolute_uri(attachment.file.url) if attachment.file else "",
        "uploaded_at": _datetime(attachment.uploaded_at),
    }


def _homework_payload(homework, request):
    teacher_name = ""
    if homework.created_by_id:
        teacher_name = homework.created_by.get_full_name() or homework.created_by.username
    return {
        "id": homework.pk,
        "title": homework.title,
        "instructions": homework.instructions,
        "due_date": _date(homework.due_date),
        "created_at": _datetime(homework.created_at),
        "teacher_name": teacher_name,
        "batch": {
            "id": homework.batch_id,
            "name": homework.batch.name,
            "academic_year": homework.batch.academic_year.name if homework.batch.academic_year_id else "",
        },
        "subject": {
            "id": homework.subject_id or homework.course_id,
            "name": homework.subject.name if homework.subject_id else homework.course.name if homework.course_id else "General",
        },
        "course": {
            "id": homework.course_id,
            "name": homework.course.name if homework.course_id else "",
        },
        "attachments": [_attachment_payload(attachment, request) for attachment in homework.attachments.all()],
    }


def _homework_planner_payload(student, request):
    homework_items = [_homework_payload(homework, request) for homework in _student_homework_queryset(student, request)]
    subject_groups = {}
    batch_groups = {}

    for item in homework_items:
        subject = item["subject"]
        subject_key = str(subject["id"] or 0)
        subject_row = subject_groups.setdefault(
            subject_key,
            {"id": subject["id"], "name": subject["name"], "homework_count": 0, "items": []},
        )
        subject_row["homework_count"] += 1
        subject_row["items"].append(item)

        batch = item["batch"]
        batch_key = str(batch["id"])
        batch_row = batch_groups.setdefault(
            batch_key,
            {"id": batch["id"], "name": batch["name"], "academic_year": batch["academic_year"], "homework_count": 0},
        )
        batch_row["homework_count"] += 1

    return {
        "student": {
            "id": student.pk,
            "admission_number": student.admission_number,
            "name": student.user.get_full_name() or student.user.username,
            "username": student.user.username,
            "institute": {"id": student.institute_id, "name": student.institute.name},
        },
        "summary": {
            "homework_count": len(homework_items),
            "subject_count": len(subject_groups),
            "batch_count": len(batch_groups),
        },
        "document_download_url": _homework_document_url(request),
        "subject_wise": list(subject_groups.values()),
        "batch_wise": list(batch_groups.values()),
        "homework": homework_items,
    }


@require_GET
def mobile_homework_planner(request):
    student, error = _student_for_request(request)
    if error:
        return error
    return JsonResponse(_homework_planner_payload(student, request))


@csrf_exempt
@require_POST
def mobile_register_device(request):
    user = _api_user(request)
    if not user:
        return _unauthorized()
    data = _json_request_data(request)
    if data is None:
        return JsonResponse({"detail": "Invalid JSON body."}, status=400)

    token = (data.get("token") or "").strip()
    if not token:
        return JsonResponse({"detail": "Device token is required."}, status=400)
    platform = (data.get("platform") or UserDevice.Platform.UNKNOWN).upper()
    if platform not in UserDevice.Platform.values:
        platform = UserDevice.Platform.UNKNOWN

    device, _created = UserDevice.objects.update_or_create(
        token=token,
        defaults={
            "user": user,
            "platform": platform,
            "device_id": (data.get("device_id") or "").strip(),
            "app_version": (data.get("app_version") or "").strip(),
            "is_active": True,
        },
    )
    return JsonResponse({"detail": "Device registered.", "device_id": device.pk})


@csrf_exempt
@require_POST
def mobile_unregister_device(request):
    user = _api_user(request)
    if not user:
        return _unauthorized()
    data = _json_request_data(request)
    if data is None:
        return JsonResponse({"detail": "Invalid JSON body."}, status=400)
    token = (data.get("token") or "").strip()
    if not token:
        return JsonResponse({"detail": "Device token is required."}, status=400)
    UserDevice.objects.filter(user=user, token=token).update(is_active=False)
    return JsonResponse({"detail": "Device unregistered."})


@require_GET
def mobile_notifications(request):
    user = _api_user(request)
    if not user:
        return _unauthorized()
    notifications = PushNotification.objects.filter(user=user)[:50]
    return JsonResponse(
        {
            "notifications": [
                {
                    "id": notification.pk,
                    "type": notification.notification_type,
                    "title": notification.title,
                    "body": notification.body,
                    "data": notification.data,
                    "status": notification.status,
                    "created_at": _datetime(notification.created_at),
                    "sent_at": _datetime(notification.sent_at),
                }
                for notification in notifications
            ]
        }
    )


def _html_escape(value):
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


@require_GET
def mobile_homework_document_download(request):
    student, error = _student_for_request(request)
    if error:
        return error
    payload = _homework_planner_payload(student, request)
    rows = []
    for subject in payload["subject_wise"]:
        rows.append(f"<h2>{_html_escape(subject['name'])}</h2>")
        for item in subject["items"]:
            attachment_links = ", ".join(
                f"<a href=\"{_html_escape(attachment['file_url'])}\">{_html_escape(attachment['file_name'])}</a>"
                for attachment in item["attachments"]
            ) or "-"
            rows.append(
                "<div class=\"card\">"
                f"<h3>{_html_escape(item['title'])}</h3>"
                f"<p><strong>Batch:</strong> {_html_escape(item['batch']['name'])} "
                f"({_html_escape(item['batch']['academic_year'])})</p>"
                f"<p><strong>Due:</strong> {_html_escape(item['due_date'] or '-')}</p>"
                f"<p><strong>Teacher:</strong> {_html_escape(item['teacher_name'] or '-')}</p>"
                f"<p>{_html_escape(item['instructions'] or 'No instructions added.')}</p>"
                f"<p><strong>Attachments:</strong> {attachment_links}</p>"
                "</div>"
            )
    html = (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<title>Homework Planner</title>"
        "<style>body{font-family:Arial,sans-serif;color:#111640;margin:32px;}"
        "h1{margin-bottom:4px;}h2{border-bottom:1px solid #d8def2;padding-bottom:8px;}"
        ".muted{color:#65708a}.card{border:1px solid #d8def2;border-radius:8px;padding:14px;margin:12px 0;}"
        "</style></head><body>"
        f"<h1>Homework Planner</h1><p class=\"muted\">{_html_escape(payload['student']['name'])} - "
        f"{_html_escape(payload['student']['admission_number'])}</p>"
        + "".join(rows)
        + "</body></html>"
    )
    filename = f"homework-planner-{student.admission_number or student.pk}.html"
    response = HttpResponse(html, content_type="text/html")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
