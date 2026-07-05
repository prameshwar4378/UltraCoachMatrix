import json
import logging
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.db.models import Q
from django.utils import timezone
from django.utils.html import strip_tags

from institute_admin.models import BackgroundJob, Notice

from .models import PushNotification, StudentEnrollment, StudentProfile, UserDevice

logger = logging.getLogger(__name__)
FIREBASE_MULTICAST_LIMIT = 500
ANDROID_NOTIFICATION_CHANNEL_ID = "ultracoachmatrix_notifications"
ANDROID_NOTIFICATION_COLOR = "#0700A8"
NOTICE_PUSH_PREVIEW_LENGTH = 180

INVALID_TOKEN_ERROR_MARKERS = (
    "registration-token-not-registered",
    "requested entity was not found",
    "invalid registration token",
    "sender id",
)


def firebase_configuration_status():
    if not getattr(settings, "PUSH_NOTIFICATIONS_ENABLED", True):
        return {
            "ready": False,
            "enabled": False,
            "detail": "Push notifications are disabled.",
        }

    try:
        import firebase_admin
        from firebase_admin import credentials
    except ImportError:
        return {
            "ready": False,
            "enabled": True,
            "detail": "firebase-admin package is not installed.",
        }

    credentials_file = str(getattr(settings, "FIREBASE_CREDENTIALS_FILE", "") or "").strip()
    if not credentials_file:
        return {
            "ready": False,
            "enabled": True,
            "firebase_admin_installed": True,
            "detail": "FIREBASE_CREDENTIALS_FILE is not configured.",
        }

    credentials_path = Path(credentials_file).expanduser()
    if not credentials_path.exists():
        return {
            "ready": False,
            "enabled": True,
            "firebase_admin_installed": True,
            "credentials_file": str(credentials_path),
            "detail": "Firebase credentials file does not exist.",
        }

    project_id = getattr(settings, "FIREBASE_PROJECT_ID", "") or ""
    try:
        with credentials_path.open(encoding="utf-8") as handle:
            credential_data = json.load(handle)
    except OSError:
        return {
            "ready": False,
            "enabled": True,
            "firebase_admin_installed": True,
            "credentials_file": str(credentials_path),
            "detail": "Firebase credentials file could not be read.",
        }
    except json.JSONDecodeError:
        return {
            "ready": False,
            "enabled": True,
            "firebase_admin_installed": True,
            "credentials_file": str(credentials_path),
            "detail": "Firebase credentials file is not valid JSON.",
        }

    project_id = project_id or credential_data.get("project_id", "")
    private_key = str(credential_data.get("private_key") or "")
    client_email = str(credential_data.get("client_email") or "")
    if credential_data.get("type") != "service_account":
        return {
            "ready": False,
            "enabled": True,
            "firebase_admin_installed": True,
            "credentials_file": str(credentials_path),
            "project_id": project_id,
            "detail": "Firebase credentials file must be a service-account JSON file.",
        }
    if not client_email:
        return {
            "ready": False,
            "enabled": True,
            "firebase_admin_installed": True,
            "credentials_file": str(credentials_path),
            "project_id": project_id,
            "detail": "Firebase credentials file is missing client_email.",
        }
    if "BEGIN PRIVATE KEY" not in private_key or "END PRIVATE KEY" not in private_key:
        return {
            "ready": False,
            "enabled": True,
            "firebase_admin_installed": True,
            "credentials_file": str(credentials_path),
            "project_id": project_id,
            "detail": "Firebase credentials file is missing a valid private_key.",
        }

    return {
        "ready": True,
        "enabled": True,
        "firebase_admin_installed": True,
        "credentials_file": str(credentials_path),
        "project_id": project_id,
        "detail": "Firebase push notifications are configured.",
    }


def _firebase_messaging():
    status = firebase_configuration_status()
    if not status["ready"]:
        return None, status["detail"]

    import firebase_admin
    from firebase_admin import credentials, messaging

    if not firebase_admin._apps:
        try:
            options = {}
            if status.get("project_id"):
                options["projectId"] = status["project_id"]
            firebase_admin.initialize_app(
                credentials.Certificate(status["credentials_file"]),
                options=options or None,
            )
        except Exception as exc:
            return None, str(exc)
    return messaging, ""


