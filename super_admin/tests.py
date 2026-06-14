import json
from datetime import date, timedelta
from decimal import Decimal

from django.contrib import admin
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.test.client import RequestFactory
from django.contrib.sessions.middleware import SessionMiddleware
from django.urls import reverse
from unittest.mock import patch

from accountant.models import FeeInvoice
from institute_admin.models import AcademicYear, Batch, Course
from student_parent.models import GuardianProfile, StudentAcademicSession, StudentEnrollment, StudentProfile

from .models import (
    Institute,
    InstituteRegistration,
    InstituteSubscription,
    SubscriptionPayment,
    UserProfile,
)
from .mobile_auth import create_access_token, create_refresh_token
from .subscription_warning import SESSION_KEY, subscription_expiry_warning


class SaaSAdminTests(TestCase):
    def test_admin_contains_only_saas_control_models_and_users(self):
        registered_models = set(admin.site._registry)

        self.assertIn(User, registered_models)
        self.assertIn(Institute, registered_models)
        self.assertNotIn(InstituteRegistration, registered_models)
        self.assertNotIn(UserProfile, registered_models)
        self.assertNotIn(InstituteSubscription, registered_models)
        self.assertIn(SubscriptionPayment, registered_models)
        self.assertNotIn(Course, registered_models)
        self.assertNotIn(StudentProfile, registered_models)
        self.assertNotIn(FeeInvoice, registered_models)


