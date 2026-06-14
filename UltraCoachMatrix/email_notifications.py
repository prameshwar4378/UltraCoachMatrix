import logging
import re
import threading
from datetime import timedelta
from decimal import Decimal
from html import unescape
from urllib.parse import urljoin

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import close_old_connections, transaction
from django.db.models import Q, Sum
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
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
    text = re.sub(
        r"(?i)<br\s*/?>|</(?:p|div|h[1-6]|tr|table)>",
        "\n",
        html_body,
    )
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
                    reply_to=(
                        _unique_emails(payload.get("reply_to", []))
                        or _unique_emails([getattr(settings, "EMAIL_REPLY_TO", "")])
                    ),
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


def queue_template_messages(messages):
    prepared = [message for message in messages if _unique_emails(message.get("to", []))]
    if not prepared:
        return None
    if getattr(settings, "EMAIL_NOTIFICATIONS_RUN_SYNC", False):
        return _send_template_messages(prepared)
    thread = threading.Thread(
        target=_send_template_messages,
        args=(prepared,),
        name="ultracoachmatrix-email",
        daemon=True,
    )
    thread.start()
    return thread


def queue_template_email(*, subject, template_name, recipients, context, reply_to=None):
    return queue_template_messages(
        [
            {
                "subject": subject,
                "template_name": template_name,
                "to": recipients,
                "context": context,
                "reply_to": reply_to or [],
            }
        ]
    )


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


def _student_recipient_rows(student):
    rows = []
    if student.user.email:
        rows.append((student.user.email, _person_name(student.user, "Student")))
    for guardian in student.guardians.all():
        if guardian.email:
            rows.append((guardian.email, guardian.name or "Parent/Guardian"))

    seen = set()
    for email, name in rows:
        normalized = _clean_email(email)
        if normalized and normalized not in seen:
            seen.add(normalized)
            yield normalized, name


def send_student_welcome(student_id, temporary_password):
    from student_parent.models import StudentProfile

    student = StudentProfile.objects.select_related("user", "institute").prefetch_related("guardians").get(pk=student_id)
    context = {
        "institute_name": student.institute.name,
        "student_name": _person_name(student.user, "Student"),
        "admission_number": student.admission_number,
        "username": student.user.username,
        "temporary_password": temporary_password,
        "login_url": absolute_url(reverse("login")),
    }
    messages = [
        {
            "subject": f"Welcome to {student.institute.name}",
            "template_name": "email_templates/student_welcome_credentials.html",
            "to": [email],
            "context": context,
        }
        for email, _recipient_name in _student_recipient_rows(student)
    ]
    return _send_template_messages(messages)


def send_bulk_student_welcomes(credentials):
    sent_count = 0
    for student_id, temporary_password in credentials:
        sent_count += send_student_welcome(student_id, temporary_password) or 0
    return sent_count


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

    user = User.objects.select_related("profile__institute", "profile__institute__subscription").get(pk=user_id)
    institute = user.profile.institute
    subscription = getattr(institute, "subscription", None)
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
                    "trial_ends_on": subscription.ends_on if subscription else None,
                    "login_url": absolute_url(reverse("login")),
                },
            }
        ]
    )


def send_admission_confirmation(enrollment_id):
    from student_parent.models import StudentEnrollment

    enrollment = (
        StudentEnrollment.objects.select_related(
            "student__user",
            "student__institute",
            "academic_session__academic_year",
            "batch",
        )
        .prefetch_related("courses", "student__guardians")
        .get(pk=enrollment_id)
    )
    student = enrollment.student
    context = {
        "institute_name": student.institute.name,
        "student_name": _person_name(student.user, "Student"),
        "admission_number": enrollment.academic_session.admission_number,
        "academic_session": enrollment.academic_session.academic_year.name,
        "batch_name": enrollment.batch.name,
        "course_names": ", ".join(enrollment.courses.values_list("name", flat=True)),
        "joined_on": enrollment.enrolled_on or enrollment.academic_session.joined_on,
        "portal_url": absolute_url(reverse("school_dashboard")),
    }
    return _send_template_messages(
        [
            {
                "subject": f"Admission confirmed at {student.institute.name}",
                "template_name": "email_templates/admission_confirmation.html",
                "to": [email],
                "context": context,
            }
            for email, _recipient_name in _student_recipient_rows(student)
        ]
    )


