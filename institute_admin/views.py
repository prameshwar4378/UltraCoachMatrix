from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
import json

from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.utils import timezone
from django.views.decorators.http import require_POST
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from accountant.models import FeeCategory, FeeInvoice, Payment, PaymentActivity
from student_parent.models import (
    GuardianProfile,
    StudentAcademicSession,
    StudentDocument,
    StudentEnrollment,
    StudentProfile,
)
from student_parent.notifications import notify_fee_paid, notify_notice_published, notify_result_declared
from super_admin.models import UserProfile
from super_admin.decorators import institute_admin_required
from teacher.models import (
    Attendance,
    Exam,
    ExamAttempt,
    ExamAttemptUpload,
    ExamQuestion,
    ExamQuestionAttempt,
    ExamQuestionOption,
    ExamResult,
    Homework,
    TeacherProfile,
)
from teacher.forms import ExamQuestionForm, ExamQuestionOptionFormSet, TeacherExamForm, TeacherExamResultForm


from .forms import (
    AddStudentFeeForm,
    BatchForm,
    CourseForm,
    FeeCategoryForm,
    generate_student_admission_number,
    get_academic_year_label,
    get_institute_initials,
    get_or_create_academic_year,
    HomeworkForm,
    InstituteUserForm,
    NoticeForm,
    PaymentUpdateForm,
    PaymentVoidForm,
    ReceiveFeeForm,
    StudentBasicForm,
    StudentDocumentUploadForm,
    StudentEducationForm,
    StudentEnrollmentForm,
    StudentForm,
    StudentGuardianForm,
    SubjectForm,
    TeacherForm,
)
from .models import AcademicYear, Batch, Course, Notice, Subject


def close_popup_response(receipt_url=None):
    receipt_script = ""
    if receipt_url:
        receipt_script = (
            f"window.open({json.dumps(receipt_url)}, "
            "'feeReceiptWindow', "
            "'width=980,height=900,scrollbars=yes,resizable=yes');"
        )
    return HttpResponse(
        """
        <script>
            __RECEIPT_SCRIPT__
            if (window.opener) {
                window.opener.location.reload();
                window.close();
            } else {
                window.location.href = '/institute/';
            }
        </script>
        """.replace("__RECEIPT_SCRIPT__", receipt_script)
    )


def get_current_institute(request):
    profile = getattr(request.user, "profile", None)
    if request.user.is_superuser:
        return None
    if not profile or profile.role != UserProfile.Role.INSTITUTE_ADMIN:
        raise PermissionDenied("Only institute admins can access this page.")
    return profile.institute


def get_current_academic_year(request, institute=None):
    institute = institute or get_current_institute(request)
    if not institute:
        return None
    year_id = request.session.get("academic_year_id")
    if year_id:
        academic_year = AcademicYear.objects.filter(pk=year_id, institute=institute, is_active=True).first()
        if academic_year:
            return academic_year
    academic_year = get_or_create_academic_year(institute)
    request.session["academic_year_id"] = academic_year.pk
    return academic_year


def get_batch_course_data(institute, academic_year=None):
    batches = Batch.objects.filter(institute=institute).prefetch_related("courses") if institute else Batch.objects.none()
    if academic_year:
        batches = batches.filter(academic_year=academic_year)
    return {
        str(batch.pk): [
            {
                "id": str(course.pk),
                "name": course.name,
                "fee": str(course.fee_amount),
            }
            for course in batch.courses.all()
        ]
        for batch in batches
    }


def refresh_invoice_status(invoice):
    paid_amount = sum(payment.amount for payment in invoice.payments.filter(status=Payment.Status.ACTIVE))
    if paid_amount >= invoice.amount:
        invoice.status = FeeInvoice.Status.PAID
    elif paid_amount > 0:
        invoice.status = FeeInvoice.Status.PARTIAL
    else:
        invoice.status = FeeInvoice.Status.UNPAID
    invoice.save(update_fields=["status"])
    return invoice


