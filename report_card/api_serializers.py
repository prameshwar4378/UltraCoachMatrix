from rest_framework import serializers

from .models import ReportCardAssessment, ReportCardAssessmentSubject


class BlankableDecimalField(serializers.DecimalField):
    def to_internal_value(self, data):
        if data == "":
            return None
        return super().to_internal_value(data)


class ReportCardAssessmentSubjectComponentSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="pk")
    name = serializers.CharField(source="name_snapshot")
    max_marks = serializers.DecimalField(max_digits=7, decimal_places=2)
    weightage = serializers.DecimalField(max_digits=7, decimal_places=2)
    display_order = serializers.IntegerField()
    include_in_total = serializers.BooleanField()


class ReportCardAssessmentSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="pk")
    title = serializers.CharField()
    academic_year_id = serializers.IntegerField()
    academic_year = serializers.CharField(source="academic_year_name_snapshot")
    batch_id = serializers.IntegerField()
    batch_name = serializers.CharField(source="batch_name_snapshot")
    status = serializers.CharField()
    status_label = serializers.CharField(source="get_status_display")
    assessment_date = serializers.DateField(format="%Y-%m-%d", allow_null=True)
    result_date = serializers.DateField(format="%Y-%m-%d", allow_null=True)
    subject_count = serializers.SerializerMethodField()
    result_count = serializers.SerializerMethodField()
    my_subject_count = serializers.SerializerMethodField()
    expected_mark_count = serializers.SerializerMethodField()
    entered_mark_count = serializers.SerializerMethodField()
    missing_mark_count = serializers.SerializerMethodField()
    marks_status = serializers.SerializerMethodField()
    marks_status_label = serializers.SerializerMethodField()

    def get_subject_count(self, assessment):
        return getattr(assessment, "subject_count", assessment.assessment_subjects.count())

    def get_result_count(self, assessment):
        return getattr(assessment, "result_count", assessment.student_results.count())

    def get_my_subject_count(self, assessment):
        return getattr(assessment, "my_subject_count", getattr(assessment, "subject_count", assessment.assessment_subjects.count()))

    def get_expected_mark_count(self, assessment):
        return getattr(assessment, "expected_mark_count", 0)

    def get_entered_mark_count(self, assessment):
        return getattr(assessment, "entered_mark_count", 0)

    def get_missing_mark_count(self, assessment):
        return getattr(assessment, "missing_mark_count", 0)

    def get_marks_status(self, assessment):
        return getattr(assessment, "marks_status", "")

    def get_marks_status_label(self, assessment):
        return getattr(assessment, "marks_status_label", "")


class ReportCardAssessmentWriteSerializer(serializers.Serializer):
    academic_year_id = serializers.IntegerField()
    batch_id = serializers.IntegerField()
    title = serializers.CharField(max_length=160)
    assessment_date = serializers.DateField(required=False, allow_null=True)
    result_date = serializers.DateField(required=False, allow_null=True)


class ReportCardAssessmentUpdateSerializer(serializers.Serializer):
    academic_year_id = serializers.IntegerField(required=False)
    batch_id = serializers.IntegerField(required=False)
    title = serializers.CharField(required=False, max_length=160)
    assessment_date = serializers.DateField(required=False, allow_null=True)
    result_date = serializers.DateField(required=False, allow_null=True)


class ReportCardAssessmentSubjectSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="pk")
    assessment_id = serializers.IntegerField()
    subject_id = serializers.IntegerField()
    subject_name = serializers.CharField(source="subject_name_snapshot")
    max_marks = serializers.DecimalField(max_digits=7, decimal_places=2)
    passing_marks = serializers.DecimalField(max_digits=7, decimal_places=2)
    weightage = serializers.DecimalField(max_digits=7, decimal_places=2)
    display_order = serializers.IntegerField()
    is_optional = serializers.BooleanField()
    include_in_total = serializers.BooleanField()
    components = serializers.SerializerMethodField()
    expected_mark_count = serializers.SerializerMethodField()
    entered_mark_count = serializers.SerializerMethodField()
    missing_mark_count = serializers.SerializerMethodField()
    absent_mark_count = serializers.SerializerMethodField()
    marks_status = serializers.SerializerMethodField()
    marks_status_label = serializers.SerializerMethodField()
    can_enter_marks = serializers.SerializerMethodField()

    def get_components(self, assessment_subject):
        return ReportCardAssessmentSubjectComponentSerializer(
            assessment_subject.components.order_by("display_order", "name_snapshot", "id"),
            many=True,
        ).data

    def get_expected_mark_count(self, assessment_subject):
        return getattr(assessment_subject, "expected_mark_count", 0)

    def get_entered_mark_count(self, assessment_subject):
        return getattr(assessment_subject, "entered_mark_count", 0)

    def get_missing_mark_count(self, assessment_subject):
        return getattr(assessment_subject, "missing_mark_count", 0)

    def get_absent_mark_count(self, assessment_subject):
        return getattr(assessment_subject, "absent_mark_count", 0)

    def get_marks_status(self, assessment_subject):
        return getattr(assessment_subject, "marks_status", "")

    def get_marks_status_label(self, assessment_subject):
        return getattr(assessment_subject, "marks_status_label", "")

    def get_can_enter_marks(self, assessment_subject):
        return bool(getattr(assessment_subject, "can_enter_marks", False))


class ReportCardAssessmentSubjectWriteSerializer(serializers.Serializer):
    subject_id = serializers.IntegerField()
    max_marks = serializers.DecimalField(max_digits=7, decimal_places=2)
    passing_marks = serializers.DecimalField(max_digits=7, decimal_places=2)
    weightage = serializers.DecimalField(max_digits=7, decimal_places=2, required=False)
    display_order = serializers.IntegerField(min_value=1, required=False, default=1)
    is_optional = serializers.BooleanField(required=False, default=False)
    include_in_total = serializers.BooleanField(required=False, default=True)


class ReportCardAssessmentSubjectUpdateSerializer(serializers.Serializer):
    subject_id = serializers.IntegerField(required=False)
    max_marks = serializers.DecimalField(max_digits=7, decimal_places=2, required=False)
    passing_marks = serializers.DecimalField(max_digits=7, decimal_places=2, required=False)
    weightage = serializers.DecimalField(max_digits=7, decimal_places=2, required=False)
    display_order = serializers.IntegerField(min_value=1, required=False)
    is_optional = serializers.BooleanField(required=False)
    include_in_total = serializers.BooleanField(required=False)


class ReportCardMarkEntrySerializer(serializers.Serializer):
    id = serializers.IntegerField(source="pk", allow_null=True)
    academic_session_id = serializers.IntegerField()
    student_id = serializers.IntegerField()
    student_name = serializers.SerializerMethodField()
    admission_number = serializers.CharField(source="academic_session.admission_number")
    roll_number = serializers.CharField(source="student.roll_number", allow_blank=True)
    marks_obtained = serializers.DecimalField(max_digits=7, decimal_places=2, allow_null=True)
    is_absent = serializers.BooleanField()
    remark = serializers.CharField()

    def get_student_name(self, entry):
        return entry.student.user.get_full_name() or entry.student.user.username


