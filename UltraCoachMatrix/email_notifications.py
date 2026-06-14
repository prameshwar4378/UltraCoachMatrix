import logging
import re
import threading
from decimal import Decimal
from html import unescape
from urllib.parse import urljoin

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import close_old_connections, transaction
from django.db.models import Sum
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.html import strip_tags


logger = logging.getLogger(__name__)


def _clean_email(value):
    return str(value or "").strip().lower()


def _unique_emails(values):
    seen = set()
    result = []
    for value in values:
        email = _clean_email(value)
        if email and not email.endswith(".test") and email not in seen:
            seen.add(email)
            result.append(email)
    return result


def absolute_url(path):
    if not path:
        return ""
    base_url = str(getattr(settings, "EMAIL_BASE_URL", "") or "").strip()
    if not base_url:
        return path
    return urljoin(f"{base_url.rstrip('/')}/", path.lstrip("/"))


def _plain_text_body(html_body):
    text = re.sub(r"(?i)<br\s*/?>|</(?:p|div|h[1-6]|tr|table)>", "\n", html_body)
    text = unescape(strip_tags(text))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _send_template_messages(messages):
    close_old_connections()
    sent_count = 0
    try:
        for payload in messages:
            recipients = _unique_emails(payload.get("to", []))
            if not recipients:
                continue
            try:
                html_body = render_to_string(payload["template_name"], payload.get("context", {}))
                message = EmailMultiAlternatives(
                    subject=payload["subject"],
                    body=_plain_text_body(html_body),
                    from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                    to=recipients,
                    reply_to=_unique_emails([getattr(settings, "EMAIL_REPLY_TO", "")]),
                    headers={
                        "Auto-Submitted": "auto-generated",
                        "X-Auto-Response-Suppress": "All",
                    },
                )
                message.attach_alternative(html_body, "text/html")
                sent_count += message.send(fail_silently=False)
            except Exception:
                logger.exception(
                    "Could not send email template %s to %s.",
                    payload.get("template_name"),
                    recipients,
                )
    finally:
        close_old_connections()
    return sent_count


def run_in_email_thread(callback, *args, **kwargs):
    def worker():
        close_old_connections()
        try:
            callback(*args, **kwargs)
        except Exception:
            logger.exception("Background email action %s failed.", callback.__name__)
        finally:
            close_old_connections()

    if getattr(settings, "EMAIL_NOTIFICATIONS_RUN_SYNC", False):
        return worker()
    thread = threading.Thread(
        target=worker,
        name=f"ultracoachmatrix-email-{callback.__name__}",
        daemon=True,
    )
    thread.start()
    return thread


def on_commit_email(callback, *args, **kwargs):
    transaction.on_commit(lambda: run_in_email_thread(callback, *args, **kwargs))


def _person_name(user, fallback="User"):
    return user.get_full_name().strip() or user.username or fallback


def _student_recipients(student):
    values = [student.user.email]
    values.extend(student.guardians.values_list("email", flat=True))
    return _unique_emails(values)


def send_student_welcome(student_id, temporary_password):
    from student_parent.models import StudentProfile

    student = (
        StudentProfile.objects.select_related("user", "institute")
        .prefetch_related("guardians")
        .get(pk=student_id)
    )
    download_url = getattr(settings, "STUDENT_APP_DOWNLOAD_URL", "")
    if not download_url:
        download_url = absolute_url(reverse("apk_download"))
    return _send_template_messages(
        [
            {
                "subject": f"Welcome to {student.institute.name}",
                "template_name": "email_templates/student_welcome_credentials.html",
                "to": [recipient],
                "context": {
                    "institute_name": student.institute.name,
                    "student_name": _person_name(student.user, "Student"),
                    "admission_number": student.admission_number,
                    "username": student.user.username,
                    "temporary_password": temporary_password,
                    "app_download_url": download_url,
                },
            }
            for recipient in _student_recipients(student)
        ]
    )


def send_bulk_student_welcomes(credentials):
    return sum(
        send_student_welcome(student_id, temporary_password) or 0
        for student_id, temporary_password in credentials
    )


def send_teacher_welcome(teacher_id, temporary_password):
    from teacher.models import TeacherProfile

    teacher = TeacherProfile.objects.select_related("user", "institute").get(pk=teacher_id)
    return _send_template_messages(
        [
            {
                "subject": f"Your teacher account for {teacher.institute.name}",
                "template_name": "email_templates/teacher_welcome_credentials.html",
                "to": [teacher.user.email],
                "context": {
                    "institute_name": teacher.institute.name,
                    "teacher_name": _person_name(teacher.user, "Teacher"),
                    "employee_id": teacher.employee_id,
                    "username": teacher.user.username,
                    "temporary_password": temporary_password,
                    "login_url": absolute_url(reverse("login")),
                },
            }
        ]
    )


def send_institute_welcome(user_id, temporary_password):
    from django.contrib.auth.models import User

    user = User.objects.select_related("profile__institute").get(pk=user_id)
    institute = user.profile.institute
    return _send_template_messages(
        [
            {
                "subject": f"Welcome to UltraCoachMatrix, {institute.name}",
                "template_name": "email_templates/institute_welcome_credentials.html",
                "to": [user.email or institute.email],
                "context": {
                    "institute_name": institute.name,
                    "institute_code": institute.code,
                    "owner_name": institute.owner_name or _person_name(user),
                    "username": user.username,
                    "temporary_password": temporary_password,
                    "login_url": absolute_url(reverse("login")),
                },
            }
        ]
    )


def _send_payment_email(payment_id, *, updated):
    from accountant.models import Payment

    payment = (
        Payment.objects.select_related("invoice__student__user", "invoice__student__institute")
        .prefetch_related("invoice__student__guardians")
        .get(pk=payment_id)
    )
    invoice = payment.invoice
    paid_total = (
        invoice.payments.filter(status=Payment.Status.ACTIVE).aggregate(total=Sum("amount"))["total"]
        or Decimal("0.00")
    )
    event_label = "updated" if updated else "received"
    return _send_template_messages(
        [
            {
                "subject": f"Payment {event_label} - Receipt {payment.receipt_number or payment.pk}",
                "template_name": "email_templates/payment_confirmation_receipt.html",
                "to": [recipient],
                "context": {
                    "institute_name": invoice.institute.name,
                    "student_name": _person_name(invoice.student.user, "Student"),
                    "receipt_number": payment.receipt_number,
                    "fee_title": invoice.title,
                    "amount": payment.amount,
                    "paid_on": payment.paid_on,
                    "payment_method": payment.get_method_display(),
                    "remaining_balance": max(invoice.amount - paid_total, Decimal("0.00")),
                    "receipt_url": absolute_url(
                        reverse("institute_admin:payment_receipt", args=[payment.pk])
                    ),
                    "payment_updated": updated,
                },
            }
            for recipient in _student_recipients(invoice.student)
        ]
    )


def send_payment_confirmation(payment_id):
    return _send_payment_email(payment_id, updated=False)


def send_payment_update(payment_id):
    return _send_payment_email(payment_id, updated=True)
