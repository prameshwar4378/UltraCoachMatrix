"""Business logic for the Report Card Generator app."""

from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    ReportCardAssessment,
    ReportCardAssessmentSubject,
    ReportCardAssessmentSubjectComponent,
    ReportCardAuditLog,
    ReportCardComponentMarkEntry,
    ReportCardGradeRule,
    ReportCardMarkEntry,
    ReportCardStudentResult,
    ReportCardSubjectResult,
    ReportCardTeacherSubjectAllocation,
)
from .selectors import (
    get_assessment_subject_components,
    get_active_student_sessions_for_assessment,
    get_assessment_subjects,
    get_completion_summary,
)


EDIT_BLOCKED_STATUSES = {
    ReportCardAssessment.Status.PUBLISHED,
    ReportCardAssessment.Status.LOCKED,
}
STRUCTURE_EDIT_STATUSES = {
    ReportCardAssessment.Status.DRAFT,
    ReportCardAssessment.Status.STRUCTURE_READY,
}
MARKS_EDIT_STATUSES = {
    ReportCardAssessment.Status.MARKS_ENTRY_OPEN,
    ReportCardAssessment.Status.MARKS_ENTRY_COMPLETED,
    ReportCardAssessment.Status.GENERATED,
}


def _actor_role(actor):
    profile = getattr(actor, "profile", None)
    return getattr(profile, "role", None)


def _actor_institute_id(actor):
    profile = getattr(actor, "profile", None)
    return getattr(profile, "institute_id", None)


def _actor_is_teacher(actor):
    return _actor_role(actor) == "TEACHER"


def _actor_can_admin_manage_marks(actor, assessment):
    if not actor:
        return True
    if getattr(actor, "is_superuser", False):
        return True
    role = _actor_role(actor)
    return role in {"INSTITUTE_ADMIN", "ACCOUNTANT"} and _actor_institute_id(actor) == assessment.institute_id


def _enforce_marks_save_permission(assessment_subject, actor):
    if not actor:
        return
    assessment = assessment_subject.assessment
    if _actor_is_teacher(actor):
        allowed = ReportCardTeacherSubjectAllocation.objects.filter(
            institute=assessment.institute,
            academic_year=assessment.academic_year,
            batch=assessment.batch,
            subject=assessment_subject.subject,
            teacher=actor,
            is_active=True,
        ).exists()
        if not allowed:
            raise ValidationError("You can save marks only for your allocated report-card subject.")
        return
    if not _actor_can_admin_manage_marks(actor, assessment):
        raise ValidationError("You do not have permission to save report-card marks.")
TWO_PLACES = Decimal("0.01")


def _quantize(value):
    if value is None:
        return None
    return Decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _require_not_published_or_locked(assessment):
    if assessment.status in EDIT_BLOCKED_STATUSES:
        raise ValidationError("Published or locked assessments cannot be changed.")


def _mark_results_stale_after_change(assessment):
    if assessment.status in {
        ReportCardAssessment.Status.STRUCTURE_READY,
        ReportCardAssessment.Status.MARKS_ENTRY_OPEN,
        ReportCardAssessment.Status.MARKS_ENTRY_COMPLETED,
        ReportCardAssessment.Status.GENERATED,
    }:
        ReportCardStudentResult.objects.filter(assessment=assessment).update(is_stale=True)
    if assessment.status == ReportCardAssessment.Status.GENERATED:
        assessment.status = ReportCardAssessment.Status.MARKS_ENTRY_OPEN
        assessment.save(update_fields=["status", "updated_at"])


def _snapshot_student_name(student):
    return student.user.get_full_name() or student.user.username


def write_audit_log(assessment, action, *, actor=None, message="", metadata=None):
    return ReportCardAuditLog.objects.create(
        assessment=assessment,
        actor=actor,
        action=action,
        message=message,
        metadata=metadata or {},
    )


def create_assessment(*, institute, academic_year, batch, title, created_by=None, assessment_date=None, result_date=None):
    assessment = ReportCardAssessment(
        institute=institute,
        academic_year=academic_year,
        batch=batch,
        title=title,
        assessment_date=assessment_date,
        result_date=result_date,
        created_by=created_by,
    )
    assessment.save()
    write_audit_log(
        assessment,
        ReportCardAuditLog.Action.ASSESSMENT_CREATED,
        actor=created_by,
        message="Assessment created.",
    )
    return assessment