class ReportCardMarksGridRowSerializer(serializers.Serializer):
    academic_session_id = serializers.IntegerField(source="academic_session.pk")
    student_id = serializers.IntegerField(source="student.pk")
    student_name = serializers.SerializerMethodField()
    admission_number = serializers.SerializerMethodField()
    roll_number = serializers.SerializerMethodField()
    mark_entry = serializers.SerializerMethodField()

    def get_student_name(self, row):
        if row.get("student_name"):
            return row["student_name"]
        student = row["student"]
        return student.user.get_full_name() or student.user.username

    def get_admission_number(self, row):
        if row.get("admission_number"):
            return row["admission_number"]
        return row["academic_session"].admission_number or row["student"].admission_number

    def get_roll_number(self, row):
        if row.get("roll_number"):
            return row["roll_number"]
        return row["student"].roll_number or ""

    def get_mark_entry(self, row):
        entry = row.get("mark_entry")
        component_entries = row.get("component_entries", {})
        component_marks = {
            str(component_id): {
                "id": component_entry.pk,
                "marks_obtained": str(component_entry.marks_obtained) if component_entry.marks_obtained is not None else None,
                "is_absent": component_entry.is_absent,
                "remark": component_entry.remark,
            }
            for component_id, component_entry in component_entries.items()
        }
        if not entry:
            return {"component_marks": component_marks} if component_marks else None
        return {
            "id": entry.pk,
            "marks_obtained": str(entry.marks_obtained) if entry.marks_obtained is not None else None,
            "is_absent": entry.is_absent,
            "remark": entry.remark,
            "component_marks": component_marks,
        }


class ReportCardMarkRowWriteSerializer(serializers.Serializer):
    academic_session_id = serializers.IntegerField()
    marks_obtained = BlankableDecimalField(max_digits=7, decimal_places=2, required=False, allow_null=True)
    component_marks = serializers.DictField(
        child=BlankableDecimalField(max_digits=7, decimal_places=2, allow_null=True),
        required=False,
        allow_empty=True,
    )
    is_absent = serializers.BooleanField(required=False, default=False)
    remark = serializers.CharField(required=False, allow_blank=True, default="")


class ReportCardBulkMarksSaveSerializer(serializers.Serializer):
    rows = ReportCardMarkRowWriteSerializer(many=True, allow_empty=False)


class ReportCardStudentResultSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="pk")
    assessment_id = serializers.IntegerField()
    assessment_title = serializers.CharField(source="assessment.title")
    academic_year = serializers.CharField(source="assessment.academic_year_name_snapshot")
    batch_name = serializers.CharField(source="assessment.batch_name_snapshot")
    student_id = serializers.IntegerField()
    student_name = serializers.CharField(source="student_name_snapshot")
    admission_number = serializers.CharField(source="admission_number_snapshot")
    total_obtained = serializers.DecimalField(max_digits=9, decimal_places=2)
    total_max_marks = serializers.DecimalField(max_digits=9, decimal_places=2)
    weighted_total = serializers.DecimalField(max_digits=9, decimal_places=2)
    total_weightage = serializers.DecimalField(max_digits=9, decimal_places=2)
    percentage = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True)
    grade = serializers.CharField(allow_blank=True)
    rank = serializers.IntegerField(allow_null=True)
    result_status = serializers.CharField()
    result_status_label = serializers.CharField(source="get_result_status_display")
    remark = serializers.CharField(allow_blank=True)
    is_stale = serializers.BooleanField()


class ReportCardSubjectResultRowSerializer(serializers.Serializer):
    subject_id = serializers.IntegerField(source="assessment_subject.pk")
    subject_name = serializers.CharField(source="assessment_subject.subject_name_snapshot")
    max_marks = serializers.DecimalField(source="assessment_subject.max_marks", max_digits=7, decimal_places=2)
    passing_marks = serializers.DecimalField(source="assessment_subject.passing_marks", max_digits=7, decimal_places=2)
    weightage = serializers.DecimalField(source="assessment_subject.weightage", max_digits=7, decimal_places=2)
    is_optional = serializers.BooleanField(source="assessment_subject.is_optional")
    include_in_total = serializers.BooleanField(source="assessment_subject.include_in_total")
    marks_obtained = serializers.SerializerMethodField()
    is_absent = serializers.SerializerMethodField()
    remark = serializers.SerializerMethodField()

    def get_marks_obtained(self, row):
        entry = row.get("mark_entry")
        if not entry or entry.marks_obtained is None:
            return None
        return str(entry.marks_obtained)

    def get_is_absent(self, row):
        entry = row.get("mark_entry")
        return bool(entry and entry.is_absent)

    def get_remark(self, row):
        entry = row.get("mark_entry")
        return entry.remark if entry else ""
