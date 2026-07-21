"""Models for the independent Report Card Generator app."""

from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


MARKS_VALIDATOR = MinValueValidator(Decimal("0.00"))
POSITIVE_MARKS_VALIDATOR = MinValueValidator(Decimal("0.01"))


def _user_display_name(user):
    if not user:
        return ""
    return user.get_full_name() or user.username


class ReportCardAssessment(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        STRUCTURE_READY = "STRUCTURE_READY", "Structure ready"
        MARKS_ENTRY_OPEN = "MARKS_ENTRY_OPEN", "Marks entry open"
        MARKS_ENTRY_COMPLETED = "MARKS_ENTRY_COMPLETED", "Marks entry completed"
        GENERATED = "GENERATED", "Generated"
        PUBLISHED = "PUBLISHED", "Published"
        LOCKED = "LOCKED", "Locked"

    institute = models.ForeignKey(
        "super_admin.Institute",
        on_delete=models.CASCADE,
        related_name="report_card_assessments",
    )
    academic_year = models.ForeignKey(
        "institute_admin.AcademicYear",
        on_delete=models.PROTECT,
        related_name="report_card_assessments",
    )
    batch = models.ForeignKey(
        "institute_admin.Batch",
        on_delete=models.PROTECT,
        related_name="report_card_assessments",
    )
    title = models.CharField(max_length=160)
    assessment_date = models.DateField(null=True, blank=True)
    result_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.DRAFT)
    institute_name_snapshot = models.CharField(max_length=160, blank=True)
    academic_year_name_snapshot = models.CharField(max_length=20, blank=True)
    batch_name_snapshot = models.CharField(max_length=120, blank=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_report_card_assessments",
    )
    published_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="published_report_card_assessments",
    )
    locked_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="locked_report_card_assessments",
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "title"]
        constraints = [
            models.UniqueConstraint(
                fields=["institute", "academic_year", "batch", "title"],
                name="rc_assessment_unique_title",
            ),
        ]
        indexes = [
            models.Index(fields=["institute", "academic_year", "status"], name="rc_assess_scope_idx"),
            models.Index(fields=["batch", "status", "-created_at"], name="rc_assess_batch_idx"),
            models.Index(fields=["created_by", "-created_at"], name="rc_assess_creator_idx"),
        ]

    def __str__(self):
        return f"{self.title} - {self.batch_name_snapshot or self.batch}"

    def clean(self):
        super().clean()
        errors = {}
        if self.academic_year_id and self.academic_year.institute_id != self.institute_id:
            errors["academic_year"] = "Selected academic year belongs to another institute."
        if self.batch_id:
            if self.batch.institute_id != self.institute_id:
                errors["batch"] = "Selected batch belongs to another institute."
            if self.academic_year_id and self.batch.academic_year_id != self.academic_year_id:
                errors["batch"] = "Selected batch belongs to another academic year."
        if self.assessment_date and self.result_date and self.result_date < self.assessment_date:
            errors["result_date"] = "Result date cannot be before assessment date."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.institute_id:
            self.institute_name_snapshot = self.institute.name
        if self.academic_year_id:
            self.academic_year_name_snapshot = self.academic_year.name
        if self.batch_id:
            self.batch_name_snapshot = self.batch.name
        self.full_clean()
        super().save(*args, **kwargs)