def get_student_enrollment_due_data(student_or_session):
    if isinstance(student_or_session, StudentAcademicSession):
        student_session = student_or_session
        student = student_session.student
        enrollments = student_session.enrollments.exclude(status=StudentEnrollment.Status.CANCELLED).select_related(
            "batch"
        ).prefetch_related("courses")
    else:
        student_session = None
        student = student_or_session
        enrollments = student.enrollments.exclude(status=StudentEnrollment.Status.CANCELLED).select_related(
            "batch"
        ).prefetch_related("courses")
    data = {}
    for enrollment in enrollments:
        payment_filter = {
            "invoice__student": student,
            "invoice__enrollment": enrollment,
            "status": Payment.Status.ACTIVE,
        }
        if student_session:
            payment_filter["invoice__academic_session"] = student_session
        paid_amount = Payment.objects.filter(
            **payment_filter,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        due_amount = enrollment.total_course_fee - paid_amount
        if due_amount < 0:
            due_amount = Decimal("0.00")
        first_due_invoice = None
        pending_filter = {
            "student": student,
            "enrollment": enrollment,
            "status__in": [FeeInvoice.Status.UNPAID, FeeInvoice.Status.PARTIAL],
        }
        if student_session:
            pending_filter["academic_session"] = student_session
        pending_invoices = (
            FeeInvoice.objects.filter(
                **pending_filter,
            )
            .prefetch_related("payments")
            .order_by("-created_at", "-pk")
        )
        for invoice in pending_invoices:
            invoice_paid = sum(payment.amount for payment in invoice.payments.filter(status=Payment.Status.ACTIVE))
            invoice_due = invoice.amount - invoice_paid
            if invoice_due <= 0 or due_amount <= 0:
                continue
            collectable_due = min(invoice_due, due_amount)
            first_due_invoice = {
                "id": str(invoice.pk),
                "title": invoice.title,
                "amount": str(invoice.amount),
                "paid": str(invoice_paid),
                "due": str(collectable_due),
            }
            break
        data[str(enrollment.pk)] = {
            "title": f"{enrollment.batch.name} Fee",
            "total_fee": str(enrollment.total_course_fee),
            "paid": str(paid_amount),
            "due": str(due_amount),
            "invoice": first_due_invoice,
        }
    return data


def get_student_category_due_data(student_or_session):
    if isinstance(student_or_session, StudentAcademicSession):
        student_session = student_or_session
        student = student_session.student
    else:
        student_session = None
        student = student_or_session
    data = {}
    total_due = Decimal("0.00")
    categories = FeeCategory.objects.filter(institute=student.institute, is_active=True)
    for category in categories:
        invoice_filter = {
            "student": student,
            "category": category,
            "status__in": [FeeInvoice.Status.UNPAID, FeeInvoice.Status.PARTIAL],
        }
        if student_session:
            invoice_filter["academic_session"] = student_session
        invoices = (
            FeeInvoice.objects.filter(
                **invoice_filter,
            )
            .select_related("category")
            .prefetch_related("payments")
        )
        category_total = Decimal("0.00")
        category_paid = Decimal("0.00")
        first_due_invoice = None
        for invoice in invoices:
            paid_amount = sum(payment.amount for payment in invoice.payments.filter(status=Payment.Status.ACTIVE))
            due_amount = invoice.amount - paid_amount
            if due_amount < 0:
                due_amount = Decimal("0.00")
            if due_amount <= 0:
                continue
            category_total += invoice.amount
            category_paid += paid_amount
            total_due += due_amount
            if first_due_invoice is None:
                first_due_invoice = {
                    "id": str(invoice.pk),
                    "title": invoice.title,
                    "amount": str(invoice.amount),
                    "paid": str(paid_amount),
                    "due": str(due_amount),
                }

        category_due = category_total - category_paid
        if category_due < 0:
            category_due = Decimal("0.00")
        data[str(category.pk)] = {
            "name": category.name,
            "default_amount": str(category.default_amount),
            "total": str(category_total),
            "paid": str(category_paid),
            "due": str(category_due),
            "invoice": first_due_invoice,
        }

    return {
        "categories": data,
        "total_due": str(total_due),
    }


@login_required
def academic_year_switch(request):
    profile = getattr(request.user, "profile", None)
    if not profile or profile.role not in {UserProfile.Role.INSTITUTE_ADMIN, UserProfile.Role.TEACHER} or not profile.institute_id:
        return redirect(reverse("school_dashboard"))
    institute = profile.institute
    if request.method == "POST":
        year_name = request.POST.get("academic_year", "").strip()
        if year_name:
            academic_year = get_or_create_academic_year(institute, year_name)
            request.session["academic_year_id"] = academic_year.pk
            messages.success(request, f"Academic year changed to {academic_year.name}.")
    return redirect(request.META.get("HTTP_REFERER") or reverse("institute_admin:dashboard"))


@institute_admin_required
def dashboard(request):
    profile = getattr(request.user, "profile", None)
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    institute_filter = {"institute": institute} if institute else {}

    invoices = FeeInvoice.objects.filter(**institute_filter).exclude(status=FeeInvoice.Status.CANCELLED).prefetch_related("payments")
    if academic_year:
        invoices = invoices.filter(academic_session__academic_year=academic_year)

    students = StudentAcademicSession.objects.filter(**institute_filter)
    if academic_year:
        students = students.filter(academic_year=academic_year)
    batches = Batch.objects.filter(**institute_filter)
    courses = Course.objects.filter(**institute_filter)
    if academic_year:
        batches = batches.filter(academic_year=academic_year)
        courses = courses.filter(academic_year=academic_year)
    today = date.today()
    today_attendance = Attendance.objects.filter(date=today)
    if institute:
        today_attendance = today_attendance.filter(batch__institute=institute)
    if academic_year:
        today_attendance = today_attendance.filter(academic_session__academic_year=academic_year)
    today_attendance_count = today_attendance.count()
    today_present_count = today_attendance.filter(status=Attendance.Status.PRESENT).count()
    today_absent_count = today_attendance.filter(status=Attendance.Status.ABSENT).count()
    today_late_count = today_attendance.filter(status=Attendance.Status.LATE).count()
    attendance_rate = round((today_present_count / today_attendance_count) * 100, 1) if today_attendance_count else 0
    recent_payments = Payment.objects.filter(status=Payment.Status.ACTIVE).select_related(
        "invoice",
        "invoice__student",
        "invoice__student__user",
    )
    if institute:
        recent_payments = recent_payments.filter(invoice__institute=institute)
    if academic_year:
        recent_payments = recent_payments.filter(invoice__academic_session__academic_year=academic_year)
    today_collection = recent_payments.filter(paid_on=today).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    month_collection = recent_payments.filter(paid_on__year=today.year, paid_on__month=today.month).aggregate(
        total=Sum("amount")
    )["total"] or Decimal("0.00")

    invoice_amount = Decimal("0.00")
    paid_amount = Decimal("0.00")
    due_amount = Decimal("0.00")
    due_invoice_rows = []
    dashboard_sessions = students.select_related("student", "student__user").prefetch_related(
        "enrollments",
        "enrollments__batch",
        "enrollments__courses",
        "fee_invoices",
        "fee_invoices__payments",
    )
    for student_session in dashboard_sessions:
        fee_enrollments = student_session.enrollments.exclude(status=StudentEnrollment.Status.CANCELLED)
        session_invoices = student_session.fee_invoices.exclude(status=FeeInvoice.Status.CANCELLED)
        enrollment_fee_amount = sum(enrollment.total_course_fee for enrollment in fee_enrollments)
        invoiced_amount = Decimal("0.00")
        additional_fee_amount = Decimal("0.00")
        session_paid_amount = Decimal("0.00")
        for invoice in session_invoices:
            invoiced_amount += invoice.amount
            if not invoice.enrollment_id:
                additional_fee_amount += invoice.amount
            session_paid_amount += sum(payment.amount for payment in invoice.payments.all() if payment.status == Payment.Status.ACTIVE)

        session_total_fee = enrollment_fee_amount + additional_fee_amount if enrollment_fee_amount > 0 else invoiced_amount
        session_due_amount = session_total_fee - session_paid_amount
        if session_due_amount < 0:
            session_due_amount = Decimal("0.00")

        invoice_amount += session_total_fee
        paid_amount += session_paid_amount
        due_amount += session_due_amount

        if session_due_amount > 0:
            due_invoice_rows.append(
                {
                    "student_name": student_session.student.user.get_full_name() or student_session.student.user.username,
                    "title": ", ".join(enrollment.batch.name for enrollment in fee_enrollments[:2]) or "Pending fees",
                    "due_date": min(
                        [enrollment.enrolled_on for enrollment in fee_enrollments if enrollment.enrolled_on],
                        default=None,
                    ),
                    "due_amount": session_due_amount,
                }
            )

    collection_rate = round((paid_amount / invoice_amount) * 100, 1) if invoice_amount else 0
    due_invoice_rows = sorted(due_invoice_rows, key=lambda row: row["due_amount"], reverse=True)

    latest_students = students.select_related("student", "student__user").order_by("-id")[:5]

    context = {
        "profile": profile,
        "institute": institute,
        "course_count": courses.count(),
        "batch_count": batches.count(),
        "active_batch_count": batches.filter(is_active=True).count(),
        "student_count": students.count(),
        "active_student_count": students.filter(status=StudentAcademicSession.Status.ACTIVE, student__is_active=True).count(),
        "teacher_count": UserProfile.objects.filter(
            institute=institute,
            role=UserProfile.Role.TEACHER,
        ).count() if institute else 0,
        "accountant_count": UserProfile.objects.filter(
            institute=institute,
            role=UserProfile.Role.ACCOUNTANT,
        ).count() if institute else 0,
        "invoice_count": invoices.count(),
        "invoice_amount": invoice_amount,
        "due_amount": due_amount,
        "paid_amount": paid_amount or 0,
        "collection_rate": collection_rate,
        "today": today,
        "today_attendance_count": today_attendance_count,
        "today_present_count": today_present_count,
        "today_absent_count": today_absent_count,
        "today_late_count": today_late_count,
        "attendance_rate": attendance_rate,
        "today_collection": today_collection,
        "month_collection": month_collection,
        "recent_payments": recent_payments.order_by("-created_at", "-pk")[:5],
        "due_invoice_rows": due_invoice_rows[:6],
        "latest_students": latest_students,
        "recent_notices": Notice.objects.filter(**institute_filter)[:5],
        "recent_homework": Homework.objects.filter(
            batch__institute=institute,
            batch__academic_year=academic_year,
        )[:5] if institute and academic_year else [],
        "recent_attendance": Attendance.objects.filter(
            batch__institute=institute,
            academic_session__academic_year=academic_year,
            batch__academic_year=academic_year,
        )[:5] if institute and academic_year else [],
    }
    return render(request, "institute_admin/dashboard.html", context)


@institute_admin_required
def course_list(request):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    courses = Course.objects.select_related("institute").annotate(batch_count=Count("batches"))
    if institute:
        courses = courses.filter(institute=institute)
    if academic_year:
        courses = courses.filter(academic_year=academic_year)

    search_query = request.GET.get("search", "").strip()
    status_filter = request.GET.get("status", "").strip()

    if search_query:
        courses = courses.filter(name__icontains=search_query)

    if status_filter == "active":
        courses = courses.filter(is_active=True)
    elif status_filter == "inactive":
        courses = courses.filter(is_active=False)

    base_queryset = Course.objects.filter(institute=institute) if institute else Course.objects.all()
    batch_queryset = Batch.objects.filter(institute=institute) if institute else Batch.objects.all()
    if academic_year:
        batch_queryset = batch_queryset.filter(academic_year=academic_year)
    if academic_year:
        base_queryset = base_queryset.filter(academic_year=academic_year)
        batch_queryset = batch_queryset.filter(academic_year=academic_year)
    context = {
        "courses": courses,
        "search_query": search_query,
        "status_filter": status_filter,
        "total_courses": base_queryset.count(),
        "active_courses": base_queryset.filter(is_active=True).count(),
        "inactive_courses": base_queryset.filter(is_active=False).count(),
        "total_batches": batch_queryset.count(),
    }
    return render(request, "institute_admin/course_list.html", context)


@institute_admin_required
def course_create(request):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    if not institute:
        messages.error(request, "Select an institute before creating a course.")
        return redirect("institute_admin:course_list")

    if request.method == "POST":
        form = CourseForm(request.POST, institute=institute, academic_year=academic_year)
        if form.is_valid():
            course = form.save(commit=False)
            course.institute = institute
            course.academic_year = academic_year
            course.save()
            messages.success(request, "Course created successfully.")
            return close_popup_response()
    else:
        form = CourseForm(institute=institute, academic_year=academic_year)

    return render(
        request,
        "institute_admin/course_form.html",
        {
            "form": form,
            "title": "Create Course",
            "subtitle": "Add a course offered by your institute.",
            "button_text": "Save Course",
        },
    )


@institute_admin_required
def course_update(request, pk):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    queryset = Course.objects.all()
    if institute:
        queryset = queryset.filter(institute=institute)
    if academic_year:
        queryset = queryset.filter(academic_year=academic_year)
    course = get_object_or_404(queryset, pk=pk)

    if request.method == "POST":
        form = CourseForm(request.POST, instance=course, institute=course.institute, academic_year=course.academic_year)
        if form.is_valid():
            form.save()
            messages.success(request, "Course updated successfully.")
            return close_popup_response()
    else:
        form = CourseForm(instance=course, institute=course.institute, academic_year=course.academic_year)

    return render(
        request,
        "institute_admin/course_form.html",
        {
            "form": form,
            "title": "Edit Course",
            "subtitle": "Update course details and active status.",
            "button_text": "Update Course",
        },
    )


@institute_admin_required
def course_delete(request, pk):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    queryset = Course.objects.all()
    if institute:
        queryset = queryset.filter(institute=institute)
    if academic_year:
        queryset = queryset.filter(academic_year=academic_year)
    course = get_object_or_404(queryset, pk=pk)

    if request.method == "POST":
        if course.batches.exists():
            messages.error(request, "This course is used in batches. Remove it from those batches before deleting.")
        else:
            course.delete()
            messages.success(request, "Course deleted successfully.")

    return redirect("institute_admin:course_list")


@institute_admin_required
def subject_list(request):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    subjects = Subject.objects.select_related("institute", "academic_year")
    if institute:
        subjects = subjects.filter(institute=institute)
    if academic_year:
        subjects = subjects.filter(academic_year=academic_year)

    search_query = request.GET.get("search", "").strip()
    status_filter = request.GET.get("status", "").strip()

    if search_query:
        subjects = subjects.filter(Q(name__icontains=search_query) | Q(description__icontains=search_query))

    if status_filter == "active":
        subjects = subjects.filter(is_active=True)
    elif status_filter == "inactive":
        subjects = subjects.filter(is_active=False)

    base_queryset = Subject.objects.filter(institute=institute) if institute else Subject.objects.all()
    if academic_year:
        base_queryset = base_queryset.filter(academic_year=academic_year)

    context = {
        "subjects": subjects,
        "search_query": search_query,
        "status_filter": status_filter,
        "total_subjects": base_queryset.count(),
        "active_subjects": base_queryset.filter(is_active=True).count(),
        "inactive_subjects": base_queryset.filter(is_active=False).count(),
    }
    return render(request, "institute_admin/subject_list.html", context)


@institute_admin_required
def subject_create(request):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    if not institute:
        messages.error(request, "Select an institute before creating a subject.")
        return redirect("institute_admin:subject_list")

    if request.method == "POST":
        form = SubjectForm(request.POST, institute=institute, academic_year=academic_year)
        if form.is_valid():
            subject = form.save(commit=False)
            subject.institute = institute
            subject.academic_year = academic_year
            subject.save()
            messages.success(request, "Subject created successfully.")
            return close_popup_response()
    else:
        form = SubjectForm(institute=institute, academic_year=academic_year)

    return render(
        request,
        "institute_admin/subject_form.html",
        {
            "form": form,
            "title": "Create Subject",
            "subtitle": "Add a subject for exams and academic work.",
            "button_text": "Save Subject",
        },
    )


@institute_admin_required
def subject_update(request, pk):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    queryset = Subject.objects.all()
    if institute:
        queryset = queryset.filter(institute=institute)
    if academic_year:
        queryset = queryset.filter(academic_year=academic_year)
    subject = get_object_or_404(queryset, pk=pk)

    if request.method == "POST":
        form = SubjectForm(request.POST, instance=subject, institute=subject.institute, academic_year=subject.academic_year)
        if form.is_valid():
            form.save()
            messages.success(request, "Subject updated successfully.")
            return close_popup_response()
    else:
        form = SubjectForm(instance=subject, institute=subject.institute, academic_year=subject.academic_year)

    return render(
        request,
        "institute_admin/subject_form.html",
        {
            "form": form,
            "title": "Edit Subject",
            "subtitle": "Update subject details and active status.",
            "button_text": "Update Subject",
        },
    )


@institute_admin_required
def subject_delete(request, pk):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    queryset = Subject.objects.all()
    if institute:
        queryset = queryset.filter(institute=institute)
    if academic_year:
        queryset = queryset.filter(academic_year=academic_year)
    subject = get_object_or_404(queryset, pk=pk)

    if request.method == "POST":
        if subject.exams.exists():
            messages.error(request, "This subject is used in exams. Remove it from exams before deleting.")
        else:
            subject.delete()
            messages.success(request, "Subject deleted successfully.")

    return redirect("institute_admin:subject_list")


@institute_admin_required
def fee_category_list(request):
    institute = get_current_institute(request)
    categories = FeeCategory.objects.select_related("institute").annotate(invoice_count=Count("invoices"))
    if institute:
        categories = categories.filter(institute=institute)

    search_query = request.GET.get("search", "").strip()
    status_filter = request.GET.get("status", "").strip()

    if search_query:
        categories = categories.filter(name__icontains=search_query)

    if status_filter == "active":
        categories = categories.filter(is_active=True)
    elif status_filter == "inactive":
        categories = categories.filter(is_active=False)

    base_queryset = FeeCategory.objects.filter(institute=institute) if institute else FeeCategory.objects.all()
    context = {
        "categories": categories,
        "search_query": search_query,
        "status_filter": status_filter,
        "total_categories": base_queryset.count(),
        "active_categories": base_queryset.filter(is_active=True).count(),
        "inactive_categories": base_queryset.filter(is_active=False).count(),
        "used_categories": base_queryset.filter(invoices__isnull=False).distinct().count(),
    }
    return render(request, "institute_admin/fee_category_list.html", context)


@institute_admin_required
def fee_category_create(request):
    institute = get_current_institute(request)
    if not institute:
        messages.error(request, "Select an institute before creating a fee category.")
        return redirect("institute_admin:fee_category_list")

    if request.method == "POST":
        form = FeeCategoryForm(request.POST, institute=institute)
        if form.is_valid():
            category = form.save(commit=False)
            category.institute = institute
            category.save()
            messages.success(request, "Fee category created successfully.")
            return close_popup_response()
    else:
        form = FeeCategoryForm(institute=institute)

    return render(
        request,
        "institute_admin/fee_category_form.html",
        {
            "form": form,
            "title": "Create Fee Category",
            "subtitle": "Add a dynamic fee head for your institute services.",
            "button_text": "Save Category",
        },
    )


@institute_admin_required
def fee_category_update(request, pk):
    institute = get_current_institute(request)
    queryset = FeeCategory.objects.all()
    if institute:
        queryset = queryset.filter(institute=institute)
    category = get_object_or_404(queryset, pk=pk)

    if request.method == "POST":
        form = FeeCategoryForm(request.POST, institute=category.institute, instance=category)
        if form.is_valid():
            form.save()
            messages.success(request, "Fee category updated successfully.")
            return close_popup_response()
    else:
        form = FeeCategoryForm(institute=category.institute, instance=category)

    return render(
        request,
        "institute_admin/fee_category_form.html",
        {
            "form": form,
            "title": "Edit Fee Category",
            "subtitle": "Update category name, default amount and status.",
            "button_text": "Update Category",
        },
    )


@institute_admin_required
def fee_category_delete(request, pk):
    institute = get_current_institute(request)
    queryset = FeeCategory.objects.all()
    if institute:
        queryset = queryset.filter(institute=institute)
    category = get_object_or_404(queryset, pk=pk)

    if request.method == "POST":
        if category.invoices.exists():
            messages.error(request, "This category is used in invoices. Mark it inactive instead of deleting.")
        else:
            category.delete()
            messages.success(request, "Fee category deleted successfully.")

    return redirect("institute_admin:fee_category_list")


@institute_admin_required
def batch_list(request):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    batches = Batch.objects.select_related("institute").prefetch_related("courses", "teachers")
    if institute:
        batches = batches.filter(institute=institute)
    if academic_year:
        batches = batches.filter(academic_year=academic_year)

    search_query = request.GET.get("search", "").strip()
    course_filter = request.GET.get("course", "").strip()
    status_filter = request.GET.get("status", "").strip()

    if search_query:
        batches = batches.filter(
            Q(name__icontains=search_query)
            | Q(courses__name__icontains=search_query)
            | Q(timing__icontains=search_query)
        ).distinct()

    if course_filter:
        batches = batches.filter(courses__id=course_filter)

    if status_filter == "active":
        batches = batches.filter(is_active=True)
    elif status_filter == "inactive":
        batches = batches.filter(is_active=False)

    base_queryset = Batch.objects.filter(institute=institute) if institute else Batch.objects.all()
    course_queryset = Course.objects.filter(institute=institute) if institute else Course.objects.all()
    if academic_year:
        base_queryset = base_queryset.filter(academic_year=academic_year)
        course_queryset = course_queryset.filter(academic_year=academic_year)

    context = {
        "batches": batches,
        "courses": course_queryset,
        "search_query": search_query,
        "course_filter": course_filter,
        "status_filter": status_filter,
        "total_batches": base_queryset.count(),
        "active_batches": base_queryset.filter(is_active=True).count(),
        "inactive_batches": base_queryset.filter(is_active=False).count(),
        "total_courses": course_queryset.count(),
    }
    return render(request, "institute_admin/batch_list.html", context)


@institute_admin_required
def batch_create(request):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    if not institute:
        messages.error(request, "Select an institute before creating a batch.")
        return redirect("institute_admin:batch_list")

    if request.method == "POST":
        form = BatchForm(request.POST, institute=institute, academic_year=academic_year)
        if form.is_valid():
            batch = form.save(commit=False)
            batch.institute = institute
            batch.academic_year = academic_year
            batch.save()
            batch.courses.set(form.cleaned_data["courses"])
            teacher_profiles = form.cleaned_data["teachers"]
            batch.teachers.set([profile.user for profile in teacher_profiles])
            messages.success(request, "Batch created successfully.")
            return close_popup_response()
    else:
        form = BatchForm(institute=institute, academic_year=academic_year)

    return render(
        request,
        "institute_admin/batch_form.html",
        {
            "form": form,
            "title": "Create Batch",
            "subtitle": "Add a batch, select one or more courses, and assign teachers.",
            "button_text": "Save Batch",
        },
    )


@institute_admin_required
def batch_update(request, pk):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    queryset = Batch.objects.all()
    if institute:
        queryset = queryset.filter(institute=institute)
    if academic_year:
        queryset = queryset.filter(academic_year=academic_year)
    batch = get_object_or_404(queryset, pk=pk)

    if request.method == "POST":
        form = BatchForm(request.POST, instance=batch, institute=batch.institute, academic_year=batch.academic_year)
        if form.is_valid():
            batch = form.save(commit=False)
            batch.save()
            batch.courses.set(form.cleaned_data["courses"])
            teacher_profiles = form.cleaned_data["teachers"]
            batch.teachers.set([profile.user for profile in teacher_profiles])
            messages.success(request, "Batch updated successfully.")
            return close_popup_response()
    else:
        initial_profiles = UserProfile.objects.filter(user__in=batch.teachers.all())
        form = BatchForm(instance=batch, institute=batch.institute, academic_year=batch.academic_year, initial={"teachers": initial_profiles})

    return render(
        request,
        "institute_admin/batch_form.html",
        {
            "form": form,
            "title": "Edit Batch",
            "subtitle": "Update batch details, timing and assigned teachers.",
            "button_text": "Update Batch",
        },
    )


@institute_admin_required
def batch_delete(request, pk):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    queryset = Batch.objects.all()
    if institute:
        queryset = queryset.filter(institute=institute)
    if academic_year:
        queryset = queryset.filter(academic_year=academic_year)
    batch = get_object_or_404(queryset, pk=pk)

    if request.method == "POST":
        try:
            batch.delete()
            messages.success(request, "Batch deleted successfully.")
        except ProtectedError:
            messages.error(request, "This batch has related records and cannot be deleted.")

    return redirect("institute_admin:batch_list")


@institute_admin_required
def user_list(request):
    institute = get_current_institute(request)
    profiles = UserProfile.objects.select_related("user", "institute").exclude(role=UserProfile.Role.SUPER_ADMIN)
    if institute:
        profiles = profiles.filter(institute=institute)

    search_query = request.GET.get("search", "").strip()
    role_filter = request.GET.get("role", "").strip()
    status_filter = request.GET.get("status", "").strip()

    if search_query:
        profiles = profiles.filter(
            Q(user__first_name__icontains=search_query)
            | Q(user__last_name__icontains=search_query)
            | Q(user__username__icontains=search_query)
            | Q(user__email__icontains=search_query)
            | Q(phone__icontains=search_query)
        )

    if role_filter:
        profiles = profiles.filter(role=role_filter)

    if status_filter == "active":
        profiles = profiles.filter(user__is_active=True)
    elif status_filter == "inactive":
        profiles = profiles.filter(user__is_active=False)

    base_queryset = UserProfile.objects.exclude(role=UserProfile.Role.SUPER_ADMIN)
    if institute:
        base_queryset = base_queryset.filter(institute=institute)

    context = {
        "profiles": profiles,
        "role_choices": InstituteUserForm.ROLE_CHOICES,
        "search_query": search_query,
        "role_filter": role_filter,
        "status_filter": status_filter,
        "total_users": base_queryset.count(),
        "active_users": base_queryset.filter(user__is_active=True).count(),
        "teacher_users": base_queryset.filter(role=UserProfile.Role.TEACHER).count(),
        "accountant_users": base_queryset.filter(role=UserProfile.Role.ACCOUNTANT).count(),
        "student_parent_users": base_queryset.filter(role=UserProfile.Role.STUDENT_PARENT).count(),
    }
    return render(request, "institute_admin/user_list.html", context)


@institute_admin_required
def user_create(request):
    institute = get_current_institute(request)
    if not institute:
        messages.error(request, "Select an institute before creating a user.")
        return redirect("institute_admin:user_list")

    if request.method == "POST":
        form = InstituteUserForm(request.POST, institute=institute)
        if form.is_valid():
            form.save()
            messages.success(request, "User account created successfully.")
            return close_popup_response()
    else:
        form = InstituteUserForm(institute=institute)

    return render(
        request,
        "institute_admin/user_form.html",
        {
            "form": form,
            "title": "Create User",
            "subtitle": "Create login access and assign a role.",
            "button_text": "Save User",
        },
    )


@institute_admin_required
def user_update(request, pk):
    institute = get_current_institute(request)
    queryset = UserProfile.objects.select_related("user").exclude(role=UserProfile.Role.SUPER_ADMIN)
    if institute:
        queryset = queryset.filter(institute=institute)
    profile = get_object_or_404(queryset, pk=pk)

    if request.method == "POST":
        form = InstituteUserForm(request.POST, institute=profile.institute, profile=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "User account updated successfully.")
            return close_popup_response()
    else:
        form = InstituteUserForm(institute=profile.institute, profile=profile)

    return render(
        request,
        "institute_admin/user_form.html",
        {
            "form": form,
            "title": "Edit User",
            "subtitle": "Update login access, role and account status.",
            "button_text": "Update User",
        },
    )


@institute_admin_required
def user_delete(request, pk):
    institute = get_current_institute(request)
    queryset = UserProfile.objects.select_related("user").exclude(role=UserProfile.Role.SUPER_ADMIN)
    if institute:
        queryset = queryset.filter(institute=institute)
    profile = get_object_or_404(queryset, pk=pk)

    if request.method == "POST":
        if profile.user_id == request.user.id:
            messages.error(request, "You cannot delete your own account.")
        elif hasattr(profile.user, "student_profile"):
            messages.error(request, "This user is linked with a student profile. Manage it from Student section.")
        elif hasattr(profile.user, "teacher_profile") and profile.user.assigned_batches.exists():
            messages.error(request, "This teacher is assigned to batches. Remove them from batches before deleting.")
        else:
            profile.user.delete()
            messages.success(request, "User account deleted successfully.")

    return redirect("institute_admin:user_list")


@institute_admin_required
def student_list(request):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    sessions = StudentAcademicSession.objects.select_related(
        "institute",
        "academic_year",
        "student",
        "student__user",
        "student__user__profile",
    ).prefetch_related(
        "student__guardians",
        "student__enrollments__batch",
        "student__enrollments__courses",
        "student__fee_invoices__payments",
    )
    if institute:
        sessions = sessions.filter(institute=institute)
    if academic_year:
        sessions = sessions.filter(academic_year=academic_year)

    search_query = request.GET.get("search", "").strip()
    status_filter = request.GET.get("status", "").strip()

    if search_query:
        sessions = sessions.filter(
            Q(admission_number__icontains=search_query)
            | Q(student__user__first_name__icontains=search_query)
            | Q(student__user__last_name__icontains=search_query)
            | Q(student__user__username__icontains=search_query)
            | Q(student__user__email__icontains=search_query)
            | Q(student__user__profile__phone__icontains=search_query)
            | Q(student__guardians__name__icontains=search_query)
            | Q(student__guardians__phone__icontains=search_query)
        ).distinct()

    if status_filter == "active":
        sessions = sessions.filter(status=StudentAcademicSession.Status.ACTIVE, student__is_active=True)
    elif status_filter == "inactive":
        sessions = sessions.exclude(status=StudentAcademicSession.Status.ACTIVE, student__is_active=True)

    paginator = Paginator(sessions, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    sessions_page = page_obj.object_list
    query_params = request.GET.copy()
    query_params.pop("page", None)
    pagination_query = query_params.urlencode()

    for session in sessions_page:
        student = session.student
        fee_enrollments = session.enrollments.exclude(status=StudentEnrollment.Status.CANCELLED)
        invoices = session.fee_invoices.exclude(status=FeeInvoice.Status.CANCELLED)
        enrollment_fee_amount = sum(enrollment.total_course_fee for enrollment in fee_enrollments)
        invoiced_amount = Decimal("0.00")
        additional_fee_amount = Decimal("0.00")
        paid_amount = Decimal("0.00")
        for invoice in invoices:
            invoiced_amount += invoice.amount
            if not invoice.enrollment_id:
                additional_fee_amount += invoice.amount
            paid_amount += sum(payment.amount for payment in invoice.payments.filter(status=Payment.Status.ACTIVE))
        total_fee_amount = enrollment_fee_amount + additional_fee_amount if enrollment_fee_amount > 0 else invoiced_amount
        due_amount = total_fee_amount - paid_amount
        if due_amount < 0:
            due_amount = Decimal("0.00")
        session.total_fee_amount = total_fee_amount
        session.paid_amount = paid_amount
        session.due_amount = due_amount
        session.display_enrollments = list(fee_enrollments.select_related("batch")[:2])
        session.display_enrollment_count = fee_enrollments.count()

    base_queryset = StudentAcademicSession.objects.filter(institute=institute) if institute else StudentAcademicSession.objects.all()
    if academic_year:
        base_queryset = base_queryset.filter(academic_year=academic_year)
    context = {
        "students": sessions_page,
        "page_obj": page_obj,
        "paginator": paginator,
        "pagination_query": pagination_query,
        "search_query": search_query,
        "status_filter": status_filter,
        "total_students": base_queryset.count(),
        "active_students": base_queryset.filter(
            status=StudentAcademicSession.Status.ACTIVE,
            student__is_active=True,
        ).count(),
        "inactive_students": base_queryset.exclude(
            status=StudentAcademicSession.Status.ACTIVE,
            student__is_active=True,
        ).count(),
        "total_enrollments": StudentEnrollment.objects.filter(academic_session__in=base_queryset).count()
        if institute
        else StudentEnrollment.objects.count(),
    }
    return render(request, "institute_admin/student_list.html", context)


def get_next_academic_year_name(source_year):
    try:
        start_year = int(str(source_year.name).split("-", 1)[0])
    except (AttributeError, TypeError, ValueError):
        today = timezone.localdate()
        start_year = today.year if today.month >= 4 else today.year - 1
    next_start = start_year + 1
    return f"{next_start}-{str(next_start + 1)[-2:]}"


def is_valid_academic_year_name(year_name):
    try:
        start_part, end_part = str(year_name).split("-", 1)
        start_year = int(start_part)
        end_year = int(end_part)
    except (TypeError, ValueError):
        return False
    return len(start_part) == 4 and len(end_part) == 2 and int(str(start_year + 1)[-2:]) == end_year


@institute_admin_required
def student_promote(request):
    institute = get_current_institute(request)
    current_year = get_current_academic_year(request, institute)
    if not institute:
        messages.error(request, "Select an institute before promoting students.")
        return redirect("institute_admin:student_list")

    academic_years = AcademicYear.objects.filter(institute=institute, is_active=True)
    source_year_id = request.POST.get("source_year") or request.GET.get("source_year") or current_year.pk
    source_year = academic_years.filter(pk=source_year_id).first() or current_year
    target_year_name = (
        request.POST.get("target_year_name")
        or request.GET.get("target_year_name")
        or get_next_academic_year_name(source_year)
    ).strip()

    source_sessions = (
        StudentAcademicSession.objects.filter(
            institute=institute,
            academic_year=source_year,
            status=StudentAcademicSession.Status.ACTIVE,
            student__is_active=True,
        )
        .select_related("student", "student__user", "student__user__profile")
        .prefetch_related("student__guardians")
        .order_by("admission_number")
    )
    existing_target_year = AcademicYear.objects.filter(
        institute=institute,
        name=target_year_name,
        is_active=True,
    ).first()
    already_promoted_student_ids = set()
    if existing_target_year:
        already_promoted_student_ids = set(
            StudentAcademicSession.objects.filter(
                institute=institute,
                academic_year=existing_target_year,
            ).values_list("student_id", flat=True)
        )

    if request.method == "POST":
        selected_ids = [student_id for student_id in request.POST.getlist("students") if student_id.isdigit()]

        if not selected_ids:
            messages.error(request, "Select at least one student to promote.")
            return redirect(f"{reverse('institute_admin:student_promote')}?source_year={source_year.pk}&target_year_name={target_year_name}")
        if not is_valid_academic_year_name(target_year_name):
            messages.error(request, "Enter target academic year in format like 2027-28.")
            return redirect(f"{reverse('institute_admin:student_promote')}?source_year={source_year.pk}")
        if target_year_name == source_year.name:
            messages.error(request, "Target academic year must be different from source academic year.")
            return redirect(f"{reverse('institute_admin:student_promote')}?source_year={source_year.pk}&target_year_name={target_year_name}")

        target_year = get_or_create_academic_year(institute, target_year_name)
        selected_sessions = source_sessions.filter(student_id__in=selected_ids)
        created_count = 0
        skipped_count = 0

        with transaction.atomic():
            for source_session in selected_sessions:
                exists = StudentAcademicSession.objects.filter(
                    student=source_session.student,
                    academic_year=target_year,
                ).exists()
                if exists:
                    skipped_count += 1
                    continue
                StudentAcademicSession.objects.create(
                    institute=institute,
                    student=source_session.student,
                    academic_year=target_year,
                    admission_number=generate_student_admission_number(institute, target_year),
                    joined_on=timezone.localdate(),
                    status=StudentAcademicSession.Status.ACTIVE,
                )
                created_count += 1

        request.session["academic_year_id"] = target_year.pk
        if created_count:
            messages.success(request, f"{created_count} student(s) promoted to {target_year.name}. No enrollments, batches, courses, fees, or attendance were copied.")
        if skipped_count:
            messages.warning(request, f"{skipped_count} student(s) already had a session in {target_year.name}.")
        return redirect("institute_admin:student_list")

    context = {
        "academic_years": academic_years,
        "source_year": source_year,
        "target_year_name": target_year_name,
        "students": source_sessions,
        "already_promoted_student_ids": already_promoted_student_ids,
        "available_count": source_sessions.exclude(student_id__in=already_promoted_student_ids).count(),
    }
    return render(request, "institute_admin/student_promote.html", context)


def style_student_workbook_header(sheet, title, max_col):
    primary = "0F766E"
    dark = "0F172A"
    border_color = "CBD5E1"
    thin = Side(style="thin", color=border_color)
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max_col)
    sheet.cell(row=1, column=1, value=title)
    sheet.cell(row=1, column=1).font = Font(size=18, bold=True, color="FFFFFF")
    sheet.cell(row=1, column=1).fill = PatternFill("solid", fgColor=primary)
    sheet.cell(row=1, column=1).alignment = Alignment(horizontal="center", vertical="center")
    sheet.row_dimensions[1].height = 30
    for col in range(1, max_col + 1):
        cell = sheet.cell(row=3, column=col)
        cell.fill = PatternFill("solid", fgColor=dark)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border
    return border


def student_import_columns():
    return [
        "First Name *",
        "Last Name",
        "Username",
        "Password",
        "Email",
        "Phone",
        "Date of Birth",
        "Joined On",
        "Address",
        "Current School / College",
        "Current School Address",
        "Previous School / College",
        "Previous Class",
        "Guardian Name",
        "Guardian Relation",
        "Guardian Phone",
        "Guardian Email",
        "Active",
    ]


def parse_excel_date_value(value):
    if not value:
        return None
    if hasattr(value, "date"):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Invalid date: {text}. Use YYYY-MM-DD.")


def bool_from_excel(value):
    if value in (True, False):
        return bool(value)
    text = str(value or "Yes").strip().lower()
    return text not in {"no", "false", "0", "inactive"}


def validate_student_import_file(upload, institute, academic_year=None):
    academic_year = academic_year or get_or_create_academic_year(institute)
    try:
        workbook = load_workbook(upload, data_only=True)
        sheet = workbook["Students"] if "Students" in workbook.sheetnames else workbook.active
    except Exception as exc:
        return {
            "valid": False,
            "valid_count": 0,
            "errors": [f"Could not read Excel file: {exc}"],
            "warnings": [],
        }

    expected = student_import_columns()
    headers = [str(cell.value or "").strip() for cell in sheet[3]]
    if headers[: len(expected)] != expected:
        return {
            "valid": False,
            "valid_count": 0,
            "errors": ["Invalid template format. Download the latest template and try again."],
            "warnings": [],
        }

    errors = []
    warnings = []
    cell_errors = {}
    preview_rows = []
    valid_count = 0
    seen_usernames = {}
    seen_emails = {}
    seen_phones = {}
    existing_usernames = set(User.objects.values_list("username", flat=True))
    existing_phones = set(
        UserProfile.objects.filter(institute=institute)
        .exclude(phone="")
        .values_list("phone", flat=True)
    )

    for row_number in range(4, sheet.max_row + 1):
        row_values = [sheet.cell(row=row_number, column=col).value for col in range(1, len(expected) + 1)]
        if not any(value not in (None, "") for value in row_values):
            continue

        row = dict(zip(expected, row_values))
        row_errors = []
        row_cell_errors = {}
        first_name = str(row["First Name *"] or "").strip()
        username = str(row["Username"] or "").strip()
        email = str(row["Email"] or "").strip().lower()
        phone = str(row["Phone"] or "").strip()

        if not first_name:
            error = "First Name is required."
            row_errors.append(error)
            row_cell_errors["First Name *"] = error
        if username:
            if username in existing_usernames:
                error = f"Username already exists: {username}."
                row_errors.append(error)
                row_cell_errors["Username"] = error
            if username in seen_usernames:
                error = f"Duplicate username in file. Also used on row {seen_usernames[username]}."
                row_errors.append(error)
                row_cell_errors["Username"] = error
            seen_usernames[username] = row_number
        if phone:
            if phone in existing_phones:
                error = f"Mobile number already exists: {phone}."
                row_errors.append(error)
                row_cell_errors["Phone"] = error
            if phone in seen_phones:
                error = f"Duplicate mobile number in file. Also used on row {seen_phones[phone]}."
                row_errors.append(error)
                row_cell_errors["Phone"] = error
            seen_phones[phone] = row_number
        else:
            error = "Phone is required and must be unique."
            row_errors.append(error)
            row_cell_errors["Phone"] = error
        if email:
            if email in seen_emails:
                warnings.append(f"Row {row_number}: Email also appears on row {seen_emails[email]} ({email}).")
            seen_emails[email] = row_number
        for date_column in ("Date of Birth", "Joined On"):
            try:
                parse_excel_date_value(row[date_column])
            except ValueError as exc:
                row_errors.append(str(exc))
                row_cell_errors[date_column] = str(exc)
        if not row["Password"]:
            warnings.append(f"Row {row_number}: Password is blank. Default Student@123 will be used.")
        if not username:
            warnings.append(f"Row {row_number}: Username is blank. Generated admission number will be used.")

        if row_errors:
            errors.extend(f"Row {row_number}: {error}" for error in row_errors)
        else:
            valid_count += 1
        if row_cell_errors:
            cell_errors[str(row_number)] = row_cell_errors
        preview_rows.append(
            {
                "row_number": row_number,
                "values": ["" if value is None else str(value) for value in row_values],
                "errors": row_cell_errors,
            }
        )

    if valid_count == 0 and not errors:
        errors.append("No student rows found in the file.")

    return {
        "valid": not errors and valid_count > 0,
        "valid_count": valid_count,
        "errors": errors,
        "warnings": warnings,
        "prefix": f"{get_institute_initials(institute)}-{academic_year.name}-0001",
        "headers": expected,
        "rows": preview_rows[:100],
        "cell_errors": cell_errors,
    }


@institute_admin_required
def student_import_template(request):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Students"
    columns = student_import_columns()
    border = style_student_workbook_header(sheet, "Student Bulk Import Template", len(columns))
    sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(columns))
    sheet.cell(
        row=2,
        column=1,
        value=f"Admission number will be generated automatically like {get_institute_initials(institute)}-{academic_year.name}-0001",
    )
    sheet.cell(row=2, column=1).font = Font(italic=True, color="64748B")
    for col, header in enumerate(columns, start=1):
        sheet.cell(row=3, column=col, value=header)
        sheet.column_dimensions[get_column_letter(col)].width = 22
    examples = [
        "Rohan",
        "Sharma",
        "",
        "Student@123",
        "rohan@example.com",
        "9876543210",
        "2010-05-12",
        timezone.localdate().isoformat(),
        "Student address",
        "Saint Monica International School",
        "School address",
        "Previous School",
        "10th",
        "Mahesh Sharma",
        "Father",
        "9876543210",
        "guardian@example.com",
        "Yes",
    ]
    for col, value in enumerate(examples, start=1):
        cell = sheet.cell(row=4, column=col, value=value)
        cell.border = border
        cell.fill = PatternFill("solid", fgColor="F8FAFC")
    sheet.freeze_panes = "A4"

    info = workbook.create_sheet("Instructions")
    info["A1"] = "Instructions"
    info["A1"].font = Font(size=16, bold=True, color="0F766E")
    info["A3"] = "1. Do not add Admission Number. It is generated automatically."
    info["A4"] = "2. First Name is required."
    info["A5"] = "3. Username is optional. If blank, it will use the generated admission number."
    info["A6"] = "4. Password is optional. If blank, Student@123 will be used."
    info["A7"] = "5. Dates can be YYYY-MM-DD or DD-MM-YYYY."
    info.column_dimensions["A"].width = 90

    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    response = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="student_import_template.xlsx"'
    return response


