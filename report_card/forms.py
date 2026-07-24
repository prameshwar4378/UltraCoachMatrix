"""Forms for the Report Card Generator app."""

import json
from decimal import Decimal

from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from institute_admin.models import AcademicYear, Batch, Subject
from student_parent.models import StudentAcademicSession
from super_admin.models import UserProfile

from .models import (
    ReportCardAssessment,
    ReportCardAssessmentSubject,
    ReportCardAssessmentSubjectComponent,
    ReportCardGradeRule,
    ReportCardTeacherSubjectAllocation,
)
from .selectors import get_active_student_sessions_for_assessment, get_teacher_assigned_batches, get_teacher_institute


EDIT_BLOCKED_STATUSES = {
    ReportCardAssessment.Status.PUBLISHED,
    ReportCardAssessment.Status.LOCKED,
}
STRUCTURE_EDIT_STATUSES = {
    ReportCardAssessment.Status.DRAFT,
    ReportCardAssessment.Status.STRUCTURE_READY,
}


def _add_form_control(field):
    css_class = field.widget.attrs.get("class", "")
    field.widget.attrs["class"] = f"{css_class} form-control".strip()


def _add_form_select(field):
    css_class = field.widget.attrs.get("class", "")
    field.widget.attrs["class"] = f"{css_class} form-select".strip()