def update_assessment(assessment, *, actor=None, **fields):
    _require_not_published_or_locked(assessment)
    allowed_fields = {"academic_year", "batch", "title", "assessment_date", "result_date", "status"}
    for field, value in fields.items():
        if field in allowed_fields:
            setattr(assessment, field, value)
    assessment.save()
    write_audit_log(
        assessment,
        ReportCardAuditLog.Action.ASSESSMENT_UPDATED,
        actor=actor,
        message="Assessment updated.",
        metadata={key: str(value) for key, value in fields.items() if key in allowed_fields},
    )
    return assessment


def add_assessment_subject(
    assessment,
    *,
    subject,
    max_marks,
    passing_marks,
    weightage=Decimal("100.00"),
    display_order=1,
    is_optional=False,
    include_in_total=True,
    actor=None,
):
    if assessment.status not in STRUCTURE_EDIT_STATUSES:
        raise ValidationError("Assessment structure can only be changed before marks entry opens.")
    assessment_subject = ReportCardAssessmentSubject(
        assessment=assessment,
        subject=subject,
        max_marks=_quantize(max_marks),
        passing_marks=_quantize(passing_marks),
        weightage=_quantize(weightage),
        display_order=display_order,
        is_optional=is_optional,
        include_in_total=include_in_total,
    )
    assessment_subject.save()
    _mark_results_stale_after_change(assessment)
    if assessment.status == ReportCardAssessment.Status.DRAFT:
        assessment.status = ReportCardAssessment.Status.STRUCTURE_READY
        assessment.save(update_fields=["status", "updated_at"])
    write_audit_log(
        assessment,
        ReportCardAuditLog.Action.STRUCTURE_CHANGED,
        actor=actor,
        message=f"Subject added: {assessment_subject.subject_name_snapshot}.",
        metadata={"assessment_subject_id": assessment_subject.pk},
    )
    return assessment_subject


def update_assessment_subject(assessment_subject, *, actor=None, **fields):
    assessment = assessment_subject.assessment
    if assessment.status not in STRUCTURE_EDIT_STATUSES:
        raise ValidationError("Assessment structure can only be changed before marks entry opens.")
    allowed_fields = {
        "subject",
        "max_marks",
        "passing_marks",
        "weightage",
        "display_order",
        "is_optional",
        "include_in_total",
    }
    for field, value in fields.items():
        if field not in allowed_fields:
            continue
        if field in {"max_marks", "passing_marks", "weightage"}:
            value = _quantize(value)
        setattr(assessment_subject, field, value)
    assessment_subject.save()
    _mark_results_stale_after_change(assessment)
    write_audit_log(
        assessment,
        ReportCardAuditLog.Action.STRUCTURE_CHANGED,
        actor=actor,
        message=f"Subject updated: {assessment_subject.subject_name_snapshot}.",
        metadata={"assessment_subject_id": assessment_subject.pk},
    )
    return assessment_subject


def remove_assessment_subject(assessment_subject, *, actor=None):
    assessment = assessment_subject.assessment
    if assessment.status not in STRUCTURE_EDIT_STATUSES:
        raise ValidationError("Assessment structure can only be changed before marks entry opens.")
    subject_name = assessment_subject.subject_name_snapshot
    subject_id = assessment_subject.pk
    assessment_subject.delete()
    _mark_results_stale_after_change(assessment)
    if not assessment.assessment_subjects.exists() and assessment.status == ReportCardAssessment.Status.STRUCTURE_READY:
        assessment.status = ReportCardAssessment.Status.DRAFT
        assessment.save(update_fields=["status", "updated_at"])
    write_audit_log(
        assessment,
        ReportCardAuditLog.Action.STRUCTURE_CHANGED,
        actor=actor,
        message=f"Subject removed: {subject_name}.",
        metadata={"assessment_subject_id": subject_id},
    )
    return assessment


def add_assessment_subject_component(
    assessment_subject,
    *,
    name,
    max_marks,
    passing_marks=Decimal("0.00"),
    weightage=Decimal("100.00"),
    display_order=1,
    include_in_total=True,
    actor=None,
):
    assessment = assessment_subject.assessment
    if assessment.status not in STRUCTURE_EDIT_STATUSES:
        raise ValidationError("Subject columns can only be changed before marks entry opens.")
    component = ReportCardAssessmentSubjectComponent(
        assessment_subject=assessment_subject,
        name=name,
        max_marks=_quantize(max_marks),
        passing_marks=_quantize(passing_marks),
        weightage=_quantize(weightage),
        display_order=display_order,
        include_in_total=include_in_total,
    )
    component.save()
    _mark_results_stale_after_change(assessment)
    write_audit_log(
        assessment,
        ReportCardAuditLog.Action.STRUCTURE_CHANGED,
        actor=actor,
        message=f"Subject column added: {component.name_snapshot}.",
        metadata={"assessment_subject_id": assessment_subject.pk, "component_id": component.pk},
    )
    return component