def send_payment_confirmation(payment_id):
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
    remaining_balance = max(invoice.amount - paid_total, Decimal("0.00"))
    context = {
        "institute_name": invoice.institute.name,
        "student_name": _person_name(invoice.student.user, "Student"),
        "receipt_number": payment.receipt_number,
        "fee_title": invoice.title,
        "amount": payment.amount,
        "paid_on": payment.paid_on,
        "payment_method": payment.get_method_display(),
        "remaining_balance": remaining_balance,
        "receipt_url": absolute_url(reverse("institute_admin:payment_receipt", args=[payment.pk])),
    }
    return _send_template_messages(
        [
            {
                "subject": f"Payment received - Receipt {payment.receipt_number or payment.pk}",
                "template_name": "email_templates/payment_confirmation_receipt.html",
                "to": [email],
                "context": context,
            }
            for email, _recipient_name in _student_recipient_rows(invoice.student)
        ]
    )


def send_attendance_alerts(attendance_ids):
    from teacher.models import Attendance

    records = (
        Attendance.objects.filter(
            pk__in=attendance_ids,
            status__in=[Attendance.Status.ABSENT, Attendance.Status.LATE],
        )
        .select_related("student__user", "student__institute", "batch")
        .prefetch_related("student__guardians")
    )
    messages = []
    for record in records:
        for email, recipient_name in _student_recipient_rows(record.student):
            messages.append(
                {
                    "subject": f"Attendance alert for {_person_name(record.student.user, 'Student')}",
                    "template_name": "email_templates/attendance_alert.html",
                    "to": [email],
                    "context": {
                        "institute_name": record.student.institute.name,
                        "recipient_name": recipient_name,
                        "student_name": _person_name(record.student.user, "Student"),
                        "attendance_date": record.date,
                        "batch_name": record.batch.name,
                        "attendance_status": record.status,
                        "attendance_status_display": record.get_status_display(),
                        "attendance_note": record.note,
                    },
                }
            )
    return _send_template_messages(messages)


def _active_batch_students(batch):
    from student_parent.models import StudentEnrollment, StudentProfile

    return (
        StudentProfile.objects.filter(
            enrollments__batch=batch,
            enrollments__status=StudentEnrollment.Status.ACTIVE,
            is_active=True,
        )
        .select_related("user", "institute")
        .prefetch_related("guardians")
        .distinct()
    )


def send_homework_published(homework_id):
    from teacher.models import Homework

    homework = Homework.objects.select_related("batch__institute", "course", "subject").get(pk=homework_id)
    messages = []
    for student in _active_batch_students(homework.batch):
        context = {
            "institute_name": homework.batch.institute.name,
            "student_name": _person_name(student.user, "Student"),
            "homework_title": homework.title,
            "batch_name": homework.batch.name,
            "subject_name": homework.subject.name if homework.subject else "",
            "course_name": homework.course.name if homework.course else "",
            "due_date": homework.due_date,
            "instructions": homework.instructions,
            "homework_url": absolute_url(reverse("school_dashboard")),
        }
        for email, _recipient_name in _student_recipient_rows(student):
            messages.append(
                {
                    "subject": f"New homework: {homework.title}",
                    "template_name": "email_templates/homework_published.html",
                    "to": [email],
                    "context": context,
                }
            )
    return _send_template_messages(messages)