def send_push_to_user(user, notification_type, title, body, data=None):
    payload = {key: str(value) for key, value in (data or {}).items() if value is not None}
    payload.setdefault("title", title)
    payload.setdefault("body", body)
    payload.setdefault("created_at", timezone.now().isoformat())
    record = PushNotification.objects.create(
        user=user,
        notification_type=notification_type,
        title=title,
        body=body,
        data=payload,
    )
    payload["notification_id"] = str(record.pk)
    record.data = payload
    record.save(update_fields=["data"])
    devices = list(UserDevice.objects.filter(user=user, is_active=True))
    if not devices:
        record.status = PushNotification.Status.SKIPPED
        record.error_message = "No active device token registered for this user."
        record.save(update_fields=["status", "error_message"])
        return record

    messaging, error = _firebase_messaging()
    if messaging is None:
        record.status = PushNotification.Status.SKIPPED
        record.error_message = error
        record.save(update_fields=["status", "error_message"])
        return record

    sent_ids = []
    errors = []
    logo_url = payload.get("institute_logo_url") or None
    for device in devices:
        message = messaging.Message(
            token=device.token,
            notification=messaging.Notification(title=title, body=body),
            data=payload,
            android=messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(
                    channel_id=ANDROID_NOTIFICATION_CHANNEL_ID,
                    icon="ic_stat_notification",
                    color=ANDROID_NOTIFICATION_COLOR,
                    image=logo_url,
                    sound="default",
                    tag=f"ucm-{notification_type.lower()}-{user.pk}",
                    default_vibrate_timings=True,
                    visibility="public",
                ),
            ),
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(aps=messaging.Aps(sound="default"))
            ),
        )
        try:
            sent_ids.append(messaging.send(message))
        except Exception as exc:
            error_message = str(exc)
            errors.append(f"{device.platform}:{device.pk}: {error_message}")
            if _is_invalid_token_error(error_message):
                device.is_active = False
                device.save(update_fields=["is_active", "updated_at"])
                logger.info("Deactivated invalid FCM token for device %s.", device.pk)

    if sent_ids:
        record.status = PushNotification.Status.SENT
        record.firebase_message_id = ",".join(sent_ids)[:255]
        record.sent_at = timezone.now()
        if errors:
            record.error_message = "; ".join(errors)
            update_fields = ["status", "firebase_message_id", "sent_at", "error_message"]
        else:
            update_fields = ["status", "firebase_message_id", "sent_at"]
    else:
        record.status = PushNotification.Status.FAILED
        record.error_message = "; ".join(errors)
        update_fields = ["status", "error_message"]
    record.save(update_fields=update_fields)
    return record


def _absolute_logo_url(institute):
    if not institute or not getattr(institute, "logo", None):
        return ""
    try:
        logo_url = institute.logo.url
    except ValueError:
        return ""
    base_url = str(getattr(settings, "EMAIL_BASE_URL", "") or "").rstrip("/")
    if not base_url:
        return logo_url
    return f"{base_url}{logo_url}"


def _institute_payload(institute):
    if not institute:
        return {}
    return {
        "institute_id": institute.pk,
        "institute_name": institute.name,
        "institute_logo_url": _absolute_logo_url(institute),
    }


def _is_invalid_token_error(error_message):
    normalized = error_message.lower()
    return any(marker in normalized for marker in INVALID_TOKEN_ERROR_MARKERS)


def notify_fee_paid(payment):
    invoice = payment.invoice
    student = invoice.student
    title = "Fee payment received"
    body = f"Payment of Rs. {payment.amount} received for {invoice.title}. Receipt: {payment.receipt_number or payment.pk}."
    return send_push_to_user(
        student.user,
        PushNotification.NotificationType.FEE_PAID,
        title,
        body,
        {
            "type": PushNotification.NotificationType.FEE_PAID,
            "route": "fees",
            "action": "OPEN_FEES",
            "payment_id": payment.pk,
            "invoice_id": invoice.pk,
            "student_id": student.pk,
            "receipt_number": payment.receipt_number,
            "amount": payment.amount,
            **_institute_payload(invoice.institute),
        },
    )