class SaaSBillingModelTests(TestCase):
    def setUp(self):
        self.institute = Institute.objects.create(
            name="Billing Institute",
            code="billing-institute",
            status=Institute.Status.ACTIVE,
        )
        self.subscription = InstituteSubscription.objects.create(
            institute=self.institute,
            starts_on=date.today(),
            ends_on=date.today() + timedelta(days=30),
        )

    def test_subscription_uses_end_date_as_expiry(self):
        self.assertEqual(self.subscription.plan, InstituteSubscription.Plan.FREE_TRIAL)
        self.assertEqual(self.subscription.expiry_date, self.subscription.ends_on)
        self.assertFalse(self.subscription.is_expired)
        self.assertTrue(self.subscription.is_active)

    def test_invalid_subscription_date_range_is_rejected(self):
        self.subscription.ends_on = date.today() - timedelta(days=1)

        with self.assertRaises(ValidationError):
            self.subscription.full_clean()

    def test_payment_history_is_stored_directly_against_school(self):
        payment = SubscriptionPayment.objects.create(
            institute=self.institute,
            amount=Decimal("500.00"),
            method=SubscriptionPayment.Method.UPI,
            transaction_id="TXN-500",
        )

        self.assertEqual(payment.institute, self.institute)
        self.assertEqual(payment.transaction_id, "TXN-500")

    def test_expired_school_is_blocked_from_web_and_api_login(self):
        self.subscription.ends_on = date.today() - timedelta(days=1)
        self.subscription.save(update_fields=["ends_on"])
        user = User.objects.create_user(username="expired-admin", password="pass12345")
        UserProfile.objects.create(
            user=user,
            institute=self.institute,
            role=UserProfile.Role.INSTITUTE_ADMIN,
        )

        self.client.force_login(user)
        response = self.client.get(reverse("institute_admin:dashboard"))
        self.assertRedirects(
            response,
            f"{reverse('subscription_expired')}?reason=Your%20software%20subscription%20has%20expired.",
            fetch_redirect_response=False,
        )

        self.client.logout()
        response = self.client.post(
            reverse("api_login"),
            data=json.dumps({"username": "expired-admin", "password": "pass12345"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)


class ExpiredSubscriptionAccessTests(TestCase):
    def setUp(self):
        self.institute = Institute.objects.create(
            name="Expired Institute",
            code="expired-institute",
            status=Institute.Status.ACTIVE,
        )
        self.subscription = InstituteSubscription.objects.create(
            institute=self.institute,
            plan=InstituteSubscription.Plan.PREMIUM,
            starts_on=date.today() - timedelta(days=60),
            ends_on=date.today() - timedelta(days=1),
        )

    def create_user(self, username, role):
        user = User.objects.create_user(username=username, password="pass12345")
        UserProfile.objects.create(user=user, institute=self.institute, role=role)
        return user

    def assert_locked(self, user, url):
        self.client.force_login(user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url.split("?")[0], reverse("subscription_expired"))
        self.client.logout()

    def test_all_institute_roles_are_blocked_from_panel_pages(self):
        cases = (
            (UserProfile.Role.INSTITUTE_ADMIN, reverse("institute_admin:dashboard")),
            (UserProfile.Role.TEACHER, reverse("teacher:dashboard")),
            (UserProfile.Role.STUDENT_PARENT, reverse("student_parent:download_app")),
        )
        for index, (role, url) in enumerate(cases):
            with self.subTest(role=role):
                self.assert_locked(self.create_user(f"expired-{index}", role), url)

    def test_recovery_help_and_security_pages_remain_available(self):
        admin_user = self.create_user("expired-help-admin", UserProfile.Role.INSTITUTE_ADMIN)
        self.client.force_login(admin_user)

        for url in (reverse("security_settings"), reverse("help_support")):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)

    def test_expired_api_request_returns_machine_readable_renewal_response(self):
        teacher = self.create_user("expired-api-teacher", UserProfile.Role.TEACHER)
        self.client.force_login(teacher)

        response = self.client.get("/api/mobile/bootstrap/")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "subscription_expired")
        self.assertTrue(response.json()["renewal_required"])

    def test_expired_student_mobile_identity_and_refresh_remain_valid(self):
        student = self.create_user(
            "expired-mobile-student",
            UserProfile.Role.STUDENT_PARENT,
        )
        access_token = create_access_token(student)
        refresh_token = create_refresh_token(student)

        me_response = self.client.get(
            reverse("mobile_me"),
            headers={"Authorization": f"Bearer {access_token}"},
        )
        refresh_response = self.client.post(
            reverse("mobile_token_refresh"),
            data=json.dumps({"refresh": refresh_token}),
            content_type="application/json",
        )

        self.assertEqual(me_response.status_code, 200)
        self.assertFalse(
            me_response.json()["user"]["subscription_access_allowed"]
        )
        self.assertEqual(refresh_response.status_code, 200)
        self.assertFalse(
            refresh_response.json()["user"]["subscription_access_allowed"]
        )

    def test_institute_admin_can_open_renewal_and_billing_pages(self):
        admin_user = self.create_user("expired-renew-admin", UserProfile.Role.INSTITUTE_ADMIN)
        self.client.force_login(admin_user)

        expired_response = self.client.get(reverse("subscription_expired"))
        billing_response = self.client.get(reverse("subscription_billing"))

        self.assertEqual(expired_response.status_code, 200)
        self.assertContains(expired_response, "Renew subscription")
        self.assertContains(expired_response, self.institute.name)
        self.assertEqual(billing_response.status_code, 200)

    def test_teacher_sees_locked_page_without_renewal_control(self):
        teacher = self.create_user("expired-locked-teacher", UserProfile.Role.TEACHER)
        self.client.force_login(teacher)

        response = self.client.get(reverse("subscription_expired"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "contact your institute administrator")
        self.assertNotContains(response, "Renew subscription")


class SubscriptionExpiryWarningTests(TestCase):
    def setUp(self):
        self.today = date(2026, 6, 13)
        self.institute = Institute.objects.create(
            name="Reminder Institute",
            code="reminder-institute",
            status=Institute.Status.ACTIVE,
        )
        self.subscription = InstituteSubscription.objects.create(
            institute=self.institute,
            plan=InstituteSubscription.Plan.PREMIUM,
            starts_on=self.today - timedelta(days=30),
            ends_on=self.today + timedelta(days=5),
        )
        self.user = User.objects.create_user(username="reminder-admin", password="pass12345")
        UserProfile.objects.create(
            user=self.user,
            institute=self.institute,
            role=UserProfile.Role.INSTITUTE_ADMIN,
        )

    def request_for(self, user=None):
        request = RequestFactory().get("/institute/")
        request.user = user or self.user
        SessionMiddleware(lambda req: None).process_request(request)
        request.session.save()
        return request

    @patch("super_admin.subscription_warning.timezone.localdate")
    def test_warning_starts_at_five_days_and_includes_expiry_day(self, localdate):
        localdate.return_value = self.today
        warning = subscription_expiry_warning(self.request_for())
        self.assertTrue(warning["show"])
        self.assertEqual(warning["days_remaining"], 5)

        localdate.return_value = self.subscription.ends_on
        warning = subscription_expiry_warning(self.request_for())
        self.assertTrue(warning["show"])
        self.assertEqual(warning["days_remaining"], 0)

    @patch("super_admin.subscription_warning.timezone.localdate")
    def test_warning_does_not_show_before_five_day_window_or_after_expiry(self, localdate):
        localdate.return_value = self.today
        self.subscription.ends_on = self.today + timedelta(days=6)
        self.subscription.save(update_fields=["ends_on"])
        self.assertIsNone(subscription_expiry_warning(self.request_for()))

        self.subscription.ends_on = self.today - timedelta(days=1)
        self.subscription.save(update_fields=["ends_on"])
        self.assertIsNone(subscription_expiry_warning(self.request_for()))

    @patch("super_admin.subscription_warning.timezone.localdate")
    def test_acknowledgement_hides_only_current_day_and_current_expiry(self, localdate):
        localdate.return_value = self.today
        request = self.request_for()
        warning = subscription_expiry_warning(request)
        request.session[SESSION_KEY] = warning["acknowledgement"]
        request.session.save()
        self.assertFalse(subscription_expiry_warning(request)["show"])

        localdate.return_value = self.today + timedelta(days=1)
        self.assertTrue(subscription_expiry_warning(request)["show"])

        localdate.return_value = self.today
        self.subscription.ends_on = self.today + timedelta(days=4)
        self.subscription.save(update_fields=["ends_on"])
        self.assertTrue(subscription_expiry_warning(request)["show"])

    @patch("super_admin.subscription_warning.timezone.localdate")
    def test_acknowledgement_endpoint_suppresses_modal_for_same_day(self, localdate):
        localdate.return_value = self.today
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("acknowledge_subscription_expiry"),
            {"next": reverse("institute_admin:dashboard")},
        )

        self.assertRedirects(
            response,
            reverse("institute_admin:dashboard"),
            fetch_redirect_response=False,
        )
        session = self.client.session
        self.assertEqual(
            session[SESSION_KEY],
            f"{self.subscription.ends_on.isoformat()}:{self.today.isoformat()}",
        )

    @patch("super_admin.models.timezone.localdate")
    @patch("super_admin.context_processors.timezone.localdate")
    @patch("super_admin.subscription_warning.timezone.localdate")
    def test_institute_layout_renders_warning_then_hides_after_acknowledgement(
        self,
        warning_localdate,
        context_localdate,
        model_localdate,
    ):
        warning_localdate.return_value = self.today
        context_localdate.return_value = self.today
        model_localdate.return_value = self.today
        self.client.force_login(self.user)

        response = self.client.get(reverse("institute_admin:dashboard"))
        self.assertContains(response, "Subscription expiry reminder")
        self.assertContains(response, "OK, do not show again today")

        self.client.post(
            reverse("acknowledge_subscription_expiry"),
            {"next": reverse("institute_admin:dashboard")},
        )
        response = self.client.get(reverse("institute_admin:dashboard"))
        self.assertNotContains(response, "Subscription expiry reminder")

    @patch("super_admin.subscription_warning.timezone.localdate")
    def test_acknowledgement_rejects_external_redirect(self, localdate):
        localdate.return_value = self.today
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("acknowledge_subscription_expiry"),
            {"next": "https://example.com/steal"},
        )

        self.assertRedirects(
            response,
            reverse("school_dashboard"),
            fetch_redirect_response=False,
        )


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

    def test_mobile_change_password_requires_current_password(self):
        login_response = self.post_json(
            "mobile_login",
            {"username": "admin", "password": "pass12345"},
        )
        access_token = login_response.json()["access"]

        response = self.client.post(
            reverse("mobile_change_password"),
            data=json.dumps(
                {
                    "current_password": "wrong-password",
                    "new_password": "newpass12345",
                    "confirm_password": "newpass12345",
                }
            ),
            content_type="application/json",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("pass12345"))

        response = self.client.post(
            reverse("mobile_change_password"),
            data=json.dumps(
                {
                    "current_password": "pass12345",
                    "new_password": "newpass12345",
                    "confirm_password": "newpass12345",
                }
            ),
            content_type="application/json",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("newpass12345"))

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
            weekly_timetable={
                "monday": {"start": "09:00", "end": "11:00"},
                "wednesday": {"start": "13:00", "end": "15:00"},
            },
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
        self.assertEqual(
            data["enrollments"][0]["batch"]["weekly_timetable"]["monday"],
            {"start": "09:00", "end": "11:00"},
        )


