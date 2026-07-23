"""Read/query helpers for the Report Card Generator app."""

from datetime import date

from django.db.models import Case, IntegerField, Prefetch, Value, When
from django.utils import timezone

from institute_admin.models import AcademicYear, Batch, Subject
from student_parent.models import StudentAcademicSession, StudentEnrollment

from .models import (
    ReportCardAssessment,
    ReportCardAssessmentSubject,
    ReportCardAssessmentSubjectComponent,
    ReportCardComponentMarkEntry,
    ReportCardMarkEntry,
    ReportCardStudentResult,
    ReportCardTeacherSubjectAllocation,
)


def _current_academic_year_label(today=None):
    today = today or timezone.localdate()
    start_year = today.year if today.month >= 4 else today.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def _academic_year_dates(name):
    start_year = int(str(name).split("-", 1)[0])
    return date(start_year, 4, 1), date(start_year + 1, 3, 31)


def _get_or_create_academic_year(institute):
    name = _current_academic_year_label()
    start_date, end_date = _academic_year_dates(name)
    academic_year, _created = AcademicYear.objects.get_or_create(
        institute=institute,
        name=name,
        defaults={
            "start_date": start_date,
            "end_date": end_date,
            "is_active": True,
        },
    )
    return academic_year


def get_teacher_institute(user):
    teacher_profile = getattr(user, "teacher_profile", None)
    if teacher_profile and teacher_profile.institute_id:
        return teacher_profile.institute
    assigned_batch = (
        Batch.objects.filter(teachers=user, is_active=True)
        .select_related("institute")
        .order_by("pk")
        .first()
    )
    if assigned_batch:
        return assigned_batch.institute
    profile = getattr(user, "profile", None)
    if not profile or not profile.institute_id:
        return None
    return profile.institute


def get_selected_academic_year(request):
    institute = get_teacher_institute(request.user)
    if not institute:
        return None

    requested_year_id = (
        getattr(request, "query_params", {}).get("academic_year_id")
        if hasattr(request, "query_params")
        else request.GET.get("academic_year_id")
    )
    if requested_year_id:
        academic_year = institute.academic_years.filter(pk=requested_year_id, is_active=True).first()
        if academic_year:
            return academic_year

    session_year_id = request.session.get("academic_year_id")
    if session_year_id:
        academic_year = institute.academic_years.filter(pk=session_year_id, is_active=True).first()
        if academic_year:
            return academic_year

    academic_year = _get_or_create_academic_year(institute)
    request.session["academic_year_id"] = academic_year.pk
    return academic_year


def get_teacher_assigned_batches(user, academic_year=None):
    institute = get_teacher_institute(user)
    if not institute:
        return Batch.objects.none()

    batches = (
        Batch.objects.filter(institute=institute, teachers=user, is_active=True)
        .select_related("institute", "academic_year")
        .prefetch_related("courses")
    )
    if academic_year:
        batches = batches.filter(academic_year=academic_year)
    return batches.order_by("academic_year__start_date", "name")


def get_available_subjects(institute, academic_year=None):
    if not institute:
        return Subject.objects.none()

    subjects = Subject.objects.filter(institute=institute, is_active=True).select_related("academic_year")
    if academic_year:
        subjects = subjects.filter(academic_year=academic_year)
    return subjects.order_by("academic_year__start_date", "name")


def get_teacher_report_card_allocations(user, academic_year=None):
    institute = get_teacher_institute(user)
    if not user or not institute:
        return ReportCardTeacherSubjectAllocation.objects.none()

    allocations = (
        ReportCardTeacherSubjectAllocation.objects.filter(
            institute=institute,
            teacher=user,
            is_active=True,
        )
        .select_related("institute", "academic_year", "batch", "subject", "teacher")
    )
    if academic_year:
        allocations = allocations.filter(academic_year=academic_year)
    return allocations.order_by("academic_year__start_date", "batch__name", "subject__name")


