from unittest.mock import patch

from django.core import mail
from django.test import SimpleTestCase, override_settings

from .email_notifications import queue_template_email, run_in_email_thread


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_NOTIFICATIONS_RUN_SYNC=True,
    DEFAULT_FROM_EMAIL="UltraCoachMatrix <no-reply@example.com>",
)
class TemplateEmailSenderTests(SimpleTestCase):
    def test_template_email_has_plain_text_and_html_parts(self):
        queue_template_email(
            subject="Payment received",
            template_name="email_templates/payment_confirmation_receipt.html",
            recipients=["student@example.com"],
            context={
                "institute_name": "Demo Institute",
                "student_name": "Aarav Student",
                "receipt_number": "RCP-001",
                "fee_title": "Tuition Fee",
                "amount": 1500,
                "paid_on": None,
                "payment_method": "UPI",
                "remaining_balance": 0,
            },
        )

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["student@example.com"])
        self.assertIn("Payment received", message.subject)
        self.assertIn("Aarav Student", message.body)
        self.assertEqual(message.alternatives[0].mimetype, "text/html")
        self.assertEqual(message.reply_to, ["ultoxy.tech@gmail.com"])
        self.assertEqual(message.extra_headers["Auto-Submitted"], "auto-generated")

    def test_empty_and_test_domain_recipients_are_skipped(self):
        queue_template_email(
            subject="Skipped",
            template_name="email_templates/fee_reminder.html",
            recipients=["", "student@dummy.test"],
            context={},
        )

        self.assertEqual(len(mail.outbox), 0)


@override_settings(EMAIL_NOTIFICATIONS_RUN_SYNC=False)
class BackgroundThreadTests(SimpleTestCase):
    @patch("UltraCoachMatrix.email_notifications.threading.Thread")
    def test_background_action_uses_daemon_thread(self, thread_class):
        run_in_email_thread(lambda: None)

        thread_class.assert_called_once()
        self.assertTrue(thread_class.call_args.kwargs["daemon"])
        thread_class.return_value.start.assert_called_once_with()
