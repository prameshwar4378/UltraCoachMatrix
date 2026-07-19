import json
from decimal import Decimal, InvalidOperation

from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from super_admin.mobile_auth import (
    bearer_identity_user,
    create_access_token,
    create_refresh_token,
    get_active_refresh_token,
    revoke_refresh_token,
)

from .models import (
    PartnerCallHistory,
    PartnerCommission,
    PartnerLead,
    PartnerProfile,
    PartnerSaleClaim,
)


def _json_request_data(request):
    if request.content_type == "application/json":
        try:
            return json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return None
    return request.POST


def _partner_payload(partner):
    user = partner.user
    return {
        "id": partner.pk,
        "user_id": user.pk,
        "username": user.get_username(),
        "name": partner.full_name,
        "mobile": partner.mobile,
        "email": partner.email or user.email,
        "area": partner.area,
        "bank_account_holder_name": partner.bank_account_holder_name,
        "bank_name": partner.bank_name,
        "bank_account_number": partner.bank_account_number,
        "bank_ifsc_code": partner.bank_ifsc_code,
        "phonepe_number": partner.phonepe_number,
        "google_pay_number": partner.google_pay_number,
        "commission_percent": str(partner.commission_percent),
        "status": partner.status,
    }


def _token_payload(partner):
    return {
        "access": create_access_token(partner.user),
        "refresh": create_refresh_token(partner.user),
        "token_type": "Bearer",
        "expires_in": 15 * 60,
        "partner": _partner_payload(partner),
    }


def _active_partner_for_user(user):
    if not user:
        return None
    partner = (
        PartnerProfile.objects.select_related("user")
        .filter(user=user)
        .first()
    )
    if not partner or partner.status != PartnerProfile.Status.ACTIVE:
        return None
    return partner


def _request_partner(request):
    user = bearer_identity_user(request)
    return _active_partner_for_user(user)


def _lead_payload(lead):
    return {
        "id": lead.pk,
        "school_name": lead.school_name,
        "contact_person": lead.contact_person,
        "mobile": lead.mobile,
        "city": lead.city,
        "status": lead.status,
        "status_label": lead.get_status_display(),
        "priority": lead.priority,
        "priority_label": lead.get_priority_display(),
        "next_follow_up_on": lead.next_follow_up_on.isoformat()
        if lead.next_follow_up_on
        else None,
        "notes": lead.notes,
        "created_at": lead.created_at.isoformat(),
        "updated_at": lead.updated_at.isoformat(),
    }


def _commission_payload(commission):
    return {
        "id": commission.pk,
        "lead_id": commission.lead_id,
        "lead_school_name": commission.lead.school_name,
        "sale_amount": _decimal_payload(commission.sale_amount),
        "commission_percent": _decimal_payload(commission.commission_percent),
        "commission_amount": _decimal_payload(commission.commission_amount),
        "status": commission.status,
        "status_label": commission.get_status_display(),
        "sale_date": commission.sale_date.isoformat()
        if commission.sale_date
        else None,
        "paid_on": commission.paid_on.isoformat()
        if commission.paid_on
        else None,
        "transaction_id": commission.transaction_id,
    }


def _call_history_payload(call):
    return {
        "id": call.pk,
        "lead_id": call.lead_id,
        "lead_school_name": call.lead.school_name,
        "call_time": call.call_time.isoformat(),
        "result": call.result,
        "result_label": call.get_result_display(),
        "notes": call.notes,
        "created_at": call.created_at.isoformat(),
    }


def _sale_claim_payload(claim):
    screenshot_url = claim.payment_screenshot.url if claim.payment_screenshot else ""
    return {
        "id": claim.pk,
        "lead_id": claim.lead_id,
        "lead_school_name": claim.lead.school_name,
        "selling_price": _decimal_payload(claim.selling_price),
        "commission_percent": _decimal_payload(claim.commission_percent),
        "commission_amount": _decimal_payload(claim.commission_amount),
        "payment_screenshot": screenshot_url,
        "payment_note": claim.payment_note,
        "status": claim.status,
        "status_label": claim.get_status_display(),
        "admin_note": claim.admin_note,
        "submitted_at": claim.submitted_at.isoformat() if claim.submitted_at else None,
        "approved_at": claim.approved_at.isoformat() if claim.approved_at else None,
        "paid_at": claim.paid_at.isoformat() if claim.paid_at else None,
    }