def notify_result_declared(result):
    exam = result.exam
    student = result.student
    title = "Result declared"
    body = f"{exam.title} result is available. Marks: {result.marks_obtained}/{exam.total_marks}."
    return send_push_to_user(
        student.user,
        PushNotification.NotificationType.RESULT_DECLARED,
        title,
        body,
        {
            "type": PushNotification.NotificationType.RESULT_DECLARED,
            "route": "results",
            "action": "OPEN_RESULTS",
            "result_id": result.pk,
            "exam_id": exam.pk,
            "student_id": student.pk,
            "marks_obtained": result.marks_obtained,
            "total_marks": exam.total_marks,
            **_institute_payload(student.institute),
        },
    )


def notify_exam_results_declared(exam):
    from teacher.models import ExamResult

    exam_id = exam.pk if hasattr(exam, "pk") else exam
    results = ExamResult.objects.filter(exam_id=exam_id).select_related(
        "exam",
        "student__user",
    )
    return [notify_result_declared(result) for result in results]


def students_for_notice(notice):
    queryset = StudentProfile.objects.filter(institute=notice.institute, is_active=True).select_related("user")
    if notice.audience == Notice.Audience.TEACHERS:
        return queryset.none()
    if notice.academic_year_id:
        queryset = queryset.filter(academic_sessions__academic_year=notice.academic_year)

    student_ids = set(notice.target_students.values_list("pk", flat=True))
    batch_ids = list(notice.target_batches.values_list("pk", flat=True))
    course_ids = list(notice.target_courses.values_list("pk", flat=True))
    if batch_ids or course_ids:
        enrollment_filter = Q(status=StudentEnrollment.Status.ACTIVE)
        if notice.academic_year_id:
            enrollment_filter &= Q(academic_session__academic_year=notice.academic_year)
        if batch_ids:
            enrollment_filter &= Q(batch_id__in=batch_ids)
        if course_ids:
            enrollment_filter &= Q(courses__id__in=course_ids)
        student_ids.update(
            StudentEnrollment.objects.filter(enrollment_filter).values_list("student_id", flat=True)
        )

    if student_ids:
        return queryset.filter(pk__in=student_ids).distinct()

    return queryset


def _chunks(items, size):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _notice_multicast_message(messaging, notice, tokens):
    preview = strip_tags(notice.message or "").strip()
    if len(preview) > NOTICE_PUSH_PREVIEW_LENGTH:
        preview = f"{preview[:NOTICE_PUSH_PREVIEW_LENGTH - 1].rstrip()}…"
    payload = {
        "type": PushNotification.NotificationType.NOTICE,
        "route": "notices",
        "action": "OPEN_NOTICE",
        "notice_id": str(notice.pk),
        "category": str(notice.category),
        "priority": str(notice.priority),
        "category_label": notice.get_category_display(),
        "priority_label": notice.get_priority_display(),
        **_institute_payload(notice.institute),
    }
    payload = {key: str(value) for key, value in payload.items() if value is not None}
    return messaging.MulticastMessage(
        tokens=tokens,
        notification=messaging.Notification(
            title=notice.title,
            body=preview,
        ),
        data=payload,
        android=messaging.AndroidConfig(
            priority="high",
                notification=messaging.AndroidNotification(
                    channel_id=ANDROID_NOTIFICATION_CHANNEL_ID,
                    icon="ic_stat_notification",
                    color=ANDROID_NOTIFICATION_COLOR,
                    image=payload.get("institute_logo_url") or None,
                    sound="default",
                tag=f"ucm-notice-{notice.pk}",
                default_vibrate_timings=True,
                visibility="public",
            ),
        ),
        apns=messaging.APNSConfig(
            payload=messaging.APNSPayload(
                aps=messaging.Aps(sound="default")
            )
        ),
    )


def _finalize_notice_records(records, devices_by_user, deliveries, configuration_error=""):
    sent_at = timezone.now()
    for record in records:
        devices = devices_by_user.get(record.user_id, [])
        delivery = deliveries.get(record.user_id, {"sent_ids": [], "errors": []})
        sent_ids = delivery["sent_ids"]
        errors = delivery["errors"]

        if not devices:
            record.status = PushNotification.Status.SKIPPED
            record.error_message = "No active device token registered for this user."
        elif configuration_error:
            record.status = PushNotification.Status.SKIPPED
            record.error_message = configuration_error
        elif sent_ids:
            record.status = PushNotification.Status.SENT
            record.firebase_message_id = ",".join(sent_ids)[:255]
            record.sent_at = sent_at
            record.error_message = "; ".join(errors)
        else:
            record.status = PushNotification.Status.FAILED
            record.error_message = "; ".join(errors) or "Firebase did not accept the notification."

    PushNotification.objects.bulk_update(
        records,
        [
            "status",
            "firebase_message_id",
            "error_message",
            "sent_at",
        ],
        batch_size=500,
    )


