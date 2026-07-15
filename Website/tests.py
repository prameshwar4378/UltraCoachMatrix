from io import BytesIO

from django.contrib.admin.sites import AdminSite
from django.core import mail
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from openpyxl import load_workbook

from .admin import CareerApplicationAdmin
from .models import CareerApplication


class AndroidAppDownloadTests(TestCase):
    def test_apk_download_is_public_and_has_attachment_headers(self):
        response = self.client.get(reverse("apk_download"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.android.package-archive",
        )
        self.assertIn("UltraCoachMatrix.apk", response["Content-Disposition"])
        response.close()

    def test_homepage_uses_direct_apk_download_url(self):
        response = self.client.get(reverse("index"))
        self.assertContains(response, reverse("apk_download"), count=2)

    def test_legacy_apk_download_urls_still_work(self):
        for url_name in ("apk_download_legacy", "apk_download_legacy_spaced"):
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 200)
            self.assertIn("UltraCoachMatrix.apk", response["Content-Disposition"])
            response.close()

    def test_careers_page_is_public_and_linked_in_menu(self):
        response = self.client.get(reverse("web_careers"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Careers at UltraCoachMatrix")
        self.assertContains(response, reverse("web_careers"))
        self.assertContains(response, "Sales Executive")

    def test_career_application_can_be_submitted(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("web_careers"),
                {
                    "full_name": "Amit Sharma",
                    "email": "amit@example.com",
                    "phone": "+919876543210",
                    "experience": "1-3",
                    "qualification": "BBA",
                    "city": "Pune",
                    "notice_period": "15 days",
                    "resume": SimpleUploadedFile(
                        "resume.pdf",
                        b"%PDF-1.4 test resume",
                        content_type="application/pdf",
                    ),
                    "portfolio_link": "https://example.com/profile",
                    "cover_letter": "I can handle institute demos and follow-ups.",
                },
            )

        self.assertRedirects(response, f"{reverse('web_careers')}#career-application")
        application = CareerApplication.objects.get(email="amit@example.com")
        self.assertEqual(application.role, "sales_executive")
        self.assertEqual(application.full_name, "Amit Sharma")
        self.assertEqual(application.experience, "1-3")
        self.assertTrue(application.resume.name.startswith("career_resumes/resume"))
        self.assertEqual(len(mail.outbox), 1)
        notification = mail.outbox[0]
        self.assertEqual(
            notification.to,
            ["prameshwar4378@gmail.com", "ultoxy.tech@gmail.com"],
        )
        self.assertEqual(notification.reply_to[0], "amit@example.com")
        self.assertIn("New career application", notification.subject)
        self.assertIn("Amit Sharma", notification.body)
        self.assertEqual(len(notification.attachments), 1)

    def test_public_career_application_uses_open_sales_role(self):
        self.client.post(
            reverse("web_careers"),
            {
                "full_name": "Sneha Patil",
                "email": "sneha@example.com",
                "phone": "+919123456789",
                "experience": "0-1",
                "qualification": "BE Computer",
                "city": "Mumbai",
                "resume": SimpleUploadedFile(
                    "sneha.docx",
                    b"test resume",
                    content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ),
            },
        )

        application = CareerApplication.objects.get(email="sneha@example.com")
        self.assertEqual(application.role, "sales_executive")

    def test_career_application_admin_exports_selected_rows_to_excel(self):
        application = CareerApplication.objects.create(
            full_name="Rohit Jadhav",
            email="rohit@example.com",
            phone="+919111111111",
            role="sales_executive",
            experience="fresher",
            qualification="BCom",
            city="Nashik",
            notice_period="Immediate",
            resume="career_resumes/rohit.pdf",
            portfolio_link="https://example.com/rohit",
            cover_letter="Interested in software sales.",
        )
        admin_instance = CareerApplicationAdmin(CareerApplication, AdminSite())

        response = admin_instance.export_selected_to_excel(
            request=None,
            queryset=CareerApplication.objects.filter(pk=application.pk),
        )

        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertIn("career_applications_", response["Content-Disposition"])
        workbook = load_workbook(BytesIO(response.content), data_only=True)
        sheet = workbook.active
        self.assertEqual(sheet["A1"].value, "Full name")
        self.assertEqual(sheet["A2"].value, "Rohit Jadhav")
        self.assertEqual(sheet["B2"].value, "Sales Executive")
        self.assertEqual(sheet["J2"].value, "career_resumes/rohit.pdf")
