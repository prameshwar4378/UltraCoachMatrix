from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from institute_admin.models import AcademicYear, Batch, Course, InstitutePrintTemplate, PrintDocumentType
from student_parent.models import StudentAcademicSession, StudentEnrollment, StudentProfile
from super_admin.mobile_auth import create_access_token
from super_admin.models import Institute, UserProfile

from .models import FeeCategory, FeeInvoice, Payment


class MobileFeesApiTests(TestCase):
    def setUp(self):
        self.institute = Institute.objects.create(name="Demo Institute", code="demo")
        self.user = User.objects.create_user(
            username="student",
            password="password",
            first_name="Demo",
            last_name="Student",
        )
        UserProfile.objects.create(
            user=self.user,
            institute=self.institute,
            role=UserProfile.Role.STUDENT_PARENT,
        )
        self.student = StudentProfile.objects.create(
            institute=self.institute,
            user=self.user,
            admission_number="ADM-001",
        )
        self.academic_year = AcademicYear.objects.create(
            institute=self.institute,
            name="2026-27",
            start_date=date(2026, 4, 1),
            end_date=date(2027, 3, 31),
        )
        self.session = StudentAcademicSession.objects.create(
            institute=self.institute,
            student=self.student,
            academic_year=self.academic_year,
            admission_number="ADM-001",
        )
        self.course = Course.objects.create(
            institute=self.institute,
            academic_year=self.academic_year,
            name="Class 10",
            fee_amount=Decimal("12000.00"),
        )
        self.batch = Batch.objects.create(
            institute=self.institute,
            academic_year=self.academic_year,
            name="Morning",
        )
        self.batch.courses.add(self.course)
        self.enrollment = StudentEnrollment.objects.create(
            student=self.student,
            academic_session=self.session,
            batch=self.batch,
        )
        self.enrollment.courses.add(self.course)
        self.category = FeeCategory.objects.create(
            institute=self.institute,
            name="Tuition",
            default_amount=Decimal("12000.00"),
        )
        self.invoice = FeeInvoice.objects.create(
            institute=self.institute,
            student=self.student,
            academic_session=self.session,
            enrollment=self.enrollment,
            course=self.course,
            batch=self.batch,
            category=self.category,
            title="Term 1",
            amount=Decimal("12000.00"),
            due_date=date(2026, 6, 30),
            status=FeeInvoice.Status.PARTIAL,
        )
        self.payment = Payment.objects.create(
            invoice=self.invoice,
            amount=Decimal("5000.00"),
            paid_on=date(2026, 5, 29),
            receipt_number="RCP-001",
        )
        self.new_course = Course.objects.create(
            institute=self.institute,
            academic_year=self.academic_year,
            name="Crash Course",
            fee_amount=Decimal("3000.00"),
        )
        self.new_batch = Batch.objects.create(
            institute=self.institute,
            academic_year=self.academic_year,
            name="Evening",
        )
        self.new_batch.courses.add(self.new_course)
        self.new_enrollment = StudentEnrollment.objects.create(
            student=self.student,
            academic_session=self.session,
            batch=self.new_batch,
        )
        self.new_enrollment.courses.add(self.new_course)

    def auth_headers(self):
        return {"HTTP_AUTHORIZATION": f"Bearer {create_access_token(self.user)}"}

    def test_mobile_health_is_public(self):
        response = self.client.get("/api/mobile/health/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_mobile_fee_details_returns_summary_and_breakups(self):
        response = self.client.get("/api/mobile/fees/", **self.auth_headers())

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["student"]["username"], "student")
        self.assertEqual(data["summary"]["total_fee_amount"], "15000.00")
        self.assertEqual(data["summary"]["total_paid_amount"], "5000.00")
        self.assertEqual(data["summary"]["total_due_amount"], "10000.00")
        self.assertTrue(any(fee["batch"]["name"] == "Morning" for fee in data["fees"]))
        self.assertTrue(any(fee["batch"]["name"] == "Evening" for fee in data["fees"]))
        self.assertEqual(data["payment_history"][0]["receipt_number"], "RCP-001")

    def test_mobile_fee_summary_returns_only_fast_summary_payload(self):
        response = self.client.get("/api/mobile/fees/summary/", **self.auth_headers())

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["student"]["username"], "student")
        self.assertEqual(data["summary"]["total_fee_amount"], "15000.00")
        self.assertEqual(data["summary"]["total_due_amount"], "10000.00")
        self.assertEqual(len(data["academic_sessions"]), 1)
        self.assertNotIn("fees", data)
        self.assertNotIn("payment_history", data)

    def test_mobile_fee_details_use_selected_session_admission_and_invoice_amount(self):
        next_year = AcademicYear.objects.create(
            institute=self.institute,
            name="2027-28",
            start_date=date(2027, 4, 1),
            end_date=date(2028, 3, 31),
        )
        next_session = StudentAcademicSession.objects.create(
            institute=self.institute,
            student=self.student,
            academic_year=next_year,
            admission_number="SM-2027-28-0001",
        )
        next_course = Course.objects.create(
            institute=self.institute,
            academic_year=next_year,
            name="Class 11",
            fee_amount=Decimal("20000.00"),
        )
        next_batch = Batch.objects.create(
            institute=self.institute,
            academic_year=next_year,
            name="Advanced",
        )
        next_batch.courses.add(next_course)
        next_enrollment = StudentEnrollment.objects.create(
            student=self.student,
            academic_session=next_session,
            batch=next_batch,
        )
        next_enrollment.courses.add(next_course)
        next_invoice = FeeInvoice.objects.create(
            institute=self.institute,
            student=self.student,
            academic_session=next_session,
            enrollment=next_enrollment,
            course=next_course,
            batch=next_batch,
            category=self.category,
            title="Annual Fee",
            amount=Decimal("45000.00"),
            due_date=date(2027, 6, 30),
            status=FeeInvoice.Status.PARTIAL,
        )
        Payment.objects.create(
            invoice=next_invoice,
            amount=Decimal("1000.00"),
            paid_on=date(2027, 5, 29),
            receipt_number="RCP-2027",
        )

        response = self.client.get(
            f"/api/mobile/fees/?academic_session_id={next_session.pk}",
            **self.auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["student"]["admission_number"], "SM-2027-28-0001")
        self.assertEqual(data["summary"]["total_fee_amount"], "45000.00")
        self.assertEqual(data["summary"]["total_paid_amount"], "1000.00")
        self.assertEqual(data["summary"]["total_due_amount"], "44000.00")
        self.assertEqual(data["fees"][0]["amount"], "45000.00")
        self.assertEqual(data["fees"][0]["due_amount"], "44000.00")

    def test_mobile_fee_invoices_returns_invoice_list_only(self):
        response = self.client.get("/api/mobile/fees/invoices/", **self.auth_headers())

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["student"]["username"], "student")
        self.assertEqual(len(data["fees"]), 2)
        morning_fee = next(fee for fee in data["fees"] if fee["batch"]["name"] == "Morning")
        evening_fee = next(fee for fee in data["fees"] if fee["batch"]["name"] == "Evening")
        self.assertEqual(morning_fee["title"], "Morning Fee")
        self.assertEqual(morning_fee["due_amount"], "7000.00")
        self.assertEqual(evening_fee["title"], "Evening Fee")
        self.assertEqual(evening_fee["amount"], "3000.00")
        self.assertEqual(evening_fee["due_amount"], "3000.00")
        self.assertEqual(evening_fee["status"], "UNPAID")
        self.assertNotIn("summary", data)

    def test_mobile_fee_breakup_returns_breakup_without_payment_history(self):
        response = self.client.get("/api/mobile/fees/breakup/", **self.auth_headers())

        self.assertEqual(response.status_code, 200)
        data = response.json()
        enrollment_group = next(group for group in data["category_wise"] if group["name"] == "Enrollment")
        evening_group = next(group for group in data["batch_wise"] if group["name"] == "Evening")
        self.assertEqual(enrollment_group["total_amount"], "15000.00")
        self.assertEqual(enrollment_group["due_amount"], "10000.00")
        self.assertEqual(evening_group["total_amount"], "3000.00")
        self.assertTrue(any(enrollment["batch"]["name"] == "Morning" for enrollment in data["enrollments"]))
        self.assertTrue(any(enrollment["batch"]["name"] == "Evening" for enrollment in data["enrollments"]))
        self.assertNotIn("fees", data)
        self.assertNotIn("payment_history", data)

    def test_mobile_fee_details_requires_valid_token(self):
        response = self.client.get("/api/mobile/fees/")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Invalid or expired access token.")

    def test_mobile_receipt_download_returns_html(self):
        transport = FeeCategory.objects.create(
            institute=self.institute,
            name="Transport",
            default_amount=Decimal("2500.00"),
        )
        transport_invoice = FeeInvoice.objects.create(
            institute=self.institute,
            student=self.student,
            academic_session=self.session,
            category=transport,
            title="Transport Fee",
            amount=Decimal("2500.00"),
            due_date=date(2026, 7, 15),
            status=FeeInvoice.Status.PARTIAL,
        )
        Payment.objects.create(
            invoice=transport_invoice,
            amount=Decimal("1000.00"),
            paid_on=date(2026, 6, 10),
            receipt_number="RCP-TRANSPORT",
        )

        response = self.client.get(
            f"/api/mobile/fees/payments/{self.payment.pk}/receipt/download/",
            **self.auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/html")
        self.assertIn("fee-receipt-RCP-001.html", response["Content-Disposition"])
        html = response.content.decode()
        office_copy_html, student_copy_html = html.split("Cut Here", 1)
        self.assertIn("Fee Receipt", html)
        self.assertIn("Logo", html)
        self.assertIn("Morning", html)
        self.assertNotIn("Pending Category", office_copy_html)
        self.assertNotIn("Due Balance", office_copy_html)
        self.assertIn("Received Amount", office_copy_html)
        self.assertIn("Pending Category", student_copy_html)
        self.assertIn("Due Balance", html)
        self.assertIn("Fees", html)
        self.assertIn("Transport", html)
        self.assertIn("11500.00", html)

    def test_mobile_receipt_download_uses_selected_payment_receipt_template(self):
        InstitutePrintTemplate.objects.create(
            institute=self.institute,
            document_type=PrintDocumentType.PAYMENT_RECEIPT,
            title="Custom Receipt",
            html_file=SimpleUploadedFile(
                "payment-receipt.html",
                b"<html><body>Custom payment receipt {{ payment.receipt_number }} {{ receipt_batch_label }}</body></html>",
                content_type="text/html",
            ),
            is_active=True,
        )

        response = self.client.get(
            f"/api/mobile/fees/payments/{self.payment.pk}/receipt/download/",
            **self.auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("Custom payment receipt", html)
        self.assertIn("RCP-001", html)
        self.assertIn("Morning", html)
