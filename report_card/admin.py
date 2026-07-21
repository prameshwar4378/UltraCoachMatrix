"""Admin registrations for the Report Card Generator app."""

from django.contrib import admin

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
)


SNAPSHOT_FIELDS = (
    "institute_name_snapshot",
    "academic_year_name_snapshot",
    "batch_name_snapshot",
    "subject_name_snapshot",
    "student_name_snapshot",
    "admission_number_snapshot",
)


class ReportCardAssessmentSubjectInline(admin.TabularInline):
    model = ReportCardAssessmentSubject
    extra = 0
    raw_id_fields = ("subject",)
    fields = (
        "display_order",
        "subject",
        "subject_name_snapshot",
        "max_marks",
        "passing_marks",
        "weightage",
        "is_optional",
        "include_in_total",
    )
    readonly_fields = ("subject_name_snapshot",)
    show_change_link = True


class ReportCardAssessmentSubjectComponentInline(admin.TabularInline):
    model = ReportCardAssessmentSubjectComponent
    extra = 0
    fields = (
        "display_order",
        "name",
        "name_snapshot",
        "max_marks",
        "passing_marks",
        "weightage",
        "include_in_total",
    )
    readonly_fields = ("name_snapshot",)


@admin.register(ReportCardAssessment)
class ReportCardAssessmentAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "institute",
        "academic_year",
        "batch",
        "status",
        "assessment_date",
        "result_date",
        "created_by",
        "created_at",
    )
    list_filter = ("status", "institute", "academic_year", "batch", "assessment_date", "created_at")
    search_fields = (
        "title",
        "institute__name",
        "academic_year__name",
        "batch__name",
        "institute_name_snapshot",
        "academic_year_name_snapshot",
        "batch_name_snapshot",
    )
    raw_id_fields = ("institute", "academic_year", "batch", "created_by", "published_by", "locked_by")
    readonly_fields = (
        "institute_name_snapshot",
        "academic_year_name_snapshot",
        "batch_name_snapshot",
        "created_at",
        "updated_at",
        "published_at",
        "locked_at",
    )
    inlines = (ReportCardAssessmentSubjectInline,)
    date_hierarchy = "created_at"


@admin.register(ReportCardAssessmentSubject)
class ReportCardAssessmentSubjectAdmin(admin.ModelAdmin):
    list_display = (
        "assessment",
        "subject",
        "subject_name_snapshot",
        "max_marks",
        "passing_marks",
        "weightage",
        "display_order",
        "is_optional",
        "include_in_total",
    )
    list_filter = ("assessment__status", "is_optional", "include_in_total", "assessment__academic_year")
    search_fields = (
        "assessment__title",
        "assessment__batch__name",
        "subject__name",
        "subject_name_snapshot",
    )
    raw_id_fields = ("assessment", "subject")
    readonly_fields = ("subject_name_snapshot", "created_at", "updated_at")
    inlines = (ReportCardAssessmentSubjectComponentInline,)


@admin.register(ReportCardAssessmentSubjectComponent)
class ReportCardAssessmentSubjectComponentAdmin(admin.ModelAdmin):
    list_display = (
        "assessment_subject",
        "name_snapshot",
        "max_marks",
        "passing_marks",
        "weightage",
        "display_order",
        "include_in_total",
    )
    list_filter = ("assessment_subject__assessment__status", "include_in_total")
    search_fields = ("assessment_subject__subject_name_snapshot", "name", "name_snapshot")
    raw_id_fields = ("assessment_subject",)
    readonly_fields = ("name_snapshot", "created_at", "updated_at")


@admin.register(ReportCardMarkEntry)
class ReportCardMarkEntryAdmin(admin.ModelAdmin):
    list_display = (
        "assessment_subject",
        "student",
        "academic_session",
        "marks_obtained",
        "is_absent",
        "entered_by",
        "updated_at",
    )
    list_filter = (
        "assessment_subject__assessment__status",
        "assessment_subject__assessment__academic_year",
        "assessment_subject__assessment__batch",
        "is_absent",
        "updated_at",
    )
    search_fields = (
        "assessment_subject__assessment__title",
        "assessment_subject__subject__name",
        "student__admission_number",
        "student__user__first_name",
        "student__user__last_name",
        "student__user__username",
        "student_name_snapshot",
        "admission_number_snapshot",
    )
    raw_id_fields = ("assessment_subject", "student", "academic_session", "entered_by", "updated_by")
    readonly_fields = (
        "student_name_snapshot",
        "admission_number_snapshot",
        "entered_at",
        "updated_at",
    )


