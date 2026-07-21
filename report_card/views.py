from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from student_parent.models import StudentAcademicSession
from super_admin.decorators import institute_admin_required, student_parent_required, teacher_required

from .forms import (
    BulkMarksEntryForm,
    ReportCardAssessmentForm,
    ReportCardAssessmentSubjectComponentForm,
    ReportCardAssessmentSubjectForm,
    ReportCardGradeRuleForm,
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
)
from .permissions import (
    admin_can_manage_assessment,
    student_can_view_result,
    teacher_can_access_assessment,
    teacher_can_edit_assessment,
    teacher_can_enter_marks,
)
from .selectors import (
    get_assessment_subjects,
    get_assessment_subject_components,
    get_assessments_for_teacher,
    get_completion_summary,
    get_generated_results,
    get_marks_grid,
    get_published_results_for_student,
    get_result_subject_rows,
    get_selected_academic_year,
    get_teacher_assigned_batches,
    get_teacher_institute,
)
from .services import (
    add_assessment_subject,
    add_assessment_subject_component,
    bulk_save_subject_marks,
    create_assessment,
    generate_assessment_results,
    lock_assessment as lock_assessment_service,
    open_marks_entry,
    publish_assessment_results,
    remove_assessment_subject,
    remove_assessment_subject_component,
    sync_assessment_subject_components,
    update_assessment,
    update_assessment_subject,
    update_assessment_subject_component,
    unlock_assessment_for_admin,
    validate_marks_completion,
)


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
    return get_assessments_for_teacher(request.user, academic_year=academic_year)


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


@teacher_required
def assessment_list(request):
    academic_year = get_selected_academic_year(request)
    assessments = get_assessments_for_teacher(request.user, academic_year=academic_year)
    batch_options = get_teacher_assigned_batches(request.user, academic_year=academic_year)
    all_assigned_batches = get_teacher_assigned_batches(request.user)
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
        assessment.first_assessment_subject = next(iter(assessment.assessment_subjects.all()), None)

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
    institute = get_teacher_institute(request.user)
    academic_year = get_selected_academic_year(request)
    form = ReportCardAssessmentForm(
        request.POST or None,
        user=request.user,
        institute=institute,
        academic_year=academic_year,
    )
    if request.method == "POST" and form.is_valid():
        assessment = create_assessment(
            institute=form.effective_institute,
            academic_year=form.cleaned_data["academic_year"],
            batch=form.cleaned_data["batch"],
            title=form.cleaned_data["title"],
            assessment_date=form.cleaned_data.get("assessment_date"),
            result_date=form.cleaned_data.get("result_date"),
            created_by=request.user,
        )
        messages.success(request, "Report card assessment created.")
        return _close_report_card_popup_response("/teacher/report-cards/")

    return render(
        request,
        "report_card/teacher/assessment_form.html",
        {
            "form": form,
            "academic_year": academic_year,
            "page_title": "Create Report Card Assessment",
        },
    )


