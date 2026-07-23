import json
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from institute_admin.models import AcademicYear, Batch, Subject
from student_parent.models import StudentAcademicSession
from super_admin.decorators import institute_admin_required, student_parent_required, teacher_required
from super_admin.models import UserProfile

from .forms import (
    BulkMarksEntryForm,
    ReportCardAssessmentForm,
    ReportCardAssessmentSubjectComponentForm,
    ReportCardAssessmentSubjectForm,
    ReportCardGradeRuleForm,
    ReportCardTeacherSubjectAllocationForm,
)
from .exports import (
    consolidated_results_response,
    import_marks_workbook,
    marks_entry_template_response,
    report_card_pdf_response,
)
from .models import (
    ReportCardAssessment,
    ReportCardAssessmentSubject,
    ReportCardAssessmentSubjectComponent,
    ReportCardGradeRule,
    ReportCardStudentResult,
    ReportCardTeacherSubjectAllocation,
)
from .permissions import (
    MARKS_ENTRY_STATUSES,
    admin_can_manage_assessment,
    student_can_view_result,
    teacher_can_access_assessment,
    teacher_can_edit_assessment,
    teacher_can_enter_marks,
    teacher_has_subject_allocation,
)
from .selectors import (
    get_assessment_subjects,
    get_assessment_subject_components,
    get_completion_summary,
    get_deleted_assessments_for_admin,
    get_generated_results,
    get_marks_grid,
    get_published_results_for_student,
    get_result_subject_rows,
    get_selected_academic_year,
    get_teacher_assigned_batches,
    get_teacher_accessible_assessment_subjects,
    get_teacher_accessible_assessments,
    get_teacher_allocated_batches,
    get_teacher_institute,
)
from .services import (
    add_assessment_subject,
    add_assessment_subject_component,
    bulk_save_subject_marks,
    create_assessment,
    generate_assessment_results,
    get_assessment_delete_impact,
    lock_assessment as lock_assessment_service,
    open_marks_entry,
    permanent_delete_assessment,
    publish_assessment_results,
    reopen_marks_entry,
    remove_assessment_subject,
    remove_assessment_subject_component,
    restore_deleted_assessment,
    soft_delete_assessment,
    sync_assessment_subject_components,
    update_assessment,
    update_assessment_subject,
    update_assessment_subject_component,
    unlock_assessment_for_admin,
    validate_marks_completion,
)


DEFAULT_GRADE_RULES = [
    (Decimal("90.00"), Decimal("100.00"), "A1", "Outstanding"),
    (Decimal("80.00"), Decimal("89.99"), "A2", "Excellent"),
    (Decimal("70.00"), Decimal("79.99"), "B1", "Very Good"),
    (Decimal("60.00"), Decimal("69.99"), "B2", "Good"),
    (Decimal("50.00"), Decimal("59.99"), "C1", "Satisfactory"),
    (Decimal("40.00"), Decimal("49.99"), "C2", "Needs Improvement"),
    (Decimal("0.00"), Decimal("39.99"), "F", "Fail"),
]


def _validation_messages(error):
    if hasattr(error, "message_dict"):
        for field_errors in error.message_dict.values():
            for message in field_errors:
                yield message
        return
    for message in getattr(error, "messages", [str(error)]):
        yield message


def _handle_validation_error(request, error):
    for message in _validation_messages(error):
        messages.error(request, message)


def _marks_entry_closed_message(assessment):
    return (
        f"Marks entry is not open. Current status: {assessment.get_status_display()}. "
        "Institute admin must open or reopen marks entry before teachers can save marks."
    )


def _has_active_grade_rules(institute, academic_year=None):
    if not institute:
        return False
    rules = ReportCardGradeRule.objects.filter(institute=institute, is_active=True)
    if academic_year:
        rules = rules.filter(Q(academic_year=academic_year) | Q(academic_year__isnull=True))
    return rules.exists()


def _assessments_missing_grade_rules(institute):
    grade_sensitive_statuses = [
        ReportCardAssessment.Status.STRUCTURE_READY,
        ReportCardAssessment.Status.MARKS_ENTRY_OPEN,
        ReportCardAssessment.Status.MARKS_ENTRY_COMPLETED,
        ReportCardAssessment.Status.GENERATED,
    ]
    assessments = (
        ReportCardAssessment.objects.filter(
            institute=institute,
            status__in=grade_sensitive_statuses,
            is_deleted=False,
        )
        .select_related("academic_year", "batch")
        .order_by("academic_year__start_date", "batch__name", "title")
    )
    return [
        assessment
        for assessment in assessments
        if not _has_active_grade_rules(institute, assessment.academic_year)
    ]


def _close_report_card_popup_response(fallback_url="/teacher/report-cards/"):
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


def _teacher_assessment_queryset(request):
    academic_year = get_selected_academic_year(request)
    return get_teacher_accessible_assessments(request.user, academic_year=academic_year)


def _get_teacher_assessment(request, assessment_id):
    return get_object_or_404(_teacher_assessment_queryset(request), pk=assessment_id)


def _get_assessment_subject_or_404(assessment, assessment_subject_id):
    return get_object_or_404(
        ReportCardAssessmentSubject.objects.select_related("assessment", "subject"),
        pk=assessment_subject_id,
        assessment=assessment,
    )


def _get_subject_component_or_404(assessment_subject, component_id):
    return get_object_or_404(
        ReportCardAssessmentSubjectComponent.objects.select_related("assessment_subject", "assessment_subject__assessment"),
        pk=component_id,
        assessment_subject=assessment_subject,
    )


def _teacher_own_completion_summary(user, assessment):
    subjects = list(get_teacher_accessible_assessment_subjects(user, assessment))
    summary = get_completion_summary(assessment, assessment_subjects=subjects)
    required_subjects = [
        item for item in summary["subjects"] if not item["assessment_subject"].is_optional
    ]
    required_expected = sum(item["expected_mark_count"] for item in required_subjects)
    required_missing = sum(item["missing_mark_count"] for item in required_subjects)
    summary["required_expected_mark_count"] = required_expected
    summary["required_missing_mark_count"] = required_missing
    summary["is_complete"] = required_expected > 0 and required_missing == 0
    return summary


@teacher_required
def assessment_list(request):
    academic_year = get_selected_academic_year(request)
    assessments = get_teacher_accessible_assessments(request.user, academic_year=academic_year)
    batch_options = get_teacher_allocated_batches(request.user, academic_year=academic_year)
    all_assigned_batches = get_teacher_allocated_batches(request.user)
    academic_year_options = []
    seen_academic_years = set()
    for batch in all_assigned_batches:
        if batch.academic_year_id and batch.academic_year_id not in seen_academic_years:
            academic_year_options.append(batch.academic_year)
            seen_academic_years.add(batch.academic_year_id)

    filter_batch_id = (request.GET.get("batch_id") or "").strip()
    filter_status = (request.GET.get("status") or "").strip()
    search_query = (request.GET.get("q") or "").strip()

    summary = {
        "total": assessments.count(),
        "draft": assessments.filter(status=ReportCardAssessment.Status.DRAFT).count(),
        "marks_entry_open": assessments.filter(status=ReportCardAssessment.Status.MARKS_ENTRY_OPEN).count(),
        "published": assessments.filter(status=ReportCardAssessment.Status.PUBLISHED).count(),
    }

    if filter_batch_id and batch_options.filter(pk=filter_batch_id).exists():
        assessments = assessments.filter(batch_id=filter_batch_id)
    if filter_status in dict(ReportCardAssessment.Status.choices):
        assessments = assessments.filter(status=filter_status)
    if search_query:
        assessments = assessments.filter(title__icontains=search_query)

    assessment_rows = list(assessments)
    for assessment in assessment_rows:
        assessment.first_assessment_subject = next(
            iter(get_teacher_accessible_assessment_subjects(request.user, assessment)),
            None,
        )

    return render(
        request,
        "report_card/teacher/assessment_list.html",
        {
            "academic_year": academic_year,
            "academic_year_options": academic_year_options,
            "assessments": assessment_rows,
            "batch_options": batch_options,
            "filter_batch_id": filter_batch_id,
            "filter_status": filter_status,
            "search_query": search_query,
            "status_choices": ReportCardAssessment.Status.choices,
            "summary": summary,
        },
    )