def _lead_has_paid_commission(lead):
    return (
        PartnerSaleClaim.objects.filter(
            lead=lead,
            status=PartnerSaleClaim.Status.PAID,
        ).exists()
        or PartnerCommission.objects.filter(
            lead=lead,
            status=PartnerCommission.Status.PAID,
        ).exists()
    )


def _parse_lead_data(data, *, partial=False):
    errors = {}
    cleaned = {}

    text_fields = {
        "school_name": 160,
        "contact_person": 120,
        "mobile": 20,
        "city": 80,
        "notes": None,
    }
    required_fields = {"school_name", "mobile"}

    for field, max_length in text_fields.items():
        if field not in data:
            if not partial and field in required_fields:
                errors[field] = "This field is required."
            continue
        value = str(data.get(field) or "").strip()
        if field in required_fields and not value:
            errors[field] = "This field is required."
            continue
        if max_length and len(value) > max_length:
            errors[field] = f"Ensure this value has at most {max_length} characters."
            continue
        cleaned[field] = value

    if "status" in data:
        status = str(data.get("status") or "").strip().upper()
        valid_statuses = {choice for choice, _label in PartnerLead.Status.choices}
        if status not in valid_statuses:
            errors["status"] = "Invalid lead status."
        else:
            cleaned["status"] = status
    elif not partial:
        cleaned["status"] = PartnerLead.Status.NEW

    if "priority" in data:
        priority = str(data.get("priority") or "").strip().upper()
        valid_priorities = {choice for choice, _label in PartnerLead.Priority.choices}
        if priority not in valid_priorities:
            errors["priority"] = "Invalid lead priority."
        else:
            cleaned["priority"] = priority
    elif not partial:
        cleaned["priority"] = PartnerLead.Priority.WARM

    if "next_follow_up_on" in data:
        raw_date = data.get("next_follow_up_on")
        if raw_date in {"", None}:
            cleaned["next_follow_up_on"] = None
        else:
            follow_up_on = parse_date(str(raw_date))
            if not follow_up_on:
                errors["next_follow_up_on"] = "Use date format YYYY-MM-DD."
            else:
                cleaned["next_follow_up_on"] = follow_up_on

    return cleaned, errors


def _parse_sale_claim_data(data, files):
    errors = {}
    cleaned = {}

    raw_selling_price = str(data.get("selling_price") or "").strip()
    if not raw_selling_price:
        errors["selling_price"] = "This field is required."
    else:
        try:
            selling_price = Decimal(raw_selling_price)
        except (InvalidOperation, TypeError):
            errors["selling_price"] = "Enter a valid amount."
        else:
            if selling_price <= Decimal("0.00"):
                errors["selling_price"] = "Selling price must be greater than zero."
            else:
                cleaned["selling_price"] = selling_price.quantize(Decimal("0.01"))

    payment_screenshot = files.get("payment_screenshot")
    if not payment_screenshot:
        errors["payment_screenshot"] = "This field is required."
    else:
        cleaned["payment_screenshot"] = payment_screenshot

    cleaned["payment_note"] = str(data.get("payment_note") or "").strip()
    return cleaned, errors


def _parse_call_history_data(data):
    errors = {}
    cleaned = {}

    result = str(data.get("result") or "").strip().upper()
    valid_results = {choice for choice, _label in PartnerCallHistory.Result.choices}
    if result not in valid_results:
        errors["result"] = "Invalid call result."
    else:
        cleaned["result"] = result

    notes = str(data.get("notes") or "").strip()
    cleaned["notes"] = notes

    if "call_time" in data:
        raw_call_time = data.get("call_time")
        if raw_call_time in {"", None}:
            errors["call_time"] = "Call time cannot be blank."
        else:
            call_time = parse_datetime(str(raw_call_time))
            if not call_time:
                errors["call_time"] = "Use ISO date-time format."
            else:
                if timezone.is_naive(call_time):
                    call_time = timezone.make_aware(call_time, timezone.get_current_timezone())
                cleaned["call_time"] = call_time

    return cleaned, errors