class ReportCardAssessmentSubject(models.Model):
    assessment = models.ForeignKey(
        ReportCardAssessment,
        on_delete=models.CASCADE,
        related_name="assessment_subjects",
    )
    subject = models.ForeignKey(
        "institute_admin.Subject",
        on_delete=models.PROTECT,
        related_name="report_card_assessment_subjects",
    )
    subject_name_snapshot = models.CharField(max_length=120, blank=True)
    max_marks = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        validators=[POSITIVE_MARKS_VALIDATOR],
    )
    passing_marks = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        validators=[MARKS_VALIDATOR],
    )
    weightage = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        default=Decimal("100.00"),
        validators=[POSITIVE_MARKS_VALIDATOR],
    )
    display_order = models.PositiveIntegerField(default=1)
    is_optional = models.BooleanField(default=False)
    include_in_total = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "subject_name_snapshot", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["assessment", "subject"],
                name="rc_subject_unique_subject",
            ),
            models.UniqueConstraint(
                fields=["assessment", "display_order"],
                name="rc_subject_unique_order",
            ),
        ]
        indexes = [
            models.Index(fields=["assessment", "display_order"], name="rc_subject_order_idx"),
            models.Index(fields=["subject"], name="rc_subject_master_idx"),
        ]

    def __str__(self):
        return f"{self.subject_name_snapshot or self.subject} - {self.assessment}"

    def clean(self):
        super().clean()
        errors = {}
        if self.assessment_id and self.assessment.status in {
            ReportCardAssessment.Status.PUBLISHED,
            ReportCardAssessment.Status.LOCKED,
        }:
            errors["assessment"] = "Published or locked assessments cannot be changed."
        if self.subject_id and self.assessment_id:
            if self.subject.institute_id != self.assessment.institute_id:
                errors["subject"] = "Selected subject belongs to another institute."
            if self.subject.academic_year_id != self.assessment.academic_year_id:
                errors["subject"] = "Selected subject belongs to another academic year."
        if self.max_marks is not None and self.max_marks <= 0:
            errors["max_marks"] = "Max marks must be greater than 0."
        if self.passing_marks is not None and self.passing_marks < 0:
            errors["passing_marks"] = "Passing marks cannot be negative."
        if (
            self.max_marks is not None
            and self.passing_marks is not None
            and self.passing_marks > self.max_marks
        ):
            errors["passing_marks"] = "Passing marks cannot exceed max marks."
        if self.weightage is not None and self.weightage <= 0:
            errors["weightage"] = "Weightage must be greater than 0."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.subject_id:
            self.subject_name_snapshot = self.subject.name
        self.full_clean()
        super().save(*args, **kwargs)


class ReportCardAssessmentSubjectComponent(models.Model):
    assessment_subject = models.ForeignKey(
        ReportCardAssessmentSubject,
        on_delete=models.CASCADE,
        related_name="components",
    )
    name = models.CharField(max_length=80)
    max_marks = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        validators=[POSITIVE_MARKS_VALIDATOR],
    )
    passing_marks = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MARKS_VALIDATOR],
    )
    weightage = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        default=Decimal("100.00"),
        validators=[POSITIVE_MARKS_VALIDATOR],
    )
    display_order = models.PositiveIntegerField(default=1)
    include_in_total = models.BooleanField(default=True)
    name_snapshot = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "name_snapshot", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["assessment_subject", "name"],
                name="rc_component_unique_name",
            ),
            models.UniqueConstraint(
                fields=["assessment_subject", "display_order"],
                name="rc_component_unique_order",
            ),
        ]
        indexes = [
            models.Index(fields=["assessment_subject", "display_order"], name="rc_comp_order_idx"),
        ]

    def __str__(self):
        return f"{self.name_snapshot or self.name} - {self.assessment_subject}"

    def clean(self):
        super().clean()
        errors = {}
        assessment = self.assessment_subject.assessment if self.assessment_subject_id else None
        if assessment and assessment.status in {
            ReportCardAssessment.Status.PUBLISHED,
            ReportCardAssessment.Status.LOCKED,
        }:
            errors["assessment_subject"] = "Published or locked assessment components cannot be changed."
        if self.max_marks is not None and self.max_marks <= 0:
            errors["max_marks"] = "Component max marks must be greater than 0."
        if self.passing_marks is not None and self.passing_marks < 0:
            errors["passing_marks"] = "Component passing marks cannot be negative."
        if (
            self.max_marks is not None
            and self.passing_marks is not None
            and self.passing_marks > self.max_marks
        ):
            errors["passing_marks"] = "Component passing marks cannot exceed max marks."
        if self.weightage is not None and self.weightage <= 0:
            errors["weightage"] = "Component weightage must be greater than 0."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.name_snapshot = self.name
        self.full_clean()
        super().save(*args, **kwargs)