@institute_admin_required
def student_export(request):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    sessions = StudentAcademicSession.objects.select_related(
        "student",
        "student__user",
        "student__user__profile",
        "academic_year",
    ).prefetch_related("student__guardians")
    if institute:
        sessions = sessions.filter(institute=institute)
    if academic_year:
        sessions = sessions.filter(academic_year=academic_year)
    search_query = request.GET.get("search", "").strip()
    status_filter = request.GET.get("status", "").strip()
    if search_query:
        sessions = sessions.filter(
            Q(admission_number__icontains=search_query)
            | Q(student__user__first_name__icontains=search_query)
            | Q(student__user__last_name__icontains=search_query)
            | Q(student__user__username__icontains=search_query)
            | Q(student__user__email__icontains=search_query)
            | Q(student__user__profile__phone__icontains=search_query)
            | Q(student__guardians__name__icontains=search_query)
            | Q(student__guardians__phone__icontains=search_query)
        ).distinct()
    if status_filter == "active":
        sessions = sessions.filter(status=StudentAcademicSession.Status.ACTIVE, student__is_active=True)
    elif status_filter == "inactive":
        sessions = sessions.exclude(status=StudentAcademicSession.Status.ACTIVE, student__is_active=True)

    columns = [
        "Admission Number",
        "First Name",
        "Last Name",
        "Username",
        "Email",
        "Phone",
        "Date of Birth",
        "Joined On",
        "Guardian Name",
        "Guardian Relation",
        "Guardian Phone",
        "Guardian Email",
        "Active",
    ]
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Students"
    border = style_student_workbook_header(sheet, "Student Export", len(columns))
    for col, header in enumerate(columns, start=1):
        sheet.cell(row=3, column=col, value=header)
        sheet.column_dimensions[get_column_letter(col)].width = 22
    for row, session in enumerate(sessions.order_by("admission_number"), start=4):
        student = session.student
        profile = getattr(student.user, "profile", None)
        guardian = student.guardians.filter(is_primary=True).first() or student.guardians.first()
        values = [
            session.admission_number,
            student.user.first_name,
            student.user.last_name,
            student.user.username,
            student.user.email,
            profile.phone if profile else "",
            student.date_of_birth.isoformat() if student.date_of_birth else "",
            session.joined_on.isoformat() if session.joined_on else "",
            guardian.name if guardian else "",
            guardian.relation if guardian else "",
            guardian.phone if guardian else "",
            guardian.email if guardian else "",
            "Yes" if session.status == StudentAcademicSession.Status.ACTIVE and student.is_active else "No",
        ]
        for col, value in enumerate(values, start=1):
            cell = sheet.cell(row=row, column=col, value=value)
            cell.border = border
            cell.alignment = Alignment(vertical="center")
    sheet.freeze_panes = "A4"
    sheet.auto_filter.ref = f"A3:{get_column_letter(len(columns))}{max(4, sessions.count() + 3)}"
    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    response = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="student_export.xlsx"'
    return response


