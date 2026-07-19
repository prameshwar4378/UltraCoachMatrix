import json
import tempfile
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import AnonymousUser, User
from django.contrib.admin.sites import AdminSite
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, override_settings
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from super_admin.mobile_auth import create_access_token
from super_admin.private_media import private_media

from .admin import PartnerCommissionAdmin, PartnerSaleClaimAdmin
from .models import (
    PartnerCallHistory,
    PartnerCommission,
    PartnerLead,
    PartnerProfile,
    PartnerSaleClaim,
)


class PartnerAuthTests(TestCase):
    def post_json(self, name, payload):
        return self.client.post(
            reverse(f"ucm_partner:{name}"),
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_partner_login_returns_tokens(self):
        user = User.objects.create_user(username="partner1", password="pass12345")
        PartnerProfile.objects.create(
            user=user,
            full_name="Partner One",
            mobile="9999999999",
            area="Pune",
            bank_account_holder_name="Partner One",
            bank_name="HDFC Bank",
            bank_account_number="1234567890",
            bank_ifsc_code="HDFC0001234",
            phonepe_number="9999999999",
            google_pay_number="8888888888",
        )

        response = self.post_json(
            "login",
            {"username": "partner1", "password": "pass12345"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["token_type"], "Bearer")
        self.assertIn("access", payload)
        self.assertIn("refresh", payload)
        self.assertEqual(payload["partner"]["name"], "Partner One")
        self.assertEqual(payload["partner"]["bank_name"], "HDFC Bank")
        self.assertEqual(payload["partner"]["bank_ifsc_code"], "HDFC0001234")
        self.assertEqual(payload["partner"]["phonepe_number"], "9999999999")
        self.assertEqual(payload["partner"]["google_pay_number"], "8888888888")

    def test_non_partner_login_is_rejected(self):
        User.objects.create_user(username="teacher1", password="pass12345")

        response = self.post_json(
            "login",
            {"username": "teacher1", "password": "pass12345"},
        )

        self.assertEqual(response.status_code, 401)


class PartnerLeadApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="partner1", password="pass12345")
        self.partner = PartnerProfile.objects.create(
            user=self.user,
            full_name="Partner One",
            mobile="9999999999",
            area="Pune",
        )
        self.other_user = User.objects.create_user(username="partner2", password="pass12345")
        self.other_partner = PartnerProfile.objects.create(
            user=self.other_user,
            full_name="Partner Two",
            mobile="8888888888",
            area="Mumbai",
        )

    def auth_headers(self, user=None):
        return {"HTTP_AUTHORIZATION": f"Bearer {create_access_token(user or self.user)}"}

    def request_json(self, method, name, payload=None, *, kwargs=None, user=None):
        request = getattr(self.client, method)
        return request(
            reverse(f"ucm_partner:{name}", kwargs=kwargs),
            data=json.dumps(payload or {}),
            content_type="application/json",
            **self.auth_headers(user),
        )

    def test_partner_can_create_and_list_own_leads(self):
        response = self.request_json(
            "post",
            "leads",
            {
                "school_name": "ABC School",
                "contact_person": "Mr Sharma",
                "mobile": "9876543210",
                "city": "Pune",
                "status": "FOLLOW_UP",
                "priority": "HOT",
                "next_follow_up_on": "2026-07-20",
                "notes": "Interested in demo.",
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["lead"]["school_name"], "ABC School")
        self.assertEqual(response.json()["lead"]["priority"], "HOT")
        self.assertEqual(response.json()["lead"]["priority_label"], "Hot")
        self.assertEqual(PartnerLead.objects.count(), 1)
        self.assertEqual(PartnerLead.objects.first().partner, self.partner)

        list_response = self.client.get(
            reverse("ucm_partner:leads"),
            **self.auth_headers(),
        )

        self.assertEqual(list_response.status_code, 200)
        leads = list_response.json()["leads"]
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["mobile"], "9876543210")
        self.assertEqual(leads[0]["priority"], "HOT")

    def test_partner_can_view_and_patch_own_lead(self):
        lead = PartnerLead.objects.create(
            partner=self.partner,
            school_name="ABC School",
            mobile="9876543210",
        )

        detail_response = self.client.get(
            reverse("ucm_partner:lead_detail", kwargs={"lead_id": lead.pk}),
            **self.auth_headers(),
        )
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.json()["lead"]["status"], "NEW")
        self.assertEqual(detail_response.json()["lead"]["priority"], "WARM")

        patch_response = self.request_json(
            "patch",
            "lead_detail",
            {
                "status": "CONVERTED",
                "priority": "COLD",
                "notes": "Converted after demo.",
                "next_follow_up_on": None,
            },
            kwargs={"lead_id": lead.pk},
        )

        self.assertEqual(patch_response.status_code, 200)
        lead.refresh_from_db()
        self.assertEqual(lead.status, PartnerLead.Status.CONVERTED)
        self.assertEqual(lead.priority, PartnerLead.Priority.COLD)
        self.assertEqual(lead.notes, "Converted after demo.")
        self.assertIsNone(lead.next_follow_up_on)

    def test_partner_cannot_patch_lead_after_commission_paid(self):
        lead = PartnerLead.objects.create(
            partner=self.partner,
            school_name="Paid School",
            mobile="9876543210",
            status=PartnerLead.Status.CONVERTED,
        )
        PartnerSaleClaim.objects.create(
            partner=self.partner,
            lead=lead,
            selling_price=Decimal("10000.00"),
            payment_screenshot="partner_sale_claims/screenshots/payment.png",
            status=PartnerSaleClaim.Status.PAID,
        )

        response = self.request_json(
            "patch",
            "lead_detail",
            {"status": "FOLLOW_UP", "notes": "Try to edit paid deal."},
            kwargs={"lead_id": lead.pk},
        )

        self.assertEqual(response.status_code, 409)
        lead.refresh_from_db()
        self.assertEqual(lead.status, PartnerLead.Status.CONVERTED)
        self.assertEqual(lead.notes, "")

    def test_partner_cannot_access_another_partner_lead(self):
        other_lead = PartnerLead.objects.create(
            partner=self.other_partner,
            school_name="Other School",
            mobile="7777777777",
        )

        response = self.client.get(
            reverse("ucm_partner:lead_detail", kwargs={"lead_id": other_lead.pk}),
            **self.auth_headers(),
        )

        self.assertEqual(response.status_code, 404)

    def test_lead_api_requires_partner_token(self):
        response = self.client.get(reverse("ucm_partner:leads"))

        self.assertEqual(response.status_code, 401)

    def test_create_lead_validates_required_fields_status_and_priority(self):
        response = self.request_json(
            "post",
            "leads",
            {"school_name": "", "mobile": "", "status": "BAD", "priority": "BAD"},
        )

        self.assertEqual(response.status_code, 400)
        errors = response.json()["errors"]
        self.assertIn("school_name", errors)
        self.assertIn("mobile", errors)
        self.assertIn("status", errors)
        self.assertIn("priority", errors)

    def test_create_lead_defaults_priority_to_warm(self):
        response = self.request_json(
            "post",
            "leads",
            {"school_name": "Default Priority School", "mobile": "9876543210"},
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["lead"]["priority"], "WARM")
        self.assertEqual(response.json()["lead"]["priority_label"], "Warm")
        self.assertEqual(PartnerLead.objects.first().priority, PartnerLead.Priority.WARM)


class PartnerDashboardApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="partner1", password="pass12345")
        self.partner = PartnerProfile.objects.create(
            user=self.user,
            full_name="Partner One",
            mobile="9999999999",
        )
        self.other_user = User.objects.create_user(username="partner2", password="pass12345")
        self.other_partner = PartnerProfile.objects.create(
            user=self.other_user,
            full_name="Partner Two",
            mobile="8888888888",
        )

    def auth_headers(self, user=None):
        return {"HTTP_AUTHORIZATION": f"Bearer {create_access_token(user or self.user)}"}

    def test_dashboard_returns_partner_counts_and_commission_totals(self):
        today = timezone.localdate()
        converted_lead = PartnerLead.objects.create(
            partner=self.partner,
            school_name="Converted School",
            mobile="9000000001",
            status=PartnerLead.Status.CONVERTED,
            next_follow_up_on=today,
        )
        pending_lead = PartnerLead.objects.create(
            partner=self.partner,
            school_name="Pending School",
            mobile="9000000002",
            next_follow_up_on=today,
        )
        paid_lead = PartnerLead.objects.create(
            partner=self.partner,
            school_name="Paid School",
            mobile="9000000003",
        )
        PartnerLead.objects.create(
            partner=self.other_partner,
            school_name="Other School",
            mobile="9000000004",
            status=PartnerLead.Status.CONVERTED,
            next_follow_up_on=today,
        )

        PartnerCommission.objects.create(
            partner=self.partner,
            lead=converted_lead,
            sale_amount=Decimal("10000.00"),
            commission_percent=Decimal("20.00"),
            status=PartnerCommission.Status.PENDING,
        )
        PartnerCommission.objects.create(
            partner=self.partner,
            lead=paid_lead,
            sale_amount=Decimal("5000.00"),
            commission_percent=Decimal("20.00"),
            status=PartnerCommission.Status.PAID,
            paid_on=today,
        )
        PartnerCommission.objects.create(
            partner=self.other_partner,
            lead=PartnerLead.objects.create(
                partner=self.other_partner,
                school_name="Other Paid School",
                mobile="9000000005",
            ),
            sale_amount=Decimal("50000.00"),
            commission_percent=Decimal("20.00"),
            status=PartnerCommission.Status.PAID,
            paid_on=today,
        )

        response = self.client.get(
            reverse("ucm_partner:dashboard"),
            **self.auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_leads"], 3)
        self.assertEqual(payload["today_follow_ups"], 2)
        self.assertEqual(payload["converted_leads"], 1)
        self.assertEqual(payload["pending_commission"], "2000.00")
        self.assertEqual(payload["paid_commission"], "1000.00")

    def test_dashboard_requires_partner_token(self):
        response = self.client.get(reverse("ucm_partner:dashboard"))

        self.assertEqual(response.status_code, 401)


class PartnerCommissionApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="partner1", password="pass12345")
        self.partner = PartnerProfile.objects.create(
            user=self.user,
            full_name="Partner One",
            mobile="9999999999",
        )
        self.other_user = User.objects.create_user(username="partner2", password="pass12345")
        self.other_partner = PartnerProfile.objects.create(
            user=self.other_user,
            full_name="Partner Two",
            mobile="8888888888",
        )

    def auth_headers(self, user=None):
        return {"HTTP_AUTHORIZATION": f"Bearer {create_access_token(user or self.user)}"}

    def test_partner_can_list_only_own_commissions(self):
        today = timezone.localdate()
        lead = PartnerLead.objects.create(
            partner=self.partner,
            school_name="ABC School",
            mobile="9000000001",
        )
        other_lead = PartnerLead.objects.create(
            partner=self.other_partner,
            school_name="Other School",
            mobile="9000000002",
        )
        PartnerCommission.objects.create(
            partner=self.partner,
            lead=lead,
            sale_amount=Decimal("15000.00"),
            commission_percent=Decimal("20.00"),
            status=PartnerCommission.Status.PAID,
            paid_on=today,
            transaction_id="TXN-ABC-1001",
        )
        PartnerCommission.objects.create(
            partner=self.other_partner,
            lead=other_lead,
            sale_amount=Decimal("50000.00"),
            commission_percent=Decimal("20.00"),
            status=PartnerCommission.Status.PENDING,
        )

        response = self.client.get(
            reverse("ucm_partner:commissions"),
            **self.auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        commissions = response.json()["commissions"]
        self.assertEqual(len(commissions), 1)
        self.assertEqual(commissions[0]["lead_school_name"], "ABC School")
        self.assertEqual(commissions[0]["sale_amount"], "15000.00")
        self.assertEqual(commissions[0]["commission_percent"], "20.00")
        self.assertEqual(commissions[0]["commission_amount"], "3000.00")
        self.assertEqual(commissions[0]["status"], "PAID")
        self.assertEqual(commissions[0]["sale_date"], today.isoformat())
        self.assertEqual(commissions[0]["paid_on"], today.isoformat())
        self.assertEqual(commissions[0]["transaction_id"], "TXN-ABC-1001")

    def test_commission_api_requires_partner_token(self):
        response = self.client.get(reverse("ucm_partner:commissions"))

        self.assertEqual(response.status_code, 401)

    def test_partner_cannot_create_commission_from_api(self):
        response = self.client.post(
            reverse("ucm_partner:commissions"),
            data=json.dumps({}),
            content_type="application/json",
            **self.auth_headers(),
        )

        self.assertEqual(response.status_code, 405)


class PartnerCommissionAdminTests(TestCase):
    def test_mark_selected_as_paid_sets_status_and_paid_date(self):
        user = User.objects.create_user(username="partner1", password="pass12345")
        partner = PartnerProfile.objects.create(
            user=user,
            full_name="Partner One",
            mobile="9999999999",
        )
        lead = PartnerLead.objects.create(
            partner=partner,
            school_name="ABC School",
            mobile="9000000001",
        )
        commission = PartnerCommission.objects.create(
            partner=partner,
            lead=lead,
            sale_amount=Decimal("10000.00"),
            commission_percent=Decimal("20.00"),
            status=PartnerCommission.Status.PENDING,
        )
        request = RequestFactory().post("/")
        request.session = {}
        request._messages = FallbackStorage(request)
        admin_model = PartnerCommissionAdmin(PartnerCommission, AdminSite())

        admin_model.mark_selected_as_paid(
            request,
            PartnerCommission.objects.filter(pk=commission.pk),
        )

        commission.refresh_from_db()
        self.assertEqual(commission.status, PartnerCommission.Status.PAID)
        self.assertEqual(commission.paid_on, timezone.localdate())


class PartnerSaleClaimModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="partner1", password="pass12345")
        self.partner = PartnerProfile.objects.create(
            user=self.user,
            full_name="Partner One",
            mobile="9999999999",
            commission_percent=Decimal("20.00"),
        )
        self.converted_lead = PartnerLead.objects.create(
            partner=self.partner,
            school_name="Converted School",
            mobile="9000000001",
            status=PartnerLead.Status.CONVERTED,
        )
        self.new_lead = PartnerLead.objects.create(
            partner=self.partner,
            school_name="New School",
            mobile="9000000002",
            status=PartnerLead.Status.NEW,
        )
        self.other_user = User.objects.create_user(username="partner2", password="pass12345")
        self.other_partner = PartnerProfile.objects.create(
            user=self.other_user,
            full_name="Partner Two",
            mobile="8888888888",
        )

    def test_sale_claim_defaults_pending_and_calculates_commission(self):
        claim = PartnerSaleClaim.objects.create(
            partner=self.partner,
            lead=self.converted_lead,
            selling_price=Decimal("15000.00"),
            payment_screenshot="partner_sale_claims/screenshots/payment.png",
            payment_note="Company payment received by Ultoxy.",
        )

        self.assertEqual(claim.status, PartnerSaleClaim.Status.PENDING_REVIEW)
        self.assertEqual(claim.commission_percent, Decimal("20.00"))
        self.assertEqual(claim.commission_amount, Decimal("3000.00"))
        self.assertIsNotNone(claim.submitted_at)
        self.assertIsNone(claim.approved_at)
        self.assertIsNone(claim.paid_at)
        commission = PartnerCommission.objects.get(lead=self.converted_lead)
        self.assertEqual(commission.status, PartnerCommission.Status.PENDING)
        self.assertEqual(commission.sale_amount, Decimal("15000.00"))
        self.assertEqual(commission.commission_amount, Decimal("3000.00"))

    def test_sale_claim_allowed_only_for_converted_lead(self):
        claim = PartnerSaleClaim(
            partner=self.partner,
            lead=self.new_lead,
            selling_price=Decimal("15000.00"),
            payment_screenshot="partner_sale_claims/screenshots/payment.png",
        )

        with self.assertRaises(ValidationError) as error:
            claim.save()

        self.assertIn("lead", error.exception.message_dict)

    def test_sale_claim_lead_must_belong_to_same_partner(self):
        other_lead = PartnerLead.objects.create(
            partner=self.other_partner,
            school_name="Other Converted School",
            mobile="9000000003",
            status=PartnerLead.Status.CONVERTED,
        )
        claim = PartnerSaleClaim(
            partner=self.partner,
            lead=other_lead,
            selling_price=Decimal("15000.00"),
            payment_screenshot="partner_sale_claims/screenshots/payment.png",
        )

        with self.assertRaises(ValidationError) as error:
            claim.save()

        self.assertIn("lead", error.exception.message_dict)

    def test_sale_claim_paid_status_sets_review_and_paid_timestamps(self):
        claim = PartnerSaleClaim.objects.create(
            partner=self.partner,
            lead=self.converted_lead,
            selling_price=Decimal("10000.00"),
            payment_screenshot="partner_sale_claims/screenshots/payment.png",
            status=PartnerSaleClaim.Status.PAID,
        )

        self.assertIsNotNone(claim.approved_at)
        self.assertIsNotNone(claim.paid_at)
        commission = PartnerCommission.objects.get(lead=self.converted_lead)
        self.assertEqual(commission.status, PartnerCommission.Status.PAID)
        self.assertEqual(commission.paid_on, claim.paid_at.date())

    def test_sale_claim_status_updates_existing_commission_record(self):
        claim = PartnerSaleClaim.objects.create(
            partner=self.partner,
            lead=self.converted_lead,
            selling_price=Decimal("10000.00"),
            payment_screenshot="partner_sale_claims/screenshots/payment.png",
        )

        claim.selling_price = Decimal("12000.00")
        claim.status = PartnerSaleClaim.Status.REJECTED
        claim.save()

        commission = PartnerCommission.objects.get(lead=self.converted_lead)
        self.assertEqual(commission.status, PartnerCommission.Status.CANCELLED)
        self.assertEqual(commission.sale_amount, Decimal("12000.00"))
        self.assertEqual(commission.commission_amount, Decimal("2400.00"))


class PartnerSaleClaimAdminTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="partner1", password="pass12345")
        self.partner = PartnerProfile.objects.create(
            user=self.user,
            full_name="Partner One",
            mobile="9999999999",
            commission_percent=Decimal("20.00"),
        )
        self.lead = PartnerLead.objects.create(
            partner=self.partner,
            school_name="Converted School",
            mobile="9000000001",
            status=PartnerLead.Status.CONVERTED,
        )
        self.claim = PartnerSaleClaim.objects.create(
            partner=self.partner,
            lead=self.lead,
            selling_price=Decimal("10000.00"),
            payment_screenshot="partner_sale_claims/screenshots/payment.png",
        )
        self.request = RequestFactory().post("/")
        self.request.session = {}
        self.request._messages = FallbackStorage(self.request)
        self.admin_model = PartnerSaleClaimAdmin(PartnerSaleClaim, AdminSite())

    def test_approve_selected_claims_sets_status_and_approved_at(self):
        self.admin_model.approve_selected_claims(
            self.request,
            PartnerSaleClaim.objects.filter(pk=self.claim.pk),
        )

        self.claim.refresh_from_db()
        self.assertEqual(self.claim.status, PartnerSaleClaim.Status.APPROVED)
        self.assertIsNotNone(self.claim.approved_at)
        self.assertIsNone(self.claim.paid_at)
        commission = PartnerCommission.objects.get(lead=self.lead)
        self.assertEqual(commission.status, PartnerCommission.Status.PENDING)

    def test_mark_selected_claims_as_paid_sets_status_and_timestamps(self):
        self.admin_model.mark_selected_claims_as_paid(
            self.request,
            PartnerSaleClaim.objects.filter(pk=self.claim.pk),
        )

        self.claim.refresh_from_db()
        self.assertEqual(self.claim.status, PartnerSaleClaim.Status.PAID)
        self.assertIsNotNone(self.claim.approved_at)
        self.assertIsNotNone(self.claim.paid_at)
        commission = PartnerCommission.objects.get(lead=self.lead)
        self.assertEqual(commission.status, PartnerCommission.Status.PAID)
        self.assertEqual(commission.paid_on, self.claim.paid_at.date())

    def test_reject_selected_claims_sets_status_and_admin_note(self):
        self.admin_model.reject_selected_claims(
            self.request,
            PartnerSaleClaim.objects.filter(pk=self.claim.pk),
        )

        self.claim.refresh_from_db()
        self.assertEqual(self.claim.status, PartnerSaleClaim.Status.REJECTED)
        self.assertIn("Rejected by admin", self.claim.admin_note)
        commission = PartnerCommission.objects.get(lead=self.lead)
        self.assertEqual(commission.status, PartnerCommission.Status.CANCELLED)

    def test_reject_action_does_not_reject_paid_claim(self):
        self.claim.status = PartnerSaleClaim.Status.PAID
        self.claim.save()

        self.admin_model.reject_selected_claims(
            self.request,
            PartnerSaleClaim.objects.filter(pk=self.claim.pk),
        )

        self.claim.refresh_from_db()
        self.assertEqual(self.claim.status, PartnerSaleClaim.Status.PAID)

    def test_payment_screenshot_preview_and_download_links(self):
        preview = str(self.admin_model.payment_screenshot_preview(self.claim))
        download = str(self.admin_model.payment_screenshot_download(self.claim))

        self.assertIn("payment.png", preview)
        self.assertIn("<img", preview)
        self.assertIn("Download screenshot", download)
        self.assertIn("payment.png", download)

    def test_manage_commission_payment_opens_default_commission_admin(self):
        button = str(self.admin_model.manage_commission_payment(self.claim))
        commission = PartnerCommission.objects.get(lead=self.lead)

        self.assertIn(
            f"/admin/UCMPartner/partnercommission/{commission.pk}/change/",
            button,
        )
        self.assertNotIn("window.open", button)
        self.assertIn("Add / update payment details", button)

    def test_manage_commission_payment_add_link_uses_default_commission_admin(self):
        PartnerCommission.objects.filter(lead=self.lead).delete()

        button = str(self.admin_model.manage_commission_payment(self.claim))

        self.assertIn("/admin/UCMPartner/partnercommission/add/", button)
        self.assertIn(f"partner={self.partner.pk}", button)
        self.assertIn(f"lead={self.lead.pk}", button)
        self.assertIn("sale_amount=10000.00", button)
        self.assertIn("commission_percent=20.00", button)

    def test_default_commission_admin_save_updates_claim_and_commission(self):
        paid_on = timezone.localdate()
        sale_date = paid_on - timedelta(days=7)
        commission = PartnerCommission.objects.get(lead=self.lead)
        commission.sale_amount = Decimal("12000.00")
        commission.commission_percent = Decimal("20.00")
        commission.status = PartnerCommission.Status.PAID
        commission.sale_date = sale_date
        commission.paid_on = paid_on
        commission.transaction_id = "TXN-UCM-1001"
        commission.notes = "Paid from default Django admin form."
        admin_model = PartnerCommissionAdmin(PartnerCommission, AdminSite())

        admin_model.save_model(self.request, commission, form=None, change=True)

        self.claim.refresh_from_db()
        commission = PartnerCommission.objects.get(lead=self.lead)
        self.assertEqual(self.claim.status, PartnerSaleClaim.Status.PAID)
        self.assertEqual(self.claim.selling_price, Decimal("12000.00"))
        self.assertEqual(self.claim.commission_amount, Decimal("2400.00"))
        self.assertEqual(self.claim.paid_at.date(), paid_on)
        self.assertEqual(commission.status, PartnerCommission.Status.PAID)
        self.assertEqual(commission.sale_amount, Decimal("12000.00"))
        self.assertEqual(commission.commission_amount, Decimal("2400.00"))
        self.assertEqual(commission.sale_date, sale_date)
        self.assertEqual(commission.paid_on, paid_on)
        self.assertEqual(commission.transaction_id, "TXN-UCM-1001")


class PartnerSaleClaimApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="partner1", password="pass12345")
        self.partner = PartnerProfile.objects.create(
            user=self.user,
            full_name="Partner One",
            mobile="9999999999",
            commission_percent=Decimal("20.00"),
        )
        self.converted_lead = PartnerLead.objects.create(
            partner=self.partner,
            school_name="Converted School",
            mobile="9000000001",
            status=PartnerLead.Status.CONVERTED,
        )
        self.new_lead = PartnerLead.objects.create(
            partner=self.partner,
            school_name="New School",
            mobile="9000000002",
            status=PartnerLead.Status.NEW,
        )
        self.other_user = User.objects.create_user(username="partner2", password="pass12345")
        self.other_partner = PartnerProfile.objects.create(
            user=self.other_user,
            full_name="Partner Two",
            mobile="8888888888",
        )
        self.other_lead = PartnerLead.objects.create(
            partner=self.other_partner,
            school_name="Other School",
            mobile="9000000003",
            status=PartnerLead.Status.CONVERTED,
        )

    def auth_headers(self, user=None):
        return {"HTTP_AUTHORIZATION": f"Bearer {create_access_token(user or self.user)}"}

    def screenshot(self, name="payment.png"):
        return SimpleUploadedFile(
            name,
            (
                b"\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00"
                b"\x00\x00\x00\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00"
                b"\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02"
                b"\x44\x01\x00\x3b"
            ),
            content_type="image/png",
        )

    def test_get_sale_claim_returns_none_when_not_submitted(self):
        response = self.client.get(
            reverse("ucm_partner:lead_sale_claim", kwargs={"lead_id": self.converted_lead.pk}),
            **self.auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["claim"])

    def test_partner_can_create_sale_claim_for_converted_own_lead(self):
        response = self.client.post(
            reverse("ucm_partner:lead_sale_claim", kwargs={"lead_id": self.converted_lead.pk}),
            data={
                "selling_price": "15000.00",
                "payment_note": "Paid to Ultoxy company.",
                "payment_screenshot": self.screenshot(),
            },
            **self.auth_headers(),
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()["claim"]
        self.assertEqual(payload["lead_school_name"], "Converted School")
        self.assertEqual(payload["selling_price"], "15000.00")
        self.assertEqual(payload["commission_percent"], "20.00")
        self.assertEqual(payload["commission_amount"], "3000.00")
        self.assertEqual(payload["status"], "PENDING_REVIEW")
        self.assertIn("payment_screenshot", payload)
        self.assertEqual(PartnerSaleClaim.objects.count(), 1)

    def test_get_sale_claim_returns_existing_own_claim(self):
        PartnerSaleClaim.objects.create(
            partner=self.partner,
            lead=self.converted_lead,
            selling_price=Decimal("10000.00"),
            payment_screenshot="partner_sale_claims/screenshots/payment.png",
        )

        response = self.client.get(
            reverse("ucm_partner:lead_sale_claim", kwargs={"lead_id": self.converted_lead.pk}),
            **self.auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["claim"]["commission_amount"], "2000.00")

    def test_partner_cannot_create_sale_claim_for_non_converted_lead(self):
        response = self.client.post(
            reverse("ucm_partner:lead_sale_claim", kwargs={"lead_id": self.new_lead.pk}),
            data={
                "selling_price": "15000.00",
                "payment_screenshot": self.screenshot(),
            },
            **self.auth_headers(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("lead", response.json()["errors"])
        self.assertEqual(PartnerSaleClaim.objects.count(), 0)

    def test_partner_cannot_access_other_partner_sale_claim(self):
        PartnerSaleClaim.objects.create(
            partner=self.other_partner,
            lead=self.other_lead,
            selling_price=Decimal("10000.00"),
            payment_screenshot="partner_sale_claims/screenshots/payment.png",
        )

        response = self.client.get(
            reverse("ucm_partner:lead_sale_claim", kwargs={"lead_id": self.other_lead.pk}),
            **self.auth_headers(),
        )

        self.assertEqual(response.status_code, 404)

    def test_partner_cannot_submit_second_sale_claim(self):
        PartnerSaleClaim.objects.create(
            partner=self.partner,
            lead=self.converted_lead,
            selling_price=Decimal("10000.00"),
            payment_screenshot="partner_sale_claims/screenshots/payment.png",
            status=PartnerSaleClaim.Status.APPROVED,
        )

        response = self.client.post(
            reverse("ucm_partner:lead_sale_claim", kwargs={"lead_id": self.converted_lead.pk}),
            data={
                "selling_price": "20000.00",
                "payment_screenshot": self.screenshot("new-payment.png"),
            },
            **self.auth_headers(),
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(PartnerSaleClaim.objects.count(), 1)
        self.assertEqual(response.json()["claim"]["status"], "APPROVED")

    def test_sale_claim_create_validates_required_fields(self):
        response = self.client.post(
            reverse("ucm_partner:lead_sale_claim", kwargs={"lead_id": self.converted_lead.pk}),
            data={"selling_price": ""},
            **self.auth_headers(),
        )

        self.assertEqual(response.status_code, 400)
        errors = response.json()["errors"]
        self.assertIn("selling_price", errors)
        self.assertIn("payment_screenshot", errors)

    def test_sale_claim_api_requires_partner_token(self):
        response = self.client.get(
            reverse("ucm_partner:lead_sale_claim", kwargs={"lead_id": self.converted_lead.pk})
        )

        self.assertEqual(response.status_code, 401)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class PartnerSaleClaimPrivateMediaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="partner1", password="pass12345")
        self.partner = PartnerProfile.objects.create(
            user=self.user,
            full_name="Partner One",
            mobile="9999999999",
            commission_percent=Decimal("20.00"),
        )
        self.lead = PartnerLead.objects.create(
            partner=self.partner,
            school_name="Media School",
            mobile="9000000001",
            status=PartnerLead.Status.CONVERTED,
        )
        self.claim = PartnerSaleClaim.objects.create(
            partner=self.partner,
            lead=self.lead,
            selling_price=Decimal("10000.00"),
            payment_screenshot=SimpleUploadedFile(
                "receipt.png",
                b"\x89PNG\r\n\x1a\n",
                content_type="image/png",
            ),
        )
        self.factory = RequestFactory()

    def test_admin_can_view_partner_sale_claim_screenshot(self):
        admin_user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pass12345",
        )
        request = self.factory.get("/")
        request.user = admin_user

        response = private_media(request, self.claim.payment_screenshot.name)

        self.assertEqual(response.status_code, 200)

    def test_partner_can_view_own_sale_claim_screenshot_with_bearer_token(self):
        request = self.factory.get(
            "/",
            HTTP_AUTHORIZATION=f"Bearer {create_access_token(self.user)}",
        )
        request.user = AnonymousUser()

        response = private_media(request, self.claim.payment_screenshot.name)

        self.assertEqual(response.status_code, 200)


class PartnerCallHistoryApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="partner1", password="pass12345")
        self.partner = PartnerProfile.objects.create(
            user=self.user,
            full_name="Partner One",
            mobile="9999999999",
        )
        self.lead = PartnerLead.objects.create(
            partner=self.partner,
            school_name="ABC School",
            mobile="9000000001",
        )
        self.other_user = User.objects.create_user(username="partner2", password="pass12345")
        self.other_partner = PartnerProfile.objects.create(
            user=self.other_user,
            full_name="Partner Two",
            mobile="8888888888",
        )
        self.other_lead = PartnerLead.objects.create(
            partner=self.other_partner,
            school_name="Other School",
            mobile="9000000002",
        )

    def auth_headers(self, user=None):
        return {"HTTP_AUTHORIZATION": f"Bearer {create_access_token(user or self.user)}"}

    def test_partner_can_create_and_list_call_history_for_own_lead(self):
        call_time = timezone.now().replace(microsecond=0)
        response = self.client.post(
            reverse("ucm_partner:lead_call_history", kwargs={"lead_id": self.lead.pk}),
            data=json.dumps(
                {
                    "call_time": call_time.isoformat(),
                    "result": "INTERESTED",
                    "notes": "Asked for a demo tomorrow.",
                }
            ),
            content_type="application/json",
            **self.auth_headers(),
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()["call"]
        self.assertEqual(payload["lead_school_name"], "ABC School")
        self.assertEqual(payload["result"], "INTERESTED")
        self.assertEqual(payload["notes"], "Asked for a demo tomorrow.")
        self.assertEqual(PartnerCallHistory.objects.count(), 1)

        list_response = self.client.get(
            reverse("ucm_partner:lead_call_history", kwargs={"lead_id": self.lead.pk}),
            **self.auth_headers(),
        )

        self.assertEqual(list_response.status_code, 200)
        calls = list_response.json()["calls"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["result_label"], "Interested")

    def test_partner_cannot_view_or_create_call_history_for_other_partner_lead(self):
        response = self.client.get(
            reverse("ucm_partner:lead_call_history", kwargs={"lead_id": self.other_lead.pk}),
            **self.auth_headers(),
        )

        self.assertEqual(response.status_code, 404)

        create_response = self.client.post(
            reverse("ucm_partner:lead_call_history", kwargs={"lead_id": self.other_lead.pk}),
            data=json.dumps({"result": "CONNECTED", "notes": ""}),
            content_type="application/json",
            **self.auth_headers(),
        )

        self.assertEqual(create_response.status_code, 404)
        self.assertEqual(PartnerCallHistory.objects.count(), 0)

    def test_call_history_api_requires_partner_token(self):
        response = self.client.get(
            reverse("ucm_partner:lead_call_history", kwargs={"lead_id": self.lead.pk})
        )

        self.assertEqual(response.status_code, 401)

    def test_call_history_create_validates_result(self):
        response = self.client.post(
            reverse("ucm_partner:lead_call_history", kwargs={"lead_id": self.lead.pk}),
            data=json.dumps({"result": "BAD_RESULT", "notes": ""}),
            content_type="application/json",
            **self.auth_headers(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("result", response.json()["errors"])