class ReportCardMarkEntry(models.Model):
    assessment_subject = models.ForeignKey(
        ReportCardAssessmentSubject,
        on_delete=models.CASCADE,
        related_name="mark_entries",
    )
    student = models.ForeignKey(
        "student_parent.StudentProfile",
        on_delete=models.CASCADE,
        related_name="report_card_mark_entries",
    )
    academic_session = models.ForeignKey(
        "student_parent.StudentAcademicSession",
        on_delete=models.PROTECT,
        related_name="report_card_mark_entries",
    )
    marks_obtained = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MARKS_VALIDATOR],
    )
    is_absent = models.BooleanField(default=False)
    remark = models.CharField(max_length=255, blank=True)
    student_name_snapshot = models.CharField(max_length=180, blank=True)
    admission_number_snapshot = models.CharField(max_length=40, blank=True)
    entered_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entered_report_card_marks",
    )
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_report_card_marks",
    )
    entered_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = [
            "academic_session__admission_number",
            "student__user__first_name",
            "student__user__username",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["assessment_subject", "academic_session"],
                name="rc_mark_unique_session",
            ),
        ]
        indexes = [
            models.Index(fields=["assessment_subject", "is_absent"], name="rc_mark_subject_idx"),
            models.Index(fields=["student", "-updated_at"], name="rc_mark_student_idx"),
            models.Index(fields=["academic_session"], name="rc_mark_session_idx"),
        ]

    def __str__(self):
        subject = self.assessment_subject.subject_name_snapshot or self.assessment_subject.subject
        return f"{self.admission_number_snapshot or self.student} - {subject}"

    def clean(self):
        super().clean()
        errors = {}
        assessment = self.assessment_subject.assessment if self.assessment_subject_id else None
        if assessment and assessment.status in {
            ReportCardAssessment.Status.PUBLISHED,
            ReportCardAssessment.Status.LOCKED,
        }:
            errors["assessment_subject"] = "Marks cannot be changed after assessment is published or locked."
        if self.academic_session_id:
            if self.student_id and self.student_id != self.academic_session.student_id:
                errors["student"] = "Mark entry student must match the academic session student."
            if assessment:
                if self.academic_session.institute_id != assessment.institute_id:
                    errors["academic_session"] = "Student session belongs to another institute."
                if self.academic_session.academic_year_id != assessment.academic_year_id:
                    errors["academic_session"] = "Student session belongs to another academic year."
        if self.marks_obtained is not None and self.marks_obtained < 0:
            errors["marks_obtained"] = "Marks cannot be negative."
        if self.is_absent:
            self._raise_errors(errors)
            return
        if self.marks_obtained is not None and self.assessment_subject_id and self.marks_obtained > self.assessment_subject.max_marks:
            errors["marks_obtained"] = "Marks cannot exceed subject max marks."
        self._raise_errors(errors)

    def _raise_errors(self, errors):
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.academic_session_id:
            self.student = self.academic_session.student
            self.admission_number_snapshot = self.academic_session.admission_number
        if self.student_id:
            self.student_name_snapshot = _user_display_name(self.student.user)
            if not self.admission_number_snapshot:
                self.admission_number_snapshot = self.student.admission_number
        self.full_clean()
        super().save(*args, **kwargs)