@admin.register(ReportCardComponentMarkEntry)
class ReportCardComponentMarkEntryAdmin(admin.ModelAdmin):
    list_display = (
        "component",
        "student",
        "academic_session",
        "marks_obtained",
        "is_absent",
        "entered_by",
        "updated_at",
    )
    list_filter = (
        "component__assessment_subject__assessment__status",
        "component__assessment_subject__assessment__academic_year",
        "component__assessment_subject__assessment__batch",
        "is_absent",
        "updated_at",
    )
    search_fields = (
        "component__name_snapshot",
        "component__assessment_subject__subject_name_snapshot",
        "student__admission_number",
        "student__user__first_name",
        "student__user__last_name",
        "student_name_snapshot",
        "admission_number_snapshot",
    )
    raw_id_fields = ("component", "student", "academic_session", "entered_by", "updated_by")
    readonly_fields = ("student_name_snapshot", "admission_number_snapshot", "entered_at", "updated_at")


class ReportCardSubjectResultInline(admin.TabularInline):
    model = ReportCardSubjectResult
    extra = 0
    raw_id_fields = ("assessment_subject", "academic_session")
    fields = (
        "assessment_subject",
        "subject_name_snapshot",
        "obtained_marks",
        "max_marks",
        "percentage",
        "grade",
        "is_absent",
        "include_in_total",
        "remark",
    )
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ReportCardStudentResult)
class ReportCardStudentResultAdmin(admin.ModelAdmin):
    list_display = (
        "assessment",
        "student",
        "academic_session",
        "total_obtained",
        "total_max_marks",
        "percentage",
        "grade",
        "rank",
        "result_status",
        "is_stale",
    )
    list_filter = (
        "assessment__status",
        "assessment__academic_year",
        "assessment__batch",
        "result_status",
        "grade",
        "is_stale",
    )
    search_fields = (
        "assessment__title",
        "student__admission_number",
        "student__user__first_name",
        "student__user__last_name",
        "student__user__username",
        "student_name_snapshot",
        "admission_number_snapshot",
    )
    raw_id_fields = ("assessment", "student", "academic_session")
    readonly_fields = (
        "total_obtained",
        "total_max_marks",
        "weighted_total",
        "total_weightage",
        "percentage",
        "grade",
        "rank",
        "result_status",
        "remark",
        "student_name_snapshot",
        "admission_number_snapshot",
        "generated_at",
        "published_at",
    )
    date_hierarchy = "generated_at"
    inlines = (ReportCardSubjectResultInline,)


@admin.register(ReportCardSubjectResult)
class ReportCardSubjectResultAdmin(admin.ModelAdmin):
    list_display = (
        "result",
        "assessment_subject",
        "obtained_marks",
        "max_marks",
        "percentage",
        "grade",
        "is_absent",
    )
    list_filter = ("grade", "is_absent", "include_in_total")
    search_fields = (
        "result__student_name_snapshot",
        "result__admission_number_snapshot",
        "subject_name_snapshot",
    )
    raw_id_fields = ("result", "assessment_subject", "academic_session")
    readonly_fields = (
        "result",
        "assessment_subject",
        "academic_session",
        "subject_name_snapshot",
        "obtained_marks",
        "max_marks",
        "percentage",
        "grade",
        "is_absent",
        "is_optional",
        "include_in_total",
        "remark",
    )


@admin.register(ReportCardGradeRule)
class ReportCardGradeRuleAdmin(admin.ModelAdmin):
    list_display = (
        "institute",
        "academic_year",
        "grade",
        "min_percentage",
        "max_percentage",
        "display_order",
        "is_active",
    )
    list_filter = ("institute", "academic_year", "is_active")
    search_fields = ("institute__name", "academic_year__name", "grade", "remark")
    raw_id_fields = ("institute", "academic_year")
    readonly_fields = ("created_at",)


@admin.register(ReportCardAuditLog)
class ReportCardAuditLogAdmin(admin.ModelAdmin):
    list_display = ("assessment", "action", "actor", "message", "created_at")
    list_filter = ("action", "assessment__status", "created_at")
    search_fields = (
        "assessment__title",
        "actor__username",
        "actor__first_name",
        "actor__last_name",
        "message",
    )
    raw_id_fields = ("assessment", "actor")
    readonly_fields = ("assessment", "actor", "action", "message", "metadata", "created_at")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False
