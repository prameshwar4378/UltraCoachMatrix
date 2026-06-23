from decimal import Decimal

from django.contrib.auth.models import User
from django.db.models import Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET

from student_parent.models import StudentAcademicSession, StudentEnrollment, StudentProfile
from super_admin.mobile_auth import bearer_user
from super_admin.models import UserProfile

from .models import FeeCategory, FeeInvoice, Payment


def _money(value):
    return str(value or Decimal("0.00"))


def _date(value):
    return value.isoformat() if value else None


def _datetime(value):
    return value.isoformat() if value else None


def _payment_url(request, payment_id):
    return request.build_absolute_uri(f"/api/mobile/fees/payments/{payment_id}/receipt/")


def _download_url(request, payment_id):
    return request.build_absolute_uri(f"/api/mobile/fees/payments/{payment_id}/receipt/download/")


def _api_user(request):
    if request.user.is_authenticated:
        return request.user
    return bearer_user(request)


def _unauthorized():
    return JsonResponse({"detail": "Invalid or expired access token."}, status=401)


def _student_for_request(request):
    user = _api_user(request)
    if not user:
        return None, _unauthorized()

    profile = getattr(user, "profile", None)
    role = profile.role if profile else None
    requested_student_id = request.GET.get("student_id")

    if role == UserProfile.Role.STUDENT_PARENT:
        student = getattr(user, "student_profile", None)
        if not student:
            return None, JsonResponse({"detail": "No student profile is linked to this user."}, status=404)
        if requested_student_id and str(student.pk) != str(requested_student_id):
            return None, JsonResponse({"detail": "You can view only your own fee details."}, status=403)
        return student, None

    if role in [UserProfile.Role.INSTITUTE_ADMIN, UserProfile.Role.ACCOUNTANT]:
        if not profile or not profile.institute_id:
            return None, JsonResponse({"detail": "No institute is linked to this user."}, status=403)
        if not requested_student_id:
            return None, JsonResponse({"detail": "student_id query parameter is required."}, status=400)
        queryset = StudentProfile.objects.select_related("user", "institute").filter(
            institute=profile.institute
        )
        return get_object_or_404(queryset, pk=requested_student_id), None

    return None, JsonResponse({"detail": "You are not allowed to view fee details."}, status=403)


def _student_sessions(student, request):
    queryset = (
        StudentAcademicSession.objects.filter(student=student)
        .select_related("academic_year", "institute", "student", "student__user", "student__institute")
        .order_by("-academic_year__start_date", "-pk")
    )
    academic_year_id = request.GET.get("academic_year_id")
    session_id = request.GET.get("academic_session_id")
    if academic_year_id:
        queryset = queryset.filter(academic_year_id=academic_year_id)
    if session_id:
        queryset = queryset.filter(pk=session_id)
    return queryset


def _invoice_paid(invoice):
    prefetched = getattr(invoice, "_prefetched_objects_cache", {}).get("payments")
    if prefetched is not None:
        return sum(
            (payment.amount for payment in prefetched if payment.status == Payment.Status.ACTIVE),
            Decimal("0.00"),
        )
    return invoice.payments.filter(status=Payment.Status.ACTIVE).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")


def _invoice_payload(invoice, request):
    paid_amount = _invoice_paid(invoice)
    due_amount = invoice.amount - paid_amount
    if due_amount < 0:
        due_amount = Decimal("0.00")
    latest_payment = invoice.payments.filter(status=Payment.Status.ACTIVE).order_by("-paid_on", "-pk").first()
    return {
        "id": invoice.pk,
        "title": invoice.title,
        "amount": _money(invoice.amount),
        "paid_amount": _money(paid_amount),
        "due_amount": _money(due_amount),
        "due_date": _date(invoice.due_date),
        "status": invoice.status,
        "category": {
            "id": invoice.category_id,
            "name": invoice.category.name if invoice.category_id else "General",
        },
        "batch": {
            "id": invoice.batch_id,
            "name": invoice.batch.name if invoice.batch_id else (invoice.enrollment.batch.name if invoice.enrollment_id else None),
        },
        "course": {
            "id": invoice.course_id,
            "name": invoice.course.name if invoice.course_id else None,
        },
        "enrollment_id": invoice.enrollment_id,
        "latest_receipt_url": _payment_url(request, latest_payment.pk) if latest_payment else None,
        "latest_receipt_download_url": _download_url(request, latest_payment.pk) if latest_payment else None,
    }


