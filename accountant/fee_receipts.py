from collections import OrderedDict
from decimal import Decimal

from django.contrib.auth.models import User
from django.db.models import Sum
from django.template import Context, Template, TemplateSyntaxError
from django.template.loader import render_to_string

from student_parent.models import StudentEnrollment

from .models import FeeInvoice, Payment


def _active_paid_amount(invoice):
    return (
        invoice.payments.filter(status=Payment.Status.ACTIVE).aggregate(total=Sum("amount"))["total"]
        or Decimal("0.00")
    )


def build_payment_receipt_context(payment):
    invoice = payment.invoice
    student = invoice.student
    student_session = invoice.academic_session
    receipt_batch = invoice.batch or (invoice.enrollment.batch if invoice.enrollment_id else None)
    receipt_category = invoice.category.name if invoice.category_id else "Fees"

    if payment.received_by_id is None:
        payment.received_by = User(username="System")

    invoice_paid_amount = _active_paid_amount(invoice)
    invoice_due_amount = invoice.amount - invoice_paid_amount
    if invoice_due_amount < 0:
        invoice_due_amount = Decimal("0.00")

    due_rows = OrderedDict()
    overall_due_amount = Decimal("0.00")

    enrollments = list(
        student_session.enrollments.exclude(status=StudentEnrollment.Status.CANCELLED)
        .select_related("batch")
        .prefetch_related("courses")
    )
    enrollment_batch_names = []
    for enrollment in enrollments:
        if enrollment.batch_id and enrollment.batch.name not in enrollment_batch_names:
            enrollment_batch_names.append(enrollment.batch.name)
    receipt_batch_label = receipt_batch.name if receipt_batch else ", ".join(enrollment_batch_names) or "-"
    fees_row = due_rows.setdefault(
        "fees",
        {
            "name": "Fees",
            "invoice_count": 0,
            "total_amount": Decimal("0.00"),
            "paid_amount": Decimal("0.00"),
            "due_amount": Decimal("0.00"),
        },
    )
    for enrollment in enrollments:
        paid_amount = (
            Payment.objects.filter(
                invoice__student=student,
                invoice__academic_session=student_session,
                invoice__enrollment=enrollment,
                status=Payment.Status.ACTIVE,
            ).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        due_amount = enrollment.total_course_fee - paid_amount
        if due_amount <= 0:
            continue
        fees_row["invoice_count"] += 1
        fees_row["total_amount"] += enrollment.total_course_fee
        fees_row["paid_amount"] += paid_amount
        fees_row["due_amount"] += due_amount
        overall_due_amount += due_amount

    if fees_row["due_amount"] <= 0:
        due_rows.pop("fees", None)

    pending_invoices = (
        FeeInvoice.objects.filter(student=student, academic_session=student_session)
        .filter(enrollment__isnull=True)
        .exclude(status=FeeInvoice.Status.CANCELLED)
        .select_related("category")
        .prefetch_related("payments")
        .order_by("category__name", "title", "due_date", "pk")
    )

    for pending_invoice in pending_invoices:
        paid_amount = sum(
            payment.amount
            for payment in pending_invoice.payments.all()
            if payment.status == Payment.Status.ACTIVE
        )
        due_amount = pending_invoice.amount - paid_amount
        if due_amount <= 0:
            continue

        overall_due_amount += due_amount
        category_key = pending_invoice.category_id or "fees"
        category_name = pending_invoice.category.name if pending_invoice.category_id else "Fees"
        row = due_rows.setdefault(
            category_key,
            {
                "name": category_name,
                "invoice_count": 0,
                "total_amount": Decimal("0.00"),
                "paid_amount": Decimal("0.00"),
                "due_amount": Decimal("0.00"),
            },
        )
        row["invoice_count"] += 1
        row["total_amount"] += pending_invoice.amount
        row["paid_amount"] += paid_amount
        row["due_amount"] += due_amount

    return {
        "payment": payment,
        "invoice": invoice,
        "student": student,
        "student_session": student_session,
        "guardian": student.guardians.filter(is_primary=True).first() or student.guardians.first(),
        "institute": student.institute,
        "invoice_paid_amount": invoice_paid_amount,
        "invoice_due_amount": invoice_due_amount,
        "receipt_batch_label": receipt_batch_label,
        "receipt_category_label": receipt_category,
        "due_category_rows": list(due_rows.values()),
        "overall_due_amount": overall_due_amount,
    }


def render_payment_receipt_html(payment, request=None):
    from institute_admin.models import InstitutePrintTemplate, PrintDocumentType

    context = build_payment_receipt_context(payment)
    institute = context["institute"]
    custom_template = (
        InstitutePrintTemplate.objects.filter(
            institute=institute,
            document_type=PrintDocumentType.PAYMENT_RECEIPT,
            is_active=True,
        )
        .select_related("library_template")
        .order_by("-updated_at")
        .first()
    )

    if custom_template and custom_template.library_template_id:
        library_template = custom_template.library_template
        is_visible = library_template.is_active and (
            library_template.is_global
            or library_template.visible_to_institutes.filter(pk=institute.pk).exists()
        )
        if not is_visible:
            custom_template = None

    if custom_template:
        try:
            html_file = custom_template.effective_html_file
            if html_file:
                with html_file.open("rb") as template_file:
                    template_source = template_file.read().decode("utf-8-sig")
                return Template(template_source).render(
                    Context(
                        {
                            **context,
                            "request": request,
                            "print_template": custom_template,
                        }
                    )
                )
        except (OSError, UnicodeDecodeError, TemplateSyntaxError):
            pass

    return render_to_string("institute_admin/payment_receipt.html", context, request=request)