def teacher_has_subject_allocation(user, assessment_subject):
    if not user or not assessment_subject:
        return False
    assessment = assessment_subject.assessment
    return get_teacher_report_card_allocations(user, academic_year=assessment.academic_year).filter(
        institute=assessment.institute,
        batch=assessment.batch,
        subject=assessment_subject.subject,
    ).exists()


def get_teacher_allocated_batches(user, academic_year=None):
    allocations = get_teacher_report_card_allocations(user, academic_year=academic_year)
    return (
        Batch.objects.filter(report_card_teacher_subject_allocations__in=allocations, is_active=True)
        .select_related("institute", "academic_year")
        .distinct()
        .order_by("academic_year__start_date", "name")
    )


def get_teacher_allocated_subjects(user, batch=None, academic_year=None):
    allocations = get_teacher_report_card_allocations(user, academic_year=academic_year)
    if batch:
        allocations = allocations.filter(batch=batch)
    return (
        Subject.objects.filter(report_card_teacher_subject_allocations__in=allocations, is_active=True)
        .select_related("institute", "academic_year")
        .distinct()
        .order_by("academic_year__start_date", "name")
    )


def get_teacher_accessible_assessment_subjects(user, assessment):
    if not user or not assessment:
        return ReportCardAssessmentSubject.objects.none()
    allocations = get_teacher_report_card_allocations(user, academic_year=assessment.academic_year).filter(
        institute=assessment.institute,
        batch=assessment.batch,
    )
    return (
        ReportCardAssessmentSubject.objects.filter(
            assessment=assessment,
            subject__in=allocations.values("subject"),
        )
        .select_related("assessment", "subject")
        .prefetch_related("components")
        .order_by("display_order", "subject_name_snapshot", "id")
    )


def get_teacher_accessible_assessments(user, academic_year=None):
    allocations = get_teacher_report_card_allocations(user, academic_year=academic_year)
    if not allocations.exists():
        return ReportCardAssessment.objects.none()

    assessments = (
        ReportCardAssessment.objects.filter(
            institute__in=allocations.values("institute"),
            academic_year__in=allocations.values("academic_year"),
            batch__in=allocations.values("batch"),
            assessment_subjects__subject__in=allocations.values("subject"),
        )
        .select_related("institute", "academic_year", "batch", "created_by")
        .prefetch_related(
            Prefetch(
                "assessment_subjects",
                queryset=ReportCardAssessmentSubject.objects.select_related("subject").order_by(
                    "display_order",
                    "subject_name_snapshot",
                    "id",
                ).prefetch_related("components"),
            )
        )
        .distinct()
    )
    if academic_year:
        assessments = assessments.filter(academic_year=academic_year)
    return assessments.order_by("-created_at", "title")


def get_assessments_for_teacher(user, academic_year=None):
    institute = get_teacher_institute(user)
    if not institute:
        return ReportCardAssessment.objects.none()

    assigned_batches = get_teacher_assigned_batches(user, academic_year=academic_year)
    assessments = (
        ReportCardAssessment.objects.filter(institute=institute, batch__in=assigned_batches)
        .select_related("institute", "academic_year", "batch", "created_by")
        .prefetch_related(
            Prefetch(
                "assessment_subjects",
                queryset=ReportCardAssessmentSubject.objects.select_related("subject").order_by(
                    "display_order",
                    "subject_name_snapshot",
                    "id",
                ).prefetch_related("components"),
            )
        )
    )
    if academic_year:
        assessments = assessments.filter(academic_year=academic_year)
    return assessments.order_by("-created_at", "title")


def get_assessment_subjects(assessment):
    if not assessment:
        return ReportCardAssessmentSubject.objects.none()
    return (
        ReportCardAssessmentSubject.objects.filter(assessment=assessment)
        .select_related("assessment", "subject")
        .prefetch_related("components")
        .order_by("display_order", "subject_name_snapshot", "id")
    )