def update_assessment_subject_component(component, *, actor=None, **fields):
    assessment = component.assessment_subject.assessment
    if assessment.status not in STRUCTURE_EDIT_STATUSES:
        raise ValidationError("Subject columns can only be changed before marks entry opens.")
    allowed_fields = {"name", "max_marks", "passing_marks", "weightage", "display_order", "include_in_total"}
    for field, value in fields.items():
        if field not in allowed_fields:
            continue
        if field in {"max_marks", "passing_marks", "weightage"}:
            value = _quantize(value)
        setattr(component, field, value)
    component.save()
    _mark_results_stale_after_change(assessment)
    write_audit_log(
        assessment,
        ReportCardAuditLog.Action.STRUCTURE_CHANGED,
        actor=actor,
        message=f"Subject column updated: {component.name_snapshot}.",
        metadata={"assessment_subject_id": component.assessment_subject_id, "component_id": component.pk},
    )
    return component


def remove_assessment_subject_component(component, *, actor=None):
    assessment = component.assessment_subject.assessment
    if assessment.status not in STRUCTURE_EDIT_STATUSES:
        raise ValidationError("Subject columns can only be changed before marks entry opens.")
    component_name = component.name_snapshot
    component_id = component.pk
    assessment_subject_id = component.assessment_subject_id
    component.delete()
    _mark_results_stale_after_change(assessment)
    write_audit_log(
        assessment,
        ReportCardAuditLog.Action.STRUCTURE_CHANGED,
        actor=actor,
        message=f"Subject column removed: {component_name}.",
        metadata={"assessment_subject_id": assessment_subject_id, "component_id": component_id},
    )
    return assessment


@transaction.atomic
def sync_assessment_subject_components(assessment_subject, component_rows, *, actor=None):
    assessment = assessment_subject.assessment
    if assessment.status not in STRUCTURE_EDIT_STATUSES:
        raise ValidationError("Subject columns can only be changed before marks entry opens.")

    existing_components = {
        component.pk: component
        for component in ReportCardAssessmentSubjectComponent.objects.select_for_update().filter(
            assessment_subject=assessment_subject
        )
    }
    existing_count = len(existing_components)
    incoming_ids = {row.get("id") for row in component_rows if row.get("id")}

    for component in existing_components.values():
        component.name = f"__sync_{component.pk}"
        component.display_order = 100000 + component.pk
        component.save(update_fields=["name", "name_snapshot", "display_order", "updated_at"])

    saved_components = []
    for row in component_rows:
        component = existing_components.get(row.get("id"))
        if component is None:
            component = ReportCardAssessmentSubjectComponent(assessment_subject=assessment_subject)
        component.name = row["name"]
        component.max_marks = _quantize(row["max_marks"])
        component.passing_marks = Decimal("0.00")
        component.weightage = _quantize(row["max_marks"])
        component.display_order = row["display_order"]
        component.include_in_total = row["include_in_total"]
        component.save()
        saved_components.append(component)

    removed_components = [
        component
        for component_id, component in existing_components.items()
        if component_id not in incoming_ids
    ]
    removed_count = len(removed_components)
    for component in removed_components:
        component.delete()

    if component_rows or existing_count:
        _mark_results_stale_after_change(assessment)
        write_audit_log(
            assessment,
            ReportCardAuditLog.Action.STRUCTURE_CHANGED,
            actor=actor,
            message=f"Subject columns synced for {assessment_subject.subject_name_snapshot}.",
            metadata={
                "assessment_subject_id": assessment_subject.pk,
                "column_count": len(saved_components),
                "previous_column_count": existing_count,
                "removed_column_count": removed_count,
            },
        )
    return saved_components