def _teachers_for_notice(notice):
    from teacher.models import TeacherProfile

    if notice.audience == notice.Audience.STUDENTS_PARENTS:
        return TeacherProfile.objects.none()
    queryset = TeacherProfile.objects.filter(institute=notice.institute, is_active=True).select_related("user")
    batch_ids = list(notice.target_batches.values_list("pk", flat=True))
    course_ids = list(notice.target_courses.values_list("pk", flat=True))
    if batch_ids or course_ids:
        target_filter = Q(user__assigned_batches__in=batch_ids)
        if course_ids:
            target_filter |= Q(user__assigned_batches__courses__in=course_ids)
        queryset = queryset.filter(target_filter)
    return queryset.distinct()


def send_notice_published(notice_id):
    from institute_admin.models import Notice
    from student_parent.notifications import students_for_notice

    notice = (
        Notice.objects.select_related("institute")
        .prefetch_related("target_batches", "target_courses", "target_students")
        .get(pk=notice_id)
    )
    if not notice.is_published or (notice.publish_at and notice.publish_at > timezone.now()):
        return 0

    recipients = []
    for student in students_for_notice(notice).prefetch_related("guardians"):
        recipients.extend(_student_recipient_rows(student))
    recipients.extend(
        (teacher.user.email, _person_name(teacher.user, "Teacher"))
        for teacher in _teachers_for_notice(notice)
        if teacher.user.email
    )

    messages = []
    seen = set()
    for email, recipient_name in recipients:
        normalized = _clean_email(email)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        messages.append(
            {
                "subject": f"{notice.title} - {notice.institute.name}",
                "template_name": "email_templates/notice_published.html",
                "to": [normalized],
                "context": {
                    "institute_name": notice.institute.name,
                    "recipient_name": recipient_name,
                    "notice_title": notice.title,
                    "notice_category": notice.category,
                    "notice_category_display": notice.get_category_display(),
                    "notice_priority": notice.priority,
                    "notice_priority_display": notice.get_priority_display(),
                    "notice_message": notice.message,
                    "publish_at": notice.publish_at or notice.created_at,
                    "notice_url": absolute_url(reverse("school_dashboard")),
                },
            }
        )
    return _send_template_messages(messages)


def send_exam_published(exam_id):
    from teacher.models import Exam

    exam = Exam.objects.select_related("batch__institute", "course", "subject").get(pk=exam_id)
    if not exam.is_published:
        return 0
    messages = []
    for student in _active_batch_students(exam.batch):
        context = {
            "institute_name": exam.batch.institute.name,
            "student_name": _person_name(student.user, "Student"),
            "exam_title": exam.title,
            "exam_date": exam.exam_date,
            "batch_name": exam.batch.name,
            "subject_name": exam.subject.name if exam.subject else "",
            "duration_minutes": exam.duration_minutes,
            "total_marks": exam.total_marks,
            "instructions": exam.instructions,
            "exam_url": absolute_url(reverse("school_dashboard")),
        }
        for email, _recipient_name in _student_recipient_rows(student):
            messages.append(
                {
                    "subject": f"Exam published: {exam.title}",
                    "template_name": "email_templates/exam_published.html",
                    "to": [email],
                    "context": context,
                }
            )
    return _send_template_messages(messages)