def notify_notice_published(notice):
    if not notice.push_to_app or not notice.is_published or not notice.is_active_for_app:
        return []

    students = list(students_for_notice(notice))
    if not students:
        return []

    records = PushNotification.objects.bulk_create(
        [
            PushNotification(
                user=student.user,
                notification_type=PushNotification.NotificationType.NOTICE,
                title=notice.title,
                body=notice.message,
                data={
                    "type": PushNotification.NotificationType.NOTICE,
                    "route": "notices",
                    "action": "OPEN_NOTICE",
                    "notice_id": str(notice.pk),
                    "category": str(notice.category),
                    "priority": str(notice.priority),
                    "category_label": notice.get_category_display(),
                    "priority_label": notice.get_priority_display(),
                    "title": notice.title,
                    "body": notice.message,
                    "created_at": notice.created_at.isoformat(),
                    "student_id": str(student.pk),
                    **_institute_payload(notice.institute),
                },
            )
            for student in students
        ],
        batch_size=500,
    )
    records_by_user = {record.user_id: record for record in records}
    devices = list(
        UserDevice.objects.filter(
            user_id__in=records_by_user,
            is_active=True,
        ).order_by("pk")
    )
    devices_by_user = {}
    for device in devices:
        devices_by_user.setdefault(device.user_id, []).append(device)

    messaging, configuration_error = _firebase_messaging()
    deliveries = {
        user_id: {"sent_ids": [], "errors": []}
        for user_id in records_by_user
    }
    if messaging is None:
        _finalize_notice_records(
            records,
            devices_by_user,
            deliveries,
            configuration_error,
        )
        return records

    invalid_devices = []
    for device_chunk in _chunks(devices, FIREBASE_MULTICAST_LIMIT):
        message = _notice_multicast_message(
            messaging,
            notice,
            [device.token for device in device_chunk],
        )
        try:
            batch_response = messaging.send_each_for_multicast(message)
        except Exception as exc:
            error_message = str(exc)
            for device in device_chunk:
                deliveries[device.user_id]["errors"].append(
                    f"{device.platform}:{device.pk}: {error_message}"
                )
            continue

        for device, response in zip(device_chunk, batch_response.responses):
            delivery = deliveries[device.user_id]
            if response.success:
                delivery["sent_ids"].append(response.message_id or "")
                continue

            error_message = str(response.exception or "Firebase delivery failed.")
            delivery["errors"].append(
                f"{device.platform}:{device.pk}: {error_message}"
            )
            if _is_invalid_token_error(error_message):
                device.is_active = False
                device.updated_at = timezone.now()
                invalid_devices.append(device)

    if invalid_devices:
        UserDevice.objects.bulk_update(
            invalid_devices,
            ["is_active", "updated_at"],
            batch_size=500,
        )

    _finalize_notice_records(records, devices_by_user, deliveries)
    return records


def enqueue_fee_paid_notification(payment):
    from institute_admin.background_jobs import enqueue_background_job

    payment_id = payment.pk if hasattr(payment, "pk") else payment
    from accountant.models import Payment

    payment_record = Payment.objects.select_related(
        "invoice",
        "invoice__academic_session",
    ).get(pk=payment_id)
    existing_job = BackgroundJob.objects.filter(
        job_type=BackgroundJob.JobType.FEE_NOTIFICATION,
        payload__payment_id=payment_id,
    ).first()
    if existing_job:
        return existing_job
    return enqueue_background_job(
        BackgroundJob.JobType.FEE_NOTIFICATION,
        institute=payment_record.invoice.institute,
        academic_year=payment_record.invoice.academic_session.academic_year,
        payload={"payment_id": payment_id},
    )


def enqueue_notice_published_notification(notice):
    from institute_admin.background_jobs import enqueue_due_notice_notifications

    notice_id = notice.pk if hasattr(notice, "pk") else notice
    jobs = enqueue_due_notice_notifications(limit=1, notice_ids=[notice_id])
    return jobs[0] if jobs else None