def _payment_payload(payment, request, include_activity=False):
    invoice = payment.invoice
    payload = {
        "id": payment.pk,
        "receipt_number": payment.receipt_number,
        "amount": _money(payment.amount),
        "paid_on": _date(payment.paid_on),
        "method": payment.method,
        "status": payment.status,
        "note": payment.note,
        "created_at": _datetime(payment.created_at),
        "invoice": {
            "id": invoice.pk,
            "title": invoice.title,
            "amount": _money(invoice.amount),
            "status": invoice.status,
            "category": invoice.category.name if invoice.category_id else "General",
            "batch": invoice.batch.name if invoice.batch_id else (invoice.enrollment.batch.name if invoice.enrollment_id else None),
        },
        "receipt_url": _payment_url(request, payment.pk),
        "receipt_download_url": _download_url(request, payment.pk),
    }
    if include_activity:
        payload["activities"] = [
            {
                "id": activity.pk,
                "action": activity.action,
                "performed_at": _datetime(activity.performed_at),
                "performed_by": activity.performed_by.get_full_name() or activity.performed_by.username if activity.performed_by_id else None,
                "old_amount": _money(activity.old_amount),
                "new_amount": _money(activity.new_amount),
                "note": activity.note,
            }
            for activity in payment.activities.select_related("performed_by").all()
        ]
    return payload


def _active_fee_session(student, request):
    return _student_sessions(student, request).first()


def _student_payload(student, request=None):
    session = _active_fee_session(student, request) if request is not None else None
    admission_number = session.admission_number if session else student.admission_number
    payload = {
        "id": student.pk,
        "admission_number": admission_number,
        "name": student.user.get_full_name() or student.user.username,
        "username": student.user.username,
        "institute": {"id": student.institute_id, "name": student.institute.name},
    }
    if session:
        payload["academic_session"] = {
            "id": session.pk,
            "admission_number": session.admission_number,
            "academic_year": session.academic_year.name if session.academic_year_id else "",
            "status": session.status,
        }
    return payload


def _academic_sessions_payload(sessions):
    return [
        {
            "id": session.pk,
            "academic_year": {"id": session.academic_year_id, "name": session.academic_year.name},
            "status": session.status,
            "admission_number": session.admission_number,
        }
        for session in sessions
    ]


def _invoice_queryset(student, request):
    sessions = _student_sessions(student, request)
    return (
        FeeInvoice.objects.filter(academic_session__in=sessions)
        .exclude(status=FeeInvoice.Status.CANCELLED)
        .select_related(
            "category",
            "course",
            "batch",
            "enrollment",
            "enrollment__batch",
            "academic_session",
            "academic_session__academic_year",
        )
        .prefetch_related("payments")
        .order_by("-due_date", "-pk")
    )


def _payment_queryset(student, request):
    sessions = _student_sessions(student, request)
    return (
        Payment.objects.filter(invoice__academic_session__in=sessions)
        .select_related("invoice", "invoice__category", "invoice__batch", "invoice__enrollment", "invoice__enrollment__batch")
        .order_by("-paid_on", "-pk")
    )


