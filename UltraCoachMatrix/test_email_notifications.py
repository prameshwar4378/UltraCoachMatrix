from unittest.mock import patch

from django.core import mail
from django.template.loader import render_to_string
from django.test import SimpleTestCase, override_settings

from .email_notifications import _send_template_messages, run_in_email_thread


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_NOTIFICATIONS_RUN_SYNC=True,
    DEFAULT_FROM_EMAIL="UltraCoachMatrix <no-reply@example.com>",
    EMAIL_REPLY_TO="support@example.com",
)
class TemplateEmailSenderTests(SimpleTestCase):
    def test_role_welcome_templates_show_only_the_correct_action(self):
        credentials = {
            "username": "demo-user",
            "temporary_password": "DemoPassword123",
        }
        student_html = render_to_string(
            "email_templates/student_welcome_credentials.html",
            {
                **credentials,
                "student_name": "Student",
                "institute_name": "Demo Institute",
                "app_download_url": "https://example.com/app.apk",
            },
        )
        teacher_html = render_to_string(
            "email_templates/teacher_welcome_credentials.html",
            {
                **credentials,
                "teacher_name": "Teacher",
                "institute_name": "Demo Institute",
                "login_url": "https://example.com/login/",
            },
        )
        institute_html = render_to_string(
            "email_templates/institute_welcome_credentials.html",
            {
                **credentials,
                "owner_name": "Owner",
                "institute_name": "Demo Institute",
                "login_url": "https://example.com/login/",
            },
        )

        self.assertIn("Download Android application", student_html)
        self.assertNotIn("Open teacher portal", student_html)
        self.assertIn("Open teacher portal", teacher_html)
        self.assertNotIn("Download Android application", teacher_html)
        self.assertIn("Open institute login", institute_html)
        self.assertNotIn("Download Android application", institute_html)

    def test_payment_email_has_plain_text_and_html_parts(self):
        _send_template_messages(
            [
                {
                    "subject": "Payment updated - Receipt RCP-001",
                    "template_name": "email_templates/payment_confirmation_receipt.html",
                    "to": ["student@example.com"],
                    "context": {
                        "institute_name": "Demo Institute",
                        "student_name": "Aarav Student",
                        "receipt_number": "RCP-001",
                        "fee_title": "Tuition Fee",
                        "amount": 1500,
                        "paid_on": None,
                        "payment_method": "UPI",
                        "remaining_balance": 0,
                        "payment_updated": True,
                    },
                }
            ]
        )

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["student@example.com"])
        self.assertIn("Payment updated", message.subject)
        self.assertIn("updated your payment details", message.body)
        self.assertEqual(message.alternatives[0].mimetype, "text/html")
        self.assertEqual(message.reply_to, ["support@example.com"])
        self.assertEqual(message.extra_headers["Auto-Submitted"], "auto-generated")

    def test_empty_and_test_domain_recipients_are_skipped(self):
        sent_count = _send_template_messages(
            [
                {
                    "subject": "Skipped",
                    "template_name": "email_templates/student_welcome_credentials.html",
                    "to": ["", "student@dummy.test"],
                    "context": {},
                }
            ]
        )

        self.assertEqual(sent_count, 0)
        self.assertEqual(len(mail.outbox), 0)


@override_settings(EMAIL_NOTIFICATIONS_RUN_SYNC=False)
class BackgroundThreadTests(SimpleTestCase):
    @patch("UltraCoachMatrix.email_notifications.threading.Thread")
    def test_background_action_uses_daemon_thread(self, thread_class):
        run_in_email_thread(lambda: None)

        thread_class.assert_called_once()
        self.assertTrue(thread_class.call_args.kwargs["daemon"])
        thread_class.return_value.start.assert_called_once_with()