def open_marks_entry(assessment, *, actor=None):
    _require_not_published_or_locked(assessment)
    if not assessment.assessment_subjects.exists():
        raise ValidationError("Add at least one subject before opening marks entry.")
    if assessment.status == ReportCardAssessment.Status.MARKS_ENTRY_OPEN:
        return assessment
    if assessment.status != ReportCardAssessment.Status.STRUCTURE_READY:
        raise ValidationError("Marks entry can only be opened after the assessment structure is ready.")
    assessment.status = ReportCardAssessment.Status.MARKS_ENTRY_OPEN
    assessment.save(update_fields=["status", "updated_at"])
    write_audit_log(
        assessment,
        ReportCardAuditLog.Action.MARKS_ENTRY_OPENED,
        actor=actor,
        message="Marks entry opened.",
    )
    return assessment


@transaction.atomic
def bulk_save_subject_marks(assessment_subject, mark_rows, *, actor=None):
    assessment = assessment_subject.assessment
    _enforce_marks_save_permission(assessment_subject, actor)
    if assessment.status not in MARKS_EDIT_STATUSES:
        raise ValidationError("Marks can only be entered after marks entry is opened.")
    if assessment.status in EDIT_BLOCKED_STATUSES:
        raise ValidationError("Published or locked assessments cannot be changed.")

    active_sessions = {
        session.pk: session
        for session in get_active_student_sessions_for_assessment(assessment).select_for_update()
    }
    components = list(get_assessment_subject_components(assessment_subject).select_for_update())
    components_by_id = {component.pk: component for component in components}
    saved_entries = []
    for row in mark_rows:
        session = row.get("academic_session") or active_sessions.get(row.get("academic_session_id"))
        if not session or session.pk not in active_sessions:
            raise ValidationError("One or more students are not active in this assessment batch.")

        is_absent = bool(row.get("is_absent", False))
        component_marks = row.get("component_marks") or {}
        raw_marks = row.get("marks_obtained")
        component_total = Decimal("0.00")
        included_component_missing = False
        if components:
            if not is_absent:
                for component in components:
                    raw_component_marks = component_marks.get(component.pk)
                    if raw_component_marks is None and str(component.pk) in component_marks:
                        raw_component_marks = component_marks.get(str(component.pk))
                    component_value = None if raw_component_marks in ("", None) else _quantize(raw_component_marks)
                    if component_value is None:
                        if component.include_in_total:
                            included_component_missing = True
                        continue
                    if component_value < 0:
                        raise ValidationError("Marks cannot be less than 0.")
                    if component_value > component.max_marks:
                        raise ValidationError(f"{component.name_snapshot} marks cannot exceed {component.max_marks}.")
                    if component.include_in_total:
                        component_total += component_value
                marks_obtained = None if included_component_missing else component_total
            else:
                marks_obtained = None
        else:
            marks_obtained = None if raw_marks in ("", None) else _quantize(raw_marks)
        if marks_obtained is not None and marks_obtained < 0:
            raise ValidationError("Marks cannot be less than 0.")
        if not is_absent and marks_obtained is not None and marks_obtained > assessment_subject.max_marks:
            raise ValidationError("Marks cannot exceed subject max marks.")

        entry, _created = ReportCardMarkEntry.objects.select_for_update().get_or_create(
            assessment_subject=assessment_subject,
            academic_session=session,
            defaults={
                "student": session.student,
                "marks_obtained": marks_obtained,
                "is_absent": is_absent,
                "remark": row.get("remark", ""),
                "entered_by": actor,
                "updated_by": actor,
            },
        )
        entry.student = session.student
        entry.marks_obtained = marks_obtained
        entry.is_absent = is_absent
        entry.remark = row.get("remark", "")
        if not entry.entered_by_id:
            entry.entered_by = actor
        entry.updated_by = actor
        entry.save()
        saved_entries.append(entry)

        for component in components:
            raw_component_marks = component_marks.get(component.pk)
            if raw_component_marks is None and str(component.pk) in component_marks:
                raw_component_marks = component_marks.get(str(component.pk))
            component_marks_obtained = None if is_absent or raw_component_marks in ("", None) else _quantize(raw_component_marks)
            component_entry, _created = ReportCardComponentMarkEntry.objects.select_for_update().get_or_create(
                component=component,
                academic_session=session,
                defaults={
                    "student": session.student,
                    "marks_obtained": component_marks_obtained,
                    "is_absent": is_absent,
                    "remark": row.get("remark", ""),
                    "entered_by": actor,
                    "updated_by": actor,
                },
            )
            component_entry.student = session.student
            component_entry.marks_obtained = component_marks_obtained
            component_entry.is_absent = is_absent
            component_entry.remark = row.get("remark", "")
            if not component_entry.entered_by_id:
                component_entry.entered_by = actor
            component_entry.updated_by = actor
            component_entry.save()

    _mark_results_stale_after_change(assessment)
    summary = validate_marks_completion(assessment)
    if summary["is_complete"]:
        assessment.status = ReportCardAssessment.Status.MARKS_ENTRY_COMPLETED
        assessment.save(update_fields=["status", "updated_at"])
    elif assessment.status == ReportCardAssessment.Status.MARKS_ENTRY_COMPLETED:
        assessment.status = ReportCardAssessment.Status.MARKS_ENTRY_OPEN
        assessment.save(update_fields=["status", "updated_at"])

    write_audit_log(
        assessment,
        ReportCardAuditLog.Action.MARKS_SAVED,
        actor=actor,
        message=f"Saved {len(saved_entries)} mark entries for {assessment_subject.subject_name_snapshot}.",
        metadata={"assessment_subject_id": assessment_subject.pk, "saved_count": len(saved_entries)},
    )
    return saved_entries