def _fee_service_rows(student, request):
    cache_key = (student.pk, request.GET.urlencode())
    cache = getattr(request, "_mobile_fee_rows_cache", None)
    if cache is None:
        cache = {}
        request._mobile_fee_rows_cache = cache
    if cache_key in cache:
        return cache[cache_key]

    sessions = _student_sessions(student, request)
    rows = []
    raw_paid_amount = Decimal("0.00")
    excess_credit = Decimal("0.00")
    additional_groups = {}
    enrollment_invoice_totals = {}

    invoices = _invoice_queryset(student, request)
    for invoice in invoices:
        paid_amount = _invoice_paid(invoice)
        raw_paid_amount += paid_amount
        if invoice.enrollment_id:
            enrollment_invoice_totals[invoice.enrollment_id] = (
                enrollment_invoice_totals.get(invoice.enrollment_id, Decimal("0.00")) + invoice.amount
            )
            continue

        group_key = f"category-{invoice.category_id}" if invoice.category_id else f"invoice-{invoice.pk}"
        if group_key not in additional_groups:
            additional_groups[group_key] = {
                "id": invoice.pk,
                "title": invoice.category.name if invoice.category_id else invoice.title,
                "category": {"id": invoice.category_id, "name": invoice.category.name if invoice.category_id else "General"},
                "batch": {"id": invoice.batch_id, "name": invoice.batch.name if invoice.batch_id else None},
                "course": {"id": invoice.course_id, "name": invoice.course.name if invoice.course_id else None},
                "enrollment_id": None,
                "amount": Decimal("0.00"),
                "actual_paid": Decimal("0.00"),
                "due_date": invoice.due_date,
            }
        additional_groups[group_key]["amount"] += invoice.amount
        additional_groups[group_key]["actual_paid"] += paid_amount
        if invoice.due_date and invoice.due_date > additional_groups[group_key]["due_date"]:
            additional_groups[group_key]["due_date"] = invoice.due_date

    for session in sessions.prefetch_related("enrollments__batch", "enrollments__courses"):
        enrollments = session.enrollments.exclude(status=StudentEnrollment.Status.CANCELLED).select_related("batch")
        for enrollment in enrollments:
            enrollment_invoice_total = enrollment_invoice_totals.get(enrollment.pk, Decimal("0.00"))
            fee_amount = max(enrollment.total_course_fee, enrollment_invoice_total)
            paid_amount = (
                Payment.objects.filter(
                    invoice__student=student,
                    invoice__academic_session=session,
                    invoice__enrollment=enrollment,
                    status=Payment.Status.ACTIVE,
                ).aggregate(total=Sum("amount"))["total"]
                or Decimal("0.00")
            )
            display_paid = min(paid_amount, fee_amount)
            if paid_amount > fee_amount:
                excess_credit += paid_amount - fee_amount
            courses = list(enrollment.courses.all())
            rows.append(
                {
                    "id": -enrollment.pk,
                    "title": f"{enrollment.batch.name} Fee",
                    "category": {"id": None, "name": "Enrollment"},
                    "batch": {"id": enrollment.batch_id, "name": enrollment.batch.name},
                    "course": {"id": courses[0].pk, "name": courses[0].name} if len(courses) == 1 else {"id": None, "name": None},
                    "enrollment_id": enrollment.pk,
                    "amount": fee_amount,
                    "paid_amount": display_paid,
                    "actual_paid": paid_amount,
                    "due_amount": fee_amount - display_paid,
                    "due_date": enrollment.enrolled_on,
                    "status": "PAID" if display_paid >= fee_amount else "PARTIAL" if display_paid > 0 else "UNPAID",
                    "latest_receipt_url": None,
                    "latest_receipt_download_url": None,
                }
            )

    for group in additional_groups.values():
        display_paid = min(group["actual_paid"], group["amount"])
        if group["actual_paid"] > group["amount"]:
            excess_credit += group["actual_paid"] - group["amount"]
        rows.append(
            {
                "id": group["id"],
                "title": group["title"],
                "category": group["category"],
                "batch": group["batch"],
                "course": group["course"],
                "enrollment_id": group["enrollment_id"],
                "amount": group["amount"],
                "paid_amount": display_paid,
                "actual_paid": group["actual_paid"],
                "due_amount": group["amount"] - display_paid,
                "due_date": group["due_date"],
                "status": "PAID" if display_paid >= group["amount"] else "PARTIAL" if display_paid > 0 else "UNPAID",
                "latest_receipt_url": None,
                "latest_receipt_download_url": None,
            }
        )

    for row in rows:
        if excess_credit <= 0:
            break
        if row["due_amount"] <= 0:
            continue
        credit = min(row["due_amount"], excess_credit)
        row["paid_amount"] += credit
        row["due_amount"] -= credit
        excess_credit -= credit

    for row in rows:
        if row["due_amount"] <= 0:
            row["due_amount"] = Decimal("0.00")
            row["status"] = "PAID"
        elif row["paid_amount"] > 0:
            row["status"] = "PARTIAL"
        else:
            row["status"] = "UNPAID"

    rows.sort(key=lambda row: (row["due_date"] is None, row["due_date"], row["title"]), reverse=True)
    cache[cache_key] = (rows, raw_paid_amount)
    return cache[cache_key]


def _fee_row_payload(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "amount": _money(row["amount"]),
        "paid_amount": _money(row["paid_amount"]),
        "due_amount": _money(row["due_amount"]),
        "due_date": _date(row["due_date"]),
        "status": row["status"],
        "category": row["category"],
        "batch": row["batch"],
        "course": row["course"],
        "enrollment_id": row["enrollment_id"],
        "latest_receipt_url": row["latest_receipt_url"],
        "latest_receipt_download_url": row["latest_receipt_download_url"],
    }