@teacher_required
def assessment_update(request, assessment_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    if not teacher_can_edit_assessment(request.user, assessment):
        messages.error(request, "You cannot edit this assessment.")
        return redirect("report_card:assessment_detail", assessment_id=assessment.pk)

    form = ReportCardAssessmentForm(
        request.POST or None,
        instance=assessment,
        user=request.user,
        institute=assessment.institute,
        academic_year=assessment.academic_year,
    )
    if request.method == "POST" and form.is_valid():
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
        return redirect("report_card:assessment_detail", assessment_id=assessment.pk)

    return render(
        request,
        "report_card/teacher/assessment_form.html",
        {
            "assessment": assessment,
            "form": form,
            "academic_year": assessment.academic_year,
            "page_title": "Edit Report Card Assessment",
        },
    )


@teacher_required
def assessment_detail(request, assessment_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    subjects = list(get_assessment_subjects(assessment))
    summary = get_completion_summary(assessment)
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
    results = get_generated_results(assessment)
    return render(
        request,
        "report_card/teacher/assessment_detail.html",
        {
            "assessment": assessment,
            "subjects": subjects,
            "summary": summary,
            "results": results,
        },
    )


@teacher_required
def assessment_structure(request, assessment_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    subjects = list(get_assessment_subjects(assessment))
    can_edit = teacher_can_edit_assessment(request.user, assessment)
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
            "summary": summary,
        },
    )


@teacher_required
def assessment_subject_create(request, assessment_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    if not teacher_can_edit_assessment(request.user, assessment):
        messages.error(request, "You cannot change this assessment structure.")
        return redirect("report_card:assessment_structure", assessment_id=assessment.pk)

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
            return redirect("report_card:assessment_structure", assessment_id=assessment.pk)
        except ValidationError as error:
            _handle_validation_error(request, error)

    return render(
        request,
        "report_card/teacher/assessment_subject_form.html",
        {
            "assessment": assessment,
            "form": form,
            "page_title": "Add Assessment Subject",
        },
    )


@teacher_required
def assessment_subject_update(request, assessment_id, assessment_subject_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    assessment_subject = _get_assessment_subject_or_404(assessment, assessment_subject_id)
    if not teacher_can_edit_assessment(request.user, assessment):
        messages.error(request, "You cannot change this assessment structure.")
        return redirect("report_card:assessment_structure", assessment_id=assessment.pk)

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
            return redirect("report_card:assessment_structure", assessment_id=assessment.pk)
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
        },
    )


@teacher_required
@require_POST
def assessment_subject_delete(request, assessment_id, assessment_subject_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    assessment_subject = _get_assessment_subject_or_404(assessment, assessment_subject_id)
    if not teacher_can_edit_assessment(request.user, assessment):
        messages.error(request, "You cannot change this assessment structure.")
        return redirect("report_card:assessment_structure", assessment_id=assessment.pk)

    try:
        remove_assessment_subject(assessment_subject, actor=request.user)
        messages.success(request, "Assessment subject removed.")
    except ValidationError as error:
        _handle_validation_error(request, error)
    return redirect("report_card:assessment_structure", assessment_id=assessment.pk)


@teacher_required
def assessment_subject_component_create(request, assessment_id, assessment_subject_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    assessment_subject = _get_assessment_subject_or_404(assessment, assessment_subject_id)
    if not teacher_can_edit_assessment(request.user, assessment):
        messages.error(request, "You cannot change this subject structure.")
        return redirect("report_card:assessment_structure", assessment_id=assessment.pk)

    form = ReportCardAssessmentSubjectComponentForm(request.POST or None, assessment_subject=assessment_subject)
    if request.method == "POST" and form.is_valid():
        try:
            add_assessment_subject_component(
                assessment_subject,
                name=form.cleaned_data["name"],
                max_marks=form.cleaned_data["max_marks"],
                passing_marks=form.cleaned_data["passing_marks"],
                weightage=form.cleaned_data["weightage"],
                display_order=form.cleaned_data["display_order"],
                include_in_total=form.cleaned_data["include_in_total"],
                actor=request.user,
            )
            messages.success(request, "Subject column added.")
            return redirect("report_card:assessment_structure", assessment_id=assessment.pk)
        except ValidationError as error:
            _handle_validation_error(request, error)

    return render(
        request,
        "report_card/teacher/assessment_component_form.html",
        {
            "assessment": assessment,
            "assessment_subject": assessment_subject,
            "form": form,
            "page_title": "Add Subject Column",
        },
    )


@teacher_required
def assessment_subject_component_update(request, assessment_id, assessment_subject_id, component_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    assessment_subject = _get_assessment_subject_or_404(assessment, assessment_subject_id)
    component = _get_subject_component_or_404(assessment_subject, component_id)
    if not teacher_can_edit_assessment(request.user, assessment):
        messages.error(request, "You cannot change this subject structure.")
        return redirect("report_card:assessment_structure", assessment_id=assessment.pk)

    form = ReportCardAssessmentSubjectComponentForm(
        request.POST or None,
        instance=component,
        assessment_subject=assessment_subject,
    )
    if request.method == "POST" and form.is_valid():
        try:
            update_assessment_subject_component(
                component,
                name=form.cleaned_data["name"],
                max_marks=form.cleaned_data["max_marks"],
                passing_marks=form.cleaned_data["passing_marks"],
                weightage=form.cleaned_data["weightage"],
                display_order=form.cleaned_data["display_order"],
                include_in_total=form.cleaned_data["include_in_total"],
                actor=request.user,
            )
            messages.success(request, "Subject column updated.")
            return redirect("report_card:assessment_structure", assessment_id=assessment.pk)
        except ValidationError as error:
            _handle_validation_error(request, error)

    return render(
        request,
        "report_card/teacher/assessment_component_form.html",
        {
            "assessment": assessment,
            "assessment_subject": assessment_subject,
            "component": component,
            "form": form,
            "page_title": "Edit Subject Column",
        },
    )


@teacher_required
@require_POST
def assessment_subject_component_delete(request, assessment_id, assessment_subject_id, component_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    assessment_subject = _get_assessment_subject_or_404(assessment, assessment_subject_id)
    component = _get_subject_component_or_404(assessment_subject, component_id)
    if not teacher_can_edit_assessment(request.user, assessment):
        messages.error(request, "You cannot change this subject structure.")
        return redirect("report_card:assessment_structure", assessment_id=assessment.pk)

    try:
        remove_assessment_subject_component(component, actor=request.user)
        messages.success(request, "Subject column removed.")
    except ValidationError as error:
        _handle_validation_error(request, error)
    return redirect("report_card:assessment_structure", assessment_id=assessment.pk)


@teacher_required
def marks_entry(request, assessment_id, assessment_subject_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    assessment_subject = _get_assessment_subject_or_404(assessment, assessment_subject_id)
    if not teacher_can_enter_marks(request.user, assessment):
        messages.error(request, "Marks entry is not open for this assessment.")
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
    return marks_entry_template_response(assessment_subject)


@teacher_required
@require_POST
def marks_entry_import(request, assessment_id, assessment_subject_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    assessment_subject = _get_assessment_subject_or_404(assessment, assessment_subject_id)
    if not teacher_can_enter_marks(request.user, assessment):
        messages.error(request, "Marks import is allowed only while marks entry is open.")
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
    return redirect("report_card:marks_entry", assessment_id=assessment.pk, assessment_subject_id=assessment_subject.pk)


@teacher_required
def completion_summary(request, assessment_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    summary = validate_marks_completion(assessment)
    required_expected = summary.get("required_expected_mark_count") or summary.get("expected_mark_count") or 0
    required_missing = summary.get("required_missing_mark_count", summary.get("missing_mark_count", 0))
    required_entered = max(required_expected - required_missing, 0)
    completion_percentage = round((required_entered / required_expected) * 100, 1) if required_expected else 0
    return render(
        request,
        "report_card/teacher/completion_summary.html",
        {
            "assessment": assessment,
            "completion_percentage": completion_percentage,
            "summary": summary,
        },
    )


@teacher_required
@require_POST
def generate_results(request, assessment_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    if not teacher_can_edit_assessment(request.user, assessment):
        messages.error(request, "You cannot generate results for this assessment.")
        return redirect("report_card:assessment_detail", assessment_id=assessment.pk)

    try:
        generate_assessment_results(assessment, actor=request.user)
        messages.success(request, "Report card results generated.")
        return redirect("report_card:results_preview", assessment_id=assessment.pk)
    except ValidationError as error:
        _handle_validation_error(request, error)
        return redirect("report_card:completion_summary", assessment_id=assessment.pk)


@teacher_required
def results_preview(request, assessment_id):
    assessment = _get_teacher_assessment(request, assessment_id)
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
            "results": results,
            "filter_result_status": filter_result_status,
            "filter_stale": filter_stale,
            "result_status_choices": ReportCardStudentResult.ResultStatus.choices,
            "search_query": search_query,
            "summary": summary,
        },
    )


@teacher_required
def results_export(request, assessment_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    return consolidated_results_response(assessment)


@teacher_required
def result_pdf_download(request, assessment_id, result_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    result = get_object_or_404(
        ReportCardStudentResult.objects.select_related("assessment", "student", "student__user", "academic_session"),
        pk=result_id,
        assessment=assessment,
    )
    return report_card_pdf_response(result)


@teacher_required
@require_POST
def publish_results(request, assessment_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    if not teacher_can_edit_assessment(request.user, assessment):
        messages.error(request, "You cannot publish this assessment.")
        return redirect("report_card:results_preview", assessment_id=assessment.pk)

    try:
        publish_assessment_results(assessment, actor=request.user)
        messages.success(request, "Report card results published.")
    except ValidationError as error:
        _handle_validation_error(request, error)
    return redirect("report_card:results_preview", assessment_id=assessment.pk)


@teacher_required
@require_POST
def lock_assessment(request, assessment_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    if not teacher_can_access_assessment(request.user, assessment):
        messages.error(request, "You cannot lock this assessment.")
        return redirect("report_card:assessment_list")

    try:
        lock_assessment_service(assessment, actor=request.user)
        messages.success(request, "Report card assessment locked.")
    except ValidationError as error:
        _handle_validation_error(request, error)
    return redirect("report_card:assessment_detail", assessment_id=assessment.pk)


@teacher_required
@require_POST
def open_marks_entry_view(request, assessment_id):
    assessment = _get_teacher_assessment(request, assessment_id)
    if not teacher_can_edit_assessment(request.user, assessment):
        messages.error(request, "You cannot open marks entry for this assessment.")
        return redirect("report_card:assessment_detail", assessment_id=assessment.pk)

    try:
        open_marks_entry(assessment, actor=request.user)
        messages.success(request, "Marks entry opened.")
    except ValidationError as error:
        _handle_validation_error(request, error)
    return redirect("report_card:assessment_detail", assessment_id=assessment.pk)


def _student_from_request(request):
    return getattr(request.user, "student_profile", None)


def _selected_student_session(student, request):
    session_id = (request.GET.get("academic_session_id") or "").strip()
    sessions = StudentAcademicSession.objects.filter(student=student).select_related("academic_year", "institute")
    if session_id:
        selected = sessions.filter(pk=session_id).first()
        if selected:
            return selected
    return sessions.filter(status=StudentAcademicSession.Status.ACTIVE).order_by("-academic_year__start_date", "-pk").first()


@student_parent_required
def published_report_cards(request):
    student = _student_from_request(request)
    if not student:
        messages.error(request, "No student profile is linked to this account.")
        return redirect("student_parent:download_app")

    sessions = StudentAcademicSession.objects.filter(student=student).select_related("academic_year")
    selected_session = _selected_student_session(student, request)
    results = get_published_results_for_student(student, academic_session=selected_session)
    return render(
        request,
        "report_card/student_parent/published_report_cards.html",
        {
            "student": student,
            "sessions": sessions,
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


@institute_admin_required
def grade_rule_list(request):
    institute = _admin_institute(request)
    rules = (
        ReportCardGradeRule.objects.filter(institute=institute)
        .select_related("academic_year")
        .order_by("academic_year__start_date", "display_order", "-min_percentage")
    )
    return render(
        request,
        "report_card/institute_admin/grade_rule_list.html",
        {
            "institute": institute,
            "rules": rules,
        },
    )


@institute_admin_required
def grade_rule_create(request):
    institute = _admin_institute(request)
    form = ReportCardGradeRuleForm(request.POST or None, institute=institute)
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
        },
    )


@institute_admin_required
def grade_rule_update(request, rule_id):
    institute = _admin_institute(request)
    rule = get_object_or_404(ReportCardGradeRule, pk=rule_id, institute=institute)
    form = ReportCardGradeRuleForm(request.POST or None, instance=rule, institute=institute)
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
