import json
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from institute_admin.models import AcademicYear, Batch, Course
from student_parent.models import GuardianProfile, StudentAcademicSession, StudentEnrollment, StudentProfile

from .models import Institute, UserProfile


class AuthEndpointTests(TestCase):
    def setUp(self):
        self.institute = Institute.objects.create(
            name="Arohan Academy",
            code="aa",
            status=Institute.Status.ACTIVE,
        )
        self.user = User.objects.create_user(
            username="admin",
            password="pass12345",
            email="admin@example.com",
            first_name="Admin",
            last_name="User",
        )
        UserProfile.objects.create(
            user=self.user,
            institute=self.institute,
            role=UserProfile.Role.INSTITUTE_ADMIN,
            phone="9000000000",
        )

    def post_json(self, url_name, data):
        return self.client.post(
            reverse(url_name),
            data=json.dumps(data),
            content_type="application/json",
        )

    def test_login_accepts_valid_credentials_and_creates_session(self):
        response = self.post_json(
            "api_login",
            {"username": "admin", "password": "pass12345"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["detail"], "Login successful.")
        self.assertEqual(payload["user"]["username"], "admin")
        self.assertEqual(payload["user"]["role"], UserProfile.Role.INSTITUTE_ADMIN)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_login_rejects_invalid_or_inactive_credentials(self):
        response = self.post_json(
            "api_login",
            {"username": "admin", "password": "wrong-password"},
        )
        self.assertEqual(response.status_code, 401)

        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        response = self.post_json(
            "api_login",
            {"username": "admin", "password": "pass12345"},
        )
        self.assertEqual(response.status_code, 401)

    def test_login_requires_post_and_required_fields(self):
        response = self.client.get(reverse("api_login"))
        self.assertEqual(response.status_code, 405)

        response = self.post_json("api_login", {"username": "admin"})
        self.assertEqual(response.status_code, 400)

    def test_logout_requires_authenticated_post(self):
        response = self.client.post(reverse("api_logout"))
        self.assertEqual(response.status_code, 401)

        self.client.force_login(self.user)
        response = self.client.get(reverse("api_logout"))
        self.assertEqual(response.status_code, 405)

        response = self.client.post(reverse("api_logout"))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_mobile_login_returns_tokens_without_session_login(self):
        response = self.post_json(
            "mobile_login",
            {"username": "admin", "password": "pass12345"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["token_type"], "Bearer")
        self.assertIn("access", payload)
        self.assertIn("refresh", payload)
        self.assertEqual(payload["user"]["role"], UserProfile.Role.INSTITUTE_ADMIN)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_mobile_access_token_can_read_profile(self):
        login_response = self.post_json(
            "mobile_login",
            {"username": "admin", "password": "pass12345"},
        )
        access_token = login_response.json()["access"]

        response = self.client.get(
            reverse("mobile_me"),
            headers={"Authorization": f"Bearer {access_token}"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["username"], "admin")

    def test_mobile_refresh_issues_new_access_token(self):
        login_response = self.post_json(
            "mobile_login",
            {"username": "admin", "password": "pass12345"},
        )
        refresh_token = login_response.json()["refresh"]

        response = self.post_json("mobile_token_refresh", {"refresh": refresh_token})

        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.json())

    def test_mobile_logout_revokes_refresh_token(self):
        login_response = self.post_json(
            "mobile_login",
            {"username": "admin", "password": "pass12345"},
        )
        refresh_token = login_response.json()["refresh"]

        response = self.post_json("mobile_logout", {"refresh": refresh_token})
        self.assertEqual(response.status_code, 200)

        response = self.post_json("mobile_token_refresh", {"refresh": refresh_token})
        self.assertEqual(response.status_code, 401)

    def test_mobile_profile_returns_student_details(self):
        student_user = User.objects.create_user(
            username="student",
            password="pass12345",
            email="student@example.com",
            first_name="Demo",
            last_name="Student",
        )
        UserProfile.objects.create(
            user=student_user,
            institute=self.institute,
            role=UserProfile.Role.STUDENT_PARENT,
            phone="9111111111",
        )
        student = StudentProfile.objects.create(
            institute=self.institute,
            user=student_user,
            admission_number="ADM-001",
            date_of_birth=date(2010, 1, 2),
            address="Main Road",
        )
        GuardianProfile.objects.create(
            student=student,
            name="Parent One",
            relation="Father",
            phone="9222222222",
            is_primary=True,
        )
        academic_year = AcademicYear.objects.create(
            institute=self.institute,
            name="2026-27",
            start_date=date(2026, 4, 1),
            end_date=date(2027, 3, 31),
        )
        course = Course.objects.create(
            institute=self.institute,
            academic_year=academic_year,
            name="Class 10",
            fee_amount=Decimal("12000.00"),
        )
        batch = Batch.objects.create(
            institute=self.institute,
            academic_year=academic_year,
            name="Morning",
        )
        batch.courses.add(course)
        session = StudentAcademicSession.objects.create(
            institute=self.institute,
            student=student,
            academic_year=academic_year,
            admission_number="ADM-001",
        )
        enrollment = StudentEnrollment.objects.create(
            student=student,
            academic_session=session,
            batch=batch,
        )
        enrollment.courses.add(course)
        login_response = self.post_json(
            "mobile_login",
            {"username": "student", "password": "pass12345"},
        )
        access_token = login_response.json()["access"]

        response = self.client.get(
            reverse("mobile_profile"),
            headers={"Authorization": f"Bearer {access_token}"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["student"]["admission_number"], "ADM-001")
        self.assertEqual(data["student"]["phone"], "9111111111")
        self.assertEqual(data["guardians"][0]["name"], "Parent One")
        self.assertEqual(data["enrollments"][0]["batch"]["name"], "Morning")