@institute_admin_required
def student_bulk_import_validate(request):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    if request.method != "POST":
        return JsonResponse({"valid": False, "errors": ["Invalid request."], "warnings": [], "valid_count": 0}, status=405)
    upload = request.FILES.get("student_file")
    if not upload:
        return JsonResponse(
            {"valid": False, "errors": ["Select an Excel file before validation."], "warnings": [], "valid_count": 0},
            status=400,
        )
    result = validate_student_import_file(upload, institute, academic_year)
    return JsonResponse(result)


@institute_admin_required
def student_bulk_import(request):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    if request.method != "POST":
        return redirect("institute_admin:student_list")
    upload = request.FILES.get("student_file")
    if not upload:
        messages.error(request, "Select an Excel file before importing students.")
        return redirect("institute_admin:student_list")

    validation = validate_student_import_file(upload, institute, academic_year)
    if hasattr(upload, "seek"):
        upload.seek(0)
    if validation["errors"]:
        messages.error(request, "Fix validation errors before importing: " + " | ".join(validation["errors"][:5]))
        return redirect("institute_admin:student_list")

    try:
        workbook = load_workbook(upload, data_only=True)
        sheet = workbook["Students"] if "Students" in workbook.sheetnames else workbook.active
    except Exception as exc:
        messages.error(request, f"Could not read Excel file: {exc}")
        return redirect("institute_admin:student_list")

    headers = [str(cell.value or "").strip() for cell in sheet[3]]
    expected = student_import_columns()
    if headers[: len(expected)] != expected:
        messages.error(request, "Invalid template format. Download the latest template and try again.")
        return redirect("institute_admin:student_list")

    created_count = 0
    errors = []
    for row_number in range(4, sheet.max_row + 1):
        row_values = [sheet.cell(row=row_number, column=col).value for col in range(1, len(expected) + 1)]
        if not any(value not in (None, "") for value in row_values):
            continue
        row = dict(zip(expected, row_values))
        try:
            first_name = str(row["First Name *"] or "").strip()
            if not first_name:
                raise ValidationError("First Name is required.")
            admission_number = generate_student_admission_number(institute, academic_year)
            username = str(row["Username"] or admission_number).strip()
            if User.objects.filter(username=username).exists():
                raise ValidationError(f"Username already exists: {username}")
            user = User(
                username=username,
                first_name=first_name,
                last_name=str(row["Last Name"] or "").strip(),
                email=str(row["Email"] or "").strip(),
                is_active=bool_from_excel(row["Active"]),
            )
            user.set_password(str(row["Password"] or "Student@123"))
            with transaction.atomic():
                user.save()
                UserProfile.objects.create(
                    user=user,
                    institute=institute,
                    academic_year=academic_year,
                    role=UserProfile.Role.STUDENT_PARENT,
                    phone=str(row["Phone"] or "").strip(),
                )
                student = StudentProfile.objects.create(
                    institute=institute,
                    academic_year=academic_year,
                    user=user,
                    admission_number=admission_number,
                    date_of_birth=parse_excel_date_value(row["Date of Birth"]),
                    joined_on=parse_excel_date_value(row["Joined On"]),
                    address=str(row["Address"] or "").strip(),
                    current_school_name=str(row["Current School / College"] or "").strip(),
                    current_school_address=str(row["Current School Address"] or "").strip(),
                    previous_school_name=str(row["Previous School / College"] or "").strip(),
                    previous_class=str(row["Previous Class"] or "").strip(),
                    is_active=bool_from_excel(row["Active"]),
                )
                StudentAcademicSession.objects.create(
                    institute=institute,
                    student=student,
                    academic_year=academic_year,
                    admission_number=admission_number,
                    joined_on=student.joined_on,
                    status=(
                        StudentAcademicSession.Status.ACTIVE
                        if student.is_active
                        else StudentAcademicSession.Status.LEFT
                    ),
                    current_school_name=student.current_school_name,
                    current_school_address=student.current_school_address,
                    previous_school_name=student.previous_school_name,
                    previous_class=student.previous_class,
                )
                if row["Guardian Name"] or row["Guardian Phone"]:
                    GuardianProfile.objects.create(
                        student=student,
                        name=str(row["Guardian Name"] or "Primary Guardian").strip(),
                        relation=str(row["Guardian Relation"] or "").strip(),
                        phone=str(row["Guardian Phone"] or row["Phone"] or "").strip(),
                        email=str(row["Guardian Email"] or "").strip(),
                        is_primary=True,
                    )
                created_count += 1
        except Exception as exc:
            errors.append(f"Row {row_number}: {exc}")

    if created_count:
        messages.success(request, f"{created_count} student(s) imported successfully.")
    if errors:
        messages.error(request, "Import completed with errors: " + " | ".join(errors[:5]))
    return redirect("institute_admin:student_list")


