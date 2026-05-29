from django.conf import settings
from django.contrib.auth.models import User
from django.db.models import Q
from django.utils import timezone

from institute_admin.models import Notice

from .models import PushNotification, StudentEnrollment, StudentProfile, UserDevice


def _firebase_messaging():
    if not getattr(settings, "PUSH_NOTIFICATIONS_ENABLED", True):
        return None, "Push notifications are disabled."

    try:
        import firebase_admin
        from firebase_admin import credentials, messaging
    except ImportError:
        return None, "firebase-admin package is not installed."

    if not firebase_admin._apps:
        credentials_file = getattr(settings, "FIREBASE_CREDENTIALS_FILE", "")
        if not credentials_file:
            return None, "FIREBASE_CREDENTIALS_FILE is not configured."
        try:
            firebase_admin.initialize_app(credentials.Certificate(credentials_file))
        except Exception as exc:
            return None, str(exc)
    return messaging, ""


def send_push_to_user(user, notification_type, title, body, data=None):
    payload = {key: str(value) for key, value in (data or {}).items() if value is not None}
    record = PushNotification.objects.create(
        user=user,
        notification_type=notification_type,
        title=title,
        body=body,
        data=payload,
    )
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
    for device in devices:
        message = messaging.Message(
            token=device.token,
            notification=messaging.Notification(title=title, body=body),
            data=payload,
            android=messaging.AndroidConfig(priority="high"),
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(aps=messaging.Aps(sound="default"))
            ),
        )
        try:
            sent_ids.append(messaging.send(message))
        except Exception as exc:
            errors.append(str(exc))

    if sent_ids:
        record.status = PushNotification.Status.SENT
        record.firebase_message_id = ",".join(sent_ids)[:255]
        record.sent_at = timezone.now()
        update_fields = ["status", "firebase_message_id", "sent_at"]
    else:
        record.status = PushNotification.Status.FAILED
        record.error_message = "; ".join(errors)
        update_fields = ["status", "error_message"]
    record.save(update_fields=update_fields)
    return record


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
            "payment_id": payment.pk,
            "invoice_id": invoice.pk,
            "student_id": student.pk,
            "receipt_number": payment.receipt_number,
            "amount": payment.amount,
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
            "result_id": result.pk,
            "exam_id": exam.pk,
            "student_id": student.pk,
            "marks_obtained": result.marks_obtained,
            "total_marks": exam.total_marks,
        },
    )


def students_for_notice(notice):
    queryset = StudentProfile.objects.filter(institute=notice.institute, is_active=True).select_related("user")
    if notice.audience == Notice.Audience.TEACHERS:
        return queryset.none()

    student_ids = set(notice.target_students.values_list("pk", flat=True))
    batch_ids = list(notice.target_batches.values_list("pk", flat=True))
    course_ids = list(notice.target_courses.values_list("pk", flat=True))
    if batch_ids or course_ids:
        enrollment_filter = Q(status=StudentEnrollment.Status.ACTIVE)
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


def notify_notice_published(notice):
    if not notice.push_to_app or not notice.is_published or not notice.is_active_for_app:
        return []
    records = []
    for student in students_for_notice(notice):
        records.append(
            send_push_to_user(
                student.user,
                PushNotification.NotificationType.NOTICE,
                notice.title,
                notice.message,
                {
                    "type": PushNotification.NotificationType.NOTICE,
                    "notice_id": notice.pk,
                    "category": notice.category,
                    "priority": notice.priority,
                    "student_id": student.pk,
                },
            )
        )
    return records