def _decimal_payload(value):
    return str((value or Decimal("0.00")).quantize(Decimal("0.01")))


@csrf_exempt
@require_POST
def partner_login(request):
    data = _json_request_data(request)
    if data is None:
        return JsonResponse({"detail": "Invalid JSON body."}, status=400)

    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return JsonResponse({"detail": "Username and password are required."}, status=400)

    user = authenticate(request, username=username, password=password)
    partner = _active_partner_for_user(user)
    if partner is None:
        return JsonResponse({"detail": "Invalid partner username or password."}, status=401)

    return JsonResponse(_token_payload(partner))


@csrf_exempt
@require_POST
def partner_token_refresh(request):
    data = _json_request_data(request)
    if data is None:
        return JsonResponse({"detail": "Invalid JSON body."}, status=400)

    refresh = data.get("refresh") or ""
    refresh_token = get_active_refresh_token(refresh, check_institute_access=False)
    partner = _active_partner_for_user(refresh_token.user if refresh_token else None)
    if partner is None:
        return JsonResponse({"detail": "Invalid or expired refresh token."}, status=401)

    return JsonResponse(
        {
            "access": create_access_token(partner.user),
            "token_type": "Bearer",
            "expires_in": 15 * 60,
            "partner": _partner_payload(partner),
        }
    )


@csrf_exempt
@require_POST
def partner_logout(request):
    data = _json_request_data(request)
    if data is None:
        return JsonResponse({"detail": "Invalid JSON body."}, status=400)

    refresh = data.get("refresh") or ""
    if not revoke_refresh_token(refresh):
        return JsonResponse({"detail": "Invalid or expired refresh token."}, status=401)
    return JsonResponse({"detail": "Logout successful."})


@require_GET
def partner_me(request):
    user = bearer_identity_user(request)
    partner = _active_partner_for_user(user)
    if partner is None:
        return JsonResponse({"detail": "Invalid or expired access token."}, status=401)
    return JsonResponse({"partner": _partner_payload(partner)})


@require_GET
def partner_dashboard(request):
    partner = _request_partner(request)
    if partner is None:
        return JsonResponse({"detail": "Invalid or expired access token."}, status=401)

    leads = PartnerLead.objects.filter(partner=partner)
    commissions = PartnerCommission.objects.filter(partner=partner)

    pending_commission = commissions.filter(
        status=PartnerCommission.Status.PENDING
    ).aggregate(total=Sum("commission_amount"))["total"]
    paid_commission = commissions.filter(
        status=PartnerCommission.Status.PAID
    ).aggregate(total=Sum("commission_amount"))["total"]

    return JsonResponse(
        {
            "total_leads": leads.count(),
            "today_follow_ups": leads.filter(
                next_follow_up_on=timezone.localdate()
            ).count(),
            "converted_leads": leads.filter(status=PartnerLead.Status.CONVERTED).count(),
            "pending_commission": _decimal_payload(pending_commission),
            "paid_commission": _decimal_payload(paid_commission),
        }
    )


@require_GET
def partner_commissions(request):
    partner = _request_partner(request)
    if partner is None:
        return JsonResponse({"detail": "Invalid or expired access token."}, status=401)

    commissions = (
        PartnerCommission.objects.select_related("lead")
        .filter(partner=partner)
        .order_by("-sale_date", "-created_at")
    )
    return JsonResponse(
        {"commissions": [_commission_payload(commission) for commission in commissions]}
    )


@csrf_exempt
@require_http_methods(["GET", "POST"])
def partner_leads(request):
    partner = _request_partner(request)
    if partner is None:
        return JsonResponse({"detail": "Invalid or expired access token."}, status=401)

    if request.method == "GET":
        leads = PartnerLead.objects.filter(partner=partner)
        return JsonResponse({"leads": [_lead_payload(lead) for lead in leads]})

    data = _json_request_data(request)
    if data is None:
        return JsonResponse({"detail": "Invalid JSON body."}, status=400)

    cleaned, errors = _parse_lead_data(data)
    if errors:
        return JsonResponse({"detail": "Invalid lead data.", "errors": errors}, status=400)

    lead = PartnerLead.objects.create(partner=partner, **cleaned)
    return JsonResponse({"lead": _lead_payload(lead)}, status=201)


