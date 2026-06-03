from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from institute_admin.models import AcademicYear, Batch, Course, Notice
from super_admin.mobile_auth import create_access_token
from super_admin.models import Institute, UserProfile
from teacher.models import Attendance, Exam, ExamResult, Homework

from .models import PushNotification, StudentAcademicSession, StudentEnrollment, StudentProfile, UserDevice
from .notifications import notify_result_declared


class MobileHomeworkPlannerTests(TestCase):
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
        self.math = Course.objects.create(
            institute=self.institute,
            academic_year=self.academic_year,
            name="Mathematics",
            fee_amount=Decimal("1000.00"),
        )
        self.science = Course.objects.create(
            institute=self.institute,
            academic_year=self.academic_year,
            name="Science",
            fee_amount=Decimal("1000.00"),
        )
        self.batch = Batch.objects.create(
            institute=self.institute,
            academic_year=self.academic_year,
            name="Morning",
        )
        self.batch.courses.add(self.math, self.science)
        self.session = StudentAcademicSession.objects.create(
            institute=self.institute,
            student=self.student,
            academic_year=self.academic_year,
            admission_number="ADM-001",
        )
        enrollment = StudentEnrollment.objects.create(
            student=self.student,
            academic_session=self.session,
            batch=self.batch,
        )
        enrollment.courses.add(self.math, self.science)
        Homework.objects.create(
            batch=self.batch,
            course=self.math,
            title="Algebra practice",
            instructions="Complete exercise 4A.",
            due_date=date(2026, 6, 1),
        )
        Homework.objects.create(
            batch=self.batch,
            course=self.science,
            title="Lab reading",
            instructions="Read chapter 2.",
            due_date=date(2026, 6, 2),
        )
        Attendance.objects.create(
            academic_session=self.session,
            batch=self.batch,
            date=date(2026, 5, 29),
            status=Attendance.Status.PRESENT,
            note="On time",
        )
        Attendance.objects.create(
            academic_session=self.session,
            batch=self.batch,
            date=date(2026, 5, 30),
            status=Attendance.Status.LATE,
            note="Traffic",
        )
        Attendance.objects.create(
            academic_session=self.session,
            batch=self.batch,
            date=date(2026, 5, 31),
            status=Attendance.Status.ABSENT,
            note="Leave",
        )
        self.notice = Notice.objects.create(
            institute=self.institute,
            title="Exam circular",
            message="<p>Math exam starts next week.</p>",
            audience=Notice.Audience.STUDENTS_PARENTS,
            category=Notice.Category.EXAM,
            priority=Notice.Priority.IMPORTANT,
            pin_on_top=True,
        )
        self.batch_notice = Notice.objects.create(
            institute=self.institute,
            title="Batch timing update",
            message="Morning batch starts at 8 AM.",
            audience=Notice.Audience.STUDENTS_PARENTS,
            category=Notice.Category.GENERAL,
            priority=Notice.Priority.NORMAL,
        )
        self.batch_notice.target_batches.add(self.batch)

    def auth_headers(self):
        return {"HTTP_AUTHORIZATION": f"Bearer {create_access_token(self.user)}"}

    def test_mobile_homework_planner_groups_subject_wise_with_batch(self):
        response = self.client.get("/api/mobile/homework/", **self.auth_headers())

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["summary"]["homework_count"], 2)
        self.assertEqual(data["summary"]["subject_count"], 2)
        math_group = next(group for group in data["subject_wise"] if group["name"] == "Mathematics")
        self.assertEqual(math_group["items"][0]["batch"]["name"], "Morning")
        self.assertEqual(math_group["items"][0]["title"], "Algebra practice")
        self.assertIn("/api/mobile/homework/document/download/", data["document_download_url"])

    def test_mobile_homework_document_download_returns_html(self):
        response = self.client.get(
            "/api/mobile/homework/document/download/",
            **self.auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/html")
        self.assertIn("homework-planner-ADM-001.html", response["Content-Disposition"])
        html = response.content.decode()
        self.assertIn("Homework Planner", html)
        self.assertIn("Algebra practice", html)

    def test_mobile_attendance_returns_summary_and_records(self):
        response = self.client.get(
            "/api/mobile/attendance/?date_from=2026-05-01&date_to=2026-05-31",
            **self.auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["summary"]["total_count"], 3)
        self.assertEqual(data["summary"]["present_count"], 1)
        self.assertEqual(data["summary"]["late_count"], 1)
        self.assertEqual(data["summary"]["absent_count"], 1)
        self.assertEqual(data["summary"]["attendance_rate"], 66.7)
        self.assertEqual(data["records"][0]["status"], Attendance.Status.ABSENT)
        self.assertEqual(data["batch_wise"][0]["name"], "Morning")

    def test_mobile_attendance_supports_status_filter(self):
        response = self.client.get(
            "/api/mobile/attendance/?date_from=2026-05-01&date_to=2026-05-31&status=LATE",
            **self.auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["summary"]["total_count"], 1)
        self.assertEqual(data["records"][0]["note"], "Traffic")

    def test_mobile_attendance_requires_valid_token(self):
        response = self.client.get("/api/mobile/attendance/")

        self.assertEqual(response.status_code, 401)

    def test_mobile_notices_returns_targeted_active_notices(self):
        response = self.client.get("/api/mobile/notices/", **self.auth_headers())

        self.assertEqual(response.status_code, 200)
        data = response.json()
        titles = [notice["title"] for notice in data["notices"]]
        self.assertIn("Exam circular", titles)
        self.assertIn("Batch timing update", titles)
        self.assertEqual(data["summary"]["total_count"], 2)
        self.assertEqual(data["summary"]["unread_count"], 2)
        self.assertEqual(data["notices"][0]["message"], "Math exam starts next week.")

    def test_mobile_notice_mark_read_updates_unread_count(self):
        response = self.client.post(
            f"/api/mobile/notices/{self.notice.pk}/read/",
            **self.auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        listing = self.client.get("/api/mobile/notices/", **self.auth_headers())
        data = listing.json()
        read_notice = next(notice for notice in data["notices"] if notice["id"] == self.notice.pk)
        self.assertTrue(read_notice["is_read"])
        self.assertEqual(data["summary"]["unread_count"], 1)


class MobilePushNotificationTests(TestCase):
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
            admission_number="ADM-002",
        )
        self.academic_year = AcademicYear.objects.create(
            institute=self.institute,
            name="2026-27",
            start_date=date(2026, 4, 1),
            end_date=date(2027, 3, 31),
        )
        self.batch = Batch.objects.create(
            institute=self.institute,
            academic_year=self.academic_year,
            name="Morning",
        )

    def auth_headers(self):
        return {"HTTP_AUTHORIZATION": f"Bearer {create_access_token(self.user)}"}

    def test_mobile_register_device_stores_token_for_authenticated_user(self):
        response = self.client.post(
            "/api/mobile/devices/register/",
            data='{"token":"fcm-token-1","platform":"ANDROID","device_id":"device-1"}',
            content_type="application/json",
            **self.auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        device = UserDevice.objects.get(token="fcm-token-1")
        self.assertEqual(device.user, self.user)
        self.assertEqual(device.platform, UserDevice.Platform.ANDROID)
        self.assertTrue(device.is_active)

    def test_notification_log_is_created_for_particular_result_student(self):
        exam = Exam.objects.create(batch=self.batch, title="Unit Test", exam_date=date(2026, 6, 1))
        result = ExamResult.objects.create(exam=exam, student=self.student, marks_obtained="88.00")

        notification = notify_result_declared(result)

        self.assertEqual(notification.user, self.user)
        self.assertEqual(notification.notification_type, PushNotification.NotificationType.RESULT_DECLARED)
        self.assertEqual(notification.status, PushNotification.Status.SKIPPED)
        self.assertEqual(PushNotification.objects.count(), 1)