def validate_marks_completion(assessment):
    summary = get_completion_summary(assessment)
    required_subjects = [
        item
        for item in summary["subjects"]
        if not item["assessment_subject"].is_optional
    ]
    required_expected = sum(item["expected_mark_count"] for item in required_subjects)
    required_missing = sum(item["missing_mark_count"] for item in required_subjects)
    summary["required_expected_mark_count"] = required_expected
    summary["required_missing_mark_count"] = required_missing
    summary["is_complete"] = required_expected > 0 and required_missing == 0
    return summary


def _matching_grade_rule(assessment, percentage):
    if percentage is None:
        return None
    scoped_rules = ReportCardGradeRule.objects.filter(
        institute=assessment.institute,
        academic_year=assessment.academic_year,
        is_active=True,
        min_percentage__lte=percentage,
        max_percentage__gte=percentage,
    ).order_by("-academic_year_id", "display_order", "-min_percentage")
    default_rules = ReportCardGradeRule.objects.filter(
        institute=assessment.institute,
        academic_year__isnull=True,
        is_active=True,
        min_percentage__lte=percentage,
        max_percentage__gte=percentage,
    ).order_by("display_order", "-min_percentage")
    return scoped_rules.first() or default_rules.first()


def _subject_grade(assessment, percentage):
    grade_rule = _matching_grade_rule(assessment, percentage)
    return grade_rule.grade if grade_rule else "", grade_rule.remark if grade_rule and grade_rule.remark else ""