class ReportCardComponentMarkEntry(models.Model):
    component = models.ForeignKey(
        ReportCardAssessmentSubjectComponent,
        on_delete=models.CASCADE,
        related_name="mark_entries",
    )
    student = models.ForeignKey(
        "student_parent.StudentProfile",
        on_delete=models.CASCADE,
        related_name="report_card_component_mark_entries",
    )
    academic_session = models.ForeignKey(
        "student_parent.StudentAcademicSession",
        on_delete=models.PROTECT,
        related_name="report_card_component_mark_entries",
    )
    marks_obtained = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MARKS_VALIDATOR],
    )
    is_absent = models.BooleanField(default=False)
    remark = models.CharField(max_length=255, blank=True)
    student_name_snapshot = models.CharField(max_length=180, blank=True)
    admission_number_snapshot = models.CharField(max_length=40, blank=True)
    entered_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="entered_report_card_component_marks",
    )
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_report_card_component_marks",
    )
    entered_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["academic_session__admission_number", "component__display_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["component", "academic_session"],
                name="rc_comp_mark_unique_session",
            ),
        ]
        indexes = [
            models.Index(fields=["component", "is_absent"], name="rc_comp_mark_comp_idx"),
            models.Index(fields=["student", "-updated_at"], name="rc_comp_mark_student_idx"),
            models.Index(fields=["academic_session"], name="rc_comp_mark_session_idx"),
        ]

    def __str__(self):
        return f"{self.admission_number_snapshot or self.student} - {self.component}"

    def clean(self):
        super().clean()
        errors = {}
        assessment = None
        if self.component_id:
            assessment = self.component.assessment_subject.assessment
        if assessment and assessment.status in {
            ReportCardAssessment.Status.PUBLISHED,
            ReportCardAssessment.Status.LOCKED,
        }:
            errors["component"] = "Component marks cannot be changed after assessment is published or locked."
        if self.academic_session_id:
            if self.student_id and self.student_id != self.academic_session.student_id:
                errors["student"] = "Component mark student must match the academic session student."
            if assessment:
                if self.academic_session.institute_id != assessment.institute_id:
                    errors["academic_session"] = "Student session belongs to another institute."
                if self.academic_session.academic_year_id != assessment.academic_year_id:
                    errors["academic_session"] = "Student session belongs to another academic year."
        if self.marks_obtained is not None and self.marks_obtained < 0:
            errors["marks_obtained"] = "Marks cannot be negative."
        if self.is_absent:
            if errors:
                raise ValidationError(errors)
            return
        if self.marks_obtained is not None and self.component_id and self.marks_obtained > self.component.max_marks:
            errors["marks_obtained"] = "Marks cannot exceed component max marks."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.academic_session_id:
            self.student = self.academic_session.student
            self.admission_number_snapshot = self.academic_session.admission_number
        if self.student_id:
            self.student_name_snapshot = _user_display_name(self.student.user)
            if not self.admission_number_snapshot:
                self.admission_number_snapshot = self.student.admission_number
        self.full_clean()
        super().save(*args, **kwargs)


