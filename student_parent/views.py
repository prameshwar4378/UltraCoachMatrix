import json

from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_POST

from super_admin.decorators import student_parent_required
from super_admin.mobile_auth import bearer_user
from super_admin.models import UserProfile
from teacher.models import Homework

from .models import PushNotification, StudentEnrollment, StudentProfile, UserDevice


@student_parent_required
def download_app(request):
    return render(request, "student_parent/download_app.html")


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


def _homework_document_url(request):
    return request.build_absolute_uri("/api/mobile/homework/document/download/")


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
    batch_ids = enrollments.values_list("batch_id", flat=True)
    course_ids = enrollments.values_list("courses__id", flat=True)
    queryset = (
        Homework.objects.filter(batch_id__in=batch_ids)
        .filter(course__isnull=True) | Homework.objects.filter(batch_id__in=batch_ids, course_id__in=course_ids)
    )
    academic_year_id = request.GET.get("academic_year_id")
    batch_id = request.GET.get("batch_id")
    subject_id = request.GET.get("course_id")
    if academic_year_id:
        queryset = queryset.filter(batch__academic_year_id=academic_year_id)
    if batch_id:
        queryset = queryset.filter(batch_id=batch_id)
    if subject_id:
        queryset = queryset.filter(course_id=subject_id)
    return (
        queryset.select_related("batch", "batch__academic_year", "course", "created_by")
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
            "id": homework.course_id,
            "name": homework.course.name if homework.course_id else "General",
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