@institute_admin_required
def student_dashboard(request, pk):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    session_queryset = StudentAcademicSession.objects.select_related(
        "institute",
        "academic_year",
        "student",
        "student__institute",
        "student__user",
        "student__user__profile",
    ).prefetch_related(
        "student__guardians",
        "student__documents",
        "student__enrollments__batch",
        "student__enrollments__courses",
    )
    if institute:
        session_queryset = session_queryset.filter(institute=institute)
    if academic_year:
        session_queryset = session_queryset.filter(academic_year=academic_year)
    student_session = get_object_or_404(session_queryset, student_id=pk)
    student = student_session.student

    enrollments = student_session.enrollments.select_related("batch").prefetch_related("courses").order_by("-enrolled_on", "-pk")
    fee_enrollments = enrollments.exclude(status=StudentEnrollment.Status.CANCELLED)
    invoices = (
        FeeInvoice.objects.filter(student=student, academic_session=student_session)
        .select_related("category", "batch", "enrollment")
        .prefetch_related("payments")
        .order_by("-created_at", "-pk")
    )
    payments = (
        Payment.objects.filter(invoice__student=student, invoice__academic_session=student_session)
        .select_related("invoice", "received_by")
        .order_by("-created_at", "-pk")
    )
    payment_activities = (
        PaymentActivity.objects.filter(payment__invoice__student=student, payment__invoice__academic_session=student_session)
        .select_related(
            "payment",
            "payment__invoice",
            "performed_by",
        )
        .order_by("-performed_at", "-pk")[:20]
    )
    attendance_records = (
        Attendance.objects.filter(student=student, academic_session=student_session)
        .select_related("batch", "marked_by")
        .order_by("-date", "-pk")[:10]
    )

    invoice_rows = []
    invoiced_amount = Decimal("0.00")
    additional_fee_amount = Decimal("0.00")
    raw_paid_amount = Decimal("0.00")
    service_rows = []
    excess_credit = Decimal("0.00")
    enrollment_invoice_ids = set()
    additional_groups = {}

    for invoice in invoices:
        paid_amount = sum(payment.amount for payment in invoice.payments.filter(status=Payment.Status.ACTIVE))
        due_amount = invoice.amount - paid_amount
        if due_amount < 0:
            due_amount = Decimal("0.00")
        if invoice.status != FeeInvoice.Status.CANCELLED:
            invoiced_amount += invoice.amount
            if not invoice.enrollment_id:
                additional_fee_amount += invoice.amount
            raw_paid_amount += paid_amount
            if invoice.enrollment_id:
                enrollment_invoice_ids.add(invoice.pk)
            else:
                group_key = f"category-{invoice.category_id}" if invoice.category_id else f"invoice-{invoice.pk}"
                if group_key not in additional_groups:
                    additional_groups[group_key] = {
                        "title": invoice.category.name if invoice.category_id else invoice.title,
                        "category": invoice.category.name if invoice.category_id else "General",
                        "amount": Decimal("0.00"),
                        "actual_paid": Decimal("0.00"),
                        "due_date": invoice.due_date,
                        "adjusted_credit": Decimal("0.00"),
                    }
                additional_groups[group_key]["amount"] += invoice.amount
                additional_groups[group_key]["actual_paid"] += paid_amount
                if invoice.due_date and invoice.due_date > additional_groups[group_key]["due_date"]:
                    additional_groups[group_key]["due_date"] = invoice.due_date

    for enrollment in fee_enrollments:
        enrollment_paid = (
            Payment.objects.filter(
                invoice__student=student,
                invoice__academic_session=student_session,
                invoice__enrollment=enrollment,
                status=Payment.Status.ACTIVE,
            ).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        display_paid = min(enrollment_paid, enrollment.total_course_fee)
        if enrollment_paid > enrollment.total_course_fee:
            excess_credit += enrollment_paid - enrollment.total_course_fee
        service_rows.append(
            {
                "title": f"{enrollment.batch.name} Fee",
                "category": "Enrollment",
                "amount": enrollment.total_course_fee,
                "paid_amount": display_paid,
                "actual_paid": enrollment_paid,
                "due_amount": enrollment.total_course_fee - display_paid,
                "due_date": enrollment.enrolled_on,
                "status": "PAID" if display_paid >= enrollment.total_course_fee else "PARTIAL" if display_paid > 0 else "UNPAID",
                "adjusted_credit": Decimal("0.00"),
            }
        )

    for group in additional_groups.values():
        display_paid = min(group["actual_paid"], group["amount"])
        if group["actual_paid"] > group["amount"]:
            excess_credit += group["actual_paid"] - group["amount"]
        service_rows.append(
            {
                "title": group["title"],
                "category": group["category"],
                "amount": group["amount"],
                "paid_amount": display_paid,
                "actual_paid": group["actual_paid"],
                "due_amount": group["amount"] - display_paid,
                "due_date": group["due_date"],
                "status": "PAID" if display_paid >= group["amount"] else "PARTIAL" if display_paid > 0 else "UNPAID",
                "adjusted_credit": Decimal("0.00"),
            }
        )

    for row in service_rows:
        if excess_credit <= 0:
            break
        if row["due_amount"] <= 0:
            continue
        credit = min(row["due_amount"], excess_credit)
        row["paid_amount"] += credit
        row["due_amount"] -= credit
        row["adjusted_credit"] += credit
        excess_credit -= credit

    for row in service_rows:
        if row["due_amount"] <= 0:
            row["due_amount"] = Decimal("0.00")
            row["status"] = "PAID"
        elif row["paid_amount"] > 0:
            row["status"] = "PARTIAL"
        else:
            row["status"] = "UNPAID"
        invoice_rows.append(row)

    enrollment_fee_amount = sum(enrollment.total_course_fee for enrollment in fee_enrollments)
    total_fee_amount = enrollment_fee_amount + additional_fee_amount if enrollment_fee_amount > 0 else invoiced_amount
    total_paid_amount = min(raw_paid_amount, total_fee_amount)
    overpaid_amount = raw_paid_amount - total_fee_amount
    if overpaid_amount < 0:
        overpaid_amount = Decimal("0.00")
    total_due_amount = total_fee_amount - total_paid_amount
    if total_due_amount < 0:
        total_due_amount = Decimal("0.00")

    attendance_queryset = Attendance.objects.filter(student=student, academic_session=student_session)
    attendance_total = attendance_queryset.count()
    present_count = attendance_queryset.filter(status=Attendance.Status.PRESENT).count()
    absent_count = attendance_queryset.filter(status=Attendance.Status.ABSENT).count()
    late_count = attendance_queryset.filter(status=Attendance.Status.LATE).count()
    attendance_percentage = round((present_count / attendance_total) * 100, 2) if attendance_total else 0

    context = {
        "student": student,
        "student_session": student_session,
        "primary_guardian": student.guardians.filter(is_primary=True).first() or student.guardians.first(),
        "enrollments": enrollments,
        "invoice_rows": invoice_rows,
        "payments": payments,
        "active_payment_count": payments.filter(status=Payment.Status.ACTIVE).count(),
        "all_payment_count": payments.count(),
        "payment_activities": payment_activities,
        "documents": student.documents.all(),
        "attendance_records": attendance_records,
        "total_fee_amount": total_fee_amount,
        "total_paid_amount": total_paid_amount,
        "raw_paid_amount": raw_paid_amount,
        "overpaid_amount": overpaid_amount,
        "total_due_amount": total_due_amount,
        "invoiced_amount": invoiced_amount,
        "enrollment_fee_amount": enrollment_fee_amount,
        "additional_fee_amount": additional_fee_amount,
        "attendance_total": attendance_total,
        "present_count": present_count,
        "absent_count": absent_count,
        "late_count": late_count,
        "attendance_percentage": attendance_percentage,
    }
    return render(request, "institute_admin/student_dashboard.html", context)


def get_current_session_student_or_404(request, pk, *, prefetch_documents=False):
    return get_current_session_or_404(request, pk, prefetch_documents=prefetch_documents).student


def get_current_session_or_404(request, pk, *, prefetch_documents=False):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    queryset = StudentAcademicSession.objects.select_related(
        "student",
        "student__institute",
        "student__user",
        "student__user__profile",
    )
    if prefetch_documents:
        queryset = queryset.prefetch_related("student__documents")
    if institute:
        queryset = queryset.filter(institute=institute)
    if academic_year:
        queryset = queryset.filter(academic_year=academic_year)
    return get_object_or_404(queryset, student_id=pk)


@institute_admin_required
def student_add_fee(request, pk):
    student_session = get_current_session_or_404(request, pk)
    student = student_session.student

    category_data = {
        str(category.pk): {
            "name": category.name,
            "default_amount": str(category.default_amount),
        }
        for category in FeeCategory.objects.filter(institute=student.institute, is_active=True)
    }

    if request.method == "POST":
        form = AddStudentFeeForm(request.POST, institute=student.institute)
        if form.is_valid():
            category = form.cleaned_data["category"]
            pending_invoice = (
                FeeInvoice.objects.filter(
                    student=student,
                    academic_session=student_session,
                    category=category,
                    enrollment__isnull=True,
                    status__in=[FeeInvoice.Status.UNPAID, FeeInvoice.Status.PARTIAL],
                )
                .order_by("-created_at", "-pk")
                .first()
            )
            if pending_invoice:
                pending_invoice.amount += form.cleaned_data["amount"]
                pending_invoice.title = form.cleaned_data["title"]
                pending_invoice.due_date = form.cleaned_data["due_date"]
                pending_invoice.save(update_fields=["amount", "title", "due_date"])
                refresh_invoice_status(pending_invoice)
            else:
                FeeInvoice.objects.create(
                    institute=student.institute,
                    student=student,
                    academic_session=student_session,
                    category=category,
                    title=form.cleaned_data["title"],
                    amount=form.cleaned_data["amount"],
                    due_date=form.cleaned_data["due_date"],
                    status=FeeInvoice.Status.UNPAID,
                )
            messages.success(request, "Fee added successfully.")
            return close_popup_response()
    else:
        form = AddStudentFeeForm(
            institute=student.institute,
            initial={
                "due_date": date.today(),
            },
        )

    return render(
        request,
        "institute_admin/add_student_fee_form.html",
        {
            "form": form,
            "student": student,
            "title": "Add Fee",
            "subtitle": "Add an extra charge to this student's total fees.",
            "button_text": "Add Fee",
            "category_data": category_data,
        },
    )


@institute_admin_required
def student_receive_fee(request, pk):
    student_session = get_current_session_or_404(request, pk)
    student = student_session.student

    if request.method == "POST":
        form = ReceiveFeeForm(request.POST, institute=student.institute, student=student, academic_session=student_session)
        if form.is_valid():
            with transaction.atomic():
                invoice = form.cleaned_data["existing_invoice"]
                enrollment = form.cleaned_data["enrollment"]

                if not invoice:
                    invoice = FeeInvoice.objects.create(
                        institute=student.institute,
                        student=student,
                        academic_session=student_session,
                        enrollment=enrollment,
                        batch=enrollment.batch if enrollment else None,
                        category=form.cleaned_data["category"],
                        title=form.cleaned_data["title"],
                        amount=form.cleaned_data["invoice_amount"],
                        due_date=form.cleaned_data["paid_on"],
                        status=FeeInvoice.Status.UNPAID,
                    )

                invoice_due_amount = form.get_invoice_due_amount(invoice)
                collectable_amount = invoice_due_amount
                if invoice.enrollment_id:
                    enrollment_due_amount = form.get_enrollment_due_amount(invoice.enrollment)
                    collectable_amount = min(invoice_due_amount, enrollment_due_amount)
                if form.cleaned_data["payment_amount"] > collectable_amount:
                    form.add_error("payment_amount", "Payment amount cannot be greater than remaining due amount.")
                else:
                    payment = Payment.objects.create(
                        invoice=invoice,
                        amount=form.cleaned_data["payment_amount"],
                        paid_on=form.cleaned_data["paid_on"],
                        method=form.cleaned_data["method"],
                        received_by=request.user,
                        receipt_number=form.cleaned_data["receipt_number"],
                        note=form.cleaned_data["note"],
                    )
                    if not payment.receipt_number:
                        payment.receipt_number = f"RCP-{payment.paid_on:%Y%m%d}-{payment.pk:05d}"
                        payment.save(update_fields=["receipt_number"])
                    PaymentActivity.objects.create(
                        payment=payment,
                        action=PaymentActivity.Action.CREATED,
                        performed_by=request.user,
                        new_amount=payment.amount,
                        new_method=payment.method,
                        new_receipt_number=payment.receipt_number,
                        note="Payment received.",
                    )
                    refresh_invoice_status(invoice)
                    notify_fee_paid(payment)
                    messages.success(request, "Fee payment received successfully.")
                    receipt_url = reverse("institute_admin:payment_receipt", args=[payment.pk])
                    return close_popup_response(receipt_url)
    else:
        initial = {}
        first_enrollment = student_session.enrollments.exclude(status=StudentEnrollment.Status.CANCELLED).select_related("batch").first()
        initial["paid_on"] = date.today()
        if first_enrollment:
            paid_amount = Payment.objects.filter(
                invoice__student=student,
                invoice__academic_session=student_session,
                invoice__enrollment=first_enrollment,
                status=Payment.Status.ACTIVE,
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
            remaining_amount = first_enrollment.total_course_fee - paid_amount
            if remaining_amount < 0:
                remaining_amount = Decimal("0.00")
            initial.update(
                {
                    "enrollment": first_enrollment,
                    "title": f"{first_enrollment.batch.name} Fee",
                    "invoice_amount": remaining_amount,
                    "payment_amount": remaining_amount,
                }
            )
        form = ReceiveFeeForm(institute=student.institute, student=student, academic_session=student_session, initial=initial)

    return render(
        request,
        "institute_admin/receive_fee_form.html",
        {
            "form": form,
            "student": student,
            "title": "Receive Fee",
            "subtitle": "Create or collect fee payment for this student.",
            "button_text": "Receive Payment",
            "enrollment_due_data": get_student_enrollment_due_data(student_session),
            "category_due_data": get_student_category_due_data(student_session),
        },
    )


@institute_admin_required
def payment_update(request, pk):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    queryset = Payment.objects.select_related("invoice", "invoice__student", "invoice__student__institute")
    if institute:
        queryset = queryset.filter(invoice__student__institute=institute)
    if academic_year:
        queryset = queryset.filter(invoice__academic_session__academic_year=academic_year)
    payment = get_object_or_404(queryset, pk=pk)

    if request.method == "POST":
        form = PaymentUpdateForm(request.POST, payment=payment)
        if form.is_valid():
            old_amount = payment.amount
            old_method = payment.method
            old_receipt_number = payment.receipt_number

            payment.amount = form.cleaned_data["amount"]
            payment.paid_on = form.cleaned_data["paid_on"]
            payment.method = form.cleaned_data["method"]
            payment.receipt_number = form.cleaned_data["receipt_number"]
            payment.note = form.cleaned_data["note"]
            payment.save()

            PaymentActivity.objects.create(
                payment=payment,
                action=PaymentActivity.Action.UPDATED,
                performed_by=request.user,
                old_amount=old_amount,
                new_amount=payment.amount,
                old_method=old_method,
                new_method=payment.method,
                old_receipt_number=old_receipt_number,
                new_receipt_number=payment.receipt_number,
                note=form.cleaned_data["correction_reason"],
            )
            refresh_invoice_status(payment.invoice)
            messages.success(request, "Payment corrected successfully.")
            return close_popup_response()
    else:
        form = PaymentUpdateForm(payment=payment)

    return render(
        request,
        "institute_admin/payment_update_form.html",
        {
            "form": form,
            "payment": payment,
            "title": "Correct Payment",
            "subtitle": "Update payment details with a required audit reason.",
            "button_text": "Save Correction",
        },
    )


@institute_admin_required
def payment_receipt(request, pk):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
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
    if institute:
        queryset = queryset.filter(invoice__student__institute=institute)
    if academic_year:
        queryset = queryset.filter(invoice__academic_session__academic_year=academic_year)
    payment = get_object_or_404(queryset, pk=pk)
    invoice = payment.invoice
    student = invoice.student
    student_session = invoice.academic_session
    primary_guardian = student.guardians.filter(is_primary=True).first() or student.guardians.first()
    invoice_paid_amount = (
        invoice.payments.filter(status=Payment.Status.ACTIVE).aggregate(total=Sum("amount"))["total"]
        or Decimal("0.00")
    )
    invoice_due_amount = invoice.amount - invoice_paid_amount
    if invoice_due_amount < 0:
        invoice_due_amount = Decimal("0.00")

    return render(
        request,
        "institute_admin/payment_receipt.html",
        {
            "payment": payment,
            "invoice": invoice,
            "student": student,
            "student_session": student_session,
            "guardian": primary_guardian,
            "institute": student.institute,
            "invoice_paid_amount": invoice_paid_amount,
            "invoice_due_amount": invoice_due_amount,
        },
    )


@institute_admin_required
def payment_void(request, pk):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    queryset = Payment.objects.select_related("invoice", "invoice__student", "invoice__student__institute")
    if institute:
        queryset = queryset.filter(invoice__student__institute=institute)
    if academic_year:
        queryset = queryset.filter(invoice__academic_session__academic_year=academic_year)
    payment = get_object_or_404(queryset, pk=pk)

    if request.method == "POST":
        form = PaymentVoidForm(request.POST, payment=payment)
        if form.is_valid():
            old_amount = payment.amount
            payment.void(request.user, form.cleaned_data["void_reason"])
            PaymentActivity.objects.create(
                payment=payment,
                action=PaymentActivity.Action.VOIDED,
                performed_by=request.user,
                old_amount=old_amount,
                new_amount=Decimal("0.00"),
                old_method=payment.method,
                old_receipt_number=payment.receipt_number,
                note=form.cleaned_data["void_reason"],
            )
            refresh_invoice_status(payment.invoice)
            messages.success(request, "Payment voided successfully.")
            return close_popup_response()
    else:
        form = PaymentVoidForm(payment=payment)

    return render(
        request,
        "institute_admin/payment_void_form.html",
        {
            "form": form,
            "payment": payment,
            "title": "Void Payment",
            "subtitle": "Void this payment with a required reason.",
            "button_text": "Void Payment",
        },
    )


@institute_admin_required
def student_create(request):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    if not institute:
        messages.error(request, "Select an institute before creating a student.")
        return redirect("institute_admin:student_list")

    if request.method == "POST":
        form = StudentForm(request.POST, request.FILES, institute=institute, academic_year=academic_year)
        if form.is_valid():
            form.save()
            messages.success(request, "Student created successfully.")
            return close_popup_response()
    else:
        form = StudentForm(institute=institute, academic_year=academic_year)

    return render(
        request,
        "institute_admin/student_form.html",
        {
            "form": form,
            "title": "Create Student",
            "subtitle": "Add student login, admission and parent details.",
            "button_text": "Save Student",
        },
    )


@institute_admin_required
def student_update(request, pk):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    student = get_current_session_student_or_404(request, pk)

    if request.method == "POST":
        form = StudentForm(request.POST, request.FILES, institute=student.institute, student=student, academic_year=academic_year)
        if form.is_valid():
            form.save()
            messages.success(request, "Student updated successfully.")
            return close_popup_response()
    else:
        form = StudentForm(institute=student.institute, student=student, academic_year=academic_year)

    return render(
        request,
        "institute_admin/student_form.html",
        {
            "form": form,
            "title": "Edit Student",
            "subtitle": "Update login, admission and parent details.",
            "button_text": "Update Student",
        },
    )


@institute_admin_required
def student_basic_update(request, pk):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    student = get_current_session_student_or_404(request, pk)

    if request.method == "POST":
        form = StudentBasicForm(request.POST, request.FILES, institute=student.institute, student=student, academic_year=academic_year)
        if form.is_valid():
            form.save()
            messages.success(request, "Student basic information updated successfully.")
            return close_popup_response()
    else:
        form = StudentBasicForm(institute=student.institute, student=student, academic_year=academic_year)

    return render(
        request,
        "institute_admin/student_section_form.html",
        {
            "form": form,
            "title": "Edit Student Basic Info",
            "subtitle": "Update login, admission, contact and profile image.",
            "button_text": "Save Basic Info",
            "icon": "bi-person-vcard",
        },
    )


@institute_admin_required
def student_education_update(request, pk):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    session_queryset = StudentAcademicSession.objects.select_related("student", "student__institute")
    if institute:
        session_queryset = session_queryset.filter(institute=institute)
    if academic_year:
        session_queryset = session_queryset.filter(academic_year=academic_year)
    student_session = get_object_or_404(session_queryset, student_id=pk)

    if request.method == "POST":
        form = StudentEducationForm(request.POST, instance=student_session)
        if form.is_valid():
            form.save()
            messages.success(request, "Education details updated successfully.")
            return close_popup_response()
    else:
        form = StudentEducationForm(instance=student_session)

    return render(
        request,
        "institute_admin/student_section_form.html",
        {
            "form": form,
            "title": "Edit Education Details",
            "subtitle": "Update school or college information for this student.",
            "button_text": "Save Education",
            "icon": "bi-building",
        },
    )


@institute_admin_required
def student_guardian_update(request, pk):
    student = get_current_session_student_or_404(request, pk)

    if request.method == "POST":
        form = StudentGuardianForm(request.POST, student=student)
        if form.is_valid():
            form.save()
            messages.success(request, "Guardian details updated successfully.")
            return close_popup_response()
    else:
        form = StudentGuardianForm(student=student)

    return render(
        request,
        "institute_admin/student_section_form.html",
        {
            "form": form,
            "title": "Edit Parent / Guardian",
            "subtitle": "Update the primary guardian contact for this student.",
            "button_text": "Save Guardian",
            "icon": "bi-person-hearts",
        },
    )


@institute_admin_required
def student_document_upload(request, pk):
    student = get_current_session_student_or_404(request, pk)

    if request.method == "POST":
        form = StudentDocumentUploadForm(request.POST, request.FILES, student=student)
        if form.is_valid():
            documents = form.save()
            messages.success(request, f"{len(documents)} document(s) uploaded successfully.")
            return close_popup_response()
    else:
        form = StudentDocumentUploadForm(student=student)

    return render(
        request,
        "institute_admin/student_section_form.html",
        {
            "form": form,
            "title": "Upload Student Documents",
            "subtitle": "Select one or more files to upload for this student.",
            "button_text": "Upload Documents",
            "icon": "bi-file-earmark-arrow-up",
        },
    )


@institute_admin_required
def student_document_delete(request, pk):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    queryset = StudentDocument.objects.select_related("student", "student__institute")
    if institute:
        queryset = queryset.filter(student__institute=institute)
    if academic_year:
        queryset = queryset.filter(student__academic_sessions__academic_year=academic_year)
    document = get_object_or_404(queryset, pk=pk)
    student = document.student

    if request.method == "POST":
        if document.file:
            document.file.delete(save=False)
        document.delete()
        messages.success(request, "Student document deleted successfully.")

    return redirect("institute_admin:student_dashboard", pk=student.pk)


@institute_admin_required
def student_delete(request, pk):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    queryset = StudentAcademicSession.objects.select_related("student", "student__user")
    if institute:
        queryset = queryset.filter(institute=institute)
    if academic_year:
        queryset = queryset.filter(academic_year=academic_year)
    student_session = get_object_or_404(queryset, student_id=pk)
    student = student_session.student

    if request.method == "POST":
        if student_session.fee_invoices.exists():
            messages.error(request, "This student has fee invoices. Mark inactive instead of deleting.")
        else:
            student.user.delete()
            messages.success(request, "Student deleted successfully.")

    return redirect("institute_admin:student_list")


@institute_admin_required
def enrollment_list(request):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    enrollments = StudentEnrollment.objects.select_related(
        "academic_session", "student", "student__user", "batch"
    ).prefetch_related("courses")
    if institute:
        enrollments = enrollments.filter(student__institute=institute)
    if academic_year:
        enrollments = enrollments.filter(academic_session__academic_year=academic_year)

    search_query = request.GET.get("search", "").strip()
    batch_filter = request.GET.get("batch", "").strip()
    status_filter = request.GET.get("status", "").strip()

    if search_query:
        enrollments = enrollments.filter(
            Q(academic_session__admission_number__icontains=search_query)
            | Q(student__user__first_name__icontains=search_query)
            | Q(student__user__last_name__icontains=search_query)
            | Q(batch__name__icontains=search_query)
            | Q(courses__name__icontains=search_query)
        ).distinct()

    if batch_filter:
        enrollments = enrollments.filter(batch_id=batch_filter)

    if status_filter:
        enrollments = enrollments.filter(status=status_filter)

    batch_queryset = Batch.objects.filter(institute=institute) if institute else Batch.objects.all()
    base_queryset = StudentEnrollment.objects.filter(student__institute=institute) if institute else StudentEnrollment.objects.all()
    if academic_year:
        base_queryset = base_queryset.filter(academic_session__academic_year=academic_year)

    context = {
        "enrollments": enrollments,
        "batches": batch_queryset,
        "status_choices": StudentEnrollment.Status.choices,
        "search_query": search_query,
        "batch_filter": batch_filter,
        "status_filter": status_filter,
        "total_enrollments": base_queryset.count(),
        "active_enrollments": base_queryset.filter(status=StudentEnrollment.Status.ACTIVE).count(),
        "completed_enrollments": base_queryset.filter(status=StudentEnrollment.Status.COMPLETED).count(),
        "cancelled_enrollments": base_queryset.filter(status=StudentEnrollment.Status.CANCELLED).count(),
    }
    return render(request, "institute_admin/enrollment_list.html", context)


@institute_admin_required
def enrollment_create(request):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    if not institute:
        messages.error(request, "Select an institute before creating an enrollment.")
        return redirect("institute_admin:enrollment_list")

    initial = {}
    student_id = request.GET.get("student")
    if student_id:
        initial["student"] = student_id

    if request.method == "POST":
        form = StudentEnrollmentForm(request.POST, institute=institute, academic_year=academic_year)
        if form.is_valid():
            enrollment = form.save(commit=False)
            enrollment.academic_session = get_object_or_404(
                StudentAcademicSession,
                institute=institute,
                academic_year=academic_year,
                student=enrollment.student,
            )
            enrollment.save()
            form.save_m2m()
            messages.success(request, "Enrollment created successfully.")
            return close_popup_response()
    else:
        form = StudentEnrollmentForm(institute=institute, academic_year=academic_year, initial=initial)

    return render(
        request,
        "institute_admin/enrollment_form.html",
        {
            "form": form,
            "title": "Create Enrollment",
            "subtitle": "Assign student to a batch and select courses.",
            "button_text": "Save Enrollment",
            "batch_course_data": get_batch_course_data(institute, academic_year),
        },
    )


@institute_admin_required
def enrollment_update(request, pk):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    queryset = StudentEnrollment.objects.select_related("academic_session", "student", "batch")
    if institute:
        queryset = queryset.filter(student__institute=institute)
    if academic_year:
        queryset = queryset.filter(academic_session__academic_year=academic_year)
    enrollment = get_object_or_404(queryset, pk=pk)

    if request.method == "POST":
        form = StudentEnrollmentForm(request.POST, institute=enrollment.student.institute, academic_year=academic_year, instance=enrollment)
        if form.is_valid():
            updated_enrollment = form.save(commit=False)
            updated_enrollment.academic_session = get_object_or_404(
                StudentAcademicSession,
                institute=enrollment.student.institute,
                academic_year=academic_year,
                student=updated_enrollment.student,
            )
            updated_enrollment.save()
            form.save_m2m()
            messages.success(request, "Enrollment updated successfully.")
            return close_popup_response()
    else:
        form = StudentEnrollmentForm(institute=enrollment.student.institute, academic_year=academic_year, instance=enrollment)

    return render(
        request,
        "institute_admin/enrollment_form.html",
        {
            "form": form,
            "title": "Edit Enrollment",
            "subtitle": "Update batch, courses, status or custom fee.",
            "button_text": "Update Enrollment",
            "batch_course_data": get_batch_course_data(enrollment.student.institute, academic_year),
        },
    )


@institute_admin_required
def enrollment_delete(request, pk):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    queryset = StudentEnrollment.objects.select_related("academic_session", "student")
    if institute:
        queryset = queryset.filter(student__institute=institute)
    if academic_year:
        queryset = queryset.filter(academic_session__academic_year=academic_year)
    enrollment = get_object_or_404(queryset, pk=pk)

    if request.method == "POST":
        if enrollment.fee_invoices.exists():
            messages.error(request, "This enrollment has fee invoices. Cancel it instead of deleting.")
        else:
            enrollment.delete()
            messages.success(request, "Enrollment deleted successfully.")

    return redirect("institute_admin:enrollment_list")


@institute_admin_required
def homework_list(request):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    homework = Homework.objects.select_related("batch", "subject", "course", "created_by").prefetch_related("attachments")
    if institute:
        homework = homework.filter(batch__institute=institute)
    if academic_year:
        homework = homework.filter(batch__academic_year=academic_year)

    search_query = request.GET.get("search", "").strip()
    batch_filter = request.GET.get("batch", "").strip()
    subject_filter = request.GET.get("subject", "").strip()
    course_filter = request.GET.get("course", "").strip()

    if search_query:
        homework = homework.filter(
            Q(title__icontains=search_query)
            | Q(instructions__icontains=search_query)
            | Q(batch__name__icontains=search_query)
            | Q(subject__name__icontains=search_query)
            | Q(course__name__icontains=search_query)
        )
    if batch_filter:
        homework = homework.filter(batch_id=batch_filter)
    if subject_filter:
        homework = homework.filter(subject_id=subject_filter)
    if course_filter:
        homework = homework.filter(course_id=course_filter)

    base_queryset = Homework.objects.filter(batch__institute=institute) if institute else Homework.objects.all()
    batch_queryset = Batch.objects.filter(institute=institute, is_active=True) if institute else Batch.objects.none()
    subject_queryset = Subject.objects.filter(institute=institute, is_active=True) if institute else Subject.objects.none()
    course_queryset = Course.objects.filter(institute=institute, is_active=True) if institute else Course.objects.none()
    if academic_year:
        base_queryset = base_queryset.filter(batch__academic_year=academic_year)
        batch_queryset = batch_queryset.filter(academic_year=academic_year)
        subject_queryset = subject_queryset.filter(academic_year=academic_year)
        course_queryset = course_queryset.filter(academic_year=academic_year)

    context = {
        "homework_list": homework,
        "batches": batch_queryset,
        "subjects": subject_queryset,
        "courses": course_queryset,
        "search_query": search_query,
        "batch_filter": batch_filter,
        "subject_filter": subject_filter,
        "course_filter": course_filter,
        "today": date.today(),
        "total_homework": base_queryset.count(),
        "due_homework": base_queryset.filter(due_date__gte=date.today()).count(),
        "expired_homework": base_queryset.filter(due_date__lt=date.today()).count(),
        "subject_count": subject_queryset.count(),
    }
    return render(request, "institute_admin/homework_list.html", context)


@institute_admin_required
def homework_create(request):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    if not institute:
        messages.error(request, "Select an institute before creating homework.")
        return redirect("institute_admin:homework_list")

    if request.method == "POST":
        form = HomeworkForm(request.POST, request.FILES, institute=institute, academic_year=academic_year)
        if form.is_valid():
            homework = form.save(commit=False)
            homework.created_by = request.user
            homework.save()
            form.save_attachments(homework)
            messages.success(request, "Homework created successfully.")
            return close_popup_response()
    else:
        form = HomeworkForm(institute=institute, academic_year=academic_year)

    return render(
        request,
        "institute_admin/homework_form.html",
        {
            "form": form,
            "title": "Create Homework",
            "subtitle": "Assign work to a batch with separate subject and course details.",
            "button_text": "Save Homework",
            "batch_course_data": get_batch_course_data(institute, academic_year),
            "attachments": [],
        },
    )


@institute_admin_required
def homework_update(request, pk):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    queryset = Homework.objects.select_related("batch", "subject", "course")
    if institute:
        queryset = queryset.filter(batch__institute=institute)
    if academic_year:
        queryset = queryset.filter(batch__academic_year=academic_year)
    homework = get_object_or_404(queryset, pk=pk)

    if request.method == "POST":
        form = HomeworkForm(
            request.POST,
            request.FILES,
            institute=homework.batch.institute,
            academic_year=homework.batch.academic_year,
            instance=homework,
        )
        if form.is_valid():
            homework = form.save()
            form.save_attachments(homework)
            messages.success(request, "Homework updated successfully.")
            return close_popup_response()
    else:
        form = HomeworkForm(institute=homework.batch.institute, academic_year=homework.batch.academic_year, instance=homework)

    return render(
        request,
        "institute_admin/homework_form.html",
        {
            "form": form,
            "title": "Edit Homework",
            "subtitle": "Update batch, subject, course, instructions and due date.",
            "button_text": "Update Homework",
            "batch_course_data": get_batch_course_data(homework.batch.institute, homework.batch.academic_year),
            "attachments": homework.attachments.all(),
        },
    )


@institute_admin_required
def homework_delete(request, pk):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    queryset = Homework.objects.select_related("batch")
    if institute:
        queryset = queryset.filter(batch__institute=institute)
    if academic_year:
        queryset = queryset.filter(batch__academic_year=academic_year)
    homework = get_object_or_404(queryset, pk=pk)

    if request.method == "POST":
        homework.delete()
        messages.success(request, "Homework deleted successfully.")

    return redirect("institute_admin:homework_list")


@institute_admin_required
def notice_list(request):
    institute = get_current_institute(request)
    notices = Notice.objects.select_related("created_by").prefetch_related(
        "target_batches",
        "target_courses",
        "target_students",
        "read_receipts",
    )
    if institute:
        notices = notices.filter(institute=institute)

    search_query = request.GET.get("search", "").strip()
    audience_filter = request.GET.get("audience", "").strip()
    category_filter = request.GET.get("category", "").strip()
    status_filter = request.GET.get("status", "").strip()

    if search_query:
        notices = notices.filter(Q(title__icontains=search_query) | Q(message__icontains=search_query))
    if audience_filter:
        notices = notices.filter(audience=audience_filter)
    if category_filter:
        notices = notices.filter(category=category_filter)

    now = timezone.now()
    if status_filter == "published":
        notices = notices.filter(is_published=True).filter(Q(publish_at__isnull=True) | Q(publish_at__lte=now)).filter(Q(expires_at__isnull=True) | Q(expires_at__gte=now))
    elif status_filter == "scheduled":
        notices = notices.filter(is_published=True, publish_at__gt=now)
    elif status_filter == "expired":
        notices = notices.filter(expires_at__lt=now)
    elif status_filter == "draft":
        notices = notices.filter(is_published=False)

    base_queryset = Notice.objects.filter(institute=institute) if institute else Notice.objects.all()
    paginator = Paginator(notices, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = {
        "notice_list": page_obj,
        "page_obj": page_obj,
        "search_query": search_query,
        "audience_filter": audience_filter,
        "category_filter": category_filter,
        "status_filter": status_filter,
        "audience_choices": Notice.Audience.choices,
        "category_choices": Notice.Category.choices,
        "now": now,
        "total_notices": base_queryset.count(),
        "active_notices": base_queryset.filter(is_published=True).filter(Q(publish_at__isnull=True) | Q(publish_at__lte=now)).filter(Q(expires_at__isnull=True) | Q(expires_at__gte=now)).count(),
        "scheduled_notices": base_queryset.filter(is_published=True, publish_at__gt=now).count(),
        "app_notices": base_queryset.filter(push_to_app=True).count(),
    }
    return render(request, "institute_admin/notice_list.html", context)


@institute_admin_required
def notice_create(request):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    if not institute:
        messages.error(request, "Select an institute before creating a notice.")
        return redirect("institute_admin:notice_list")

    if request.method == "POST":
        form = NoticeForm(request.POST, institute=institute, academic_year=academic_year)
        if form.is_valid():
            notice = form.save(commit=False)
            notice.institute = institute
            notice.created_by = request.user
            notice.save()
            form.save_m2m()
            notify_notice_published(notice)
            messages.success(request, "Notice created successfully.")
            return close_popup_response()
    else:
        form = NoticeForm(institute=institute, academic_year=academic_year)

    return render(
        request,
        "institute_admin/notice_form.html",
        {
            "form": form,
            "title": "Create Notice",
            "subtitle": "Publish announcements for web records and the future student/parent app.",
            "button_text": "Publish Notice",
        },
    )


@institute_admin_required
def notice_update(request, pk):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    queryset = Notice.objects.prefetch_related("target_batches", "target_courses", "target_students")
    if institute:
        queryset = queryset.filter(institute=institute)
    notice = get_object_or_404(queryset, pk=pk)

    if request.method == "POST":
        form = NoticeForm(request.POST, institute=notice.institute, academic_year=academic_year, instance=notice)
        if form.is_valid():
            form.save()
            messages.success(request, "Notice updated successfully.")
            return close_popup_response()
    else:
        form = NoticeForm(institute=notice.institute, academic_year=academic_year, instance=notice)

    return render(
        request,
        "institute_admin/notice_form.html",
        {
            "form": form,
            "title": "Edit Notice",
            "subtitle": "Adjust targeting, schedule, priority and app visibility.",
            "button_text": "Update Notice",
        },
    )


@institute_admin_required
def notice_delete(request, pk):
    institute = get_current_institute(request)
    queryset = Notice.objects.all()
    if institute:
        queryset = queryset.filter(institute=institute)
    notice = get_object_or_404(queryset, pk=pk)

    if request.method == "POST":
        notice.delete()
        messages.success(request, "Notice deleted successfully.")

    return redirect("institute_admin:notice_list")


@institute_admin_required
def attendance_list(request):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    selected_date = parse_date(request.GET.get("date", "")) or date.today()
    batch_id = request.GET.get("batch", "").strip()

    batch_queryset = Batch.objects.filter(is_active=True).prefetch_related("courses")
    if institute:
        batch_queryset = batch_queryset.filter(institute=institute)
    if academic_year:
        batch_queryset = batch_queryset.filter(academic_year=academic_year)
    selected_batch = batch_queryset.filter(pk=batch_id).first() if batch_id else batch_queryset.first()

    student_sessions = StudentAcademicSession.objects.none()
    export_student_sessions = StudentAcademicSession.objects.filter(
        status=StudentAcademicSession.Status.ACTIVE,
        student__is_active=True,
    ).select_related("student", "student__user")
    if institute:
        export_student_sessions = export_student_sessions.filter(institute=institute)
    if academic_year:
        export_student_sessions = export_student_sessions.filter(academic_year=academic_year)
    export_student_sessions = export_student_sessions.order_by(
        "admission_number", "student__user__first_name", "student__user__username"
    )
    attendance_map = {}
    if selected_batch:
        student_sessions = (
            StudentAcademicSession.objects.filter(
                enrollments__batch=selected_batch,
                enrollments__status=StudentEnrollment.Status.ACTIVE,
                student__is_active=True,
                academic_year=academic_year,
            )
            .select_related("student", "student__user")
            .order_by("admission_number", "student__user__first_name", "student__user__username")
            .distinct()
        )
        existing_attendance = Attendance.objects.filter(
            batch=selected_batch,
            date=selected_date,
            academic_session__in=student_sessions,
        ).select_related("academic_session", "student", "marked_by")
        attendance_map = {record.academic_session_id: record for record in existing_attendance}

    if request.method == "POST" and selected_batch:
        posted_student_ids = request.POST.getlist("student_ids")
        saved_count = 0
        for student_id in posted_student_ids:
            status = request.POST.get(f"status_{student_id}", Attendance.Status.PRESENT)
            note = request.POST.get(f"note_{student_id}", "").strip()
            if status not in Attendance.Status.values:
                status = Attendance.Status.PRESENT
            student_session = student_sessions.filter(student_id=student_id).first()
            if not student_session:
                continue
            Attendance.objects.update_or_create(
                academic_session=student_session,
                batch=selected_batch,
                date=selected_date,
                defaults={
                    "student": student_session.student,
                    "status": status,
                    "note": note,
                    "marked_by": request.user,
                },
            )
            saved_count += 1
        messages.success(request, f"Attendance saved for {saved_count} student(s).")
        return redirect(f"{reverse('institute_admin:attendance_list')}?batch={selected_batch.pk}&date={selected_date.isoformat()}")

    selected_date_records = Attendance.objects.filter(date=selected_date)
    all_records = Attendance.objects.all()
    if institute:
        selected_date_records = selected_date_records.filter(batch__institute=institute)
        all_records = all_records.filter(batch__institute=institute)
    if academic_year:
        selected_date_records = selected_date_records.filter(academic_session__academic_year=academic_year)
        all_records = all_records.filter(academic_session__academic_year=academic_year)
        all_records = all_records.filter(batch__academic_year=academic_year)
    if selected_batch:
        selected_date_records = selected_date_records.filter(batch=selected_batch)

    total_today = selected_date_records.count()
    present_today = selected_date_records.filter(status=Attendance.Status.PRESENT).count()
    absent_today = selected_date_records.filter(status=Attendance.Status.ABSENT).count()
    late_today = selected_date_records.filter(status=Attendance.Status.LATE).count()
    rate_today = round((present_today / total_today) * 100, 1) if total_today else 0

    rows = []
    for student_session in student_sessions:
        record = attendance_map.get(student_session.pk)
        rows.append(
            {
                "student": student_session.student,
                "student_session": student_session,
                "record": record,
                "status": record.status if record else Attendance.Status.PRESENT,
                "note": record.note if record else "",
            }
        )

    context = {
        "batches": batch_queryset,
        "selected_batch": selected_batch,
        "selected_date": selected_date,
        "attendance_rows": rows,
        "export_students": export_student_sessions,
        "status_choices": Attendance.Status.choices,
        "present_value": Attendance.Status.PRESENT,
        "absent_value": Attendance.Status.ABSENT,
        "late_value": Attendance.Status.LATE,
        "total_students": student_sessions.count() if selected_batch else 0,
        "marked_count": len(attendance_map),
        "total_today": total_today,
        "present_today": present_today,
        "absent_today": absent_today,
        "late_today": late_today,
        "rate_today": rate_today,
        "recent_attendance": all_records.select_related("student", "student__user", "batch", "marked_by")[:8],
    }
    return render(request, "institute_admin/attendance_list.html", context)


def get_attendance_export_queryset(request, institute, academic_year=None):
    records = Attendance.objects.select_related(
        "academic_session", "student", "student__user", "batch", "marked_by"
    )
    if institute:
        records = records.filter(batch__institute=institute)
    if academic_year:
        records = records.filter(academic_session__academic_year=academic_year)

    batch_id = request.GET.get("batch", "").strip()
    student_id = request.GET.get("student", "").strip()
    status = request.GET.get("status", "").strip()
    date_from = parse_date(request.GET.get("date_from", ""))
    date_to = parse_date(request.GET.get("date_to", ""))

    if batch_id:
        records = records.filter(batch_id=batch_id)
    if student_id:
        records = records.filter(student_id=student_id)
    if status in Attendance.Status.values:
        records = records.filter(status=status)
    if date_from:
        records = records.filter(date__gte=date_from)
    if date_to:
        records = records.filter(date__lte=date_to)

    return records.order_by("-date", "batch__name", "academic_session__admission_number")


def attendance_export_filename(file_format):
    stamp = timezone.now().strftime("%Y%m%d_%H%M")
    extension = "xlsx" if file_format == "excel" else "pdf"
    return f"attendance_report_{stamp}.{extension}"


def attendance_status_counts(records):
    total = len(records)
    present = sum(1 for record in records if record.status == Attendance.Status.PRESENT)
    absent = sum(1 for record in records if record.status == Attendance.Status.ABSENT)
    late = sum(1 for record in records if record.status == Attendance.Status.LATE)
    rate = round((present / total) * 100, 1) if total else 0
    return total, present, absent, late, rate


def build_attendance_excel(records, institute, filters, include_notes=True):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Attendance"

    primary = "2563EB"
    dark = "0F172A"
    muted = "64748B"
    light_blue = "DBEAFE"
    light_green = "DCFCE7"
    light_red = "FEE2E2"
    light_amber = "FEF3C7"
    border_color = "CBD5E1"

    thin = Side(style="thin", color=border_color)
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center", vertical="center")
    left = Alignment(horizontal="left", vertical="center")

    columns = ["Date", "Admission No", "Student Name", "Batch", "Status", "Marked By"]
    if include_notes:
        columns.append("Note")

    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(columns))
    title_cell = sheet.cell(row=1, column=1, value="Attendance Report")
    title_cell.font = Font(size=18, bold=True, color="FFFFFF")
    title_cell.fill = PatternFill("solid", fgColor=primary)
    title_cell.alignment = center
    sheet.row_dimensions[1].height = 30

    sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(columns))
    institute_name = getattr(institute, "name", "All Institutes") if institute else "All Institutes"
    sheet.cell(row=2, column=1, value=f"{institute_name} | Generated {timezone.now().strftime('%d-%m-%Y %I:%M %p')}").font = Font(size=10, color=muted)
    sheet.cell(row=2, column=1).alignment = center

    total, present, absent, late, rate = attendance_status_counts(records)
    summary = [
        ("Total", total, light_blue),
        ("Present", present, light_green),
        ("Absent", absent, light_red),
        ("Late", late, light_amber),
        ("Rate", f"{rate}%", light_blue),
    ]
    col = 1
    for label, value, fill in summary:
        sheet.cell(row=4, column=col, value=label).font = Font(bold=True, color=dark)
        sheet.cell(row=4, column=col).fill = PatternFill("solid", fgColor=fill)
        sheet.cell(row=4, column=col).alignment = center
        sheet.cell(row=4, column=col).border = border
        sheet.cell(row=5, column=col, value=value).font = Font(size=14, bold=True, color=dark)
        sheet.cell(row=5, column=col).alignment = center
        sheet.cell(row=5, column=col).border = border
        col += 1

    filter_text = " | ".join(part for part in filters if part)
    sheet.merge_cells(start_row=7, start_column=1, end_row=7, end_column=len(columns))
    sheet.cell(row=7, column=1, value=f"Filters: {filter_text or 'All records'}").font = Font(italic=True, color=muted)

    header_row = 9
    for index, column in enumerate(columns, start=1):
        cell = sheet.cell(row=header_row, column=index, value=column)
        cell.fill = PatternFill("solid", fgColor=dark)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.alignment = center
        cell.border = border

    status_fills = {
        Attendance.Status.PRESENT: light_green,
        Attendance.Status.ABSENT: light_red,
        Attendance.Status.LATE: light_amber,
    }
    for row_index, record in enumerate(records, start=header_row + 1):
        values = [
            record.date.strftime("%d-%m-%Y"),
            record.academic_session.admission_number,
            record.student.user.get_full_name() or record.student.user.username,
            record.batch.name,
            record.get_status_display(),
            record.marked_by.get_full_name() if record.marked_by else "Not set",
        ]
        if include_notes:
            values.append(record.note or "")
        for col_index, value in enumerate(values, start=1):
            cell = sheet.cell(row=row_index, column=col_index, value=value)
            cell.border = border
            cell.alignment = left if col_index in (3, 4, len(values)) else center
            if col_index == 5:
                cell.fill = PatternFill("solid", fgColor=status_fills.get(record.status, "F8FAFC"))
                cell.font = Font(bold=True, color=dark)

    widths = [14, 16, 28, 24, 14, 24, 34]
    for index, width in enumerate(widths[: len(columns)], start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = "A10"
    sheet.auto_filter.ref = f"A9:{get_column_letter(len(columns))}{max(10, header_row + len(records))}"

    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()


def pdf_escape(value):
    return str(value).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def pdf_text(x, y, text, size=9, font="F1", color="0 0 0"):
    return f"{color} rg BT /{font} {size} Tf {x} {y} Td ({pdf_escape(text)}) Tj ET\n"


def pdf_rect(x, y, w, h, color):
    return f"{color} rg {x} {y} {w} {h} re f\n"


def build_pdf_document(page_streams, width=842, height=595):
    objects = ["<< /Type /Catalog /Pages 2 0 R >>"]
    kids = []
    current_id = 3
    for stream in page_streams:
        page_id = current_id
        content_id = current_id + 1
        kids.append(f"{page_id} 0 R")
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] /Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> /F2 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >> >> >> /Contents {content_id} 0 R >>")
        encoded = stream.encode("latin-1", errors="replace")
        objects.append(f"<< /Length {len(encoded)} >>\nstream\n{stream}endstream")
        current_id += 2
    objects.insert(1, f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>")

    output = "%PDF-1.4\n"
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output.encode("latin-1", errors="replace")))
        output += f"{index} 0 obj\n{obj}\nendobj\n"
    xref_offset = len(output.encode("latin-1", errors="replace"))
    output += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    for offset in offsets[1:]:
        output += f"{offset:010d} 00000 n \n"
    output += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF"
    return output.encode("latin-1", errors="replace")