class InstituteSignupOnboardingTests(TestCase):
    def signup_data(self):
        return {
            "institute_name": "New Learning Center",
            "institute_code": "new-learning-center",
            "owner_name": "New Owner",
            "phone": "9000012345",
            "email": "owner@example.com",
            "username": "new-owner",
            "password1": "StrongPass123!",
            "password2": "StrongPass123!",
        }

    def test_signup_creates_fourteen_day_trial_and_opens_tour(self):
        today = date.today()

        response = self.client.post(reverse("signup"), self.signup_data())

        user = User.objects.get(username="new-owner")
        profile = user.profile
        subscription = profile.institute.subscription
        self.assertRedirects(response, reverse("institute_admin:software_tour"))
        self.assertIsNone(profile.onboarding_completed_at)
        self.assertEqual(profile.institute.status, Institute.Status.TRIAL)
        self.assertEqual(subscription.plan, InstituteSubscription.Plan.FREE_TRIAL)
        self.assertEqual(subscription.starts_on, today)
        self.assertEqual(subscription.ends_on, today + timedelta(days=14))

    def test_tour_can_be_finished_only_once(self):
        self.client.post(reverse("signup"), self.signup_data())

        tour_response = self.client.get(reverse("institute_admin:software_tour"))
        self.assertEqual(tour_response.status_code, 200)
        self.assertContains(tour_response, "Your Institute. One Control Center.")
        self.assertContains(tour_response, "Next")
        self.assertContains(tour_response, 'method="post"')
        self.assertContains(tour_response, "csrfmiddlewaretoken")

        finish_response = self.client.post(reverse("institute_admin:software_tour"))
        self.assertRedirects(finish_response, reverse("institute_admin:dashboard"))
        self.assertIsNotNone(
            User.objects.get(username="new-owner").profile.onboarding_completed_at
        )

        revisit_response = self.client.get(reverse("institute_admin:software_tour"))
        self.assertRedirects(revisit_response, reverse("institute_admin:dashboard"))
