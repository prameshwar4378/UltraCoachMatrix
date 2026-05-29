from datetime import date
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from accountant.models import FeeCategory, FeeInvoice, Payment
from student_parent.models import StudentAcademicSession, StudentEnrollment, StudentProfile
from super_admin.models import Institute, UserProfile
from teacher.models import Attendance, Homework

from .forms import PaymentUpdateForm, ReceiveFeeForm
from .models import AcademicYear, Batch, Course, Notice


class AcademicSessionIsolationTests(TestCase):
    def setUp(self):
        self.institute = Institute.objects.create(
            name="Saint Monica International School",
            code="smis",
            status=Institute.Status.ACTIVE,
        )
        self.admin_user = User.objects.create_user(
            username="admin",
            password="pass12345",
            first_name="Admin",
        )
        UserProfile.objects.create(
            user=self.admin_user,
            institute=self.institute,
            role=UserProfile.Role.INSTITUTE_ADMIN,
            phone="9000000000",
        )
        self.student_user = User.objects.create_user(
            username="student-one",
            password="pass12345",
            first_name="Student",
            last_name="One",
        )
        UserProfile.objects.create(
            user=self.student_user,
            institute=self.institute,
            role=UserProfile.Role.STUDENT_PARENT,
            phone="9111111111",
        )
        self.student = StudentProfile.objects.create(
            institute=self.institute,
            user=self.student_user,
            academic_year=None,
            admission_number="LEGACY-0001",
            is_active=True,
        )
        self.year_2026 = AcademicYear.objects.create(
            institute=self.institute,
            name="2026-27",
            start_date=date(2026, 4, 1),
            end_date=date(2027, 3, 31),
        )
        self.year_2027 = AcademicYear.objects.create(
            institute=self.institute,
            name="2027-28",
            start_date=date(2027, 4, 1),
            end_date=date(2028, 3, 31),
        )
        self.session_2026 = StudentAcademicSession.objects.create(
            institute=self.institute,
            student=self.student,
            academic_year=self.year_2026,
            admission_number="SMIS-2026-27-0001",
            joined_on=date(2026, 4, 5),
            status=StudentAcademicSession.Status.ACTIVE,
            previous_class="11th",
        )
        self.session_2027 = StudentAcademicSession.objects.create(
            institute=self.institute,
            student=self.student,
            academic_year=self.year_2027,
            admission_number="SMIS-2027-28-0001",
            joined_on=date(2027, 4, 5),
            status=StudentAcademicSession.Status.ACTIVE,
            previous_class="12th",
        )
        self.course = Course.objects.create(
            institute=self.institute,
            academic_year=self.year_2026,
            name="Science",
            fee_amount=Decimal("1000.00"),
            is_active=True,
        )
        self.course_2027 = Course.objects.create(
            institute=self.institute,
            academic_year=self.year_2027,
            name="Science",
            fee_amount=Decimal("1000.00"),
            is_active=True,
        )
        self.batch_2026 = Batch.objects.create(
            institute=self.institute,
            academic_year=self.year_2026,
            name="11th Batch",
            is_active=True,
        )
        self.batch_2026.courses.add(self.course)
        self.batch_2027 = Batch.objects.create(
            institute=self.institute,
            academic_year=self.year_2027,
            name="12th Batch",
            is_active=True,
        )
        self.batch_2027.courses.add(self.course_2027)
        self.enrollment_2026 = StudentEnrollment.objects.create(
            academic_session=self.session_2026,
            student=self.student,
            batch=self.batch_2026,
            enrolled_on=date(2026, 4, 5),
            custom_fee_amount=Decimal("1000.00"),
        )
        self.enrollment_2026.courses.add(self.course)
        self.enrollment_2027 = StudentEnrollment.objects.create(
            academic_session=self.session_2027,
            student=self.student,
            batch=self.batch_2027,
            enrolled_on=date(2027, 4, 5),
            custom_fee_amount=Decimal("2000.00"),
        )
        self.enrollment_2027.courses.add(self.course)
        self.invoice_2026 = FeeInvoice.objects.create(
            institute=self.institute,
            student=self.student,
            academic_session=self.session_2026,
            enrollment=self.enrollment_2026,
            batch=self.batch_2026,
            title="2026 Fee",
            amount=Decimal("1000.00"),
            due_date=date(2026, 5, 1),
        )
        self.invoice_2027 = FeeInvoice.objects.create(
            institute=self.institute,
            student=self.student,
            academic_session=self.session_2027,
            enrollment=self.enrollment_2027,
            batch=self.batch_2027,
            title="2027 Fee",
            amount=Decimal("2000.00"),
            due_date=date(2027, 5, 1),
        )
        self.payment_2026 = Payment.objects.create(
            invoice=self.invoice_2026,
            amount=Decimal("250.00"),
            paid_on=date(2026, 5, 2),
            method=Payment.Method.CASH,
            received_by=self.admin_user,
        )
        self.payment_2027 = Payment.objects.create(
            invoice=self.invoice_2027,
            amount=Decimal("500.00"),
            paid_on=date(2027, 5, 2),
            method=Payment.Method.CASH,
            received_by=self.admin_user,
        )
        self.attendance_2026 = Attendance.objects.create(
            academic_session=self.session_2026,
            student=self.student,
            batch=self.batch_2026,
            date=date(2026, 5, 3),
            status=Attendance.Status.PRESENT,
            marked_by=self.admin_user,
        )
        self.attendance_2027 = Attendance.objects.create(
            academic_session=self.session_2027,
            student=self.student,
            batch=self.batch_2027,
            date=date(2027, 5, 3),
            status=Attendance.Status.ABSENT,
            marked_by=self.admin_user,
        )
        self.client.force_login(self.admin_user)

    def select_year(self, academic_year):
        session = self.client.session
        session["academic_year_id"] = academic_year.pk
        session.save()

    def test_student_list_uses_selected_academic_session(self):
        self.select_year(self.year_2026)
        response = self.client.get(reverse("institute_admin:student_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SMIS-2026-27-0001")
        self.assertContains(response, "11th Batch")
        self.assertNotContains(response, "SMIS-2027-28-0001")
        self.assertNotContains(response, "12th Batch")

        self.select_year(self.year_2027)
        response = self.client.get(reverse("institute_admin:student_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SMIS-2027-28-0001")
        self.assertContains(response, "12th Batch")
        self.assertNotContains(response, "SMIS-2026-27-0001")
        self.assertNotContains(response, "11th Batch")

    def test_student_dashboard_context_is_limited_to_selected_session(self):
        self.select_year(self.year_2026)
        response = self.client.get(reverse("institute_admin:student_dashboard", args=[self.student.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["student_session"], self.session_2026)
        self.assertQuerySetEqual(response.context["enrollments"], [self.enrollment_2026])
        self.assertQuerySetEqual(response.context["payments"], [self.payment_2026])
        self.assertEqual(list(response.context["attendance_records"]), [self.attendance_2026])
        self.assertEqual(response.context["total_fee_amount"], Decimal("1000.00"))
        self.assertEqual(response.context["total_paid_amount"], Decimal("250.00"))

        self.select_year(self.year_2027)
        response = self.client.get(reverse("institute_admin:student_dashboard", args=[self.student.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["student_session"], self.session_2027)
        self.assertQuerySetEqual(response.context["enrollments"], [self.enrollment_2027])
        self.assertQuerySetEqual(response.context["payments"], [self.payment_2027])
        self.assertEqual(list(response.context["attendance_records"]), [self.attendance_2027])
        self.assertEqual(response.context["total_fee_amount"], Decimal("2000.00"))
        self.assertEqual(response.context["total_paid_amount"], Decimal("500.00"))

    def test_courses_and_batches_are_limited_to_selected_academic_year(self):
        old_only_course = Course.objects.create(
            institute=self.institute,
            academic_year=self.year_2026,
            name="Old Year Only Subject",
            fee_amount=Decimal("300.00"),
            is_active=True,
        )
        old_only_batch = Batch.objects.create(
            institute=self.institute,
            academic_year=self.year_2026,
            name="Old Year Only Batch",
            is_active=True,
        )
        old_only_batch.courses.add(old_only_course)

        self.select_year(self.year_2027)

        response = self.client.get(reverse("institute_admin:course_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Science")
        self.assertNotContains(response, "Old Year Only Subject")

        response = self.client.get(reverse("institute_admin:batch_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "12th Batch")
        self.assertNotContains(response, "Old Year Only Batch")

        response = self.client.get(reverse("institute_admin:enrollment_create"))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(old_only_batch, list(response.context["form"].fields["batch"].queryset))
        self.assertNotIn(old_only_course, list(response.context["form"].fields["courses"].queryset))

    def test_dashboard_fee_totals_include_uninvoiced_enrollment_fees(self):
        extra_course = Course.objects.create(
            institute=self.institute,
            academic_year=self.year_2026,
            name="Extra Subject",
            fee_amount=Decimal("1500.00"),
            is_active=True,
        )
        extra_batch = Batch.objects.create(
            institute=self.institute,
            academic_year=self.year_2026,
            name="Extra Batch",
            is_active=True,
        )
        extra_batch.courses.add(extra_course)
        extra_enrollment = StudentEnrollment.objects.create(
            academic_session=self.session_2026,
            student=self.student,
            batch=extra_batch,
            enrolled_on=date(2026, 4, 8),
            custom_fee_amount=Decimal("1500.00"),
        )
        extra_enrollment.courses.add(extra_course)
        self.select_year(self.year_2026)

        response = self.client.get(reverse("institute_admin:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["invoice_amount"], Decimal("2500.00"))
        self.assertEqual(response.context["paid_amount"], Decimal("250.00"))
        self.assertEqual(response.context["due_amount"], Decimal("2250.00"))
        self.assertEqual(response.context["collection_rate"], 10.0)
        self.assertTrue(any(row["due_amount"] == Decimal("2250.00") for row in response.context["due_invoice_rows"]))

    def test_session_link_is_required_for_operational_records(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                StudentEnrollment.objects.create(
                    student=self.student,
                    batch=self.batch_2026,
                    enrolled_on=date(2026, 4, 6),
                )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                FeeInvoice.objects.create(
                    institute=self.institute,
                    student=self.student,
                    title="Broken Invoice",
                    amount=Decimal("100.00"),
                    due_date=date(2026, 6, 1),
                )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Attendance.objects.create(
                    student=self.student,
                    batch=self.batch_2026,
                    date=date(2026, 6, 1),
                )

    def test_models_align_student_from_academic_session(self):
        other_user = User.objects.create_user(username="other-student", password="pass12345")
        other_student = StudentProfile.objects.create(
            institute=self.institute,
            user=other_user,
            academic_year=None,
            admission_number="LEGACY-0002",
            is_active=True,
        )
        batch = Batch.objects.create(
            institute=self.institute,
            academic_year=self.year_2027,
            name="Alignment Batch",
            is_active=True,
        )
        enrollment = StudentEnrollment.objects.create(
            academic_session=self.session_2027,
            student=other_student,
            batch=batch,
        )
        self.assertEqual(enrollment.student, self.student)

        invoice = FeeInvoice.objects.create(
            institute=self.institute,
            student=other_student,
            academic_session=self.session_2027,
            title="Aligned Invoice",
            amount=Decimal("50.00"),
            due_date=date(2027, 7, 1),
        )
        self.assertEqual(invoice.student, self.student)
        self.assertEqual(invoice.institute, self.institute)

        attendance = Attendance.objects.create(
            academic_session=self.session_2027,
            student=other_student,
            batch=batch,
            date=date(2027, 7, 2),
        )
        self.assertEqual(attendance.student, self.student)

    def test_receive_fee_rejects_more_than_enrollment_due(self):
        form = ReceiveFeeForm(
            data={
                "enrollment": self.enrollment_2026.pk,
                "category": "",
                "title": "2026 Fee",
                "invoice_amount": "1000.00",
                "payment_amount": "800.00",
                "paid_on": "2026-05-10",
                "method": Payment.Method.CASH,
                "receipt_number": "",
                "note": "",
            },
            institute=self.institute,
            student=self.student,
            academic_session=self.session_2026,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("Payment amount cannot be greater", str(form.errors))

    def test_receive_fee_rejects_more_than_category_due(self):
        category = FeeCategory.objects.create(
            institute=self.institute,
            name="Books",
            default_amount=Decimal("500.00"),
        )
        invoice = FeeInvoice.objects.create(
            institute=self.institute,
            student=self.student,
            academic_session=self.session_2026,
            category=category,
            title="Books",
            amount=Decimal("500.00"),
            due_date=date(2026, 5, 10),
        )
        Payment.objects.create(
            invoice=invoice,
            amount=Decimal("200.00"),
            paid_on=date(2026, 5, 11),
            method=Payment.Method.CASH,
            received_by=self.admin_user,
        )
        form = ReceiveFeeForm(
            data={
                "enrollment": "",
                "category": category.pk,
                "title": "Books",
                "invoice_amount": "500.00",
                "payment_amount": "400.00",
                "paid_on": "2026-05-12",
                "method": Payment.Method.CASH,
                "receipt_number": "",
                "note": "",
            },
            institute=self.institute,
            student=self.student,
            academic_session=self.session_2026,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("Payment amount cannot be greater", str(form.errors))

    def test_receive_fee_reuses_existing_enrollment_invoice(self):
        self.select_year(self.year_2026)
        invoice_count = FeeInvoice.objects.filter(academic_session=self.session_2026).count()

        response = self.client.post(
            reverse("institute_admin:student_receive_fee", args=[self.student.pk]),
            data={
                "enrollment": self.enrollment_2026.pk,
                "category": "",
                "title": "2026 Fee",
                "invoice_amount": "1000.00",
                "payment_amount": "300.00",
                "paid_on": "2026-05-12",
                "method": Payment.Method.CASH,
                "receipt_number": "",
                "note": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(FeeInvoice.objects.filter(academic_session=self.session_2026).count(), invoice_count)
        active_paid = sum(
            payment.amount
            for payment in Payment.objects.filter(invoice=self.invoice_2026, status=Payment.Status.ACTIVE)
        )
        self.assertEqual(active_paid, Decimal("550.00"))

    def test_payment_correction_rejects_overpayment(self):
        form = PaymentUpdateForm(
            data={
                "amount": "1200.00",
                "paid_on": "2026-05-12",
                "method": Payment.Method.CASH,
                "receipt_number": "CORRECTED",
                "note": "",
                "correction_reason": "Testing overpayment guard.",
            },
            payment=self.payment_2026,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("Corrected amount cannot be greater", str(form.errors))

    def test_voided_payment_is_excluded_from_dashboard_totals(self):
        extra_payment = Payment.objects.create(
            invoice=self.invoice_2026,
            amount=Decimal("100.00"),
            paid_on=date(2026, 5, 13),
            method=Payment.Method.CASH,
            received_by=self.admin_user,
        )
        extra_payment.void(self.admin_user, "Mistaken payment")
        self.select_year(self.year_2026)

        response = self.client.get(reverse("institute_admin:student_dashboard", args=[self.student.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_paid_amount"], Decimal("250.00"))

    def test_receipt_uses_academic_session_admission_number(self):
        self.select_year(self.year_2027)

        response = self.client.get(reverse("institute_admin:payment_receipt", args=[self.payment_2027.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SMIS-2027-28-0001")
        self.assertNotContains(response, "LEGACY-0001")
        self.assertNotContains(response, "SMIS-2026-27-0001")

    def test_attendance_post_creates_record_for_selected_academic_session(self):
        self.select_year(self.year_2026)
        target_date = date(2026, 6, 10)

        response = self.client.post(
            reverse("institute_admin:attendance_list")
            + f"?batch={self.batch_2026.pk}&date={target_date.isoformat()}",
            data={
                "student_ids": [str(self.student.pk)],
                f"status_{self.student.pk}": Attendance.Status.LATE,
                f"note_{self.student.pk}": "Reached after first lecture",
            },
        )

        self.assertEqual(response.status_code, 302)
        attendance = Attendance.objects.get(
            academic_session=self.session_2026,
            batch=self.batch_2026,
            date=target_date,
        )
        self.assertEqual(attendance.student, self.student)
        self.assertEqual(attendance.status, Attendance.Status.LATE)
        self.assertEqual(attendance.note, "Reached after first lecture")
        self.assertFalse(
            Attendance.objects.filter(
                academic_session=self.session_2027,
                batch=self.batch_2026,
                date=target_date,
            ).exists()
        )

    def test_attendance_post_ignores_student_outside_selected_year_batch(self):
        self.select_year(self.year_2026)
        target_date = date(2026, 6, 11)

        response = self.client.post(
            reverse("institute_admin:attendance_list")
            + f"?batch={self.batch_2027.pk}&date={target_date.isoformat()}",
            data={
                "student_ids": [str(self.student.pk)],
                f"status_{self.student.pk}": Attendance.Status.ABSENT,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Attendance.objects.filter(date=target_date).exists())

    def test_enrollment_create_attaches_selected_academic_session(self):
        self.select_year(self.year_2026)
        new_batch = Batch.objects.create(
            institute=self.institute,
            academic_year=self.year_2026,
            name="2026 Revision",
            is_active=True,
        )
        new_batch.courses.add(self.course)

        response = self.client.post(
            reverse("institute_admin:enrollment_create"),
            data={
                "student": self.student.pk,
                "batch": new_batch.pk,
                "courses": [self.course.pk],
                "enrolled_on": "2026-06-15",
                "status": StudentEnrollment.Status.ACTIVE,
                "custom_fee_amount": "750.00",
            },
        )

        self.assertEqual(response.status_code, 200)
        enrollment = StudentEnrollment.objects.get(batch=new_batch)
        self.assertEqual(enrollment.academic_session, self.session_2026)
        self.assertEqual(enrollment.student, self.student)

    def test_enrollment_create_rejects_student_without_selected_year_session(self):
        self.select_year(self.year_2026)
        other_user = User.objects.create_user(username="future-only", password="pass12345")
        UserProfile.objects.create(
            user=other_user,
            institute=self.institute,
            role=UserProfile.Role.STUDENT_PARENT,
        )
        other_student = StudentProfile.objects.create(
            institute=self.institute,
            user=other_user,
            academic_year=None,
            admission_number="LEGACY-0003",
            is_active=True,
        )
        StudentAcademicSession.objects.create(
            institute=self.institute,
            student=other_student,
            academic_year=self.year_2027,
            admission_number="SMIS-2027-28-0003",
            status=StudentAcademicSession.Status.ACTIVE,
        )
        new_batch = Batch.objects.create(
            institute=self.institute,
            academic_year=self.year_2026,
            name="Rejected Batch",
            is_active=True,
        )
        new_batch.courses.add(self.course)

        response = self.client.post(
            reverse("institute_admin:enrollment_create"),
            data={
                "student": other_student.pk,
                "batch": new_batch.pk,
                "courses": [self.course.pk],
                "enrolled_on": "2026-06-16",
                "status": StudentEnrollment.Status.ACTIVE,
                "custom_fee_amount": "750.00",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(StudentEnrollment.objects.filter(batch=new_batch).exists())
        self.assertContains(response, "Select a valid choice", status_code=200)

    def test_student_promotion_creates_only_new_student_session(self):
        self.session_2027.delete()
        self.enrollment_2027.delete()
        self.invoice_2027.delete()
        self.attendance_2027.delete()
        self.select_year(self.year_2026)
        enrollment_count = StudentEnrollment.objects.count()
        invoice_count = FeeInvoice.objects.count()
        payment_count = Payment.objects.count()
        attendance_count = Attendance.objects.count()

        response = self.client.post(
            reverse("institute_admin:student_promote"),
            data={
                "source_year": self.year_2026.pk,
                "target_year_name": "2027-28",
                "students": [str(self.student.pk)],
                "target_class": "12th",
                "target_school_name": "Should Not Copy",
                "target_school_address": "Should Not Copy",
            },
        )

        self.assertEqual(response.status_code, 302)
        promoted_session = StudentAcademicSession.objects.get(
            student=self.student,
            academic_year=self.year_2027,
        )
        self.assertEqual(promoted_session.previous_class, "")
        self.assertEqual(promoted_session.current_school_name, "")
        self.assertEqual(StudentEnrollment.objects.count(), enrollment_count)
        self.assertEqual(FeeInvoice.objects.count(), invoice_count)
        self.assertEqual(Payment.objects.count(), payment_count)
        self.assertEqual(Attendance.objects.count(), attendance_count)
        self.assertFalse(StudentEnrollment.objects.filter(academic_session=promoted_session).exists())
        self.assertFalse(FeeInvoice.objects.filter(academic_session=promoted_session).exists())
        self.assertFalse(Attendance.objects.filter(academic_session=promoted_session).exists())


class TenantIsolationTests(TestCase):
    def setUp(self):
        self.institute_a = Institute.objects.create(
            name="Arohan Academy",
            code="aa",
            status=Institute.Status.ACTIVE,
        )
        self.institute_b = Institute.objects.create(
            name="Saint Monica International School",
            code="smis",
            status=Institute.Status.ACTIVE,
        )
        self.admin_a = User.objects.create_user(username="admin-a", password="pass12345")
        self.admin_b = User.objects.create_user(username="admin-b", password="pass12345")
        UserProfile.objects.create(
            user=self.admin_a,
            institute=self.institute_a,
            role=UserProfile.Role.INSTITUTE_ADMIN,
        )
        UserProfile.objects.create(
            user=self.admin_b,
            institute=self.institute_b,
            role=UserProfile.Role.INSTITUTE_ADMIN,
        )
        self.year_a = AcademicYear.objects.create(
            institute=self.institute_a,
            name="2026-27",
            start_date=date(2026, 4, 1),
            end_date=date(2027, 3, 31),
        )
        self.year_b = AcademicYear.objects.create(
            institute=self.institute_b,
            name="2026-27",
            start_date=date(2026, 4, 1),
            end_date=date(2027, 3, 31),
        )
        self.course_a = Course.objects.create(
            institute=self.institute_a,
            academic_year=self.year_a,
            name="Math A",
            fee_amount=Decimal("1000.00"),
            is_active=True,
        )
        self.course_b = Course.objects.create(
            institute=self.institute_b,
            academic_year=self.year_b,
            name="Math B",
            fee_amount=Decimal("2000.00"),
            is_active=True,
        )
        self.batch_a = Batch.objects.create(
            institute=self.institute_a,
            academic_year=self.year_a,
            name="Batch A",
            is_active=True,
        )
        self.batch_a.courses.add(self.course_a)
        self.batch_b = Batch.objects.create(
            institute=self.institute_b,
            academic_year=self.year_b,
            name="Batch B",
            is_active=True,
        )
        self.batch_b.courses.add(self.course_b)
        self.student_a = self.create_student(
            institute=self.institute_a,
            academic_year=self.year_a,
            username="student-a",
            admission_number="AA-2026-27-0001",
        )
        self.student_b = self.create_student(
            institute=self.institute_b,
            academic_year=self.year_b,
            username="student-b",
            admission_number="SMIS-2026-27-0001",
        )
        self.enrollment_a = StudentEnrollment.objects.create(
            academic_session=self.student_a["session"],
            student=self.student_a["profile"],
            batch=self.batch_a,
            custom_fee_amount=Decimal("1000.00"),
        )
        self.enrollment_b = StudentEnrollment.objects.create(
            academic_session=self.student_b["session"],
            student=self.student_b["profile"],
            batch=self.batch_b,
            custom_fee_amount=Decimal("2000.00"),
        )
        self.invoice_a = FeeInvoice.objects.create(
            institute=self.institute_a,
            academic_session=self.student_a["session"],
            student=self.student_a["profile"],
            enrollment=self.enrollment_a,
            batch=self.batch_a,
            title="Institute A Fee",
            amount=Decimal("1000.00"),
            due_date=date(2026, 5, 1),
        )
        self.invoice_b = FeeInvoice.objects.create(
            institute=self.institute_b,
            academic_session=self.student_b["session"],
            student=self.student_b["profile"],
            enrollment=self.enrollment_b,
            batch=self.batch_b,
            title="Institute B Fee",
            amount=Decimal("2000.00"),
            due_date=date(2026, 5, 1),
        )
        self.payment_b = Payment.objects.create(
            invoice=self.invoice_b,
            amount=Decimal("500.00"),
            paid_on=date(2026, 5, 2),
            method=Payment.Method.CASH,
            received_by=self.admin_b,
            receipt_number="B-RECEIPT",
        )
        self.attendance_b = Attendance.objects.create(
            academic_session=self.student_b["session"],
            student=self.student_b["profile"],
            batch=self.batch_b,
            date=date(2026, 5, 3),
            status=Attendance.Status.ABSENT,
            marked_by=self.admin_b,
        )
        self.homework_b = Homework.objects.create(
            batch=self.batch_b,
            course=self.course_b,
            title="Institute B Homework",
            instructions="Private homework",
            due_date=date(2026, 5, 4),
            created_by=self.admin_b,
        )
        self.notice_b = Notice.objects.create(
            institute=self.institute_b,
            title="Institute B Notice",
            message="Private notice",
            audience=Notice.Audience.EVERYONE,
            created_by=self.admin_b,
        )
        self.client.force_login(self.admin_a)
        session = self.client.session
        session["academic_year_id"] = self.year_a.pk
        session.save()

    def create_student(self, *, institute, academic_year, username, admission_number):
        user = User.objects.create_user(username=username, password="pass12345", first_name=username)
        UserProfile.objects.create(
            user=user,
            institute=institute,
            role=UserProfile.Role.STUDENT_PARENT,
        )
        profile = StudentProfile.objects.create(
            institute=institute,
            user=user,
            academic_year=academic_year,
            admission_number=admission_number,
            is_active=True,
        )
        academic_session = StudentAcademicSession.objects.create(
            institute=institute,
            student=profile,
            academic_year=academic_year,
            admission_number=admission_number,
            status=StudentAcademicSession.Status.ACTIVE,
        )
        return {"user": user, "profile": profile, "session": academic_session}

    def assert_not_found(self, url_name, *args):
        response = self.client.get(reverse(url_name, args=args))
        self.assertEqual(response.status_code, 404)

    def test_institute_admin_cannot_open_other_institute_records_by_url(self):
        other_student_pk = self.student_b["profile"].pk
        protected_urls = [
            ("institute_admin:student_dashboard", other_student_pk),
            ("institute_admin:student_add_fee", other_student_pk),
            ("institute_admin:student_receive_fee", other_student_pk),
            ("institute_admin:student_update", other_student_pk),
            ("institute_admin:student_basic_update", other_student_pk),
            ("institute_admin:student_education_update", other_student_pk),
            ("institute_admin:student_guardian_update", other_student_pk),
            ("institute_admin:student_document_upload", other_student_pk),
            ("institute_admin:payment_receipt", self.payment_b.pk),
            ("institute_admin:payment_update", self.payment_b.pk),
            ("institute_admin:payment_void", self.payment_b.pk),
            ("institute_admin:enrollment_update", self.enrollment_b.pk),
            ("institute_admin:enrollment_delete", self.enrollment_b.pk),
            ("institute_admin:homework_update", self.homework_b.pk),
            ("institute_admin:homework_delete", self.homework_b.pk),
            ("institute_admin:notice_update", self.notice_b.pk),
            ("institute_admin:notice_delete", self.notice_b.pk),
        ]
        for url_name, pk in protected_urls:
            with self.subTest(url_name=url_name):
                self.assert_not_found(url_name, pk)

    def test_institute_admin_lists_do_not_show_other_institute_records(self):
        list_urls = [
            reverse("institute_admin:student_list"),
            reverse("institute_admin:enrollment_list"),
            reverse("institute_admin:homework_list"),
            reverse("institute_admin:notice_list"),
            reverse("institute_admin:attendance_list"),
        ]
        forbidden_text = [
            "SMIS-2026-27-0001",
            "student-b",
            "Batch B",
            "Institute B Homework",
            "Institute B Notice",
        ]
        for url in list_urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            for text in forbidden_text:
                with self.subTest(url=url, text=text):
                    self.assertNotContains(response, text)

    def test_attendance_export_does_not_include_other_institute_records(self):
        response = self.client.get(reverse("institute_admin:attendance_export"), {"format": "excel"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"SMIS-2026-27-0001", response.content)
        self.assertNotIn(b"Batch B", response.content)

        response = self.client.get(reverse("institute_admin:attendance_export"), {"format": "pdf"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"SMIS-2026-27-0001", response.content)
        self.assertNotIn(b"Batch B", response.content)


class SessionAuditCommandTests(TestCase):
    def setUp(self):
        self.institute = Institute.objects.create(
            name="Arohan Academy",
            code="aa",
            status=Institute.Status.ACTIVE,
        )
        self.year = AcademicYear.objects.create(
            institute=self.institute,
            name="2026-27",
            start_date=date(2026, 4, 1),
            end_date=date(2027, 3, 31),
        )
        self.user = User.objects.create_user(username="audit-student", password="pass12345")
        UserProfile.objects.create(
            user=self.user,
            institute=self.institute,
            role=UserProfile.Role.STUDENT_PARENT,
            phone="9000000001",
        )
        self.student = StudentProfile.objects.create(
            institute=self.institute,
            user=self.user,
            academic_year=self.year,
            admission_number="AA-2026-27-0001",
            is_active=True,
        )
        self.session = StudentAcademicSession.objects.create(
            institute=self.institute,
            student=self.student,
            academic_year=self.year,
            admission_number="AA-2026-27-0001",
            status=StudentAcademicSession.Status.ACTIVE,
        )
        self.batch = Batch.objects.create(
            institute=self.institute,
            academic_year=self.year,
            name="Audit Batch",
            is_active=True,
        )
        self.invoice = FeeInvoice.objects.create(
            institute=self.institute,
            academic_session=self.session,
            student=self.student,
            batch=self.batch,
            title="Audit Fee",
            amount=Decimal("1000.00"),
            due_date=date(2026, 5, 1),
            status=FeeInvoice.Status.UNPAID,
        )

    def test_audit_sessions_reports_clean_data_without_errors(self):
        output = StringIO()

        call_command("audit_sessions", institute_code="aa", stdout=output)

        self.assertIn("Audit completed with 0 errors", output.getvalue())
        self.assertIn("Invoices with active payment total greater than invoice amount", output.getvalue())

    def test_audit_sessions_can_fail_on_error_level_issues(self):
        Payment.objects.create(
            invoice=self.invoice,
            amount=Decimal("1200.00"),
            paid_on=date(2026, 5, 2),
            method=Payment.Method.CASH,
        )
        output = StringIO()

        with self.assertRaises(CommandError):
            call_command("audit_sessions", institute_code="aa", fail_on_issues=True, stdout=output)

        self.assertIn("Invoices with active payment total greater than invoice amount", output.getvalue())
        self.assertIn("Audit completed with", output.getvalue())