def get_assessment_subject_components(assessment_subject):
    if not assessment_subject:
        return ReportCardAssessmentSubjectComponent.objects.none()
    return ReportCardAssessmentSubjectComponent.objects.filter(assessment_subject=assessment_subject).order_by(
        "display_order",
        "name_snapshot",
        "id",
    )


def get_active_student_sessions_for_assessment(assessment):
    if not assessment:
        return StudentAcademicSession.objects.none()

    return (
        StudentAcademicSession.objects.filter(
            institute=assessment.institute,
            academic_year=assessment.academic_year,
            enrollments__batch=assessment.batch,
            enrollments__status=StudentEnrollment.Status.ACTIVE,
            status=StudentAcademicSession.Status.ACTIVE,
            student__is_active=True,
        )
        .select_related("student", "student__user", "academic_year", "institute")
        .distinct()
        .annotate(
            roll_missing=Case(
                When(student__roll_number="", then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            )
        )
        .order_by(
            "roll_missing",
            "student__roll_number",
            "admission_number",
            "student__user__first_name",
            "student__user__username",
        )
    )


def get_marks_grid(assessment_subject):
    if not assessment_subject:
        return []

    sessions = list(get_active_student_sessions_for_assessment(assessment_subject.assessment))
    components = list(get_assessment_subject_components(assessment_subject))
    mark_entries = {
        entry.academic_session_id: entry
        for entry in ReportCardMarkEntry.objects.filter(
            assessment_subject=assessment_subject,
            academic_session__in=sessions,
        ).select_related("student", "student__user", "academic_session", "entered_by", "updated_by")
    }
    component_entries = {}
    if components:
        component_ids = [component.pk for component in components]
        for entry in ReportCardComponentMarkEntry.objects.filter(
            component_id__in=component_ids,
            academic_session__in=sessions,
        ).select_related("component", "student", "student__user", "academic_session"):
            component_entries.setdefault(entry.academic_session_id, {})[entry.component_id] = entry

    return [
        {
            "academic_session": session,
            "student": session.student,
            "mark_entry": mark_entries.get(session.pk),
            "component_entries": component_entries.get(session.pk, {}),
        }
        for session in sessions
    ]


def get_completion_summary(assessment, assessment_subjects=None):
    if not assessment:
        return {
            "assessment": None,
            "student_count": 0,
            "subject_count": 0,
            "expected_mark_count": 0,
            "entered_mark_count": 0,
            "missing_mark_count": 0,
            "absent_mark_count": 0,
            "is_complete": False,
            "subjects": [],
        }

    sessions = list(get_active_student_sessions_for_assessment(assessment))
    session_ids = [session.pk for session in sessions]
    subjects = list(assessment_subjects) if assessment_subjects is not None else list(get_assessment_subjects(assessment))
    subject_ids = [subject.pk for subject in subjects]
    components_by_subject = {
        subject.pk: list(subject.components.all())
        for subject in subjects
    }

    mark_entries = ReportCardMarkEntry.objects.filter(
        assessment_subject_id__in=subject_ids,
        academic_session_id__in=session_ids,
    )
    component_entries = ReportCardComponentMarkEntry.objects.filter(
        component__assessment_subject_id__in=subject_ids,
        academic_session_id__in=session_ids,
    )
    entered_by_subject = {}
    absent_by_subject = {}
    for entry in mark_entries.only("assessment_subject_id", "academic_session_id", "is_absent", "marks_obtained"):
        if entry.is_absent or entry.marks_obtained is not None:
            entered_by_subject.setdefault(entry.assessment_subject_id, set()).add(entry.academic_session_id)
        if entry.is_absent:
            absent_by_subject[entry.assessment_subject_id] = absent_by_subject.get(entry.assessment_subject_id, 0) + 1
    component_entered_by_subject = {}
    component_absent_by_subject = {}
    for entry in component_entries.only(
        "component__assessment_subject_id",
        "academic_session_id",
        "is_absent",
        "marks_obtained",
    ):
        subject_id = entry.component.assessment_subject_id
        if entry.is_absent or entry.marks_obtained is not None:
            component_entered_by_subject.setdefault(subject_id, set()).add((entry.academic_session_id, entry.component_id))
        if entry.is_absent:
            component_absent_by_subject[subject_id] = component_absent_by_subject.get(subject_id, 0) + 1

    subject_summaries = []
    entered_total = 0
    absent_total = 0
    for subject in subjects:
        components = components_by_subject.get(subject.pk, [])
        if components:
            expected_count = len(session_ids) * len(components)
            entered_count = len(component_entered_by_subject.get(subject.pk, set()))
            absent_count = component_absent_by_subject.get(subject.pk, 0)
        else:
            expected_count = len(session_ids)
            entered_count = len(entered_by_subject.get(subject.pk, set()))
            absent_count = absent_by_subject.get(subject.pk, 0)
        missing_count = max(expected_count - entered_count, 0)
        entered_total += entered_count
        absent_total += absent_count
        subject_summaries.append(
            {
                "assessment_subject": subject,
                "expected_mark_count": expected_count,
                "entered_mark_count": entered_count,
                "missing_mark_count": missing_count,
                "absent_mark_count": absent_count,
                "is_complete": missing_count == 0,
            }
        )

    expected_total = sum(item["expected_mark_count"] for item in subject_summaries)
    missing_total = max(expected_total - entered_total, 0)
    return {
        "assessment": assessment,
        "student_count": len(session_ids),
        "subject_count": len(subjects),
        "expected_mark_count": expected_total,
        "entered_mark_count": entered_total,
        "missing_mark_count": missing_total,
        "absent_mark_count": absent_total,
        "is_complete": expected_total > 0 and missing_total == 0,
        "subjects": subject_summaries,
    }


def get_generated_results(assessment):
    if not assessment:
        return ReportCardStudentResult.objects.none()
    return (
        ReportCardStudentResult.objects.filter(assessment=assessment)
        .select_related("assessment", "student", "student__user", "academic_session")
        .order_by("rank", "-percentage", "admission_number_snapshot")
    )


def get_published_results_for_student(student, academic_session=None):
    if not student:
        return ReportCardStudentResult.objects.none()

    results = (
        ReportCardStudentResult.objects.filter(
            student=student,
            assessment__status__in=[
                ReportCardAssessment.Status.PUBLISHED,
                ReportCardAssessment.Status.LOCKED,
            ],
            is_stale=False,
        )
        .select_related("assessment", "assessment__academic_year", "assessment__batch", "academic_session")
        .order_by("-published_at", "-generated_at", "assessment__title")
    )
    if academic_session:
        results = results.filter(academic_session=academic_session)
    return results


def get_result_subject_rows(result):
    if not result:
        return []

    assessment_subjects = list(get_assessment_subjects(result.assessment))
    stored_subject_results = {
        subject_result.assessment_subject_id: subject_result
        for subject_result in result.subject_results.select_related("assessment_subject")
    }
    entries = {
        entry.assessment_subject_id: entry
        for entry in ReportCardMarkEntry.objects.filter(
            assessment_subject__assessment=result.assessment,
            academic_session=result.academic_session,
        ).select_related("assessment_subject")
    }
    component_entries = {}
    for entry in ReportCardComponentMarkEntry.objects.filter(
        component__assessment_subject__assessment=result.assessment,
        academic_session=result.academic_session,
    ).select_related("component"):
        component_entries.setdefault(entry.component.assessment_subject_id, []).append(entry)
    return [
        {
            "assessment_subject": assessment_subject,
            "mark_entry": entries.get(assessment_subject.pk),
            "subject_result": stored_subject_results.get(assessment_subject.pk),
            "component_entries": sorted(
                component_entries.get(assessment_subject.pk, []),
                key=lambda entry: (entry.component.display_order, entry.component.name_snapshot, entry.component_id),
            ),
        }
        for assessment_subject in assessment_subjects
    ]
