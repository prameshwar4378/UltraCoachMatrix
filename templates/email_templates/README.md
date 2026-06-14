# UltraCoachMatrix email templates

Render these templates with Django's `render_to_string()` and send the result as
an HTML email. Every action template extends `base_email.html`.

## Templates

| Action | Template |
| --- | --- |
| Student welcome/login credentials | `student_welcome_credentials.html` |
| Teacher welcome/login credentials | `teacher_welcome_credentials.html` |
| Institute welcome/login credentials | `institute_welcome_credentials.html` |
| Student admission confirmation | `admission_confirmation.html` |
| Fee payment confirmation and receipt | `payment_confirmation_receipt.html` |
| Upcoming fee reminder | `fee_reminder.html` |
| Overdue fee warning | `overdue_payment_warning.html` |
| Absent or late attendance alert | `attendance_alert.html` |
| Subscription renewal reminder | `renewal_reminder.html` |
| Homework publication | `homework_published.html` |
| Notice publication | `notice_published.html` |
| Exam publication | `exam_published.html` |
| Exam result publication | `exam_result_published.html` |
| Institute trial expiry reminder | `institute_trial_expiry_reminder.html` |
| Institute subscription expiry reminder | `institute_subscription_expiry_reminder.html` |
| Support-ticket acknowledgement | `support_ticket_acknowledgement.html` |
| Support-ticket response | `support_ticket_response.html` |

## Context conventions

Pass display-ready values such as `institute_name`, `student_name`, and
`payment_method`. Dates may be Python `date` or `datetime` objects and monetary
amounts may be `Decimal` values. Optional URLs hide their call-to-action button
when omitted.

For `attendance_alert.html`, pass `attendance_status` as `ABSENT` or `LATE`.
For urgent notices, pass `notice_priority` as `URGENT`.

## Sending and triggers

`UltraCoachMatrix.email_notifications` renders and sends the templates. Web
actions register their email work with `transaction.on_commit()` and start one
daemon thread per action. A bulk action sends its recipient messages
sequentially inside that single thread.

Configure SMTP and public links with:

```text
EMAIL_HOST
EMAIL_PORT
EMAIL_USE_TLS
EMAIL_USE_SSL
EMAIL_HOST_USER
EMAIL_HOST_PASSWORD
DEFAULT_FROM_EMAIL
EMAIL_BASE_URL
```

Fee and subscription reminders run through the Celery beat task
`institute_admin.send_scheduled_email_reminders`. The default interval is once
per day and can be changed with `EMAIL_REMINDER_INTERVAL`.

Example:

```python
html_body = render_to_string(
    "email_templates/payment_confirmation_receipt.html",
    {
        "institute_name": payment.invoice.institute.name,
        "student_name": payment.invoice.student.user.get_full_name(),
        "receipt_number": payment.receipt_number,
        "fee_title": payment.invoice.title,
        "amount": payment.amount,
        "paid_on": payment.paid_on,
        "payment_method": payment.get_method_display(),
        "remaining_balance": remaining_balance,
        "receipt_url": receipt_url,
    },
)
```