class ReportCardAssessmentForm(forms.ModelForm):
    batches = forms.ModelMultipleChoiceField(
        queryset=Batch.objects.none(),
        required=False,
        label="Classes / batches",
        widget=forms.SelectMultiple,
    )

    class Meta:
        model = ReportCardAssessment
        fields = ("academic_year", "batch", "title", "assessment_date", "result_date")
        labels = {
            "academic_year": "Academic year",
            "batch": "Class / batch",
            "title": "Assessment name",
            "assessment_date": "Assessment date",
            "result_date": "Result date",
        }
        widgets = {
            "assessment_date": forms.DateInput(attrs={"type": "date"}),
            "result_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, user=None, institute=None, academic_year=None, **kwargs):
        if args and academic_year:
            data = args[0]
            if data is not None and not data.get("academic_year"):
                data = data.copy()
                data["academic_year"] = str(academic_year.pk)
                args = (data, *args[1:])
        super().__init__(*args, **kwargs)
        self.user = user
        self.institute = institute or get_teacher_institute(user)
        self.effective_institute = self.institute
        self.selected_academic_year = academic_year

        academic_years = AcademicYear.objects.none()
        batches = Batch.objects.none()
        if user:
            batches = get_teacher_assigned_batches(user)
            assigned_year_ids = batches.values_list("academic_year_id", flat=True).distinct()
            academic_years = AcademicYear.objects.filter(pk__in=assigned_year_ids, is_active=True).order_by("-start_date")
            if self.selected_academic_year:
                academic_years = academic_years.filter(pk=self.selected_academic_year.pk)
                batches = batches.filter(academic_year=self.selected_academic_year)
        elif self.institute:
            academic_years = self.institute.academic_years.filter(is_active=True).order_by("-start_date")
            batches = Batch.objects.filter(institute=self.institute, is_active=True)
            if self.selected_academic_year:
                academic_years = academic_years.filter(pk=self.selected_academic_year.pk)
                batches = batches.filter(academic_year=self.selected_academic_year)

        self.fields["academic_year"].queryset = academic_years
        self.fields["batch"].queryset = batches
        self.fields["batches"].queryset = batches
        for field_name in ("academic_year", "batch"):
            _add_form_select(self.fields[field_name])
        _add_form_select(self.fields["batches"])
        for field_name in ("title", "assessment_date", "result_date"):
            _add_form_control(self.fields[field_name])
        self.fields["title"].widget.attrs.update({"placeholder": "Example: Mid Term Assessment"})
        self.fields["batches"].widget.attrs.update({"data-searchable": "false", "size": "5"})
        if self.selected_academic_year:
            self.fields["academic_year"].initial = self.selected_academic_year
            self.fields["academic_year"].widget = forms.HiddenInput()
        self.fields["batch"].required = False

    def clean(self):
        cleaned_data = super().clean()
        if self.instance.pk and self.instance.status in EDIT_BLOCKED_STATUSES:
            raise ValidationError("Published or locked assessments cannot be edited.")

        academic_year = cleaned_data.get("academic_year")
        batch = cleaned_data.get("batch")
        selected_batches = cleaned_data.get("batches")
        if selected_batches:
            batch = selected_batches.first()
            cleaned_data["batch"] = batch
        elif batch:
            cleaned_data["batches"] = Batch.objects.filter(pk=batch.pk)
        elif not selected_batches:
            self.add_error("batches", "Select at least one class / batch.")
        if batch and self.user and not self.user.assigned_batches.filter(pk=batch.pk).exists():
            self.add_error("batch", "Selected batch is not assigned to this teacher.")
        if batch:
            self.effective_institute = batch.institute
        elif academic_year:
            self.effective_institute = academic_year.institute

        if self.effective_institute and academic_year and academic_year.institute_id != self.effective_institute.pk:
            self.add_error("academic_year", "Selected academic year belongs to another institute.")
        if self.effective_institute and batch and batch.institute_id != self.effective_institute.pk:
            self.add_error("batch", "Selected batch belongs to another institute.")
        if academic_year and batch and batch.academic_year_id != academic_year.pk:
            self.add_error("batch", "Selected batch belongs to another academic year.")
        if self.effective_institute and selected_batches:
            for selected_batch in selected_batches:
                if selected_batch.institute_id != self.effective_institute.pk:
                    self.add_error("batches", "One selected batch belongs to another institute.")
                    break
                if academic_year and selected_batch.academic_year_id != academic_year.pk:
                    self.add_error("batches", "One selected batch belongs to another academic year.")
                    break
        if self.effective_institute:
            self.instance.institute = self.effective_institute

        assessment_date = cleaned_data.get("assessment_date")
        result_date = cleaned_data.get("result_date")
        if assessment_date and result_date and result_date < assessment_date:
            self.add_error("result_date", "Result date cannot be before assessment date.")
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.effective_institute:
            instance.institute = self.effective_institute
        if commit:
            instance.save()
        return instance


class ReportCardAssessmentSubjectForm(forms.ModelForm):
    components_json = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = ReportCardAssessmentSubject
        fields = (
            "subject",
            "max_marks",
            "passing_marks",
            "weightage",
            "display_order",
            "is_optional",
            "include_in_total",
        )
        labels = {
            "subject": "Subject",
            "max_marks": "Maximum marks",
            "passing_marks": "Passing marks",
            "weightage": "Result weightage",
            "display_order": "Display order",
            "is_optional": "Optional subject",
            "include_in_total": "Include in total percentage",
        }

    def __init__(self, *args, assessment=None, institute=None, academic_year=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.assessment = assessment or getattr(self.instance, "assessment", None)
        self.institute = institute or getattr(self.assessment, "institute", None)
        self.academic_year = academic_year or getattr(self.assessment, "academic_year", None)

        subjects = Subject.objects.none()
        if self.institute:
            subjects = Subject.objects.filter(institute=self.institute, is_active=True).order_by("name")
            if self.academic_year:
                subjects = subjects.filter(academic_year=self.academic_year)
            if self.assessment:
                used_subject_ids = self.assessment.assessment_subjects.exclude(pk=self.instance.pk).values_list(
                    "subject_id",
                    flat=True,
                )
                subjects = subjects.exclude(pk__in=used_subject_ids)
        self.fields["subject"].queryset = subjects

        _add_form_select(self.fields["subject"])
        for field_name in ("max_marks", "passing_marks", "weightage", "display_order"):
            _add_form_control(self.fields[field_name])
        for field_name in ("is_optional", "include_in_total"):
            self.fields[field_name].widget.attrs["class"] = "form-check-input"
        self.fields["max_marks"].required = False
        self.fields["weightage"].required = False
        self.fields["display_order"].required = False
        self.fields["max_marks"].widget = forms.HiddenInput()
        self.fields["weightage"].widget = forms.HiddenInput()
        self.fields["display_order"].widget = forms.HiddenInput()
        self.fields["components_json"].initial = self._initial_components_json()

    def _initial_components_json(self):
        if not self.instance.pk:
            return json.dumps(
                [
                    {
                        "id": None,
                        "name": "Theory Exam",
                        "max_marks": "",
                        "passing_marks": "0",
                        "weightage": "",
                        "display_order": 1,
                        "include_in_total": True,
                        "is_primary": True,
                    }
                ]
            )
        rows = [
            {
                "id": component.pk,
                "name": component.name_snapshot or component.name,
                "max_marks": str(component.max_marks),
                "passing_marks": "0",
                "weightage": str(component.weightage),
                "display_order": component.display_order,
                "include_in_total": component.include_in_total,
                "is_primary": component.display_order == 1,
            }
            for component in self.instance.components.order_by("display_order", "name_snapshot", "id")
        ]
        if not rows:
            rows = [
                {
                    "id": None,
                    "name": "Theory Exam",
                    "max_marks": str(self.instance.max_marks),
                    "passing_marks": "0",
                    "weightage": str(self.instance.max_marks),
                    "display_order": 1,
                    "include_in_total": True,
                    "is_primary": True,
                }
            ]
        return json.dumps(rows)

    def clean(self):
        cleaned_data = super().clean()
        assessment = self.assessment
        if not assessment:
            raise ValidationError("Assessment is required to configure a subject.")
        if assessment.status not in STRUCTURE_EDIT_STATUSES:
            raise ValidationError("Assessment subjects can only be edited before marks entry opens.")

        subject = cleaned_data.get("subject")
        max_marks = cleaned_data.get("max_marks")
        passing_marks = cleaned_data.get("passing_marks")
        weightage = cleaned_data.get("weightage")

        if subject:
            if subject.institute_id != assessment.institute_id:
                self.add_error("subject", "Selected subject belongs to another institute.")
            if subject.academic_year_id != assessment.academic_year_id:
                self.add_error("subject", "Selected subject belongs to another academic year.")
        if passing_marks is not None and passing_marks < 0:
            self.add_error("passing_marks", "Passing marks cannot be negative.")

        components = self._clean_components(cleaned_data.get("components_json") or "[]")
        cleaned_data["components"] = components
        component_total = sum(
            (row["max_marks"] for row in components if row["include_in_total"]),
            Decimal("0.00"),
        )
        if component_total <= 0:
            self.add_error("components_json", "At least one marks column must be included in total.")
        if passing_marks is not None and passing_marks > component_total:
            self.add_error("passing_marks", "Passing marks cannot exceed the total marks.")
        cleaned_data["max_marks"] = component_total
        cleaned_data["weightage"] = component_total
        if self.instance.pk:
            cleaned_data["display_order"] = self.instance.display_order
        else:
            cleaned_data["display_order"] = self._next_subject_display_order()
        self.instance.max_marks = component_total
        self.instance.weightage = component_total
        self.instance.display_order = cleaned_data["display_order"]
        return cleaned_data

    def _next_subject_display_order(self):
        if not self.assessment:
            return 1
        max_order = (
            self.assessment.assessment_subjects.exclude(pk=self.instance.pk)
            .order_by("-display_order")
            .values_list("display_order", flat=True)
            .first()
        )
        return (max_order or 0) + 1

    def _clean_components(self, raw_value):
        try:
            rows = json.loads(raw_value)
        except json.JSONDecodeError as error:
            raise ValidationError({"components_json": "Additional columns data is invalid."}) from error
        if not isinstance(rows, list):
            raise ValidationError({"components_json": "Additional columns data is invalid."})
        if not rows:
            raise ValidationError({"components_json": "At least one marks column is required."})

        cleaned_rows = []
        seen_names = set()
        seen_orders = set()
        existing_ids = set(self.instance.components.values_list("pk", flat=True)) if self.instance.pk else set()
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                raise ValidationError({"components_json": f"Column row {index} is invalid."})
            name = str(row.get("name") or "").strip()
            if not name:
                raise ValidationError({"components_json": f"Column row {index} needs a name."})
            name_key = name.lower()
            if name_key in seen_names:
                raise ValidationError({"components_json": f"Duplicate column name: {name}."})
            seen_names.add(name_key)

            try:
                max_marks = Decimal(str(row.get("max_marks")))
                passing_marks = Decimal("0.00")
                weightage = max_marks
                display_order = index
            except (TypeError, ValueError, ArithmeticError):
                raise ValidationError({"components_json": f"Column row {index} has invalid numeric values."})
            if max_marks <= 0:
                raise ValidationError({"components_json": f"{name} maximum marks must be greater than 0."})
            if weightage <= 0:
                raise ValidationError({"components_json": f"{name} weightage must be greater than 0."})
            seen_orders.add(display_order)

            component_id = row.get("id") or None
            if component_id in ("", "null"):
                component_id = None
            if component_id is not None:
                try:
                    component_id = int(component_id)
                except (TypeError, ValueError):
                    raise ValidationError({"components_json": f"{name} has an invalid column id."})
                if existing_ids and component_id not in existing_ids:
                    raise ValidationError({"components_json": f"{name} column does not belong to this subject."})

            cleaned_rows.append(
                {
                    "id": component_id,
                    "name": name,
                    "max_marks": max_marks,
                    "passing_marks": passing_marks,
                    "weightage": weightage,
                    "display_order": display_order,
                    "include_in_total": bool(row.get("include_in_total", True)),
                }
            )
        return cleaned_rows

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.assessment:
            instance.assessment = self.assessment
        if commit:
            instance.save()
        return instance


class ReportCardAssessmentSubjectComponentForm(forms.ModelForm):
    class Meta:
        model = ReportCardAssessmentSubjectComponent
        fields = (
            "name",
            "max_marks",
            "passing_marks",
            "weightage",
            "display_order",
            "include_in_total",
        )
        labels = {
            "name": "Column name",
            "max_marks": "Maximum marks",
            "passing_marks": "Passing marks",
            "weightage": "Weightage",
            "display_order": "Display order",
            "include_in_total": "Include in subject total",
        }

    def __init__(self, *args, assessment_subject=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.assessment_subject = assessment_subject or getattr(self.instance, "assessment_subject", None)
        for field_name in ("name", "max_marks", "passing_marks", "weightage", "display_order"):
            _add_form_control(self.fields[field_name])
        self.fields["include_in_total"].widget.attrs["class"] = "form-check-input"
        self.fields["name"].widget.attrs.update({"placeholder": "Notebook, Practical, Internal, Theory"})
        self.fields["weightage"].initial = self.fields["weightage"].initial or Decimal("100.00")

    def clean(self):
        cleaned_data = super().clean()
        if not self.assessment_subject:
            raise ValidationError("Subject is required to configure a column.")
        if self.assessment_subject.assessment.status not in STRUCTURE_EDIT_STATUSES:
            raise ValidationError("Subject columns can only be edited before marks entry opens.")
        max_marks = cleaned_data.get("max_marks")
        passing_marks = cleaned_data.get("passing_marks")
        weightage = cleaned_data.get("weightage")
        if max_marks is not None and max_marks <= 0:
            self.add_error("max_marks", "Maximum marks must be greater than 0.")
        if passing_marks is not None and passing_marks < 0:
            self.add_error("passing_marks", "Passing marks cannot be negative.")
        if max_marks is not None and passing_marks is not None and passing_marks > max_marks:
            self.add_error("passing_marks", "Passing marks cannot exceed maximum marks.")
        if weightage is not None and weightage <= 0:
            self.add_error("weightage", "Weightage must be greater than 0.")
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.assessment_subject:
            instance.assessment_subject = self.assessment_subject
        if commit:
            instance.save()
        return instance


class BulkMarksEntryForm(forms.Form):
    academic_session_id = forms.IntegerField(widget=forms.HiddenInput)
    marks_obtained = forms.DecimalField(
        label="Marks obtained",
        required=False,
        min_value=Decimal("0.00"),
        max_digits=7,
        decimal_places=2,
    )
    is_absent = forms.BooleanField(label="Absent", required=False)
    remark = forms.CharField(label="Remark", required=False, max_length=255)

    def __init__(self, *args, assessment_subject=None, components=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.assessment_subject = assessment_subject
        self.components = list(components or [])
        if self.components:
            self.fields.pop("marks_obtained")
            for component in self.components:
                field_name = f"component_{component.pk}"
                self.fields[field_name] = forms.DecimalField(
                    label=component.name_snapshot or component.name,
                    required=False,
                    min_value=Decimal("0.00"),
                    max_digits=7,
                    decimal_places=2,
                )
                _add_form_control(self.fields[field_name])
        else:
            _add_form_control(self.fields["marks_obtained"])
        _add_form_control(self.fields["remark"])
        self.fields["is_absent"].widget.attrs["class"] = "form-check-input"

    def clean(self):
        cleaned_data = super().clean()
        if not self.assessment_subject:
            raise ValidationError("Assessment subject is required for marks entry.")

        assessment = self.assessment_subject.assessment
        if assessment.status in EDIT_BLOCKED_STATUSES:
            raise ValidationError("Marks cannot be edited after assessment is published or locked.")

        academic_session_id = cleaned_data.get("academic_session_id")
        marks_obtained = cleaned_data.get("marks_obtained")
        is_absent = cleaned_data.get("is_absent")

        valid_session_ids = set(
            get_active_student_sessions_for_assessment(assessment).values_list("pk", flat=True)
        )
        if academic_session_id not in valid_session_ids:
            self.add_error("academic_session_id", "Student is not active in this assessment batch.")

        if is_absent:
            return cleaned_data
        if self.components:
            for component in self.components:
                field_name = f"component_{component.pk}"
                value = cleaned_data.get(field_name)
                if value is not None and value > component.max_marks:
                    self.add_error(field_name, "Marks cannot exceed column maximum marks.")
            return cleaned_data
        if marks_obtained is not None and marks_obtained > self.assessment_subject.max_marks:
            self.add_error("marks_obtained", "Marks cannot exceed subject maximum marks.")
        return cleaned_data

    @property
    def academic_session(self):
        session_id = self.cleaned_data.get("academic_session_id") if hasattr(self, "cleaned_data") else None
        if not session_id:
            return None
        return StudentAcademicSession.objects.filter(pk=session_id).select_related("student", "student__user").first()

    def to_service_row(self):
        component_marks = {}
        for component in self.components:
            component_marks[component.pk] = self.cleaned_data.get(f"component_{component.pk}")
        return {
            "academic_session_id": self.cleaned_data["academic_session_id"],
            "marks_obtained": self.cleaned_data.get("marks_obtained"),
            "component_marks": component_marks,
            "is_absent": self.cleaned_data.get("is_absent", False),
            "remark": self.cleaned_data.get("remark", ""),
        }


class ReportCardGradeRuleForm(forms.ModelForm):
    class Meta:
        model = ReportCardGradeRule
        fields = (
            "academic_year",
            "min_percentage",
            "max_percentage",
            "grade",
            "remark",
            "display_order",
            "is_active",
        )
        labels = {
            "academic_year": "Academic year",
            "min_percentage": "Minimum percentage",
            "max_percentage": "Maximum percentage",
            "grade": "Grade",
            "remark": "Result remark",
            "display_order": "Display order",
            "is_active": "Active",
        }

    def __init__(self, *args, institute=None, academic_year=None, **kwargs):
        if args and academic_year:
            data = args[0]
            if data is not None and not data.get("academic_year"):
                data = data.copy()
                data["academic_year"] = str(academic_year.pk)
                args = (data, *args[1:])
        super().__init__(*args, **kwargs)
        self.institute = institute or getattr(self.instance, "institute", None)
        self.selected_academic_year = academic_year or getattr(self.instance, "academic_year", None)
        if self.institute:
            self.instance.institute = self.institute
        academic_years = AcademicYear.objects.none()
        if self.institute:
            academic_years = self.institute.academic_years.filter(is_active=True).order_by("-start_date")
        self.fields["academic_year"].queryset = academic_years
        self.fields["academic_year"].required = False
        if self.selected_academic_year:
            self.fields["academic_year"].initial = self.selected_academic_year
            self.fields["academic_year"].widget = forms.HiddenInput()
        else:
            _add_form_select(self.fields["academic_year"])
        for field_name in ("min_percentage", "max_percentage", "grade", "remark", "display_order"):
            _add_form_control(self.fields[field_name])
        self.fields["is_active"].widget.attrs["class"] = "form-check-input"

    def clean(self):
        cleaned_data = super().clean()
        academic_year = cleaned_data.get("academic_year")
        min_percentage = cleaned_data.get("min_percentage")
        max_percentage = cleaned_data.get("max_percentage")

        if self.institute and academic_year and academic_year.institute_id != self.institute.pk:
            self.add_error("academic_year", "Selected academic year belongs to another institute.")
        if min_percentage is not None and (min_percentage < 0 or min_percentage > 100):
            self.add_error("min_percentage", "Minimum percentage must be between 0 and 100.")
        if max_percentage is not None and (max_percentage < 0 or max_percentage > 100):
            self.add_error("max_percentage", "Maximum percentage must be between 0 and 100.")
        if (
            min_percentage is not None
            and max_percentage is not None
            and max_percentage < min_percentage
        ):
            self.add_error("max_percentage", "Maximum percentage cannot be less than minimum percentage.")
        if (
            self.institute
            and min_percentage is not None
            and max_percentage is not None
            and cleaned_data.get("is_active", True)
        ):
            overlapping = ReportCardGradeRule.objects.filter(
                institute=self.institute,
                academic_year=academic_year,
                is_active=True,
                min_percentage__lte=max_percentage,
                max_percentage__gte=min_percentage,
            )
            if self.instance.pk:
                overlapping = overlapping.exclude(pk=self.instance.pk)
            if overlapping.exists():
                self.add_error("min_percentage", "This percentage range overlaps with another active grade rule.")
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.institute:
            instance.institute = self.institute
        if commit:
            instance.save()
        return instance


class ReportCardTeacherSubjectAllocationForm(forms.ModelForm):
    class Meta:
        model = ReportCardTeacherSubjectAllocation
        fields = ("academic_year", "batch", "subject", "teacher", "is_active")
        labels = {
            "academic_year": "Academic year",
            "batch": "Class / batch",
            "subject": "Subject",
            "teacher": "Teacher",
            "is_active": "Active allocation",
        }

    def __init__(self, *args, institute=None, created_by=None, academic_year=None, **kwargs):
        if args and academic_year:
            data = args[0]
            if data is not None and not data.get("academic_year"):
                data = data.copy()
                data["academic_year"] = str(academic_year.pk)
                args = (data, *args[1:])
        super().__init__(*args, **kwargs)
        self.institute = institute or getattr(self.instance, "institute", None)
        self.created_by = created_by
        self.selected_academic_year = academic_year or getattr(self.instance, "academic_year", None)
        if self.institute:
            self.instance.institute = self.institute
        academic_year = self.selected_academic_year or self._selected_academic_year()

        self.fields["academic_year"].queryset = AcademicYear.objects.none()
        self.fields["batch"].queryset = Batch.objects.none()
        self.fields["subject"].queryset = Subject.objects.none()
        self.fields["teacher"].queryset = User.objects.none()

        if self.institute:
            self.fields["academic_year"].queryset = self.institute.academic_years.filter(is_active=True).order_by("-start_date")
            self.fields["teacher"].queryset = User.objects.filter(
                profile__institute=self.institute,
                profile__role=UserProfile.Role.TEACHER,
                is_active=True,
            ).order_by("first_name", "last_name", "username")
            if academic_year:
                self.fields["batch"].queryset = Batch.objects.filter(
                    institute=self.institute,
                    academic_year=academic_year,
                    is_active=True,
                ).order_by("name")
                self.fields["subject"].queryset = Subject.objects.filter(
                    institute=self.institute,
                    academic_year=academic_year,
                    is_active=True,
                ).order_by("name")

        for field_name in ("academic_year", "batch", "subject", "teacher"):
            _add_form_select(self.fields[field_name])
        if academic_year:
            self.fields["academic_year"].initial = academic_year
            self.fields["academic_year"].widget = forms.HiddenInput()
        self.fields["is_active"].widget.attrs["class"] = "form-check-input"

    def _selected_academic_year(self):
        value = None
        if self.data:
            value = self.data.get(self.add_prefix("academic_year"))
        if not value and self.instance.pk:
            return self.instance.academic_year
        if not value:
            return None
        try:
            return AcademicYear.objects.get(pk=value)
        except (AcademicYear.DoesNotExist, TypeError, ValueError):
            return None

    def clean(self):
        cleaned_data = super().clean()
        academic_year = cleaned_data.get("academic_year")
        batch = cleaned_data.get("batch")
        subject = cleaned_data.get("subject")
        teacher = cleaned_data.get("teacher")

        if self.institute and academic_year and academic_year.institute_id != self.institute.pk:
            self.add_error("academic_year", "Selected academic year belongs to another institute.")
        if self.institute and batch:
            if batch.institute_id != self.institute.pk:
                self.add_error("batch", "Selected batch belongs to another institute.")
            if academic_year and batch.academic_year_id != academic_year.pk:
                self.add_error("batch", "Selected batch belongs to another academic year.")
        if self.institute and subject:
            if subject.institute_id != self.institute.pk:
                self.add_error("subject", "Selected subject belongs to another institute.")
            if academic_year and subject.academic_year_id != academic_year.pk:
                self.add_error("subject", "Selected subject belongs to another academic year.")
        if self.institute and teacher:
            profile = getattr(teacher, "profile", None)
            if not profile or profile.role != UserProfile.Role.TEACHER:
                self.add_error("teacher", "Selected user must be a teacher.")
            elif profile.institute_id != self.institute.pk:
                self.add_error("teacher", "Selected teacher belongs to another institute.")

        if academic_year and batch and subject and teacher:
            duplicate = ReportCardTeacherSubjectAllocation.objects.filter(
                academic_year=academic_year,
                batch=batch,
                subject=subject,
                teacher=teacher,
            )
            if self.instance.pk:
                duplicate = duplicate.exclude(pk=self.instance.pk)
            if duplicate.exists():
                self.add_error("teacher", "This teacher is already allocated to this class and subject for the selected academic year.")
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.institute:
            instance.institute = self.institute
        if self.created_by and not instance.created_by_id:
            instance.created_by = self.created_by
        if commit:
            instance.save()
        return instance