def send_exam_results_published(exam_id):
    from teacher.models import Exam, ExamAttempt, ExamResult

    exam = Exam.objects.select_related("batch__institute").get(pk=exam_id)
    results = {
        result.student_id: result
        for result in ExamResult.objects.filter(exam=exam).select_related("student__user")
    }
    attempts = (
        ExamAttempt.objects.filter(exam=exam, submitted_at__isnull=False)
        .select_related("student__user", "student__institute")
        .prefetch_related("student__guardians")
    )
    messages = []
    for attempt in attempts:
        result = results.get(attempt.student_id)
        marks = result.marks_obtained if result else attempt.score
        total_marks = result.exam.total_marks if result else (attempt.total_marks or exam.total_marks)
        percentage = (marks / total_marks * 100) if total_marks else None
        context = {
            "institute_name": exam.batch.institute.name,
            "student_name": _person_name(attempt.student.user, "Student"),
            "exam_title": exam.title,
            "marks_obtained": marks,
            "total_marks": total_marks,
            "percentage": percentage,
            "remark": result.remark if result else "",
            "result_url": absolute_url(reverse("school_dashboard")),
        }
        for email, _recipient_name in _student_recipient_rows(attempt.student):
            messages.append(
                {
                    "subject": f"Result published: {exam.title}",
                    "template_name": "email_templates/exam_result_published.html",
                    "to": [email],
                    "context": context,
                }
            )
    return _send_template_messages(messages)


def send_support_ticket_acknowledgement(ticket_id):
    from institute_admin.models import SupportTicket

    ticket = SupportTicket.objects.select_related("institute", "created_by").get(pk=ticket_id)
    recipient = ticket.created_by.email if ticket.created_by and ticket.created_by.email else ticket.institute.email
    return _send_template_messages(
        [
            {
                "subject": f"Support request received - Ticket #{ticket.pk}",
                "template_name": "email_templates/support_ticket_acknowledgement.html",
                "to": [recipient],
                "context": {
                    "institute_name": ticket.institute.name,
                    "requester_name": _person_name(ticket.created_by) if ticket.created_by else ticket.institute.owner_name,
                    "ticket_id": ticket.pk,
                    "ticket_subject": ticket.subject,
                    "ticket_category": ticket.get_category_display(),
                    "ticket_priority": ticket.get_priority_display(),
                    "ticket_status": ticket.get_status_display(),
                    "ticket_message": ticket.message,
                    "ticket_url": absolute_url(reverse("help_support")),
                },
            }
        ]
    )


def send_support_ticket_response(ticket_id):
    from institute_admin.models import SupportTicket

    ticket = SupportTicket.objects.select_related("institute", "created_by").get(pk=ticket_id)
    if not ticket.admin_response:
        return 0
    recipient = ticket.created_by.email if ticket.created_by and ticket.created_by.email else ticket.institute.email
    return _send_template_messages(
        [
            {
                "subject": f"Response to support ticket #{ticket.pk}",
                "template_name": "email_templates/support_ticket_response.html",
                "to": [recipient],
                "context": {
                    "institute_name": ticket.institute.name,
                    "requester_name": _person_name(ticket.created_by) if ticket.created_by else ticket.institute.owner_name,
                    "ticket_id": ticket.pk,
                    "ticket_subject": ticket.subject,
                    "ticket_status": ticket.get_status_display(),
                    "admin_response": ticket.admin_response,
                    "responded_at": ticket.responded_at,
                    "ticket_url": absolute_url(reverse("help_support")),
                },
            }
        ]
    )


def _fee_reminder_messages(invoice, *, overdue=False, days_overdue=0):
    context = {
        "institute_name": invoice.institute.name,
        "student_name": _person_name(invoice.student.user, "Student"),
        "fee_title": invoice.title,
        "amount_due": invoice.outstanding_amount,
        "due_date": invoice.due_date,
        "days_overdue": days_overdue,
        "batch_name": invoice.batch.name if invoice.batch else "",
        "payment_url": absolute_url(reverse("school_dashboard")),
    }
    template_name = (
        "email_templates/overdue_payment_warning.html"
        if overdue
        else "email_templates/fee_reminder.html"
    )
    subject = (
        "Overdue fee payment requires attention"
        if overdue
        else f"Fee reminder - Due {invoice.due_date:%d %b %Y}"
    )
    return [
        {
            "subject": subject,
            "template_name": template_name,
            "to": [email],
            "context": context,
        }
        for email, _recipient_name in _student_recipient_rows(invoice.student)
    ]