def _fee_summary_payload(student, request):
    sessions = _student_sessions(student, request)
    fee_rows, total_paid_raw = _fee_service_rows(student, request)
    payments = _payment_queryset(student, request)

    total_fee = sum((row["amount"] for row in fee_rows), Decimal("0.00"))

    total_paid = min(total_paid_raw, total_fee)
    overpaid = total_paid_raw - total_fee
    if overpaid < 0:
        overpaid = Decimal("0.00")
    total_due = total_fee - total_paid
    if total_due < 0:
        total_due = Decimal("0.00")

    return {
        "student": _student_payload(student, request),
        "summary": {
            "total_fee_amount": _money(total_fee),
            "total_paid_amount": _money(total_paid),
            "raw_paid_amount": _money(total_paid_raw),
            "total_due_amount": _money(total_due),
            "overpaid_amount": _money(overpaid),
            "invoice_count": len(fee_rows),
            "active_payment_count": payments.filter(status=Payment.Status.ACTIVE).count(),
        },
        "academic_sessions": _academic_sessions_payload(sessions),
    }


def _fee_invoices_payload(student, request):
    fee_rows, _total_paid_raw = _fee_service_rows(student, request)
    return {
        "student": _student_payload(student, request),
        "fees": [_fee_row_payload(row) for row in fee_rows],
    }


def _fee_breakup_payload(student, request):
    sessions = _student_sessions(student, request)
    fee_rows, _total_paid_raw = _fee_service_rows(student, request)
    category_map = {}
    batch_map = {}

    for row in fee_rows:
        category = row["category"]
        category_id = category["id"] or 0
        category_name = category["name"]
        category_row = category_map.setdefault(
            category_id,
            {"id": category["id"], "name": category_name, "total_amount": Decimal("0.00"), "paid_amount": Decimal("0.00"), "due_amount": Decimal("0.00")},
        )
        category_row["total_amount"] += row["amount"]
        category_row["paid_amount"] += row["paid_amount"]
        category_row["due_amount"] += row["due_amount"]

        batch = row["batch"]
        batch_id = batch["id"] or 0
        batch_name = batch["name"] or "Other"
        batch_row = batch_map.setdefault(
            batch_id,
            {"id": batch["id"], "name": batch_name, "total_amount": Decimal("0.00"), "paid_amount": Decimal("0.00"), "due_amount": Decimal("0.00")},
        )
        batch_row["total_amount"] += row["amount"]
        batch_row["paid_amount"] += row["paid_amount"]
        batch_row["due_amount"] += row["due_amount"]

    enrollments = []
    for session in sessions.prefetch_related("enrollments__batch", "enrollments__courses"):
        for enrollment in session.enrollments.exclude(status=StudentEnrollment.Status.CANCELLED).all():
            enrollments.append(
                {
                    "id": enrollment.pk,
                    "academic_session_id": session.pk,
                    "academic_year": session.academic_year.name,
                    "batch": {"id": enrollment.batch_id, "name": enrollment.batch.name},
                    "courses": [{"id": course.pk, "name": course.name, "fee_amount": _money(course.fee_amount)} for course in enrollment.courses.all()],
                    "total_course_fee": _money(enrollment.total_course_fee),
                    "custom_fee_amount": _money(enrollment.custom_fee_amount) if enrollment.custom_fee_amount is not None else None,
                    "status": enrollment.status,
                }
            )

    return {
        "student": _student_payload(student, request),
        "enrollments": enrollments,
        "category_wise": [
            {
                "id": row["id"],
                "name": row["name"],
                "total_amount": _money(row["total_amount"]),
                "paid_amount": _money(row["paid_amount"]),
                "due_amount": _money(row["due_amount"]),
            }
            for row in category_map.values()
        ],
        "batch_wise": [
            {
                "id": row["id"],
                "name": row["name"],
                "total_amount": _money(row["total_amount"]),
                "paid_amount": _money(row["paid_amount"]),
                "due_amount": _money(row["due_amount"]),
            }
            for row in batch_map.values()
        ],
    }


def _fee_summary(student, request):
    summary_payload = _fee_summary_payload(student, request)
    invoices_payload = _fee_invoices_payload(student, request)
    breakup_payload = _fee_breakup_payload(student, request)
    payments = _payment_queryset(student, request)
    return {
        **summary_payload,
        "enrollments": breakup_payload["enrollments"],
        "fees": invoices_payload["fees"],
        "category_wise": breakup_payload["category_wise"],
        "batch_wise": breakup_payload["batch_wise"],
        "payment_history": [_payment_payload(payment, request) for payment in payments],
    }