@csrf_exempt
@require_http_methods(["GET", "PATCH"])
def partner_lead_detail(request, lead_id):
    partner = _request_partner(request)
    if partner is None:
        return JsonResponse({"detail": "Invalid or expired access token."}, status=401)

    lead = PartnerLead.objects.filter(pk=lead_id, partner=partner).first()
    if lead is None:
        return JsonResponse({"detail": "Lead not found."}, status=404)

    if request.method == "GET":
        return JsonResponse({"lead": _lead_payload(lead)})

    if _lead_has_paid_commission(lead):
        return JsonResponse(
            {
                "detail": (
                    "This lead is locked because its commission is already paid."
                )
            },
            status=409,
        )

    data = _json_request_data(request)
    if data is None:
        return JsonResponse({"detail": "Invalid JSON body."}, status=400)

    cleaned, errors = _parse_lead_data(data, partial=True)
    if errors:
        return JsonResponse({"detail": "Invalid lead data.", "errors": errors}, status=400)

    for field, value in cleaned.items():
        setattr(lead, field, value)
    lead.save()
    return JsonResponse({"lead": _lead_payload(lead)})


@csrf_exempt
@require_http_methods(["GET", "POST"])
def partner_lead_call_history(request, lead_id):
    partner = _request_partner(request)
    if partner is None:
        return JsonResponse({"detail": "Invalid or expired access token."}, status=401)

    lead = PartnerLead.objects.filter(pk=lead_id, partner=partner).first()
    if lead is None:
        return JsonResponse({"detail": "Lead not found."}, status=404)

    if request.method == "GET":
        calls = PartnerCallHistory.objects.select_related("lead").filter(
            partner=partner,
            lead=lead,
        )
        return JsonResponse({"calls": [_call_history_payload(call) for call in calls]})

    data = _json_request_data(request)
    if data is None:
        return JsonResponse({"detail": "Invalid JSON body."}, status=400)

    cleaned, errors = _parse_call_history_data(data)
    if errors:
        return JsonResponse({"detail": "Invalid call history data.", "errors": errors}, status=400)

    call = PartnerCallHistory.objects.create(
        partner=partner,
        lead=lead,
        **cleaned,
    )
    return JsonResponse({"call": _call_history_payload(call)}, status=201)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def partner_lead_sale_claim(request, lead_id):
    partner = _request_partner(request)
    if partner is None:
        return JsonResponse({"detail": "Invalid or expired access token."}, status=401)

    lead = PartnerLead.objects.filter(pk=lead_id, partner=partner).first()
    if lead is None:
        return JsonResponse({"detail": "Lead not found."}, status=404)

    claim = (
        PartnerSaleClaim.objects.select_related("lead")
        .filter(partner=partner, lead=lead)
        .first()
    )

    if request.method == "GET":
        if claim is None:
            return JsonResponse({"claim": None})
        return JsonResponse({"claim": _sale_claim_payload(claim)})

    if claim is not None:
        return JsonResponse(
            {
                "detail": "Sale claim already exists for this lead.",
                "claim": _sale_claim_payload(claim),
            },
            status=409,
        )

    if lead.status != PartnerLead.Status.CONVERTED:
        return JsonResponse(
            {
                "detail": "Sale claim is allowed only for converted leads.",
                "errors": {"lead": "Lead must be converted before submitting sale claim."},
            },
            status=400,
        )

    data = _json_request_data(request)
    if data is None:
        return JsonResponse({"detail": "Invalid JSON body."}, status=400)

    cleaned, errors = _parse_sale_claim_data(data, request.FILES)
    if errors:
        return JsonResponse(
            {"detail": "Invalid sale claim data.", "errors": errors},
            status=400,
        )

    try:
        claim = PartnerSaleClaim.objects.create(
            partner=partner,
            lead=lead,
            commission_percent=partner.commission_percent,
            **cleaned,
        )
    except ValidationError as error:
        return JsonResponse(
            {"detail": "Invalid sale claim data.", "errors": error.message_dict},
            status=400,
        )

    return JsonResponse({"claim": _sale_claim_payload(claim)}, status=201)