def send_scheduled_fee_reminders(today=None):
    from accountant.models import FeeInvoice, Payment

    today = today or timezone.localdate()
    upcoming_days = set(getattr(settings, "FEE_REMINDER_DAYS_BEFORE", [3, 1]))
    overdue_days = set(getattr(settings, "FEE_OVERDUE_REMINDER_DAYS", [1, 7, 15, 30]))
    candidate_dates = [today + timedelta(days=days) for days in upcoming_days]
    candidate_dates += [today - timedelta(days=days) for days in overdue_days]
    invoices = (
        FeeInvoice.objects.filter(
            due_date__in=candidate_dates,
            status__in=[FeeInvoice.Status.UNPAID, FeeInvoice.Status.PARTIAL],
        )
        .select_related("institute", "student__user", "batch")
        .prefetch_related("student__guardians")
        .annotate(
            paid_total=Sum(
                "payments__amount",
                filter=Q(payments__status=Payment.Status.ACTIVE),
            )
        )
    )
    messages = []
    for invoice in invoices:
        invoice.outstanding_amount = max(
            invoice.amount - (invoice.paid_total or Decimal("0.00")),
            Decimal("0.00"),
        )
        if invoice.outstanding_amount <= 0:
            continue
        delta = (invoice.due_date - today).days
        if delta in upcoming_days:
            messages.extend(_fee_reminder_messages(invoice))
        elif -delta in overdue_days:
            messages.extend(
                _fee_reminder_messages(
                    invoice,
                    overdue=True,
                    days_overdue=-delta,
                )
            )
    return _send_template_messages(messages)


def send_scheduled_subscription_reminders(today=None):
    from super_admin.models import InstituteSubscription

    today = today or timezone.localdate()
    renewal_days = set(getattr(settings, "SUBSCRIPTION_RENEWAL_REMINDER_DAYS", [30]))
    expiry_days = set(getattr(settings, "SUBSCRIPTION_EXPIRY_REMINDER_DAYS", [7, 3, 1, 0]))
    candidate_days = renewal_days | expiry_days
    subscriptions = (
        InstituteSubscription.objects.filter(
            ends_on__in=[today + timedelta(days=days) for days in candidate_days]
        )
        .select_related("institute")
    )
    messages = []
    for subscription in subscriptions:
        institute = subscription.institute
        recipients = _unique_emails(
            [institute.email]
            + list(
                institute.user_profiles.filter(
                    role="INSTITUTE_ADMIN",
                    user__is_active=True,
                ).values_list("user__email", flat=True)
            )
        )
        if not recipients:
            continue
        days_remaining = (subscription.ends_on - today).days
        common_context = {
            "institute_name": institute.name,
            "owner_name": institute.owner_name or "Institute Administrator",
            "plan_name": subscription.get_plan_display(),
            "expiry_date": subscription.ends_on,
            "days_remaining": days_remaining,
            "renewal_url": absolute_url(reverse("subscription_billing")),
            "upgrade_url": absolute_url(reverse("subscription_billing")),
        }
        if subscription.plan == InstituteSubscription.Plan.FREE_TRIAL:
            template_name = "email_templates/institute_trial_expiry_reminder.html"
            subject = "Your UltraCoachMatrix trial expires soon"
        elif days_remaining in renewal_days:
            template_name = "email_templates/renewal_reminder.html"
            subject = f"Renewal reminder for {institute.name}"
        else:
            template_name = "email_templates/institute_subscription_expiry_reminder.html"
            subject = f"Subscription expiry reminder for {institute.name}"
        messages.extend(
            {
                "subject": subject,
                "template_name": template_name,
                "to": [recipient],
                "context": common_context,
            }
            for recipient in recipients
        )
    return _send_template_messages(messages)


def send_all_scheduled_reminders():
    return {
        "fee_email_count": send_scheduled_fee_reminders(),
        "subscription_email_count": send_scheduled_subscription_reminders(),
    }