def _calculate_student_result(assessment, session, subjects, marks_by_subject):
    total_obtained = Decimal("0.00")
    total_max_marks = Decimal("0.00")
    weighted_total = Decimal("0.00")
    total_weightage = Decimal("0.00")
    has_failure = False
    has_missing_required = False
    absent_required_count = 0
    required_count = 0
    subject_results = []

    for subject in subjects:
        entry = marks_by_subject.get(subject.pk)
        subject_components = list(subject.components.all())
        included_components = [component for component in subject_components if component.include_in_total]
        subject_max_marks = (
            sum((component.max_marks for component in included_components), Decimal("0.00"))
            if subject_components
            else subject.max_marks
        )
        is_required = not subject.is_optional
        if is_required:
            required_count += 1

        if not entry:
            if is_required:
                has_missing_required = True
            subject_results.append(
                {
                    "assessment_subject": subject,
                    "academic_session": session,
                    "obtained_marks": Decimal("0.00"),
                    "max_marks": _quantize(subject_max_marks),
                    "percentage": None,
                    "grade": "",
                    "is_absent": False,
                    "remark": "Missing marks" if is_required else "",
                }
            )
            continue

        if entry.is_absent:
            if is_required:
                absent_required_count += 1
                has_failure = True
            subject_results.append(
                {
                    "assessment_subject": subject,
                    "academic_session": session,
                    "obtained_marks": Decimal("0.00"),
                    "max_marks": _quantize(subject_max_marks),
                    "percentage": None,
                    "grade": "AB",
                    "is_absent": True,
                    "remark": entry.remark,
                }
            )
            continue

        if entry.marks_obtained is None:
            if is_required:
                has_missing_required = True
            subject_results.append(
                {
                    "assessment_subject": subject,
                    "academic_session": session,
                    "obtained_marks": Decimal("0.00"),
                    "max_marks": _quantize(subject_max_marks),
                    "percentage": None,
                    "grade": "",
                    "is_absent": False,
                    "remark": "Missing marks" if is_required else "",
                }
            )
            continue

        marks = entry.marks_obtained or Decimal("0.00")
        subject_percentage = None
        if subject_max_marks > 0:
            subject_percentage = _quantize((marks / subject_max_marks) * Decimal("100.00"))
        subject_grade, subject_remark = _subject_grade(assessment, subject_percentage)
        subject_results.append(
            {
                "assessment_subject": subject,
                "academic_session": session,
                "obtained_marks": _quantize(marks),
                "max_marks": _quantize(subject_max_marks),
                "percentage": subject_percentage,
                "grade": subject_grade,
                "is_absent": False,
                "remark": entry.remark or subject_remark,
            }
        )
        if marks < subject.passing_marks:
            has_failure = True
        if subject.include_in_total and subject_max_marks > 0:
            total_obtained += marks
            total_max_marks += subject_max_marks
            weighted_total += (marks / subject_max_marks) * subject.weightage
            total_weightage += subject.weightage

    percentage = None
    if total_weightage > 0:
        percentage = _quantize((weighted_total / total_weightage) * Decimal("100.00"))

    if has_missing_required:
        status = ReportCardStudentResult.ResultStatus.INCOMPLETE
    elif required_count > 0 and absent_required_count == required_count:
        status = ReportCardStudentResult.ResultStatus.ABSENT
    elif has_failure:
        status = ReportCardStudentResult.ResultStatus.FAIL
    else:
        status = ReportCardStudentResult.ResultStatus.PASS

    grade_rule = _matching_grade_rule(assessment, percentage)
    grade = grade_rule.grade if grade_rule else ""
    remark = grade_rule.remark if grade_rule and grade_rule.remark else ""

    return {
        "student": session.student,
        "academic_session": session,
        "total_obtained": _quantize(total_obtained),
        "total_max_marks": _quantize(total_max_marks),
        "weighted_total": _quantize(weighted_total),
        "total_weightage": _quantize(total_weightage),
        "percentage": percentage,
        "grade": grade,
        "result_status": status,
        "remark": remark,
        "subject_results": subject_results,
        "student_name_snapshot": _snapshot_student_name(session.student),
        "admission_number_snapshot": session.admission_number or session.student.admission_number,
    }


@transaction.atomic
def generate_assessment_results(assessment, *, actor=None, require_complete=True):
    _require_not_published_or_locked(assessment)
    if require_complete:
        summary = validate_marks_completion(assessment)
        if not summary["is_complete"]:
            raise ValidationError("Required subject marks are incomplete.")

    assessment = ReportCardAssessment.objects.select_for_update().get(pk=assessment.pk)
    subjects = list(get_assessment_subjects(assessment))
    sessions = list(get_active_student_sessions_for_assessment(assessment))
    entries = ReportCardMarkEntry.objects.filter(
        assessment_subject__assessment=assessment,
        academic_session__in=sessions,
    ).select_related("assessment_subject")

    marks_by_session = {}
    for entry in entries:
        marks_by_session.setdefault(entry.academic_session_id, {})[entry.assessment_subject_id] = entry

    calculated = [
        _calculate_student_result(assessment, session, subjects, marks_by_session.get(session.pk, {}))
        for session in sessions
    ]
    rankable = sorted(
        [item for item in calculated if item["percentage"] is not None and item["result_status"] == ReportCardStudentResult.ResultStatus.PASS],
        key=lambda item: (item["percentage"], item["total_obtained"]),
        reverse=True,
    )
    previous_score = None
    previous_rank = 0
    for position, item in enumerate(rankable, start=1):
        score = (item["percentage"], item["total_obtained"])
        if score != previous_score:
            previous_rank = position
            previous_score = score
        item["rank"] = previous_rank

    generated_results = []
    now = timezone.now()
    for item in calculated:
        result, _created = ReportCardStudentResult.objects.update_or_create(
            assessment=assessment,
            academic_session=item["academic_session"],
            defaults={
                "student": item["student"],
                "total_obtained": item["total_obtained"],
                "total_max_marks": item["total_max_marks"],
                "weighted_total": item["weighted_total"],
                "total_weightage": item["total_weightage"],
                "percentage": item["percentage"],
                "grade": item["grade"],
                "rank": item.get("rank"),
                "result_status": item["result_status"],
                "remark": item["remark"],
                "is_stale": False,
                "student_name_snapshot": item["student_name_snapshot"],
                "admission_number_snapshot": item["admission_number_snapshot"],
                "generated_at": now,
            },
        )
        generated_results.append(result)
        for subject_item in item["subject_results"]:
            ReportCardSubjectResult.objects.update_or_create(
                result=result,
                assessment_subject=subject_item["assessment_subject"],
                defaults={
                    "academic_session": subject_item["academic_session"],
                    "obtained_marks": subject_item["obtained_marks"],
                    "max_marks": subject_item["max_marks"],
                    "percentage": subject_item["percentage"],
                    "grade": subject_item["grade"],
                    "is_absent": subject_item["is_absent"],
                    "remark": subject_item["remark"],
                },
            )

    assessment.status = ReportCardAssessment.Status.GENERATED
    assessment.save(update_fields=["status", "updated_at"])
    write_audit_log(
        assessment,
        ReportCardAuditLog.Action.RESULTS_GENERATED,
        actor=actor,
        message=f"Generated {len(generated_results)} student results.",
        metadata={"generated_count": len(generated_results)},
    )
    return generated_results