def _fee_dashboard_payload(student, request, *, invoice_limit=6, payment_limit=3):
    summary_payload = _fee_summary_payload(student, request)
    fee_rows, _total_paid_raw = _fee_service_rows(student, request)
    due_rows = sorted(
        (row for row in fee_rows if row["due_amount"] > 0),
        key=lambda row: (row["due_date"] is None, row["due_date"], row["title"]),
    )
    payments = _payment_queryset(student, request)[:payment_limit]
    return {
        **summary_payload,
        "fees": [_fee_row_payload(row) for row in due_rows[:invoice_limit]],
        "category_wise": [],
        "batch_wise": [],
        "payment_history": [_payment_payload(payment, request) for payment in payments],
    }


@require_GET
def mobile_health(request):
    return JsonResponse({"status": "ok", "service": "mobile-api"})


@require_GET
def mobile_fee_details(request):
    student, error = _student_for_request(request)
    if error:
        return error
    return JsonResponse(_fee_summary(student, request))


@require_GET
def mobile_fee_summary(request):
    student, error = _student_for_request(request)
    if error:
        return error
    return JsonResponse(_fee_summary_payload(student, request))


@require_GET
def mobile_fee_invoices(request):
    student, error = _student_for_request(request)
    if error:
        return error
    return JsonResponse(_fee_invoices_payload(student, request))


@require_GET
def mobile_fee_breakup(request):
    student, error = _student_for_request(request)
    if error:
        return error
    return JsonResponse(_fee_breakup_payload(student, request))


@require_GET
def mobile_fee_categories(request):
    student, error = _student_for_request(request)
    if error:
        return error
    categories = FeeCategory.objects.filter(institute=student.institute, is_active=True).order_by("name")
    return JsonResponse(
        {
            "categories": [
                {"id": category.pk, "name": category.name, "default_amount": _money(category.default_amount)}
                for category in categories
            ]
        }
    )


@require_GET
def mobile_payment_history(request):
    student, error = _student_for_request(request)
    if error:
        return error
    sessions = _student_sessions(student, request)
    payments = (
        Payment.objects.filter(invoice__academic_session__in=sessions)
        .select_related("invoice", "invoice__category", "invoice__batch", "invoice__enrollment", "invoice__enrollment__batch")
        .prefetch_related("activities", "activities__performed_by")
        .order_by("-paid_on", "-pk")
    )
    return JsonResponse({"payments": [_payment_payload(payment, request, include_activity=True) for payment in payments]})


def _payment_for_request(request, payment_id):
    user = _api_user(request)
    if not user:
        return None, _unauthorized()
    profile = getattr(user, "profile", None)
    queryset = Payment.objects.select_related(
        "invoice",
        "invoice__academic_session",
        "invoice__student",
        "invoice__student__user",
        "invoice__student__institute",
        "invoice__category",
        "invoice__enrollment",
        "invoice__batch",
        "received_by",
    )
    if profile and profile.role == UserProfile.Role.STUDENT_PARENT:
        queryset = queryset.filter(invoice__student__user=user)
    elif profile and profile.role in [UserProfile.Role.INSTITUTE_ADMIN, UserProfile.Role.ACCOUNTANT]:
        queryset = queryset.filter(invoice__student__institute=profile.institute)
    elif not user.is_superuser:
        return None, JsonResponse({"detail": "You are not allowed to view this receipt."}, status=403)
    return get_object_or_404(queryset, pk=payment_id), None


def _receipt_context(payment):
    invoice = payment.invoice
    student = invoice.student
    if payment.received_by_id is None:
        payment.received_by = User(username="System")
    invoice_paid_amount = invoice.payments.filter(status=Payment.Status.ACTIVE).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    invoice_due_amount = invoice.amount - invoice_paid_amount
    if invoice_due_amount < 0:
        invoice_due_amount = Decimal("0.00")
    return {
        "payment": payment,
        "invoice": invoice,
        "student": student,
        "student_session": invoice.academic_session,
        "guardian": student.guardians.filter(is_primary=True).first() or student.guardians.first(),
        "institute": student.institute,
        "invoice_paid_amount": invoice_paid_amount,
        "invoice_due_amount": invoice_due_amount,
    }


@require_GET
def mobile_payment_receipt(request, payment_id):
    payment, error = _payment_for_request(request, payment_id)
    if error:
        return error
    return HttpResponse(render_to_string("institute_admin/payment_receipt.html", _receipt_context(payment), request=request))


@require_GET
def mobile_payment_receipt_download(request, payment_id):
    payment, error = _payment_for_request(request, payment_id)
    if error:
        return error
    html = render_to_string("institute_admin/payment_receipt.html", _receipt_context(payment), request=request)
    filename = f"fee-receipt-{payment.receipt_number or payment.pk}.html"
    response = HttpResponse(html, content_type="text/html")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