@teacher_required
def assessment_create(request):
    messages.error(request, "Report card assessments are now created by institute admin.")
    return redirect("report_card:assessment_list")


@teacher_required
def assessment_update(request, assessment_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    messages.error(request, "Report card assessment details are managed by institute admin.")
    return redirect("report_card:assessment_detail", assessment_id=assessment.pk)


@teacher_required
def assessment_detail(request, assessment_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    subjects = list(get_teacher_accessible_assessment_subjects(request.user, assessment))
    summary = _teacher_own_completion_summary(request.user, assessment)
    subject_summary_by_id = {
        item["assessment_subject"].pk: item
        for item in summary.get("subjects", [])
    }
    for subject in subjects:
        subject_summary = subject_summary_by_id.get(subject.pk, {})
        missing_count = subject_summary.get("missing_mark_count", 0)
        entered_count = subject_summary.get("entered_mark_count", 0)
        expected_count = subject_summary.get("expected_mark_count", 0)
        subject.marks_missing_count = missing_count
        subject.marks_entered_count = entered_count
        subject.marks_expected_count = expected_count
        if expected_count == 0:
            subject.marks_status = "NOT_STARTED"
            subject.marks_status_label = "Not started"
        elif missing_count == 0:
            subject.marks_status = "COMPLETED"
            subject.marks_status_label = "Completed"
        elif entered_count > 0:
            subject.marks_status = "IN_PROGRESS"
            subject.marks_status_label = "In progress"
        else:
            subject.marks_status = "PENDING"
            subject.marks_status_label = "Pending"
    return render(
        request,
        "report_card/teacher/assessment_detail.html",
        {
            "assessment": assessment,
            "subjects": subjects,
            "summary": summary,
        },
    )


@teacher_required
def assessment_structure(request, assessment_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    subjects = list(get_teacher_accessible_assessment_subjects(request.user, assessment))
    summary = {
        "subject_count": len(subjects),
        "total_marks": sum(subject.max_marks for subject in subjects if subject.include_in_total),
        "included_subject_count": sum(1 for subject in subjects if subject.include_in_total),
        "optional_subject_count": sum(1 for subject in subjects if subject.is_optional),
    }
    return render(
        request,
        "report_card/teacher/assessment_structure.html",
        {
            "assessment": assessment,
            "subjects": subjects,
            "can_edit": False,
            "can_open_marks": False,
            "summary": summary,
        },
    )


@teacher_required
def assessment_subject_create(request, assessment_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    messages.error(request, "Assessment subject structure is managed by institute admin.")
    return redirect("report_card:assessment_structure", assessment_id=assessment.pk)


@teacher_required
def assessment_subject_update(request, assessment_id, assessment_subject_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    assessment_subject = _get_assessment_subject_or_404(assessment, assessment_subject_id)
    messages.error(request, "Assessment subject structure is managed by institute admin.")
    return redirect("report_card:assessment_structure", assessment_id=assessment.pk)


@teacher_required
@require_POST
def assessment_subject_delete(request, assessment_id, assessment_subject_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    assessment_subject = _get_assessment_subject_or_404(assessment, assessment_subject_id)
    messages.error(request, "Assessment subject structure is managed by institute admin.")
    return redirect("report_card:assessment_structure", assessment_id=assessment.pk)


@teacher_required
def assessment_subject_component_create(request, assessment_id, assessment_subject_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    assessment_subject = _get_assessment_subject_or_404(assessment, assessment_subject_id)
    messages.error(request, "Subject component structure is managed by institute admin.")
    return redirect("report_card:assessment_structure", assessment_id=assessment.pk)


@teacher_required
def assessment_subject_component_update(request, assessment_id, assessment_subject_id, component_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    assessment_subject = _get_assessment_subject_or_404(assessment, assessment_subject_id)
    component = _get_subject_component_or_404(assessment_subject, component_id)
    messages.error(request, "Subject component structure is managed by institute admin.")
    return redirect("report_card:assessment_structure", assessment_id=assessment.pk)


@teacher_required
@require_POST
def assessment_subject_component_delete(request, assessment_id, assessment_subject_id, component_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    assessment_subject = _get_assessment_subject_or_404(assessment, assessment_subject_id)
    component = _get_subject_component_or_404(assessment_subject, component_id)
    messages.error(request, "Subject component structure is managed by institute admin.")
    return redirect("report_card:assessment_structure", assessment_id=assessment.pk)


@teacher_required
def marks_entry(request, assessment_id, assessment_subject_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    assessment_subject = _get_assessment_subject_or_404(assessment, assessment_subject_id)
    if not teacher_can_enter_marks(request.user, assessment, assessment_subject):
        if not teacher_has_subject_allocation(request.user, assessment_subject):
            messages.error(request, "You are not allocated to enter marks for this class and subject.")
        elif assessment.status not in MARKS_ENTRY_STATUSES:
            messages.error(request, _marks_entry_closed_message(assessment))
        else:
            messages.error(request, "You are not allowed to enter marks for this assessment.")
        return redirect("report_card:assessment_detail", assessment_id=assessment.pk)

    grid = get_marks_grid(assessment_subject)
    components = list(get_assessment_subject_components(assessment_subject))
    forms = []
    all_valid = True
    for row in grid:
        session = row["academic_session"]
        mark_entry = row["mark_entry"]
        prefix = str(session.pk)
        initial = {
            "academic_session_id": session.pk,
            "marks_obtained": getattr(mark_entry, "marks_obtained", None),
            "is_absent": getattr(mark_entry, "is_absent", False),
            "remark": getattr(mark_entry, "remark", ""),
        }
        for component in components:
            component_entry = row["component_entries"].get(component.pk)
            initial[f"component_{component.pk}"] = getattr(component_entry, "marks_obtained", None)
        form = BulkMarksEntryForm(
            request.POST or None,
            prefix=prefix,
            initial=initial,
            assessment_subject=assessment_subject,
            components=components,
        )
        if request.method == "POST" and not form.is_valid():
            all_valid = False
        component_fields = [
            {"component": component, "field": form[f"component_{component.pk}"]}
            for component in components
        ]
        forms.append({"row": row, "form": form, "component_fields": component_fields})

    if request.method == "POST" and all_valid:
        try:
            mark_rows = [item["form"].to_service_row() for item in forms]
            bulk_save_subject_marks(assessment_subject, mark_rows, actor=request.user)
            messages.success(request, "Marks saved successfully.")
            return redirect(
                "report_card:marks_entry",
                assessment_id=assessment.pk,
                assessment_subject_id=assessment_subject.pk,
            )
        except ValidationError as error:
            _handle_validation_error(request, error)

    return render(
        request,
        "report_card/teacher/marks_entry.html",
        {
            "assessment": assessment,
            "assessment_subject": assessment_subject,
            "components": components,
            "form_rows": forms,
            "student_count": len(forms),
        },
    )


@teacher_required
def marks_entry_template(request, assessment_id, assessment_subject_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    assessment_subject = _get_assessment_subject_or_404(assessment, assessment_subject_id)
    if not teacher_has_subject_allocation(request.user, assessment_subject):
        messages.error(request, "You can export marks templates only for your allocated subject.")
        return redirect("report_card:assessment_detail", assessment_id=assessment.pk)
    return marks_entry_template_response(assessment_subject)


@teacher_required
@require_POST
def marks_entry_import(request, assessment_id, assessment_subject_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    assessment_subject = _get_assessment_subject_or_404(assessment, assessment_subject_id)
    if not teacher_can_enter_marks(request.user, assessment, assessment_subject):
        if not teacher_has_subject_allocation(request.user, assessment_subject):
            messages.error(request, "You can import marks only for your allocated class and subject.")
        elif assessment.status not in MARKS_ENTRY_STATUSES:
            messages.error(request, _marks_entry_closed_message(assessment))
        else:
            messages.error(request, "Marks import is allowed only for your allocated subject while marks entry is open.")
        return redirect("report_card:marks_entry", assessment_id=assessment.pk, assessment_subject_id=assessment_subject.pk)

    upload = request.FILES.get("marks_file")
    if not upload:
        messages.error(request, "Please choose an Excel file to import.")
        return redirect("report_card:marks_entry", assessment_id=assessment.pk, assessment_subject_id=assessment_subject.pk)
    if not upload.name.lower().endswith(".xlsx"):
        messages.error(request, "Please upload the .xlsx marks template.")
        return redirect("report_card:marks_entry", assessment_id=assessment.pk, assessment_subject_id=assessment_subject.pk)

    result = import_marks_workbook(assessment_subject, upload, actor=request.user)
    if result["errors"]:
        for error in result["errors"][:10]:
            row_label = f"Row {error['row']}: " if error["row"] else ""
            messages.error(request, row_label + "; ".join(error["errors"]))
        remaining = len(result["errors"]) - 10
        if remaining > 0:
            messages.error(request, f"{remaining} more row errors found. Fix the sheet and import again.")
    else:
        messages.success(request, f"Imported {result['saved_count']} marks successfully.")
        warnings = result.get("warnings", [])
        if warnings:
            pending_fields = sum(len(warning.get("missing_fields", [])) for warning in warnings)
            messages.warning(
                request,
                f"{len(warnings)} student row(s) imported with {pending_fields} pending mark field(s). You can complete them later.",
            )
            for warning in warnings[:5]:
                row_label = f"Row {warning['row']}: " if warning.get("row") else ""
                messages.warning(request, row_label + warning.get("message", "Some marks were kept pending."))
            remaining = len(warnings) - 5
            if remaining > 0:
                messages.warning(request, f"{remaining} more imported row(s) have pending marks.")
    return redirect("report_card:marks_entry", assessment_id=assessment.pk, assessment_subject_id=assessment_subject.pk)


@teacher_required
def completion_summary(request, assessment_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    summary = _teacher_own_completion_summary(request.user, assessment)
    required_expected = summary.get("required_expected_mark_count") or summary.get("expected_mark_count") or 0
    required_missing = summary.get("required_missing_mark_count", summary.get("missing_mark_count", 0))
    required_entered = max(required_expected - required_missing, 0)
    completion_percentage = round((required_entered / required_expected) * 100, 1) if required_expected else 0
    has_grade_rules = _has_active_grade_rules(assessment.institute, assessment.academic_year)
    return render(
        request,
        "report_card/teacher/completion_summary.html",
        {
            "assessment": assessment,
            "completion_percentage": completion_percentage,
            "has_grade_rules": has_grade_rules,
            "summary": summary,
        },
    )


@teacher_required
@require_POST
def generate_results(request, assessment_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    messages.error(request, "Report card result generation is managed by institute admin.")
    return redirect("report_card:assessment_detail", assessment_id=assessment.pk)


@teacher_required
def results_preview(request, assessment_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    messages.error(request, "Report card result preview is managed by institute admin.")
    return redirect("report_card:assessment_detail", assessment_id=assessment.pk)


@teacher_required
def results_export(request, assessment_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    messages.error(request, "Consolidated result export is managed by institute admin.")
    return redirect("report_card:assessment_detail", assessment_id=assessment.pk)


@teacher_required
def result_pdf_download(request, assessment_id, result_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    messages.error(request, "Report-card PDFs are managed by institute admin after results are generated.")
    return redirect("report_card:assessment_detail", assessment_id=assessment.pk)


@teacher_required
@require_POST
def publish_results(request, assessment_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    messages.error(request, "Report card publishing is managed by institute admin.")
    return redirect("report_card:assessment_detail", assessment_id=assessment.pk)


@teacher_required
@require_POST
def lock_assessment(request, assessment_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    messages.error(request, "Report card locking is managed by institute admin.")
    return redirect("report_card:assessment_detail", assessment_id=assessment.pk)


@teacher_required
@require_POST
def open_marks_entry_view(request, assessment_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    messages.error(request, "Marks entry opening is managed by institute admin.")
    return redirect("report_card:assessment_detail", assessment_id=assessment.pk)


def _student_from_request(request):
    return getattr(request.user, "student_profile", None)


def _selected_student_session(student, request):
    sessions = StudentAcademicSession.objects.filter(student=student).select_related("academic_year", "institute")
    return sessions.filter(status=StudentAcademicSession.Status.ACTIVE).order_by("-academic_year__start_date", "-pk").first()


@student_parent_required
def published_report_cards(request):
    student = _student_from_request(request)
    if not student:
        messages.error(request, "No student profile is linked to this account.")
        return redirect("student_parent:download_app")

    selected_session = _selected_student_session(student, request)
    results = get_published_results_for_student(student, academic_session=selected_session)
    return render(
        request,
        "report_card/student_parent/published_report_cards.html",
        {
            "student": student,
            "selected_session": selected_session,
            "results": results,
        },
    )


@student_parent_required
def published_report_card_detail(request, result_id):
    student = _student_from_request(request)
    if not student:
        messages.error(request, "No student profile is linked to this account.")
        return redirect("student_parent:download_app")

    result = get_object_or_404(
        get_published_results_for_student(student).select_related("student", "student__user"),
        pk=result_id,
    )
    if not student_can_view_result(request.user, result):
        messages.error(request, "This report card is not available.")
        return redirect("report_card_student:published_report_cards")

    subject_rows = get_result_subject_rows(result)
    return render(
        request,
        "report_card/student_parent/published_report_card_detail.html",
        {
            "student": student,
            "result": result,
            "assessment": result.assessment,
            "subject_rows": subject_rows,
        },
    )


@student_parent_required
def published_report_card_pdf(request, result_id):
    student = _student_from_request(request)
    if not student:
        messages.error(request, "No student profile is linked to this account.")
        return redirect("student_parent:download_app")

    result = get_object_or_404(get_published_results_for_student(student), pk=result_id)
    if not student_can_view_result(request.user, result):
        raise Http404("Report card not found.")
    return report_card_pdf_response(result)


def _admin_institute(request):
    profile = getattr(request.user, "profile", None)
    return getattr(profile, "institute", None)


def _admin_assessment_queryset(request):
    institute = _admin_institute(request)
    return (
        ReportCardAssessment.objects.filter(institute=institute, is_deleted=False)
        .select_related("institute", "academic_year", "batch", "created_by")
        .prefetch_related("assessment_subjects")
        .order_by("-created_at")
    )


def _get_admin_assessment(request, assessment_id):
    return get_object_or_404(_admin_assessment_queryset(request), pk=assessment_id)


def _admin_deleted_assessment_queryset(request):
    institute = _admin_institute(request)
    return get_deleted_assessments_for_admin(institute)


def _get_admin_deleted_assessment(request, assessment_id):
    return get_object_or_404(_admin_deleted_assessment_queryset(request), pk=assessment_id)


@institute_admin_required
def admin_assessment_list(request):
    institute = _admin_institute(request)
    assessments = _admin_assessment_queryset(request)
    current_academic_year = get_selected_academic_year(request)
    batches = institute.batches.filter(is_active=True).select_related("academic_year").order_by("academic_year__start_date", "name") if institute else Batch.objects.none()

    filter_batch = (request.GET.get("batch") or "").strip()
    filter_status = (request.GET.get("status") or "").strip()
    search_query = (request.GET.get("q") or "").strip()

    if current_academic_year:
        assessments = assessments.filter(academic_year=current_academic_year)
        batches = batches.filter(academic_year=current_academic_year)

    summary_queryset = assessments
    summary = {
        "total": summary_queryset.count(),
        "draft": summary_queryset.filter(status=ReportCardAssessment.Status.DRAFT).count(),
        "marks_entry_open": summary_queryset.filter(status=ReportCardAssessment.Status.MARKS_ENTRY_OPEN).count(),
        "published": summary_queryset.filter(status=ReportCardAssessment.Status.PUBLISHED).count(),
    }

    if filter_batch:
        assessments = assessments.filter(batch_id=filter_batch)
    if filter_status in dict(ReportCardAssessment.Status.choices):
        assessments = assessments.filter(status=filter_status)
    if search_query:
        assessments = assessments.filter(
            Q(title__icontains=search_query)
            | Q(batch_name_snapshot__icontains=search_query)
            | Q(academic_year_name_snapshot__icontains=search_query)
        )

    return render(
        request,
        "report_card/institute_admin/assessment_list.html",
        {
            "institute": institute,
            "assessments": assessments,
            "batches": batches,
            "filter_batch": filter_batch,
            "filter_status": filter_status,
            "search_query": search_query,
            "status_choices": ReportCardAssessment.Status.choices,
            "summary": summary,
        },
    )


@institute_admin_required
def admin_assessment_bin(request):
    institute = _admin_institute(request)
    current_academic_year = get_selected_academic_year(request)
    assessments = get_deleted_assessments_for_admin(institute, academic_year=current_academic_year)
    batches = (
        institute.batches.filter(is_active=True)
        .select_related("academic_year")
        .order_by("name")
        if institute
        else Batch.objects.none()
    )
    if current_academic_year:
        batches = batches.filter(academic_year=current_academic_year)

    deleted_by_options = User.objects.filter(
        deleted_report_card_assessments__in=assessments
    ).distinct().order_by("first_name", "last_name", "username")

    filter_batch = (request.GET.get("batch") or "").strip()
    filter_status = (request.GET.get("status") or "").strip()
    filter_deleted_by = (request.GET.get("deleted_by") or "").strip()
    search_query = (request.GET.get("q") or "").strip()

    if filter_batch and batches.filter(pk=filter_batch).exists():
        assessments = assessments.filter(batch_id=filter_batch)
    if filter_status in dict(ReportCardAssessment.Status.choices):
        assessments = assessments.filter(status=filter_status)
    if filter_deleted_by and deleted_by_options.filter(pk=filter_deleted_by).exists():
        assessments = assessments.filter(deleted_by_id=filter_deleted_by)
    if search_query:
        assessments = assessments.filter(
            Q(title__icontains=search_query)
            | Q(batch_name_snapshot__icontains=search_query)
            | Q(delete_reason__icontains=search_query)
        )
    rows = []
    for assessment in assessments:
        rows.append(
            {
                "assessment": assessment,
                "impact": get_assessment_delete_impact(assessment),
            }
        )
    return render(
        request,
        "report_card/institute_admin/assessment_bin.html",
        {
            "assessments": assessments,
            "batches": batches,
            "deleted_by_options": deleted_by_options,
            "filter_batch": filter_batch,
            "filter_deleted_by": filter_deleted_by,
            "filter_status": filter_status,
            "rows": rows,
            "search_query": search_query,
            "status_choices": ReportCardAssessment.Status.choices,
        },
    )


@institute_admin_required
def admin_assessment_create(request):
    institute = _admin_institute(request)
    academic_year = get_selected_academic_year(request)
    form = ReportCardAssessmentForm(request.POST or None, institute=institute, academic_year=academic_year)
    if request.method == "POST" and form.is_valid():
        selected_batches = list(form.cleaned_data.get("batches") or [])
        if not selected_batches:
            selected_batches = [form.cleaned_data["batch"]]
        try:
            with transaction.atomic():
                for batch in selected_batches:
                    create_assessment(
                        institute=form.effective_institute,
                        academic_year=form.cleaned_data["academic_year"],
                        batch=batch,
                        title=form.cleaned_data["title"],
                        assessment_date=form.cleaned_data.get("assessment_date"),
                        result_date=form.cleaned_data.get("result_date"),
                        created_by=request.user,
                    )
            messages.success(request, f"Report card assessment created for {len(selected_batches)} class(es).")
            return redirect("report_card_admin:assessment_list")
        except ValidationError as error:
            _handle_validation_error(request, error)
    return render(
        request,
        "report_card/institute_admin/assessment_form.html",
        {
            "form": form,
            "page_title": "Create Report Card Assessment",
            "cancel_url": "report_card_admin:assessment_list",
            "academic_year": academic_year,
        },
    )


@institute_admin_required
def admin_assessment_update(request, assessment_id):
    assessment = _get_admin_assessment(request, assessment_id)
    if not admin_can_manage_assessment(request.user, assessment):
        messages.error(request, "You cannot edit this assessment.")
        return redirect("report_card_admin:assessment_detail", assessment_id=assessment.pk)

    form = ReportCardAssessmentForm(
        request.POST or None,
        instance=assessment,
        institute=assessment.institute,
        academic_year=assessment.academic_year,
    )
    if request.method == "POST" and form.is_valid():
        try:
            update_assessment(
                assessment,
                actor=request.user,
                academic_year=form.cleaned_data["academic_year"],
                batch=form.cleaned_data["batch"],
                title=form.cleaned_data["title"],
                assessment_date=form.cleaned_data.get("assessment_date"),
                result_date=form.cleaned_data.get("result_date"),
            )
            messages.success(request, "Report card assessment updated.")
            return redirect("report_card_admin:assessment_detail", assessment_id=assessment.pk)
        except ValidationError as error:
            _handle_validation_error(request, error)
    return render(
        request,
        "report_card/institute_admin/assessment_form.html",
        {
            "assessment": assessment,
            "form": form,
            "page_title": "Edit Report Card Assessment",
            "cancel_url": "report_card_admin:assessment_detail",
            "academic_year": assessment.academic_year,
        },
    )


@institute_admin_required
def admin_assessment_delete(request, assessment_id):
    assessment = _get_admin_assessment(request, assessment_id)
    if not admin_can_manage_assessment(request.user, assessment):
        messages.error(request, "You cannot delete this assessment.")
        return redirect("report_card_admin:assessment_detail", assessment_id=assessment.pk)

    impact = get_assessment_delete_impact(assessment)
    if request.method == "POST":
        try:
            soft_delete_assessment(
                assessment,
                actor=request.user,
                reason=request.POST.get("delete_reason", ""),
            )
            messages.success(request, "Report card assessment moved to recycle bin.")
            return redirect("report_card_admin:assessment_list")
        except ValidationError as error:
            _handle_validation_error(request, error)

    return render(
        request,
        "report_card/institute_admin/assessment_delete.html",
        {
            "assessment": assessment,
            "impact": impact,
        },
    )


@institute_admin_required
@require_POST
def admin_assessment_restore(request, assessment_id):
    assessment = _get_admin_deleted_assessment(request, assessment_id)
    if not admin_can_manage_assessment(request.user, assessment):
        messages.error(request, "You cannot restore this assessment.")
        return redirect("report_card_admin:assessment_bin")
    try:
        restore_deleted_assessment(assessment, actor=request.user)
        messages.success(request, "Report card assessment restored.")
    except ValidationError as error:
        _handle_validation_error(request, error)
    return redirect("report_card_admin:assessment_bin")


@institute_admin_required
def admin_assessment_permanent_delete(request, assessment_id):
    assessment = _get_admin_deleted_assessment(request, assessment_id)
    if not admin_can_manage_assessment(request.user, assessment):
        messages.error(request, "You cannot permanently delete this assessment.")
        return redirect("report_card_admin:assessment_bin")
    impact = get_assessment_delete_impact(assessment)
    if request.method != "POST":
        return render(
            request,
            "report_card/institute_admin/assessment_permanent_delete.html",
            {
                "assessment": assessment,
                "impact": impact,
            },
        )
    try:
        permanent_delete_assessment(
            assessment,
            actor=request.user,
            confirmation_text=request.POST.get("confirmation_text", ""),
            reason=request.POST.get("delete_reason", ""),
        )
        messages.success(request, "Report card assessment permanently deleted.")
    except ValidationError as error:
        _handle_validation_error(request, error)
    return redirect("report_card_admin:assessment_bin")


@institute_admin_required
def admin_assessment_classes(request, assessment_id):
    assessment = _get_admin_assessment(request, assessment_id)
    class_assessments = (
        ReportCardAssessment.objects.filter(
            institute=assessment.institute,
            academic_year=assessment.academic_year,
            title=assessment.title,
            assessment_date=assessment.assessment_date,
            result_date=assessment.result_date,
            is_deleted=False,
        )
        .select_related("academic_year", "batch")
        .prefetch_related("assessment_subjects")
        .order_by("batch__name", "id")
    )
    return render(
        request,
        "report_card/institute_admin/assessment_classes.html",
        {
            "assessment": assessment,
            "class_assessments": class_assessments,
        },
    )


@institute_admin_required
def admin_assessment_detail(request, assessment_id):
    assessment = _get_admin_assessment(request, assessment_id)
    subjects = list(get_assessment_subjects(assessment))
    summary = get_completion_summary(assessment)
    results = get_generated_results(assessment)
    return render(
        request,
        "report_card/institute_admin/assessment_detail.html",
        {
            "assessment": assessment,
            "can_reopen_marks_entry": assessment.status in {
                ReportCardAssessment.Status.MARKS_ENTRY_COMPLETED,
                ReportCardAssessment.Status.GENERATED,
                ReportCardAssessment.Status.PUBLISHED,
                ReportCardAssessment.Status.LOCKED,
            },
            "subjects": subjects,
            "summary": summary,
            "results": results,
        },
    )


@institute_admin_required
def admin_completion_dashboard(request, assessment_id):
    assessment = _get_admin_assessment(request, assessment_id)
    subjects = list(get_assessment_subjects(assessment))
    summary = get_completion_summary(assessment, assessment_subjects=subjects)
    subject_summary_by_id = {
        item["assessment_subject"].pk: item
        for item in summary.get("subjects", [])
    }
    allocations_by_subject_id = {}
    allocations = (
        ReportCardTeacherSubjectAllocation.objects.filter(
            institute=assessment.institute,
            academic_year=assessment.academic_year,
            batch=assessment.batch,
            subject__in=[subject.subject_id for subject in subjects],
            is_active=True,
        )
        .select_related("teacher", "subject", "batch", "academic_year")
        .order_by("subject__name", "teacher__first_name", "teacher__last_name", "teacher__username")
    )
    for allocation in allocations:
        allocations_by_subject_id.setdefault(allocation.subject_id, []).append(allocation)

    rows = []
    teacher_rows = []
    for subject in subjects:
        item = subject_summary_by_id.get(
            subject.pk,
            {
                "assessment_subject": subject,
                "expected_mark_count": 0,
                "entered_mark_count": 0,
                "missing_mark_count": 0,
                "absent_mark_count": 0,
                "is_complete": False,
            },
        )
        subject_allocations = allocations_by_subject_id.get(subject.subject_id, [])
        rows.append(
            {
                "assessment_subject": subject,
                "allocations": subject_allocations,
                "teacher_count": len(subject_allocations),
                "expected_mark_count": item["expected_mark_count"],
                "entered_mark_count": item["entered_mark_count"],
                "missing_mark_count": item["missing_mark_count"],
                "absent_mark_count": item["absent_mark_count"],
                "is_complete": item["is_complete"],
            }
        )
        if subject_allocations:
            for allocation in subject_allocations:
                teacher_rows.append(
                    {
                        "allocation": allocation,
                        "assessment_subject": subject,
                        "expected_mark_count": item["expected_mark_count"],
                        "entered_mark_count": item["entered_mark_count"],
                        "missing_mark_count": item["missing_mark_count"],
                        "absent_mark_count": item["absent_mark_count"],
                        "is_complete": item["is_complete"],
                    }
                )
        else:
            teacher_rows.append(
                {
                    "allocation": None,
                    "assessment_subject": subject,
                    "expected_mark_count": item["expected_mark_count"],
                    "entered_mark_count": item["entered_mark_count"],
                    "missing_mark_count": item["missing_mark_count"],
                    "absent_mark_count": item["absent_mark_count"],
                    "is_complete": False,
                }
            )

    completion_percentage = (
        round((summary["entered_mark_count"] / summary["expected_mark_count"]) * 100, 1)
        if summary["expected_mark_count"]
        else 0
    )
    return render(
        request,
        "report_card/institute_admin/completion_dashboard.html",
        {
            "assessment": assessment,
            "completion_percentage": completion_percentage,
            "can_reopen_marks_entry": assessment.status in {
                ReportCardAssessment.Status.MARKS_ENTRY_COMPLETED,
                ReportCardAssessment.Status.GENERATED,
                ReportCardAssessment.Status.PUBLISHED,
                ReportCardAssessment.Status.LOCKED,
            },
            "rows": rows,
            "summary": summary,
            "teacher_rows": teacher_rows,
        },
    )


@institute_admin_required
def admin_marks_grid(request, assessment_id, assessment_subject_id):
    assessment = _get_admin_assessment(request, assessment_id)
    assessment_subject = _get_assessment_subject_or_404(assessment, assessment_subject_id)
    if not admin_can_manage_assessment(request.user, assessment):
        messages.error(request, "You cannot inspect marks for this assessment.")
        return redirect("report_card_admin:completion_dashboard", assessment_id=assessment.pk)
    components = list(get_assessment_subject_components(assessment_subject))
    grid_rows = []
    for item in get_marks_grid(assessment_subject):
        grid_rows.append(
            {
                **item,
                "component_values": [
                    item["component_entries"].get(component.pk)
                    for component in components
                ],
            }
        )
    return render(
        request,
        "report_card/institute_admin/marks_grid.html",
        {
            "assessment": assessment,
            "assessment_subject": assessment_subject,
            "components": components,
            "grid": grid_rows,
        },
    )


def _admin_result_warning_messages(assessment):
    warnings = []
    completion = validate_marks_completion(assessment)
    missing = completion.get("required_missing_mark_count", completion.get("missing_mark_count", 0))
    if missing:
        warnings.append(f"{missing} required mark field(s) are still missing.")
    if not _has_active_grade_rules(assessment.institute, assessment.academic_year):
        warnings.append("No active grade rules are configured. Results can generate, but grade fields may remain blank.")
    stale_count = assessment.student_results.filter(is_stale=True).count()
    if stale_count:
        warnings.append(f"{stale_count} generated result(s) are stale. Regenerate before publishing.")
    return warnings


@institute_admin_required
def admin_results_preview(request, assessment_id):
    assessment = _get_admin_assessment(request, assessment_id)
    results = get_generated_results(assessment)
    search_query = (request.GET.get("q") or "").strip()
    filter_result_status = (request.GET.get("result_status") or "").strip()
    filter_stale = (request.GET.get("stale") or "").strip()

    summary = {
        "generated": results.count(),
        "passed": results.filter(result_status=ReportCardStudentResult.ResultStatus.PASS).count(),
        "failed": results.filter(result_status=ReportCardStudentResult.ResultStatus.FAIL).count(),
        "stale": results.filter(is_stale=True).count(),
    }
    if search_query:
        results = results.filter(
            Q(student_name_snapshot__icontains=search_query)
            | Q(admission_number_snapshot__icontains=search_query)
        )
    if filter_result_status in dict(ReportCardStudentResult.ResultStatus.choices):
        results = results.filter(result_status=filter_result_status)
    if filter_stale == "yes":
        results = results.filter(is_stale=True)
    elif filter_stale == "no":
        results = results.filter(is_stale=False)

    return render(
        request,
        "report_card/teacher/results_preview.html",
        {
            "assessment": assessment,
            "base_template": "institute_admin/base.html",
            "admin_mode": True,
            "filter_result_status": filter_result_status,
            "filter_stale": filter_stale,
            "result_status_choices": ReportCardStudentResult.ResultStatus.choices,
            "results": results,
            "search_query": search_query,
            "summary": summary,
            "warning_messages": _admin_result_warning_messages(assessment),
        },
    )


@institute_admin_required
@require_POST
def admin_generate_results(request, assessment_id):
    assessment = _get_admin_assessment(request, assessment_id)
    if not admin_can_manage_assessment(request.user, assessment):
        messages.error(request, "You cannot generate results for this assessment.")
        return redirect("report_card_admin:results_preview", assessment_id=assessment.pk)
    for warning in _admin_result_warning_messages(assessment):
        messages.warning(request, warning)
    try:
        generate_assessment_results(assessment, actor=request.user)
        messages.success(request, "Report card results generated.")
    except ValidationError as error:
        _handle_validation_error(request, error)
        return redirect("report_card_admin:completion_dashboard", assessment_id=assessment.pk)
    return redirect("report_card_admin:results_preview", assessment_id=assessment.pk)


@institute_admin_required
@require_POST
def admin_publish_results(request, assessment_id):
    assessment = _get_admin_assessment(request, assessment_id)
    if not admin_can_manage_assessment(request.user, assessment):
        messages.error(request, "You cannot publish this assessment.")
        return redirect("report_card_admin:results_preview", assessment_id=assessment.pk)
    try:
        publish_assessment_results(assessment, actor=request.user)
        messages.success(request, "Report card results published.")
    except ValidationError as error:
        _handle_validation_error(request, error)
    return redirect("report_card_admin:results_preview", assessment_id=assessment.pk)


@institute_admin_required
@require_POST
def admin_lock_assessment(request, assessment_id):
    assessment = _get_admin_assessment(request, assessment_id)
    if not admin_can_manage_assessment(request.user, assessment):
        messages.error(request, "You cannot lock this assessment.")
        return redirect("report_card_admin:results_preview", assessment_id=assessment.pk)
    try:
        lock_assessment_service(assessment, actor=request.user)
        messages.success(request, "Report card assessment locked.")
    except ValidationError as error:
        _handle_validation_error(request, error)
    return redirect("report_card_admin:results_preview", assessment_id=assessment.pk)


@institute_admin_required
def admin_results_export(request, assessment_id):
    assessment = _get_admin_assessment(request, assessment_id)
    return consolidated_results_response(assessment)


@institute_admin_required
def admin_result_pdf_download(request, assessment_id, result_id):
    assessment = _get_admin_assessment(request, assessment_id)
    result = get_object_or_404(
        ReportCardStudentResult.objects.select_related("assessment", "student", "student__user", "academic_session"),
        pk=result_id,
        assessment=assessment,
    )
    return report_card_pdf_response(result)


@institute_admin_required
def admin_assessment_structure(request, assessment_id):
    assessment = _get_admin_assessment(request, assessment_id)
    subjects = list(get_assessment_subjects(assessment))
    allocated_subject_ids = set(
        ReportCardTeacherSubjectAllocation.objects.filter(
            institute=assessment.institute,
            academic_year=assessment.academic_year,
            batch=assessment.batch,
            subject__in=[subject.subject_id for subject in subjects],
            is_active=True,
        ).values_list("subject_id", flat=True)
    )
    unallocated_subjects = [
        subject
        for subject in subjects
        if subject.subject_id not in allocated_subject_ids
    ]
    can_edit = admin_can_manage_assessment(request.user, assessment) and assessment.status in {
        ReportCardAssessment.Status.DRAFT,
        ReportCardAssessment.Status.STRUCTURE_READY,
    }
    can_open_marks = (
        admin_can_manage_assessment(request.user, assessment)
        and assessment.status == ReportCardAssessment.Status.STRUCTURE_READY
        and bool(subjects)
        and not unallocated_subjects
    )
    admin_warnings = []
    if not subjects:
        admin_warnings.append("Add at least one subject before opening marks entry.")
    if unallocated_subjects:
        names = ", ".join(subject.subject_name_snapshot for subject in unallocated_subjects)
        admin_warnings.append(f"Teacher allocation is missing for: {names}. Assign teachers before opening marks entry.")
    if subjects and assessment.status == ReportCardAssessment.Status.DRAFT:
        admin_warnings.append("Save at least one subject to make the assessment structure ready.")
    summary = {
        "subject_count": len(subjects),
        "total_marks": sum(subject.max_marks for subject in subjects if subject.include_in_total),
        "included_subject_count": sum(1 for subject in subjects if subject.include_in_total),
        "optional_subject_count": sum(1 for subject in subjects if subject.is_optional),
    }
    return render(
        request,
        "report_card/teacher/assessment_structure.html",
        {
            "assessment": assessment,
            "subjects": subjects,
            "can_edit": can_edit,
            "can_open_marks": can_open_marks,
            "admin_warnings": admin_warnings,
            "summary": summary,
            "admin_mode": True,
            "base_template": "institute_admin/base.html",
        },
    )


@institute_admin_required
@require_POST
def admin_open_marks_entry(request, assessment_id):
    assessment = _get_admin_assessment(request, assessment_id)
    if not admin_can_manage_assessment(request.user, assessment):
        messages.error(request, "You cannot open marks entry for this assessment.")
        return redirect("report_card_admin:assessment_structure", assessment_id=assessment.pk)

    subjects = list(get_assessment_subjects(assessment))
    if not subjects:
        messages.error(request, "Add at least one subject before opening marks entry.")
        return redirect("report_card_admin:assessment_structure", assessment_id=assessment.pk)

    allocated_subject_ids = set(
        ReportCardTeacherSubjectAllocation.objects.filter(
            institute=assessment.institute,
            academic_year=assessment.academic_year,
            batch=assessment.batch,
            subject__in=[subject.subject_id for subject in subjects],
            is_active=True,
        ).values_list("subject_id", flat=True)
    )
    unallocated_subjects = [
        subject.subject_name_snapshot
        for subject in subjects
        if subject.subject_id not in allocated_subject_ids
    ]
    if unallocated_subjects:
        messages.error(
            request,
            "Teacher allocation is missing for: "
            + ", ".join(unallocated_subjects)
            + ". Assign teachers before opening marks entry.",
        )
        return redirect("report_card_admin:assessment_structure", assessment_id=assessment.pk)

    try:
        open_marks_entry(assessment, actor=request.user)
        messages.success(request, "Marks entry opened for assigned teachers.")
    except ValidationError as error:
        _handle_validation_error(request, error)
    return redirect("report_card_admin:assessment_structure", assessment_id=assessment.pk)


@institute_admin_required
@require_POST
def admin_reopen_marks_entry(request, assessment_id):
    assessment = _get_admin_assessment(request, assessment_id)
    if not admin_can_manage_assessment(request.user, assessment):
        messages.error(request, "You cannot reopen marks entry for this assessment.")
        return redirect("report_card_admin:assessment_detail", assessment_id=assessment.pk)
    try:
        reopen_marks_entry(
            assessment,
            actor=request.user,
            reason=request.POST.get("reason", ""),
        )
        messages.success(request, "Marks entry reopened for the whole assessment. Teachers can update their allocated subject marks.")
    except ValidationError as error:
        _handle_validation_error(request, error)
    return redirect("report_card_admin:completion_dashboard", assessment_id=assessment.pk)


@institute_admin_required
@require_POST
def admin_reopen_subject_marks_entry(request, assessment_id, assessment_subject_id):
    assessment = _get_admin_assessment(request, assessment_id)
    assessment_subject = _get_assessment_subject_or_404(assessment, assessment_subject_id)
    if not admin_can_manage_assessment(request.user, assessment):
        messages.error(request, "You cannot reopen marks entry for this subject.")
        return redirect("report_card_admin:completion_dashboard", assessment_id=assessment.pk)
    try:
        reopen_marks_entry(
            assessment,
            actor=request.user,
            reason=request.POST.get("reason", ""),
            assessment_subject=assessment_subject,
        )
        messages.success(request, f"Marks entry reopened for {assessment_subject.subject_name_snapshot}.")
    except ValidationError as error:
        _handle_validation_error(request, error)
        return redirect("report_card_admin:completion_dashboard", assessment_id=assessment.pk)
    return redirect("report_card_admin:marks_grid", assessment_id=assessment.pk, assessment_subject_id=assessment_subject.pk)


@institute_admin_required
def admin_assessment_subject_create(request, assessment_id):
    assessment = _get_admin_assessment(request, assessment_id)
    if not admin_can_manage_assessment(request.user, assessment):
        messages.error(request, "You cannot change this assessment structure.")
        return redirect("report_card_admin:assessment_structure", assessment_id=assessment.pk)

    form = ReportCardAssessmentSubjectForm(request.POST or None, assessment=assessment)
    if request.method == "POST" and form.is_valid():
        try:
            assessment_subject = add_assessment_subject(
                assessment,
                subject=form.cleaned_data["subject"],
                max_marks=form.cleaned_data["max_marks"],
                passing_marks=form.cleaned_data["passing_marks"],
                weightage=form.cleaned_data["weightage"],
                display_order=form.cleaned_data["display_order"],
                is_optional=form.cleaned_data["is_optional"],
                include_in_total=form.cleaned_data["include_in_total"],
                actor=request.user,
            )
            sync_assessment_subject_components(
                assessment_subject,
                form.cleaned_data["components"],
                actor=request.user,
            )
            messages.success(request, "Assessment subject added.")
            return redirect("report_card_admin:assessment_structure", assessment_id=assessment.pk)
        except ValidationError as error:
            _handle_validation_error(request, error)

    return render(
        request,
        "report_card/teacher/assessment_subject_form.html",
        {
            "assessment": assessment,
            "form": form,
            "page_title": "Add Assessment Subject",
            "admin_mode": True,
            "base_template": "institute_admin/base.html",
        },
    )


@institute_admin_required
def admin_assessment_subject_update(request, assessment_id, assessment_subject_id):
    assessment = _get_admin_assessment(request, assessment_id)
    assessment_subject = _get_assessment_subject_or_404(assessment, assessment_subject_id)
    if not admin_can_manage_assessment(request.user, assessment):
        messages.error(request, "You cannot change this assessment structure.")
        return redirect("report_card_admin:assessment_structure", assessment_id=assessment.pk)

    form = ReportCardAssessmentSubjectForm(
        request.POST or None,
        instance=assessment_subject,
        assessment=assessment,
    )
    if request.method == "POST" and form.is_valid():
        try:
            update_assessment_subject(
                assessment_subject,
                subject=form.cleaned_data["subject"],
                max_marks=form.cleaned_data["max_marks"],
                passing_marks=form.cleaned_data["passing_marks"],
                weightage=form.cleaned_data["weightage"],
                display_order=form.cleaned_data["display_order"],
                is_optional=form.cleaned_data["is_optional"],
                include_in_total=form.cleaned_data["include_in_total"],
                actor=request.user,
            )
            sync_assessment_subject_components(
                assessment_subject,
                form.cleaned_data["components"],
                actor=request.user,
            )
            messages.success(request, "Assessment subject updated.")
            return redirect("report_card_admin:assessment_structure", assessment_id=assessment.pk)
        except ValidationError as error:
            _handle_validation_error(request, error)

    return render(
        request,
        "report_card/teacher/assessment_subject_form.html",
        {
            "assessment": assessment,
            "assessment_subject": assessment_subject,
            "form": form,
            "page_title": "Edit Assessment Subject",
            "admin_mode": True,
            "base_template": "institute_admin/base.html",
        },
    )


@institute_admin_required
@require_POST
def admin_assessment_subject_delete(request, assessment_id, assessment_subject_id):
    assessment = _get_admin_assessment(request, assessment_id)
    assessment_subject = _get_assessment_subject_or_404(assessment, assessment_subject_id)
    if not admin_can_manage_assessment(request.user, assessment):
        messages.error(request, "You cannot change this assessment structure.")
        return redirect("report_card_admin:assessment_structure", assessment_id=assessment.pk)

    try:
        remove_assessment_subject(assessment_subject, actor=request.user)
        messages.success(request, "Assessment subject removed.")
    except ValidationError as error:
        _handle_validation_error(request, error)
    return redirect("report_card_admin:assessment_structure", assessment_id=assessment.pk)


@institute_admin_required
def allocation_list(request):
    institute = _admin_institute(request)
    allocations = (
        ReportCardTeacherSubjectAllocation.objects.filter(institute=institute)
        .select_related("academic_year", "batch", "subject", "teacher", "created_by")
        .order_by("academic_year__start_date", "batch__name", "subject__name", "teacher__username")
    )
    current_academic_year = get_selected_academic_year(request)
    batches = Batch.objects.none()
    subjects = Subject.objects.none()
    teachers = User.objects.none()
    if institute:
        batches = institute.batches.filter(is_active=True).select_related("academic_year").order_by("academic_year__start_date", "name")
        subjects = institute.subjects.filter(is_active=True).select_related("academic_year").order_by("academic_year__start_date", "name")
        teachers = User.objects.filter(
            profile__institute=institute,
            profile__role=UserProfile.Role.TEACHER,
            is_active=True,
        ).order_by("first_name", "last_name", "username")

    filter_teacher = (request.GET.get("teacher") or "").strip()
    filter_batch = (request.GET.get("batch") or "").strip()
    filter_subject = (request.GET.get("subject") or "").strip()
    filter_status = (request.GET.get("status") or "").strip()
    search_query = (request.GET.get("q") or "").strip()

    if current_academic_year:
        allocations = allocations.filter(academic_year=current_academic_year)
        batches = batches.filter(academic_year=current_academic_year)
        subjects = subjects.filter(academic_year=current_academic_year)
    if filter_teacher:
        allocations = allocations.filter(teacher_id=filter_teacher)
    if filter_batch:
        allocations = allocations.filter(batch_id=filter_batch)
    if filter_subject:
        allocations = allocations.filter(subject_id=filter_subject)
    if filter_status == "active":
        allocations = allocations.filter(is_active=True)
    elif filter_status == "inactive":
        allocations = allocations.filter(is_active=False)
    if search_query:
        allocations = allocations.filter(
            Q(teacher__username__icontains=search_query)
            | Q(teacher__first_name__icontains=search_query)
            | Q(teacher__last_name__icontains=search_query)
            | Q(batch__name__icontains=search_query)
            | Q(subject__name__icontains=search_query)
        )

    return render(
        request,
        "report_card/institute_admin/allocation_list.html",
        {
            "allocations": allocations,
            "batches": batches,
            "subjects": subjects,
            "teachers": teachers,
            "filter_teacher": filter_teacher,
            "filter_batch": filter_batch,
            "filter_subject": filter_subject,
            "filter_status": filter_status,
            "search_query": search_query,
            "institute": institute,
        },
    )


@institute_admin_required
def allocation_create(request):
    institute = _admin_institute(request)
    academic_year = get_selected_academic_year(request)
    if not institute or not academic_year:
        messages.error(request, "Active academic year is required before creating teacher subject allocations.")
        return redirect("report_card_admin:allocation_list")

    batches = Batch.objects.filter(institute=institute, academic_year=academic_year, is_active=True).order_by("name")
    subjects = Subject.objects.filter(institute=institute, academic_year=academic_year, is_active=True).order_by("name")
    teachers = User.objects.filter(
        profile__institute=institute,
        profile__role=UserProfile.Role.TEACHER,
        is_active=True,
    ).order_by("first_name", "last_name", "username")
    existing_allocations = list(
        ReportCardTeacherSubjectAllocation.objects.filter(institute=institute, academic_year=academic_year)
        .select_related("batch", "subject", "teacher")
        .order_by("batch__name", "subject__name", "teacher__first_name", "teacher__username")
    )

    selected_batch_id = (request.POST.get("batch") if request.method == "POST" else request.GET.get("batch")) or ""
    posted_rows = []
    bulk_errors = []

    if request.method == "POST":
        try:
            posted_rows = json.loads(request.POST.get("allocation_rows_json") or "[]")
        except json.JSONDecodeError:
            posted_rows = []
            bulk_errors.append("Allocation rows are not valid. Please reload and try again.")
        if not posted_rows and request.POST.get("subject") and request.POST.get("teacher"):
            posted_rows = [
                {
                    "id": "",
                    "subject_id": request.POST.get("subject"),
                    "teacher_id": request.POST.get("teacher"),
                }
            ]
        batch = batches.filter(pk=selected_batch_id).first()
        if not batch:
            bulk_errors.append("Please select a class / batch.")
        if not posted_rows:
            bulk_errors.append("Please add at least one subject and teacher row.")

        cleaned_rows = []
        seen_subjects = set()
        for index, row in enumerate(posted_rows, start=1):
            subject_id = str(row.get("subject_id") or "").strip()
            teacher_id = str(row.get("teacher_id") or "").strip()
            allocation_id = str(row.get("id") or "").strip()
            if not subject_id or not teacher_id:
                bulk_errors.append(f"Row {index}: subject and teacher are required.")
                continue
            subject = subjects.filter(pk=subject_id).first()
            teacher = teachers.filter(pk=teacher_id).first()
            if not subject:
                bulk_errors.append(f"Row {index}: selected subject is not valid for the active session.")
                continue
            if not teacher:
                bulk_errors.append(f"Row {index}: selected teacher is not valid for this institute.")
                continue
            if subject.pk in seen_subjects:
                bulk_errors.append(f"Row {index}: {subject.name} is already added for this class.")
                continue
            seen_subjects.add(subject.pk)
            cleaned_rows.append({"id": allocation_id, "subject": subject, "teacher": teacher})

        if not bulk_errors:
            with transaction.atomic():
                ReportCardTeacherSubjectAllocation.objects.select_for_update().filter(
                    institute=institute,
                    academic_year=academic_year,
                    batch=batch,
                ).delete()
                ReportCardTeacherSubjectAllocation.objects.bulk_create(
                    [
                        ReportCardTeacherSubjectAllocation(
                            institute=institute,
                            academic_year=academic_year,
                            batch=batch,
                            subject=row["subject"],
                            teacher=row["teacher"],
                            is_active=True,
                            created_by=request.user,
                        )
                        for row in cleaned_rows
                    ]
                )
            messages.success(request, "Teacher subject allocations saved for the selected class.")
            return redirect("report_card_admin:allocation_list")

    return render(
        request,
        "report_card/institute_admin/allocation_form.html",
        {
            "page_title": "Create Teacher Subject Allocation",
            "bulk_mode": True,
            "academic_year": academic_year,
            "batches": batches,
            "subjects": subjects,
            "teachers": teachers,
            "selected_batch_id": str(selected_batch_id),
            "bulk_errors": bulk_errors,
            "posted_rows": posted_rows,
            "subjects_json": [{"id": subject.pk, "name": subject.name} for subject in subjects],
            "teachers_json": [
                {
                    "id": teacher.pk,
                    "name": teacher.get_full_name() or teacher.username,
                }
                for teacher in teachers
            ],
            "allocations_json": [
                {
                    "id": allocation.pk,
                    "batch_id": allocation.batch_id,
                    "subject_id": allocation.subject_id,
                    "teacher_id": allocation.teacher_id,
                }
                for allocation in existing_allocations
            ],
        },
    )


@institute_admin_required
def allocation_update(request, allocation_id):
    institute = _admin_institute(request)
    allocation = get_object_or_404(ReportCardTeacherSubjectAllocation, pk=allocation_id, institute=institute)
    form = ReportCardTeacherSubjectAllocationForm(
        request.POST or None,
        instance=allocation,
        institute=institute,
        created_by=request.user,
        academic_year=allocation.academic_year,
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Teacher subject allocation updated.")
        return redirect("report_card_admin:allocation_list")
    return render(
        request,
        "report_card/institute_admin/allocation_form.html",
        {
            "allocation": allocation,
            "form": form,
            "page_title": "Edit Teacher Subject Allocation",
            "academic_year": allocation.academic_year,
        },
    )


@institute_admin_required
@require_POST
def allocation_delete(request, allocation_id):
    institute = _admin_institute(request)
    allocation = get_object_or_404(ReportCardTeacherSubjectAllocation, pk=allocation_id, institute=institute)
    allocation.delete()
    messages.success(request, "Teacher subject allocation deleted.")
    return redirect("report_card_admin:allocation_list")


@institute_admin_required
def grade_rule_list(request):
    institute = _admin_institute(request)
    academic_year = get_selected_academic_year(request)
    rules = (
        ReportCardGradeRule.objects.filter(institute=institute, academic_year=academic_year)
        .select_related("academic_year")
        .order_by("academic_year__start_date", "display_order", "-min_percentage")
    )
    active_rule_scopes = ReportCardGradeRule.objects.filter(institute=institute, academic_year=academic_year, is_active=True).values_list(
        "academic_year_id",
        flat=True,
    )
    active_scope_ids = set(active_rule_scopes)
    return render(
        request,
        "report_card/institute_admin/grade_rule_list.html",
        {
            "institute": institute,
            "rules": rules,
            "academic_year": academic_year,
            "has_active_default_rules": None in active_scope_ids,
            "academic_years_with_active_rules": active_scope_ids - {None},
            "blank_grade_assessments": _assessments_missing_grade_rules(institute),
            "default_rule_count": len(DEFAULT_GRADE_RULES),
        },
    )


@institute_admin_required
def grade_rule_create(request):
    institute = _admin_institute(request)
    academic_year = get_selected_academic_year(request)
    form = ReportCardGradeRuleForm(request.POST or None, institute=institute, academic_year=academic_year)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Grade rule created.")
        return redirect("report_card_admin:grade_rule_list")
    return render(
        request,
        "report_card/institute_admin/grade_rule_form.html",
        {
            "form": form,
            "page_title": "Create Grade Rule",
            "academic_year": academic_year,
        },
    )


@institute_admin_required
def grade_rule_update(request, rule_id):
    institute = _admin_institute(request)
    rule = get_object_or_404(ReportCardGradeRule, pk=rule_id, institute=institute)
    form = ReportCardGradeRuleForm(request.POST or None, instance=rule, institute=institute, academic_year=rule.academic_year)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Grade rule updated.")
        return redirect("report_card_admin:grade_rule_list")
    return render(
        request,
        "report_card/institute_admin/grade_rule_form.html",
        {
            "form": form,
            "grade_rule": rule,
            "page_title": "Edit Grade Rule",
            "academic_year": rule.academic_year,
        },
    )


@institute_admin_required
@require_POST
def grade_rule_delete(request, rule_id):
    institute = _admin_institute(request)
    rule = get_object_or_404(ReportCardGradeRule, pk=rule_id, institute=institute)
    rule.delete()
    messages.success(request, "Grade rule deleted.")
    return redirect("report_card_admin:grade_rule_list")


@institute_admin_required
@require_POST
def grade_rule_create_defaults(request):
    institute = _admin_institute(request)
    scope = request.POST.get("scope") or "academic_year"
    academic_year_id = request.POST.get("academic_year_id") or ""
    academic_year = get_selected_academic_year(request)
    if scope == "academic_year" and academic_year_id:
        academic_year = get_object_or_404(AcademicYear, pk=academic_year_id, institute=institute)

    existing_active = ReportCardGradeRule.objects.filter(
        institute=institute,
        academic_year=academic_year,
        is_active=True,
    ).exists()
    if existing_active:
        scope_label = academic_year.name if academic_year else "institute default"
        messages.warning(request, f"Active grade rules already exist for {scope_label}. Delete or edit existing rules before creating defaults.")
        return redirect("report_card_admin:grade_rule_list")

    created_count = 0
    for order, (minimum, maximum, grade, remark) in enumerate(DEFAULT_GRADE_RULES, start=1):
        ReportCardGradeRule.objects.create(
            institute=institute,
            academic_year=academic_year,
            min_percentage=minimum,
            max_percentage=maximum,
            grade=grade,
            remark=remark,
            display_order=order,
            is_active=True,
        )
        created_count += 1
    scope_label = academic_year.name if academic_year else "institute default"
    messages.success(request, f"Created {created_count} default grade rules for {scope_label}.")
    return redirect("report_card_admin:grade_rule_list")


@institute_admin_required
@require_POST
def admin_unlock_assessment(request, assessment_id):
    institute = _admin_institute(request)
    assessment = get_object_or_404(ReportCardAssessment, pk=assessment_id, institute=institute)
    if not admin_can_manage_assessment(request.user, assessment):
        messages.error(request, "You cannot manage this assessment.")
        return redirect("report_card_admin:grade_rule_list")

    target_status = request.POST.get("target_status") or ReportCardAssessment.Status.MARKS_ENTRY_OPEN
    try:
        unlock_assessment_for_admin(assessment, actor=request.user, target_status=target_status)
        messages.success(request, f"Assessment unlocked to {target_status}.")
    except ValidationError as error:
        _handle_validation_error(request, error)
    return redirect("report_card_admin:grade_rule_list")