class ReportCardStudentResult(models.Model):
    class ResultStatus(models.TextChoices):
        PASS = "PASS", "Pass"
        FAIL = "FAIL", "Fail"
        INCOMPLETE = "INCOMPLETE", "Incomplete"
        ABSENT = "ABSENT", "Absent"

    assessment = models.ForeignKey(
        ReportCardAssessment,
        on_delete=models.CASCADE,
        related_name="student_results",
    )
    student = models.ForeignKey(
        "student_parent.StudentProfile",
        on_delete=models.CASCADE,
        related_name="report_card_results",
    )
    academic_session = models.ForeignKey(
        "student_parent.StudentAcademicSession",
        on_delete=models.PROTECT,
        related_name="report_card_results",
    )
    total_obtained = models.DecimalField(max_digits=9, decimal_places=2, default=Decimal("0.00"))
    total_max_marks = models.DecimalField(max_digits=9, decimal_places=2, default=Decimal("0.00"))
    weighted_total = models.DecimalField(max_digits=9, decimal_places=2, default=Decimal("0.00"))
    total_weightage = models.DecimalField(max_digits=9, decimal_places=2, default=Decimal("0.00"))
    percentage = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    grade = models.CharField(max_length=20, blank=True)
    rank = models.PositiveIntegerField(null=True, blank=True)
    result_status = models.CharField(
        max_length=20,
        choices=ResultStatus.choices,
        default=ResultStatus.INCOMPLETE,
    )
    remark = models.CharField(max_length=255, blank=True)
    is_stale = models.BooleanField(default=False)
    student_name_snapshot = models.CharField(max_length=180, blank=True)
    admission_number_snapshot = models.CharField(max_length=40, blank=True)
    generated_at = models.DateTimeField(default=timezone.now)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["rank", "-percentage", "admission_number_snapshot"]
        constraints = [
            models.UniqueConstraint(
                fields=["assessment", "academic_session"],
                name="rc_result_unique_session",
            ),
        ]
        indexes = [
            models.Index(fields=["assessment", "result_status"], name="rc_result_status_idx"),
            models.Index(fields=["student", "-generated_at"], name="rc_result_student_idx"),
            models.Index(fields=["assessment", "rank"], name="rc_result_rank_idx"),
        ]

    def __str__(self):
        return f"{self.admission_number_snapshot or self.student} - {self.assessment}"

    def clean(self):
        super().clean()
        errors = {}
        if self.academic_session_id:
            if self.student_id and self.student_id != self.academic_session.student_id:
                errors["student"] = "Result student must match the academic session student."
            if self.assessment_id:
                if self.academic_session.institute_id != self.assessment.institute_id:
                    errors["academic_session"] = "Student session belongs to another institute."
                if self.academic_session.academic_year_id != self.assessment.academic_year_id:
                    errors["academic_session"] = "Student session belongs to another academic year."
        if self.total_obtained < 0:
            errors["total_obtained"] = "Total obtained cannot be negative."
        if self.total_max_marks < 0:
            errors["total_max_marks"] = "Total max marks cannot be negative."
        if self.percentage is not None and (self.percentage < 0 or self.percentage > 100):
            errors["percentage"] = "Percentage must be between 0 and 100."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.academic_session_id:
            self.student = self.academic_session.student
            self.admission_number_snapshot = self.academic_session.admission_number
        if self.student_id:
            self.student_name_snapshot = _user_display_name(self.student.user)
            if not self.admission_number_snapshot:
                self.admission_number_snapshot = self.student.admission_number
        self.full_clean()
        super().save(*args, **kwargs)