def build_attendance_pdf(records, institute, filters, include_notes=True, title="Attendance Report"):
    width, height = 842, 595
    rows_per_page = 18 if include_notes else 22
    pages = []
    total, present, absent, late, rate = attendance_status_counts(records)
    institute_name = getattr(institute, "name", "All Institutes") if institute else "All Institutes"
    chunks = [records[index:index + rows_per_page] for index in range(0, len(records), rows_per_page)] or [[]]

    for page_number, chunk in enumerate(chunks, start=1):
        stream = ""
        stream += pdf_rect(0, 545, width, 50, "0.145 0.388 0.922")
        stream += pdf_text(34, 570, title, 18, "F2", "1 1 1")
        stream += pdf_text(34, 552, f"{institute_name} | Generated {timezone.now().strftime('%d-%m-%Y %I:%M %p')}", 8, "F1", "1 1 1")
        stream += pdf_text(700, 552, f"Page {page_number} of {len(chunks)}", 8, "F1", "1 1 1")

        summary = [("Total", total), ("Present", present), ("Absent", absent), ("Late", late), ("Rate", f"{rate}%")]
        x = 34
        for label, value in summary:
            stream += pdf_rect(x, 500, 128, 32, "0.93 0.96 1")
            stream += pdf_text(x + 8, 519, label, 7, "F1", "0.39 0.45 0.55")
            stream += pdf_text(x + 8, 506, value, 12, "F2", "0.06 0.09 0.16")
            x += 138

        filter_text = " | ".join(part for part in filters if part) or "All records"
        stream += pdf_text(34, 480, f"Filters: {filter_text[:135]}", 8, "F1", "0.39 0.45 0.55")

        headers = ["Date", "Adm No", "Student", "Batch", "Status", "Marked By"]
        widths = [68, 76, 168, 142, 76, 126]
        if include_notes:
            headers.append("Note")
            widths.append(118)
        start_x = 34
        y = 452
        stream += pdf_rect(start_x, y - 6, sum(widths), 22, "0.06 0.09 0.16")
        x = start_x
        for header, col_width in zip(headers, widths):
            stream += pdf_text(x + 4, y, header, 8, "F2", "1 1 1")
            x += col_width
        y -= 24

        for record in chunk:
            status_color = "0.86 0.99 0.91" if record.status == Attendance.Status.PRESENT else "1 0.89 0.89" if record.status == Attendance.Status.ABSENT else "1 0.95 0.78"
            stream += pdf_rect(start_x, y - 5, sum(widths), 20, "0.98 0.99 1")
            row_values = [
                record.date.strftime("%d-%m-%Y"),
                record.academic_session.admission_number,
                (record.student.user.get_full_name() or record.student.user.username)[:28],
                record.batch.name[:22],
                record.get_status_display(),
                (record.marked_by.get_full_name() if record.marked_by else "Not set")[:20],
            ]
            if include_notes:
                row_values.append((record.note or "")[:24])
            x = start_x
            for index, (value, col_width) in enumerate(zip(row_values, widths)):
                if index == 4:
                    stream += pdf_rect(x + 2, y - 3, col_width - 4, 15, status_color)
                    stream += pdf_text(x + 5, y, value, 7, "F2", "0.06 0.09 0.16")
                else:
                    stream += pdf_text(x + 4, y, value, 7, "F1", "0.06 0.09 0.16")
                x += col_width
            y -= 21

        stream += pdf_text(34, 28, "UltraCoachMatrix attendance export", 8, "F1", "0.39 0.45 0.55")
        pages.append(stream)

    return build_pdf_document(pages, width=width, height=height)