@transaction.atomic
def publish_assessment_results(assessment, *, actor=None):
    assessment = ReportCardAssessment.objects.select_for_update().get(pk=assessment.pk)
    if assessment.status not in {ReportCardAssessment.Status.GENERATED, ReportCardAssessment.Status.PUBLISHED}:
        raise ValidationError("Only generated assessments can be published.")
    if assessment.student_results.filter(is_stale=True).exists():
        raise ValidationError("Regenerate stale results before publishing.")
    now = timezone.now()
    assessment.status = ReportCardAssessment.Status.PUBLISHED
    assessment.published_at = now
    assessment.published_by = actor
    assessment.save(update_fields=["status", "published_at", "published_by", "updated_at"])
    ReportCardStudentResult.objects.filter(assessment=assessment).update(published_at=now)
    write_audit_log(
        assessment,
        ReportCardAuditLog.Action.RESULTS_PUBLISHED,
        actor=actor,
        message="Results published.",
    )
    return assessment


@transaction.atomic
def lock_assessment(assessment, *, actor=None):
    assessment = ReportCardAssessment.objects.select_for_update().get(pk=assessment.pk)
    if assessment.status not in {ReportCardAssessment.Status.PUBLISHED, ReportCardAssessment.Status.LOCKED}:
        raise ValidationError("Only published assessments can be locked.")
    now = timezone.now()
    assessment.status = ReportCardAssessment.Status.LOCKED
    assessment.locked_at = now
    assessment.locked_by = actor
    assessment.save(update_fields=["status", "locked_at", "locked_by", "updated_at"])
    write_audit_log(
        assessment,
        ReportCardAuditLog.Action.ASSESSMENT_LOCKED,
        actor=actor,
        message="Assessment locked.",
    )
    return assessment


@transaction.atomic
def unlock_assessment_for_admin(assessment, *, actor=None, target_status=ReportCardAssessment.Status.GENERATED):
    assessment = ReportCardAssessment.objects.select_for_update().get(pk=assessment.pk)
    if assessment.status != ReportCardAssessment.Status.LOCKED:
        raise ValidationError("Only locked assessments can be unlocked.")
    if target_status not in {
        ReportCardAssessment.Status.STRUCTURE_READY,
        ReportCardAssessment.Status.GENERATED,
        ReportCardAssessment.Status.MARKS_ENTRY_OPEN,
        ReportCardAssessment.Status.MARKS_ENTRY_COMPLETED,
    }:
        raise ValidationError("Invalid unlock target status.")
    assessment.status = target_status
    assessment.published_at = None
    assessment.published_by = None
    assessment.locked_at = None
    assessment.locked_by = None
    assessment.save(update_fields=["status", "published_at", "published_by", "locked_at", "locked_by", "updated_at"])
    result_updates = {"published_at": None}
    if target_status != ReportCardAssessment.Status.GENERATED:
        result_updates["is_stale"] = True
    ReportCardStudentResult.objects.filter(assessment=assessment).update(**result_updates)
    write_audit_log(
        assessment,
        ReportCardAuditLog.Action.ASSESSMENT_UNLOCKED,
        actor=actor,
        message=f"Assessment unlocked to {target_status}.",
    )
    return assessment