class ReportCardSubjectResult(models.Model):
    result = models.ForeignKey(
        ReportCardStudentResult,
        on_delete=models.CASCADE,
        related_name="subject_results",
    )
    assessment_subject = models.ForeignKey(
        ReportCardAssessmentSubject,
        on_delete=models.CASCADE,
        related_name="subject_results",
    )
    academic_session = models.ForeignKey(
        "student_parent.StudentAcademicSession",
        on_delete=models.PROTECT,
        related_name="report_card_subject_results",
    )
    subject_name_snapshot = models.CharField(max_length=120, blank=True)
    obtained_marks = models.DecimalField(max_digits=9, decimal_places=2, default=Decimal("0.00"))
    max_marks = models.DecimalField(max_digits=9, decimal_places=2, default=Decimal("0.00"))
    percentage = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    grade = models.CharField(max_length=20, blank=True)
    is_absent = models.BooleanField(default=False)
    is_optional = models.BooleanField(default=False)
    include_in_total = models.BooleanField(default=True)
    remark = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["assessment_subject__display_order", "subject_name_snapshot"]
        constraints = [
            models.UniqueConstraint(
                fields=["result", "assessment_subject"],
                name="rc_subject_result_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["result"], name="rc_subj_result_result_idx"),
            models.Index(fields=["academic_session"], name="rc_subj_result_session_idx"),
        ]

    def __str__(self):
        return f"{self.subject_name_snapshot or self.assessment_subject} - {self.result}"

    def save(self, *args, **kwargs):
        if self.assessment_subject_id:
            self.subject_name_snapshot = self.assessment_subject.subject_name_snapshot
            self.is_optional = self.assessment_subject.is_optional
            self.include_in_total = self.assessment_subject.include_in_total
        self.full_clean()
        super().save(*args, **kwargs)


class ReportCardGradeRule(models.Model):
    institute = models.ForeignKey(
        "super_admin.Institute",
        on_delete=models.CASCADE,
        related_name="report_card_grade_rules",
    )
    academic_year = models.ForeignKey(
        "institute_admin.AcademicYear",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="report_card_grade_rules",
    )
    min_percentage = models.DecimalField(max_digits=6, decimal_places=2)
    max_percentage = models.DecimalField(max_digits=6, decimal_places=2)
    grade = models.CharField(max_length=20)
    remark = models.CharField(max_length=120, blank=True)
    display_order = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["display_order", "-min_percentage"]
        constraints = [
            models.UniqueConstraint(
                fields=["institute", "academic_year", "grade"],
                name="rc_grade_unique_grade",
            ),
        ]
        indexes = [
            models.Index(fields=["institute", "academic_year", "is_active"], name="rc_grade_scope_idx"),
            models.Index(fields=["min_percentage", "max_percentage"], name="rc_grade_range_idx"),
        ]

    def __str__(self):
        year = self.academic_year.name if self.academic_year_id else "Default"
        return f"{self.institute} - {year} - {self.grade}"

    def clean(self):
        super().clean()
        errors = {}
        if self.academic_year_id and self.academic_year.institute_id != self.institute_id:
            errors["academic_year"] = "Selected academic year belongs to another institute."
        if self.min_percentage is not None and (self.min_percentage < 0 or self.min_percentage > 100):
            errors["min_percentage"] = "Minimum percentage must be between 0 and 100."
        if self.max_percentage is not None and (self.max_percentage < 0 or self.max_percentage > 100):
            errors["max_percentage"] = "Maximum percentage must be between 0 and 100."
        if (
            self.min_percentage is not None
            and self.max_percentage is not None
            and self.min_percentage > self.max_percentage
        ):
            errors["max_percentage"] = "Maximum percentage cannot be less than minimum percentage."
        if self.institute_id and self.min_percentage is not None and self.max_percentage is not None:
            overlapping = ReportCardGradeRule.objects.filter(
                institute=self.institute,
                academic_year=self.academic_year,
                is_active=True,
                min_percentage__lte=self.max_percentage,
                max_percentage__gte=self.min_percentage,
            )
            if self.pk:
                overlapping = overlapping.exclude(pk=self.pk)
            if self.is_active and overlapping.exists():
                errors["min_percentage"] = "Grade percentage range overlaps with another active rule."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class ReportCardAuditLog(models.Model):
    class Action(models.TextChoices):
        ASSESSMENT_CREATED = "ASSESSMENT_CREATED", "Assessment created"
        ASSESSMENT_UPDATED = "ASSESSMENT_UPDATED", "Assessment updated"
        STRUCTURE_CHANGED = "STRUCTURE_CHANGED", "Structure changed"
        MARKS_ENTRY_OPENED = "MARKS_ENTRY_OPENED", "Marks entry opened"
        MARKS_SAVED = "MARKS_SAVED", "Marks saved"
        RESULTS_GENERATED = "RESULTS_GENERATED", "Results generated"
        RESULTS_PUBLISHED = "RESULTS_PUBLISHED", "Results published"
        ASSESSMENT_LOCKED = "ASSESSMENT_LOCKED", "Assessment locked"
        ASSESSMENT_UNLOCKED = "ASSESSMENT_UNLOCKED", "Assessment unlocked"

    assessment = models.ForeignKey(
        ReportCardAssessment,
        on_delete=models.CASCADE,
        related_name="audit_logs",
    )
    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="report_card_audit_logs",
    )
    action = models.CharField(max_length=40, choices=Action.choices)
    message = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["assessment", "-created_at"], name="rc_audit_assess_idx"),
            models.Index(fields=["actor", "-created_at"], name="rc_audit_actor_idx"),
            models.Index(fields=["action", "-created_at"], name="rc_audit_action_idx"),
        ]

    def __str__(self):
        actor = _user_display_name(self.actor) or "System"
        return f"{self.get_action_display()} - {self.assessment} - {actor}"