@institute_admin_required
def attendance_export(request):
    institute = get_current_institute(request)
    academic_year = get_current_academic_year(request, institute)
    file_format = request.GET.get("format", "excel").strip()
    include_notes = request.GET.get("include_notes", "1") == "1"
    records = list(get_attendance_export_queryset(request, institute, academic_year))

    batch_label = "All Batches"
    batch_id = request.GET.get("batch", "").strip()
    if batch_id:
        batch_queryset = Batch.objects.filter(pk=batch_id)
        if institute:
            batch_queryset = batch_queryset.filter(institute=institute)
        if academic_year:
            batch_queryset = batch_queryset.filter(academic_year=academic_year)
        batch = batch_queryset.first()
        batch_label = batch.name if batch else batch_label
    student_label = "All Students"
    student_id = request.GET.get("student", "").strip()
    if student_id:
        session_queryset = StudentAcademicSession.objects.select_related("student", "student__user")
        if institute:
            session_queryset = session_queryset.filter(institute=institute)
        if academic_year:
            session_queryset = session_queryset.filter(academic_year=academic_year)
        student_session = session_queryset.filter(student_id=student_id).first()
        if student_session:
            student_label = str(student_session)
    status_value = request.GET.get("status", "").strip()
    status_label = dict(Attendance.Status.choices).get(status_value, "All Status")
    filters = [
        f"Batch: {batch_label}",
        f"Student: {student_label}",
        f"Status: {status_label}",
        f"From: {request.GET.get('date_from') or 'Any'}",
        f"To: {request.GET.get('date_to') or 'Any'}",
    ]

    if file_format == "pdf":
        content = build_attendance_pdf(records, institute, filters, include_notes=include_notes)
        response = HttpResponse(content, content_type="application/pdf")
    else:
        content = build_attendance_excel(records, institute, filters, include_notes=include_notes)
        response = HttpResponse(
            content,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        file_format = "excel"
    response["Content-Disposition"] = f'attachment; filename="{attendance_export_filename(file_format)}"'
    return response


@institute_admin_required
def teacher_list(request):
    institute = get_current_institute(request)
    teachers = TeacherProfile.objects.select_related("institute", "user", "user__profile")
    if institute:
        teachers = teachers.filter(institute=institute)
    teachers = teachers.filter(user__profile__role=UserProfile.Role.TEACHER)

    search_query = request.GET.get("search", "").strip()
    teacher_type_filter = request.GET.get("teacher_type", "").strip()
    status_filter = request.GET.get("status", "").strip()

    if search_query:
        teachers = teachers.filter(
            Q(user__first_name__icontains=search_query)
            | Q(user__last_name__icontains=search_query)
            | Q(user__username__icontains=search_query)
            | Q(user__email__icontains=search_query)
            | Q(employee_id__icontains=search_query)
            | Q(specialization__icontains=search_query)
            | Q(user__profile__phone__icontains=search_query)
        )

    if teacher_type_filter:
        teachers = teachers.filter(teacher_type=teacher_type_filter)

    if status_filter == "active":
        teachers = teachers.filter(is_active=True)
    elif status_filter == "inactive":
        teachers = teachers.filter(is_active=False)

    base_queryset = TeacherProfile.objects.filter(institute=institute) if institute else TeacherProfile.objects.all()
    context = {
        "teachers": teachers,
        "search_query": search_query,
        "teacher_type_filter": teacher_type_filter,
        "status_filter": status_filter,
        "total_teachers": base_queryset.count(),
        "active_teachers": base_queryset.filter(is_active=True).count(),
        "full_time_teachers": base_queryset.filter(teacher_type=TeacherProfile.TeacherType.FULL_TIME).count(),
        "part_time_teachers": base_queryset.filter(teacher_type=TeacherProfile.TeacherType.PART_TIME).count(),
    }
    return render(request, "institute_admin/teacher_list.html", context)


@institute_admin_required
def teacher_create(request):
    institute = get_current_institute(request)
    if not institute:
        messages.error(request, "Select an institute before creating a teacher.")
        return redirect("institute_admin:teacher_list")

    if request.method == "POST":
        form = TeacherForm(request.POST, institute=institute)
        if form.is_valid():
            form.save()
            messages.success(request, "Teacher created successfully.")
            return close_popup_response()
    else:
        form = TeacherForm(institute=institute)

    return render(
        request,
        "institute_admin/teacher_form.html",
        {
            "form": form,
            "title": "Create Teacher",
            "subtitle": "Add teacher identity, contact and workload details.",
            "button_text": "Save Teacher",
        },
    )


@institute_admin_required
def teacher_update(request, pk):
    institute = get_current_institute(request)
    queryset = TeacherProfile.objects.select_related("user", "institute")
    if institute:
        queryset = queryset.filter(institute=institute)
    teacher = get_object_or_404(queryset, pk=pk)

    if request.method == "POST":
        form = TeacherForm(request.POST, institute=teacher.institute, teacher=teacher)
        if form.is_valid():
            form.save()
            messages.success(request, "Teacher updated successfully.")
            return close_popup_response()
    else:
        form = TeacherForm(institute=teacher.institute, teacher=teacher)

    return render(
        request,
        "institute_admin/teacher_form.html",
        {
            "form": form,
            "title": "Edit Teacher",
            "subtitle": "Update teacher identity, contact and workload details.",
            "button_text": "Update Teacher",
        },
    )


@institute_admin_required
def teacher_delete(request, pk):
    institute = get_current_institute(request)
    queryset = TeacherProfile.objects.select_related("user")
    if institute:
        queryset = queryset.filter(institute=institute)
    teacher = get_object_or_404(queryset, pk=pk)

    if request.method == "POST":
        if teacher.user.assigned_batches.exists():
            messages.error(request, "This teacher is assigned to batches. Remove them from batches before deleting.")
        else:
            teacher.user.delete()
            messages.success(request, "Teacher deleted successfully.")

    return redirect("institute_admin:teacher_list")
















BULK_QUESTION_HEADERS = [
    "Question Text",
    "Option A",
    "Option B",
    "Option C",
    "Option D",
    "Correct Answer",
    "Marks",
]
BULK_ANSWER_TO_ORDER = {"A": 1, "B": 2, "C": 3, "D": 4}


def close_institute_exam_popup_response(fallback_url="/institute/exams/"):
    return HttpResponse(
        f"""
        <script>
            if (window.opener) {{
                window.opener.location.reload();
                window.close();
            }} else {{
                window.location.href = "{fallback_url}";
            }}
        </script>
        """
    )


def institute_exam_batches(request):
    institute = get_current_institute(request)
    selected_year = get_current_academic_year(request, institute)
    if not institute or not selected_year:
        return Batch.objects.none()
    return Batch.objects.filter(institute=institute, academic_year=selected_year)


def institute_exam_queryset(request):
    return Exam.objects.filter(batch__in=institute_exam_batches(request)).select_related("batch", "academic_year", "subject")



@institute_admin_required
def exams(request):
    batches = institute_exam_batches(request)
    selected_year = get_current_academic_year(request)
    exam_qs = (
        Exam.objects.filter(batch__in=batches)
        .select_related("batch", "academic_year", "subject")
        .annotate(question_count=Count("questions", distinct=True), marks_from_questions=Sum("questions__marks"))
    )
    search_query = request.GET.get("search", "").strip()
    status_filter = request.GET.get("status", "").strip()
    batch_filter = request.GET.get("batch", "").strip()
    if search_query:
        exam_qs = exam_qs.filter(Q(title__icontains=search_query) | Q(batch__name__icontains=search_query) | Q(subject__name__icontains=search_query))
    if status_filter == "published":
        exam_qs = exam_qs.filter(is_published=True)
    elif status_filter == "draft":
        exam_qs = exam_qs.filter(is_published=False)
    if batch_filter:
        exam_qs = exam_qs.filter(batch_id=batch_filter)
    base_qs = Exam.objects.filter(batch__in=batches)
    return render(
        request,
        "exam/institute_exams.html",
        {
            "exams": exam_qs,
            "batches": batches,
            "selected_academic_year": selected_year,
            "search_query": search_query,
            "status_filter": status_filter,
            "batch_filter": batch_filter,
            "total_exams": base_qs.count(),
            "published_exams": base_qs.filter(is_published=True).count(),
            "draft_exams": base_qs.filter(is_published=False).count(),
            "total_attempts": ExamAttempt.objects.filter(exam__in=base_qs, submitted_at__isnull=False).count(),
        },
    )


@institute_admin_required
def exam_create(request):
    batches = institute_exam_batches(request)
    form = TeacherExamForm(request.POST or None, batches=batches)
    if request.method == "POST" and form.is_valid():
        exam = form.save(commit=False)
        exam.academic_year = exam.batch.academic_year
        exam.created_by = request.user
        exam.total_marks = 0
        exam.save()
        messages.success(request, "Exam created successfully.")
        return close_institute_exam_popup_response()
    return render(
        request,
        "exam/institute_exam_form.html",
        {
            "form": form,
            "title": "Create Exam",
            "subtitle": "Set exam details for the selected academic year.",
            "button_text": "Save Exam",
        },
    )


@institute_admin_required
def exam_update(request, pk):
    exam = get_object_or_404(institute_exam_queryset(request), pk=pk)
    form = TeacherExamForm(request.POST or None, instance=exam, batches=institute_exam_batches(request))
    if request.method == "POST" and form.is_valid():
        exam = form.save(commit=False)
        exam.academic_year = exam.batch.academic_year
        exam.save()
        messages.success(request, "Exam updated successfully.")
        return close_institute_exam_popup_response()
    return render(
        request,
        "exam/institute_exam_form.html",
        {
            "form": form,
            "title": "Edit Exam",
            "subtitle": "Update exam schedule, instructions and publish settings.",
            "button_text": "Update Exam",
        },
    )

def sync_exam_total_marks(exam):
    total = exam.questions.aggregate(total=Sum("marks")).get("total") or 0
    Exam.objects.filter(pk=exam.pk).update(total_marks=total)
    exam.total_marks = total


def recalculate_exam_attempt(attempt):
    questions = list(attempt.exam.questions.prefetch_related("options"))
    answer_map = {
        row.question_id: row
        for row in attempt.question_attempts.select_related("selected_option")
    }
    score = 0
    correct_count = 0
    wrong_count = 0
    unattempted_count = 0
    total_marks = sum(question.marks for question in questions)
    for question in questions:
        answer = answer_map.get(question.pk)
        selected_option = answer.selected_option if answer else None
        if selected_option and selected_option.question_id != question.pk:
            selected_option = None
        is_correct = bool(selected_option and selected_option.is_correct)
        marks_awarded = question.marks if is_correct else 0
        if selected_option is None:
            unattempted_count += 1
        elif is_correct:
            correct_count += 1
            score += question.marks
        else:
            wrong_count += 1
        ExamQuestionAttempt.objects.update_or_create(
            attempt=attempt,
            question=question,
            defaults={
                "selected_option": selected_option,
                "is_correct": is_correct,
                "marks_awarded": marks_awarded,
            },
        )
    attempt.score = score
    attempt.total_marks = total_marks
    attempt.correct_count = correct_count
    attempt.wrong_count = wrong_count
    attempt.unattempted_count = unattempted_count
    attempt.save(
        update_fields=[
            "score",
            "total_marks",
            "correct_count",
            "wrong_count",
            "unattempted_count",
        ]
    )
    if attempt.is_submitted:
        ExamResult.objects.update_or_create(
            exam=attempt.exam,
            student=attempt.student,
            defaults={
                "marks_obtained": score,
                "remark": "Updated by teacher from exam submission management.",
            },
        )
    return attempt


def option_formset_has_one_correct(formset):
    option_rows = [
        data
        for data in formset.cleaned_data
        if data and not data.get("DELETE") and data.get("text")
    ]
    return len(option_rows) == 4 and sum(1 for data in option_rows if data.get("is_correct")) == 1


@institute_admin_required
def exam_questions(request, pk):
    exam = get_object_or_404(
        institute_exam_queryset(request).prefetch_related("questions", "questions__options"),
        pk=pk,
    )
    return render(request, "exam/institute_exam_questions.html", {"exam": exam})


@institute_admin_required
def exam_question_create(request, pk):
    exam = get_object_or_404(institute_exam_queryset(request), pk=pk)
    question = ExamQuestion(exam=exam, order=exam.questions.count() + 1)
    form = ExamQuestionForm(request.POST or None, request.FILES or None, instance=question)
    formset = ExamQuestionOptionFormSet(request.POST or None, instance=question, prefix="options")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        if not option_formset_has_one_correct(formset):
            messages.error(request, "Add exactly four options and select exactly one correct option.")
        else:
            question = form.save(commit=False)
            question.exam = exam
            question.order = exam.questions.count() + 1
            question.save()
            formset.instance = question
            options = formset.save(commit=False)
            for index, option in enumerate(options, start=1):
                option.question = question
                option.order = index
                option.save()
            for deleted in formset.deleted_objects:
                deleted.delete()
            sync_exam_total_marks(exam)
            messages.success(request, "Question added successfully.")
            return close_institute_exam_popup_response(reverse("institute_admin:institute_exam_questions", args=[exam.pk]))
    return render(
        request,
        "exam/institute_exam_question_form.html",
        {"exam": exam, "form": form, "formset": formset, "title": "Add Question"},
    )


@institute_admin_required
def exam_question_update(request, exam_pk, question_pk):
    exam = get_object_or_404(institute_exam_queryset(request), pk=exam_pk)
    question = get_object_or_404(ExamQuestion.objects.filter(exam=exam), pk=question_pk)
    form = ExamQuestionForm(request.POST or None, request.FILES or None, instance=question)
    formset = ExamQuestionOptionFormSet(request.POST or None, instance=question, prefix="options")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        if not option_formset_has_one_correct(formset):
            messages.error(request, "Add exactly four options and select exactly one correct option.")
        else:
            question = form.save()
            options = formset.save(commit=False)
            for deleted in formset.deleted_objects:
                deleted.delete()
            for index, option in enumerate(options, start=1):
                option.question = question
                option.order = index
                option.save()
            sync_exam_total_marks(exam)
            messages.success(request, "Question updated successfully.")
            return close_institute_exam_popup_response(reverse("institute_admin:institute_exam_questions", args=[exam.pk]))
    return render(
        request,
        "exam/institute_exam_question_form.html",
        {"exam": exam, "form": form, "formset": formset, "title": "Edit Question"},
    )


def normalize_bulk_cell(value):
    if value is None:
        return ""
    return str(value).strip()


@institute_admin_required
def exam_question_import_template(request, pk):
    exam = get_object_or_404(institute_exam_queryset(request), pk=pk)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Questions"
    worksheet.append(BULK_QUESTION_HEADERS)

    sample_rows = [
        [
            "A body is moving with uniform velocity. Its acceleration is?",
            "Zero",
            "Positive",
            "Negative",
            "Variable",
            "A",
            1,
        ],
        [
            "If x + 5 = 12, then x equals?",
            "5",
            "6",
            "7",
            "8",
            "C",
            1,
        ],
        [
            "Which option best represents the SI unit of force?",
            "Joule",
            "Newton",
            "Watt",
            "Pascal",
            "B",
            1,
        ],
    ]
    for row in sample_rows:
        worksheet.append(row)

    header_fill = PatternFill(start_color="EEF2FF", end_color="EEF2FF", fill_type="solid")
    for cell in worksheet[1]:
        cell.font = Font(bold=True)
        cell.fill = header_fill
    for column_index, width in enumerate([48, 28, 28, 28, 28, 18, 12], start=1):
        worksheet.column_dimensions[get_column_letter(column_index)].width = width

    answer_validation = DataValidation(type="list", formula1='"A,B,C,D"', allow_blank=False)
    answer_validation.error = "Select only A, B, C, or D as the correct answer."
    answer_validation.errorTitle = "Invalid answer"
    answer_validation.prompt = "Choose the correct option."
    answer_validation.promptTitle = "Correct Answer"
    worksheet.add_data_validation(answer_validation)
    answer_validation.add("F2:F500")

    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    filename = f"bulk-question-template-{exam.pk}.xlsx"
    response = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@institute_admin_required
def exam_question_bulk_import(request, pk):
    exam = get_object_or_404(institute_exam_queryset(request), pk=pk)
    if request.method != "POST":
        return redirect("institute_admin:institute_exam_questions", pk=exam.pk)

    upload = request.FILES.get("question_file")
    if not upload:
        messages.error(request, "Please select the completed question template.")
        return redirect("institute_admin:institute_exam_questions", pk=exam.pk)
    if not upload.name.lower().endswith(".xlsx"):
        messages.error(request, "Please upload the Excel template in .xlsx format.")
        return redirect("institute_admin:institute_exam_questions", pk=exam.pk)

    try:
        workbook = load_workbook(upload, data_only=True)
    except Exception:
        messages.error(request, "Unable to read the uploaded Excel file. Please download the template and try again.")
        return redirect("institute_admin:institute_exam_questions", pk=exam.pk)

    worksheet = workbook.active
    imported_rows = []
    errors = []
    for row_number, row in enumerate(worksheet.iter_rows(min_row=2, values_only=True), start=2):
        values = [normalize_bulk_cell(value) for value in row[:7]]
        values += [""] * (7 - len(values))
        question_text, option_a, option_b, option_c, option_d, correct_answer, marks_value = values

        if not any(values):
            continue

        row_errors = []
        if not question_text:
            row_errors.append("question text is required")
        options = [option_a, option_b, option_c, option_d]
        if any(not option for option in options):
            row_errors.append("all four options are required")
        correct_answer = correct_answer.upper()
        if correct_answer not in BULK_ANSWER_TO_ORDER:
            row_errors.append("correct answer must be A, B, C, or D")
        try:
            marks = int(float(marks_value or 1))
        except (TypeError, ValueError):
            marks = 0
        if marks < 1:
            row_errors.append("marks must be 1 or higher")

        if row_errors:
            errors.append(f"Row {row_number}: {', '.join(row_errors)}.")
            continue

        imported_rows.append(
            {
                "text": question_text,
                "options": options,
                "correct_order": BULK_ANSWER_TO_ORDER[correct_answer],
                "marks": marks,
            }
        )

    if errors:
        messages.error(request, "Bulk import failed. Fix these rows and upload again: " + " ".join(errors[:8]))
        if len(errors) > 8:
            messages.error(request, f"{len(errors) - 8} more row(s) also need correction.")
        return redirect("institute_admin:institute_exam_questions", pk=exam.pk)
    if not imported_rows:
        messages.error(request, "No question rows found in the uploaded template.")
        return redirect("institute_admin:institute_exam_questions", pk=exam.pk)

    start_order = exam.questions.count() + 1
    with transaction.atomic():
        for offset, row in enumerate(imported_rows):
            question = ExamQuestion.objects.create(
                exam=exam,
                text=row["text"],
                marks=row["marks"],
                order=start_order + offset,
            )
            ExamQuestionOption.objects.bulk_create(
                [
                    ExamQuestionOption(
                        question=question,
                        text=option_text,
                        order=option_order,
                        is_correct=option_order == row["correct_order"],
                    )
                    for option_order, option_text in enumerate(row["options"], start=1)
                ]
            )
        sync_exam_total_marks(exam)

    messages.success(request, f"{len(imported_rows)} question(s) imported successfully.")
    return redirect("institute_admin:institute_exam_questions", pk=exam.pk)


@institute_admin_required
def exam_submissions(request, pk):
    exam = get_object_or_404(institute_exam_queryset(request), pk=pk)
    enrollments = (
        StudentEnrollment.objects.filter(
            batch=exam.batch,
            academic_session__academic_year=exam.academic_year,
            academic_session__status=StudentAcademicSession.Status.ACTIVE,
            status=StudentEnrollment.Status.ACTIVE,
            student__is_active=True,
        )
        .select_related("academic_session", "student", "student__user")
        .order_by("academic_session__admission_number", "student__user__first_name", "student__user__username")
    )
    attempts = list(
        ExamAttempt.objects.filter(exam=exam)
        .select_related("student", "student__user", "academic_session")
        .prefetch_related("uploads")
    )
    attempts_by_session = {attempt.academic_session_id: attempt for attempt in attempts}
    rows = []
    seen_session_ids = set()

    for enrollment in enrollments:
        attempt = attempts_by_session.get(enrollment.academic_session_id)
        seen_session_ids.add(enrollment.academic_session_id)
        rows.append(
            {
                "academic_session": enrollment.academic_session,
                "student": enrollment.student,
                "attempt": attempt,
                "status": "Attempted" if attempt and attempt.is_submitted else "In Progress" if attempt else "Not Attempted",
            }
        )

    for attempt in attempts:
        if attempt.academic_session_id in seen_session_ids:
            continue
        rows.append(
            {
                "academic_session": attempt.academic_session,
                "student": attempt.student,
                "attempt": attempt,
                "status": "Attempted" if attempt.is_submitted else "In Progress",
            }
        )

    attempted_count = sum(1 for row in rows if row["attempt"] and row["attempt"].is_submitted)
    in_progress_count = sum(1 for row in rows if row["attempt"] and not row["attempt"].is_submitted)
    not_attempted_count = sum(1 for row in rows if not row["attempt"])
    return render(
        request,
        "exam/institute_exam_submissions.html",
        {
            "exam": exam,
            "rows": rows,
            "total_students": len(rows),
            "attempted_count": attempted_count,
            "in_progress_count": in_progress_count,
            "not_attempted_count": not_attempted_count,
        },
    )


@institute_admin_required
def exam_attempt_manage(request, exam_pk, attempt_pk):
    exam = get_object_or_404(institute_exam_queryset(request), pk=exam_pk)
    attempt = get_object_or_404(
        ExamAttempt.objects.select_related("student", "student__user", "academic_session", "exam")
        .prefetch_related("question_attempts", "uploads", "activities"),
        pk=attempt_pk,
        exam=exam,
    )
    questions = list(exam.questions.prefetch_related("options"))

    if request.method == "POST":
        action = request.POST.get("action", "save_answers")
        with transaction.atomic():
            for question in questions:
                selected_option = None
                option_id = request.POST.get(f"answer_{question.pk}")
                if option_id:
                    selected_option = question.options.filter(pk=option_id).first()
                ExamQuestionAttempt.objects.update_or_create(
                    attempt=attempt,
                    question=question,
                    defaults={"selected_option": selected_option},
                )
            if action == "force_submit" and not attempt.is_submitted:
                attempt.submitted_at = timezone.now()
                attempt.save(update_fields=["submitted_at"])
            recalculate_exam_attempt(attempt)
        if action == "force_submit":
            messages.success(request, "Attempt answers saved and marked as submitted.")
        else:
            messages.success(request, "Student answers updated and score recalculated.")
        return redirect("institute_admin:institute_exam_attempt_manage", exam_pk=exam.pk, attempt_pk=attempt.pk)

    recalculate_exam_attempt(attempt)
    attempts_by_question = {
        answer.question_id: answer
        for answer in attempt.question_attempts.select_related("selected_option")
    }
    question_rows = [
        {
            "question": question,
            "answer": attempts_by_question.get(question.pk),
            "uploads": [upload for upload in attempt.uploads.all() if upload.question_id == question.pk],
        }
        for question in questions
    ]
    unlinked_uploads = [upload for upload in attempt.uploads.all() if not upload.question_id]
    return render(
        request,
        "exam/institute_exam_attempt_manage.html",
        {
            "exam": exam,
            "attempt": attempt,
            "question_rows": question_rows,
            "unlinked_uploads": unlinked_uploads,
        },
    )


@institute_admin_required
@require_POST
def exam_attempt_reset(request, exam_pk, attempt_pk):
    exam = get_object_or_404(institute_exam_queryset(request), pk=exam_pk)
    attempt = get_object_or_404(ExamAttempt.objects.select_related("student"), pk=attempt_pk, exam=exam)
    student_name = attempt.student.user.get_full_name() or attempt.student.user.username
    ExamResult.objects.filter(exam=exam, student=attempt.student).delete()
    attempt.delete()
    messages.success(request, f"Attempt reset for {student_name}. The student can attend this exam again.")
    return redirect("institute_admin:institute_exam_submissions", pk=exam.pk)


@institute_admin_required
@require_POST
def exam_publish(request, pk):
    exam = get_object_or_404(institute_exam_queryset(request), pk=pk)
    if exam.is_published:
        messages.info(request, "Exam is already published to students.")
    else:
        exam.is_published = True
        exam.save(update_fields=["is_published"])
        messages.success(request, "Exam published successfully. Students can now view and attempt this exam.")
    return redirect("institute_admin:institute_exam_submissions", pk=exam.pk)


@institute_admin_required
@require_POST
def exam_toggle_result_publish(request, pk):
    exam = get_object_or_404(institute_exam_queryset(request), pk=pk)
    action = request.POST.get("action")
    if action == "publish":
        exam.show_result_after_submit = True
        exam.save(update_fields=["show_result_after_submit"])
        messages.success(request, "Exam results published successfully. Students can now view their scores.")
    elif action == "hide":
        exam.show_result_after_submit = False
        exam.save(update_fields=["show_result_after_submit"])
        messages.success(request, "Exam results hidden successfully. Students will not see scores until you publish again.")
    else:
        messages.error(request, "Invalid result visibility action.")
    return redirect("institute_admin:institute_exam_submissions", pk=exam.pk)


@institute_admin_required
def results(request):
    batches = institute_exam_batches(request)
    exams_qs = Exam.objects.filter(batch__in=batches)
    result_qs = ExamResult.objects.filter(exam__in=exams_qs).select_related("exam", "student", "student__user")
    return render(request, "exam/institute_results.html", {"results": result_qs})


@institute_admin_required
def result_create(request):
    batches = institute_exam_batches(request)
    exams_qs = Exam.objects.filter(batch__in=batches)
    students_qs = StudentEnrollment.objects.filter(
        batch__in=batches,
        academic_session__status=StudentAcademicSession.Status.ACTIVE,
        status=StudentEnrollment.Status.ACTIVE,
        student__is_active=True,
    ).values_list("student_id", flat=True)
    from student_parent.models import StudentProfile

    form = TeacherExamResultForm(
        request.POST or None,
        exams=exams_qs,
        students=StudentProfile.objects.filter(pk__in=students_qs).select_related("user"),
    )
    if request.method == "POST" and form.is_valid():
        result = form.save()
        notify_result_declared(result)
        messages.success(request, "Result saved successfully.")
        return redirect("institute_admin:institute_results")
    return render(request, "exam/institute_result_form.html", {"form": form, "title": "Add Result"})
