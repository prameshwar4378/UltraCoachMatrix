from decimal import Decimal
from datetime import date
import re

from django import forms
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Prefetch, Q, Sum
from django.utils import timezone

from accountant.models import Expense, FeeCategory, FeeInvoice, Payment, PaymentActivity
from super_admin.models import Institute, UserProfile
from student_parent.models import (
    GuardianProfile,
    StudentBonafideCertificate,
    StudentAcademicSession,
    StudentDocument,
    StudentEnrollment,
    StudentProfile,
    StudentTransferCertificate,
)
from teacher.models import Homework, HomeworkAttachment, TeacherProfile

from .models import AcademicYear, Batch, Course, InstitutePrintTemplate, Lead, Notice, PrintDocumentType, Subject, SupportTicket, Visitor


STUDENT_AUTOCOMPLETE_URL = "/institute/students/autocomplete/"


def ajax_student_widget(*, multiple=False):
    widget_class = forms.SelectMultiple if multiple else forms.Select
    return widget_class(
        attrs={
            "class": "form-select",
            "data-student-autocomplete": "true",
            "data-searchable": "false",
            "data-autocomplete-url": STUDENT_AUTOCOMPLETE_URL,
            "data-minimum-input-length": "2",
            "data-placeholder": "Type admission number, name, username or phone",
        }
    )


def selected_student_ids(form, field_name):
    if form.is_bound:
        if hasattr(form.data, "getlist"):
            values = form.data.getlist(field_name)
        else:
            value = form.data.get(field_name)
            values = value if isinstance(value, (list, tuple)) else [value]
        return [value for value in values if str(value or "").isdigit()]

    initial = form.initial.get(field_name)
    if initial is None and form.instance and form.instance.pk:
        relation = getattr(form.instance, field_name, None)
        if hasattr(relation, "values_list"):
            return list(relation.values_list("pk", flat=True))
        if relation is not None:
            initial = relation
    if hasattr(initial, "pk"):
        return [initial.pk]
    if isinstance(initial, (list, tuple, set)):
        return [value.pk if hasattr(value, "pk") else value for value in initial]
    return [initial] if initial else []


class SecurityPasswordChangeForm(forms.Form):
    current_password = forms.CharField(
        label="Current password",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "autocomplete": "current-password",
                "placeholder": "Enter current password",
            }
        ),
    )
    new_password = forms.CharField(
        label="New password",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "autocomplete": "new-password",
                "placeholder": "Enter new password",
            }
        ),
    )
    confirm_password = forms.CharField(
        label="Confirm new password",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "autocomplete": "new-password",
                "placeholder": "Confirm new password",
            }
        ),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_current_password(self):
        current_password = self.cleaned_data["current_password"]
        if not self.user or not self.user.check_password(current_password):
            raise ValidationError("Current password is incorrect.")
        return current_password

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get("new_password")
        confirm_password = cleaned_data.get("confirm_password")

        if new_password and confirm_password and new_password != confirm_password:
            self.add_error("confirm_password", "New passwords do not match.")

        if new_password and self.user:
            if self.user.check_password(new_password):
                self.add_error("new_password", "Choose a password different from your current password.")
            else:
                try:
                    password_validation.validate_password(new_password, self.user)
                except ValidationError as error:
                    self.add_error("new_password", error)

        return cleaned_data

    def save(self):
        self.user.set_password(self.cleaned_data["new_password"])
        self.user.save(update_fields=["password"])
        return self.user


class InstitutePrintTemplateForm(forms.ModelForm):
    document_type = forms.ChoiceField(
        label="Template Type",
        choices=(
            (PrintDocumentType.TRANSFER_CERTIFICATE, "TC"),
            (PrintDocumentType.ADMISSION_FORM, "Admission Form"),
            (PrintDocumentType.BONAFIDE_CERTIFICATE, "Bonafide"),
        ),
        widget=forms.Select(attrs={"class": "form-select"}),
        help_text="Choose which print document this HTML template will replace for this institute.",
    )

    class Meta:
        model = InstitutePrintTemplate
        fields = ("document_type", "title", "html_file", "is_active")
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control", "placeholder": "School TC template"}),
            "html_file": forms.FileInput(attrs={"class": "form-control", "accept": ".html,.htm,text/html"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        help_texts = {
            "html_file": (
                "Upload an .html file. It can use Django-style variables like "
                "{{ student.user.get_full_name }}, {{ student_session.admission_number }}, and {{ snapshot }}."
            ),
            "is_active": "Turn off to use the default built-in print template.",
        }

    def clean_html_file(self):
        uploaded_file = self.cleaned_data.get("html_file")
        if not uploaded_file:
            return uploaded_file
        name = uploaded_file.name.lower()
        if not (name.endswith(".html") or name.endswith(".htm")):
            raise ValidationError("Upload an HTML file with .html or .htm extension.")
        if uploaded_file.size > 1024 * 1024:
            raise ValidationError("Template file must be 1 MB or smaller.")
        return uploaded_file


class SupportTicketForm(forms.ModelForm):
    class Meta:
        model = SupportTicket
        fields = ("category", "priority", "subject", "message")
        widgets = {
            "message": forms.Textarea(
                attrs={
                    "rows": 5,
                    "placeholder": "Explain what happened, where it happened, and what you expected.",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["subject"].widget.attrs["placeholder"] = "Short issue title"
        for field in self.fields.values():
            field.widget.attrs.setdefault(
                "class",
                "form-select" if isinstance(field.widget, forms.Select) else "form-control",
            )

    def clean_subject(self):
        return self.cleaned_data["subject"].strip()

    def clean_message(self):
        message = self.cleaned_data["message"].strip()
        if len(message) < 15:
            raise ValidationError("Please provide a little more detail about the issue.")
        return message


class InstituteProfileForm(forms.ModelForm):
    class Meta:
        model = Institute
        fields = ("name", "code", "institute_type", "logo", "owner_name", "phone", "email", "address")
        widgets = {
            "address": forms.Textarea(attrs={"rows": 4}),
            "logo": forms.ClearableFileInput(attrs={"accept": "image/*"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        placeholders = {
            "name": "Institute name",
            "code": "Unique institute code",
            "institute_type": "Select institute type",
            "logo": "Upload institute logo",
            "owner_name": "Owner or director name",
            "phone": "Primary contact number",
            "email": "Primary email address",
            "address": "Institute address",
        }
        for field_name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")
            field.widget.attrs.setdefault("placeholder", placeholders[field_name])

    def clean_name(self):
        return self.cleaned_data["name"].strip()

    def clean_code(self):
        code = self.cleaned_data["code"].strip().lower()
        queryset = Institute.objects.filter(code__iexact=code)
        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise ValidationError("This institute code is already in use.")
        return code

    def clean_owner_name(self):
        return self.cleaned_data["owner_name"].strip()

    def clean_phone(self):
        return self.cleaned_data["phone"].strip()

    def clean_address(self):
        return self.cleaned_data["address"].strip()


class AcademicYearForm(forms.ModelForm):
    class Meta:
        model = AcademicYear
        fields = ("name", "start_date", "end_date", "is_active")
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }
        labels = {
            "name": "Session name",
            "is_active": "Active session",
        }

    def __init__(self, *args, institute=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.institute = institute
        self.fields["name"].widget.attrs.update(
            {
                "class": "form-control",
                "placeholder": "Example: 2026-27",
                "autocomplete": "off",
            }
        )
        for field_name in ("start_date", "end_date"):
            self.fields[field_name].widget.attrs["class"] = "form-control"
        self.fields["is_active"].widget.attrs["class"] = "form-check-input"

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        queryset = AcademicYear.objects.filter(institute=self.institute, name__iexact=name)
        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise ValidationError("A session with this name already exists for your institute.")
        return name

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        if not start_date or not end_date:
            return cleaned_data

        if end_date <= start_date:
            self.add_error("end_date", "End date must be after the start date.")
            return cleaned_data

        overlapping = AcademicYear.objects.filter(
            institute=self.institute,
            start_date__lte=end_date,
            end_date__gte=start_date,
        )
        if self.instance.pk:
            overlapping = overlapping.exclude(pk=self.instance.pk)
        if overlapping.exists():
            self.add_error(
                "start_date",
                "These dates overlap another academic session for your institute.",
            )
        return cleaned_data


def get_academic_year_label(today=None):
    today = today or timezone.localdate()
    start_year = today.year if today.month >= 4 else today.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def get_academic_year_dates(name):
    start_year = int(str(name).split("-", 1)[0])
    return date(start_year, 4, 1), date(start_year + 1, 3, 31)


def get_or_create_academic_year(institute, name=None):
    name = name or get_academic_year_label()
    start_date, end_date = get_academic_year_dates(name)
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


def get_institute_initials(institute):
    words = re.findall(r"[A-Za-z0-9]+", institute.name if institute else "")
    initials = "".join(word[0].upper() for word in words if word)
    return initials or "INST"


def get_student_admission_prefix(institute, academic_year):
    institute_code = re.sub(r"[^A-Za-z0-9]", "", institute.code if institute else "").upper()
    if not institute_code:
        raise ValidationError("Institute code is required to generate student registration numbers.")
    start_year = str(academic_year.start_date.year)[-2:]
    end_year = str(academic_year.end_date.year)[-2:]
    return f"{institute_code}{start_year}{end_year}"


def build_student_username(institute, admission_number):
    username = re.sub(r"[^A-Za-z0-9]", "", admission_number or "").upper()
    if not username:
        raise ValidationError("Could not generate the student username.")
    if len(username) > User._meta.get_field("username").max_length:
        raise ValidationError("Generated student username is too long.")
    return username


def get_last_student_admission_sequence(institute, academic_year):
    compact_prefix = get_student_admission_prefix(institute, academic_year)
    initials_prefix = (
        f"{get_institute_initials(institute)}"
        f"{str(academic_year.start_date.year)[-2:]}"
        f"{str(academic_year.end_date.year)[-2:]}"
    )
    legacy_prefix = f"{get_institute_initials(institute)}-{academic_year.name}-"
    existing_numbers = StudentAcademicSession.objects.filter(
        institute=institute,
        academic_year=academic_year,
    ).filter(
        Q(admission_number__startswith=compact_prefix)
        | Q(admission_number__startswith=initials_prefix)
        | Q(admission_number__startswith=legacy_prefix)
    ).values_list("admission_number", flat=True)
    last_sequence = 0
    for admission_number in existing_numbers:
        if admission_number.startswith(compact_prefix):
            prefix = compact_prefix
        elif admission_number.startswith(initials_prefix):
            prefix = initials_prefix
        else:
            prefix = legacy_prefix
        try:
            last_sequence = max(last_sequence, int(admission_number[len(prefix):]))
        except (TypeError, ValueError):
            continue
    return last_sequence


def generate_student_admission_number(institute, academic_year=None):
    academic_year = academic_year or get_or_create_academic_year(institute)
    prefix = get_student_admission_prefix(institute, academic_year)
    last_sequence = get_last_student_admission_sequence(institute, academic_year)
    return f"{prefix}{last_sequence + 1:04d}"


def generate_student_login_credentials(institute, academic_year=None):
    academic_year = academic_year or get_or_create_academic_year(institute)
    prefix = get_student_admission_prefix(institute, academic_year)
    sequence = get_last_student_admission_sequence(institute, academic_year) + 1
    while True:
        admission_number = f"{prefix}{sequence:04d}"
        username = build_student_username(institute, admission_number)
        if not User.objects.filter(username=username).exists():
            return admission_number, username
        sequence += 1


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    widget = MultipleFileInput

    def clean(self, data, initial=None):
        if not data:
            return []
        files = data if isinstance(data, (list, tuple)) else [data]
        return [super(MultipleFileField, self).clean(file, initial) for file in files]


class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = ("name", "description", "duration", "fee_amount", "is_active")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, institute=None, academic_year=None, **kwargs):
        self.institute = institute
        self.academic_year = academic_year
        super().__init__(*args, **kwargs)
        self.fields["fee_amount"].widget.attrs.setdefault("min", "0")
        self.fields["fee_amount"].widget.attrs.setdefault("step", "0.01")
        for field in self.fields.values():
            css_class = "form-check-input" if isinstance(field.widget, forms.CheckboxInput) else "form-control"
            field.widget.attrs.setdefault("class", css_class)

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        queryset = Course.objects.filter(institute=self.institute, academic_year=self.academic_year, name__iexact=name)
        if self.instance and self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if self.institute and self.academic_year and queryset.exists():
            raise ValidationError("This course already exists in the selected academic year.")
        return name

    def clean_fee_amount(self):
        fee_amount = self.cleaned_data["fee_amount"]
        if fee_amount < 0:
            raise ValidationError("Course fee cannot be negative.")
        return fee_amount


class SubjectForm(forms.ModelForm):
    class Meta:
        model = Subject
        fields = ("name", "description", "is_active")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, institute=None, academic_year=None, **kwargs):
        self.institute = institute
        self.academic_year = academic_year
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css_class = "form-check-input" if isinstance(field.widget, forms.CheckboxInput) else "form-control"
            field.widget.attrs.setdefault("class", css_class)

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        queryset = Subject.objects.filter(institute=self.institute, academic_year=self.academic_year, name__iexact=name)
        if self.instance and self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if self.institute and self.academic_year and queryset.exists():
            raise ValidationError("This subject already exists in the selected academic year.")
        return name


class FeeCategoryForm(forms.ModelForm):
    class Meta:
        model = FeeCategory
        fields = ("name", "default_amount", "is_active")

    def __init__(self, *args, institute=None, **kwargs):
        self.institute = institute
        super().__init__(*args, **kwargs)
        self.fields["default_amount"].widget.attrs.setdefault("min", "0")
        self.fields["default_amount"].widget.attrs.setdefault("step", "0.01")
        for field in self.fields.values():
            css_class = "form-check-input" if isinstance(field.widget, forms.CheckboxInput) else "form-control"
            field.widget.attrs.setdefault("class", css_class)

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        queryset = FeeCategory.objects.filter(institute=self.institute, name__iexact=name)
        if self.instance and self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise ValidationError("This fee category already exists in this institute.")
        return name

    def clean_default_amount(self):
        default_amount = self.cleaned_data["default_amount"]
        if default_amount < 0:
            raise ValidationError("Default amount cannot be negative.")
        return default_amount


class BatchForm(forms.ModelForm):
    timetable_days = {
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    }
    timetable_time_pattern = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")

    teachers = forms.ModelMultipleChoiceField(
        queryset=UserProfile.objects.none(),
        required=False,
    )

    class Meta:
        model = Batch
        fields = (
            "courses",
            "name",
            "teachers",
            "start_date",
            "end_date",
            "timing",
            "weekly_timetable",
            "is_active",
        )
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "weekly_timetable": forms.HiddenInput(),
        }

    def __init__(self, *args, institute=None, academic_year=None, **kwargs):
        self.institute = institute
        self.academic_year = academic_year
        super().__init__(*args, **kwargs)
        if institute:
            courses = Course.objects.filter(institute=institute, is_active=True)
            if academic_year:
                courses = courses.filter(academic_year=academic_year)
            self.fields["courses"].queryset = courses
            self.fields["teachers"].queryset = UserProfile.objects.filter(
                institute=institute,
                role=UserProfile.Role.TEACHER,
            ).select_related("user")
            self.fields["teachers"].label_from_instance = lambda profile: (
                profile.user.get_full_name() or profile.user.username
            )
            if self.instance and self.instance.pk:
                self.fields["teachers"].initial = UserProfile.objects.filter(
                    institute=institute,
                    role=UserProfile.Role.TEACHER,
                    user__in=self.instance.teachers.all(),
                )
        else:
            self.fields["courses"].queryset = Course.objects.none()
            self.fields["teachers"].queryset = UserProfile.objects.none()

        self.fields["teachers"].required = False
        self.fields["courses"].required = True

        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                css_class = "form-check-input"
            elif isinstance(field.widget, forms.SelectMultiple):
                css_class = "form-select"
            elif isinstance(field.widget, forms.Select):
                css_class = "form-select"
            else:
                css_class = "form-control"
            field.widget.attrs.setdefault("class", css_class)

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        name = (cleaned_data.get("name") or "").strip()

        if start_date and end_date and end_date < start_date:
            raise ValidationError("End date cannot be before start date.")

        if self.institute and self.academic_year and name:
            queryset = Batch.objects.filter(
                institute=self.institute,
                academic_year=self.academic_year,
                name__iexact=name,
            )
            if self.instance and self.instance.pk:
                queryset = queryset.exclude(pk=self.instance.pk)
            if queryset.exists():
                raise ValidationError("This batch already exists in the selected academic year.")

        courses = cleaned_data.get("courses")
        if self.academic_year and courses:
            invalid_courses = courses.exclude(academic_year=self.academic_year)
            if invalid_courses.exists():
                raise ValidationError("Selected courses must belong to the selected academic year.")

        return cleaned_data

    def clean_weekly_timetable(self):
        timetable = self.cleaned_data.get("weekly_timetable") or {}
        if not isinstance(timetable, dict):
            raise ValidationError("Weekly timetable must be a valid schedule.")

        normalized = {}
        for day, slot in timetable.items():
            if day not in self.timetable_days or not isinstance(slot, dict):
                raise ValidationError("Weekly timetable contains an invalid day.")

            start = slot.get("start")
            end = slot.get("end")
            if (
                not isinstance(start, str)
                or not isinstance(end, str)
                or not self.timetable_time_pattern.fullmatch(start)
                or not self.timetable_time_pattern.fullmatch(end)
            ):
                raise ValidationError("Each timetable day needs valid start and end times.")
            if start >= end:
                raise ValidationError("Timetable end time must be after the start time.")

            normalized[day] = {"start": start, "end": end}

        return normalized


class LeadForm(forms.ModelForm):
    class Meta:
        model = Lead
        fields = (
            "first_name",
            "last_name",
            "mobile_number",
            "email",
            "interested_class",
            "interested_batch",
            "source",
            "status",
            "follow_up_on",
            "message",
        )
        widgets = {
            "follow_up_on": forms.DateInput(attrs={"type": "date"}),
            "message": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, institute=None, academic_year=None, **kwargs):
        self.institute = institute
        self.academic_year = academic_year
        super().__init__(*args, **kwargs)
        classes = Course.objects.none()
        batches = Batch.objects.none()
        if institute:
            classes = Course.objects.filter(institute=institute, is_active=True)
            batches = Batch.objects.filter(institute=institute, is_active=True)
            if academic_year:
                classes = classes.filter(academic_year=academic_year)
                batches = batches.filter(academic_year=academic_year)
        self.fields["interested_class"].queryset = classes
        self.fields["interested_batch"].queryset = batches.prefetch_related("courses")
        self.fields["interested_class"].widget.attrs["data-searchable"] = "false"
        self.fields["interested_batch"].widget.attrs["data-searchable"] = "false"

        for field in self.fields.values():
            field.widget.attrs.setdefault(
                "class",
                "form-select" if isinstance(field.widget, forms.Select) else "form-control",
            )

    def clean_mobile_number(self):
        mobile_number = self.cleaned_data["mobile_number"].strip()
        if len(mobile_number) < 7:
            raise ValidationError("Enter a valid phone number.")
        return mobile_number

    def clean(self):
        cleaned_data = super().clean()
        interested_class = cleaned_data.get("interested_class")
        interested_batch = cleaned_data.get("interested_batch")

        if interested_batch and interested_batch.institute_id != getattr(self.institute, "pk", None):
            raise ValidationError("Select a batch from this institute.")
        if (
            interested_class
            and interested_batch
            and not interested_batch.courses.filter(pk=interested_class.pk).exists()
        ):
            raise ValidationError("Selected batch must include the interested class.")
        return cleaned_data

    def clean_interested_class(self):
        course = self.cleaned_data.get("interested_class")
        if course and course.institute_id != getattr(self.institute, "pk", None):
            raise ValidationError("Select a course from this institute.")
        return course


class ExpenseForm(forms.ModelForm):
    files = MultipleFileField(
        required=False,
        label="Expense Documents",
        help_text="Upload bills, receipts or supporting files. You can select multiple files.",
    )

    class Meta:
        model = Expense
        fields = ("title", "amount", "spent_on", "note")
        widgets = {
            "spent_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "amount": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
            "note": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["files"].widget.attrs.update(
            {
                "class": "form-control",
                "multiple": True,
                "accept": ".pdf,.jpg,.jpeg,.png,.doc,.docx,.xls,.xlsx,.csv",
            }
        )
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise ValidationError("Expense amount must be greater than zero.")
        return amount


class VisitorForm(forms.ModelForm):
    class Meta:
        model = Visitor
        fields = (
            "visitor_name",
            "phone_number",
            "id_card_number",
            "meeting_with",
            "total_person",
            "visit_date",
            "entry_time",
            "exit_time",
            "purpose",
            "attachment",
        )
        widgets = {
            "visit_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "entry_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "exit_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "purpose": forms.Textarea(attrs={"rows": 4}),
            "attachment": forms.FileInput(attrs={"accept": "image/*,.pdf"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["visit_date"].input_formats = ("%Y-%m-%d",)
        self.fields["entry_time"].input_formats = ("%H:%M",)
        self.fields["exit_time"].input_formats = ("%H:%M",)

        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean_phone_number(self):
        phone_number = self.cleaned_data["phone_number"].strip()
        if len(phone_number) < 7:
            raise ValidationError("Enter a valid phone number.")
        return phone_number

    def clean(self):
        cleaned_data = super().clean()
        entry_time = cleaned_data.get("entry_time")
        exit_time = cleaned_data.get("exit_time")
        if entry_time and exit_time and exit_time < entry_time:
            raise ValidationError("Exit time cannot be earlier than entry time.")
        return cleaned_data


class TeacherForm(forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150, required=False)
    username = forms.CharField(max_length=150)
    password = forms.CharField(
        min_length=6,
        required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    confirm_password = forms.CharField(
        min_length=6,
        required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    email = forms.EmailField(required=False)
    phone = forms.CharField(max_length=20, required=False)
    employee_id = forms.CharField(max_length=40, required=False)
    teacher_type = forms.ChoiceField(choices=TeacherProfile.TeacherType.choices)
    qualification = forms.CharField(max_length=160, required=False)
    specialization = forms.CharField(max_length=160, required=False)
    max_classes_per_day = forms.IntegerField(min_value=1, initial=6)
    max_classes_per_week = forms.IntegerField(min_value=1, initial=30)
    joined_on = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    is_active = forms.BooleanField(required=False, initial=True)

    def __init__(self, *args, institute=None, teacher=None, **kwargs):
        self.institute = institute
        self.teacher = teacher
        initial = kwargs.pop("initial", {})

        if teacher:
            user = teacher.user
            profile = getattr(user, "profile", None)
            initial.update(
                {
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "username": user.username,
                    "email": user.email,
                    "phone": profile.phone if profile else "",
                    "employee_id": teacher.employee_id,
                    "teacher_type": teacher.teacher_type,
                    "qualification": teacher.qualification,
                    "specialization": teacher.specialization,
                    "max_classes_per_day": teacher.max_classes_per_day,
                    "max_classes_per_week": teacher.max_classes_per_week,
                    "joined_on": teacher.joined_on,
                    "is_active": teacher.is_active,
                }
            )

        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        if not teacher:
            self.fields["password"].required = True
            self.fields["confirm_password"].required = True

        for field in self.fields.values():
            css_class = "form-check-input" if isinstance(field.widget, forms.CheckboxInput) else "form-control"
            if isinstance(field.widget, forms.Select):
                css_class = "form-select"
            field.widget.attrs.setdefault("class", css_class)

    def clean_username(self):
        username = self.cleaned_data["username"]
        queryset = User.objects.filter(username=username)
        if self.teacher:
            queryset = queryset.exclude(pk=self.teacher.user_id)
        if queryset.exists():
            raise ValidationError("This username is already used.")
        return username

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")

        if password or confirm_password:
            if password != confirm_password:
                raise ValidationError("Password and confirm password do not match.")

        return cleaned_data

    def clean_employee_id(self):
        employee_id = self.cleaned_data.get("employee_id", "").strip()
        if not employee_id:
            return employee_id

        queryset = TeacherProfile.objects.filter(institute=self.institute, employee_id=employee_id)
        if self.teacher:
            queryset = queryset.exclude(pk=self.teacher.pk)
        if queryset.exists():
            raise ValidationError("This employee ID is already used in this institute.")
        return employee_id

    def save(self):
        teacher = self.teacher
        if teacher:
            user = teacher.user
        else:
            user = User()

        user.username = self.cleaned_data["username"]
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.email = self.cleaned_data["email"]
        user.is_active = self.cleaned_data["is_active"]
        if self.cleaned_data.get("password"):
            user.set_password(self.cleaned_data["password"])
        user.save()

        UserProfile.objects.update_or_create(
            user=user,
            defaults={
                "institute": self.institute,
                "role": UserProfile.Role.TEACHER,
                "phone": self.cleaned_data["phone"],
            },
        )

        teacher, _created = TeacherProfile.objects.update_or_create(
            user=user,
            defaults={
                "institute": self.institute,
                "employee_id": self.cleaned_data["employee_id"],
                "teacher_type": self.cleaned_data["teacher_type"],
                "qualification": self.cleaned_data["qualification"],
                "specialization": self.cleaned_data["specialization"],
                "max_classes_per_day": self.cleaned_data["max_classes_per_day"],
                "max_classes_per_week": self.cleaned_data["max_classes_per_week"],
                "joined_on": self.cleaned_data["joined_on"],
                "is_active": self.cleaned_data["is_active"],
            },
        )
        return teacher


class InstituteUserForm(forms.Form):
    ROLE_CHOICES = (
        (UserProfile.Role.INSTITUTE_ADMIN, "Institute Admin"),
        (UserProfile.Role.TEACHER, "Teacher"),
        (UserProfile.Role.ACCOUNTANT, "Accountant"),
        (UserProfile.Role.STUDENT_PARENT, "Student/Parent"),
    )

    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150, required=False)
    username = forms.CharField(max_length=150)
    password = forms.CharField(
        min_length=6,
        required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    confirm_password = forms.CharField(
        min_length=6,
        required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    email = forms.EmailField(required=False)
    phone = forms.CharField(max_length=20, required=False)
    role = forms.ChoiceField(choices=ROLE_CHOICES)
    is_active = forms.BooleanField(required=False, initial=True)

    def __init__(self, *args, institute=None, profile=None, **kwargs):
        self.institute = institute
        self.profile = profile
        initial = kwargs.pop("initial", {})

        if profile:
            user = profile.user
            initial.update(
                {
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "username": user.username,
                    "email": user.email,
                    "phone": profile.phone,
                    "role": profile.role,
                    "is_active": user.is_active,
                }
            )

        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        if not profile:
            self.fields["password"].required = True
            self.fields["confirm_password"].required = True

        for field in self.fields.values():
            css_class = "form-check-input" if isinstance(field.widget, forms.CheckboxInput) else "form-control"
            if isinstance(field.widget, forms.Select):
                css_class = "form-select"
            field.widget.attrs.setdefault("class", css_class)

    def clean_username(self):
        username = self.cleaned_data["username"]
        queryset = User.objects.filter(username=username)
        if self.profile:
            queryset = queryset.exclude(pk=self.profile.user_id)
        if queryset.exists():
            raise ValidationError("This username is already used.")
        return username

    def clean_role(self):
        role = self.cleaned_data["role"]
        if role == UserProfile.Role.SUPER_ADMIN:
            raise ValidationError("Super admin users cannot be managed from institute panel.")
        return role

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")

        if password or confirm_password:
            if password != confirm_password:
                raise ValidationError("Password and confirm password do not match.")

        return cleaned_data

    def save(self):
        if self.profile:
            profile = self.profile
            user = profile.user
        else:
            user = User()
            profile = None

        user.username = self.cleaned_data["username"]
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.email = self.cleaned_data["email"]
        user.is_active = self.cleaned_data["is_active"]
        if self.cleaned_data.get("password"):
            user.set_password(self.cleaned_data["password"])
        user.save()

        profile, _created = UserProfile.objects.update_or_create(
            user=user,
            defaults={
                "institute": self.institute,
                "role": self.cleaned_data["role"],
                "phone": self.cleaned_data["phone"],
            },
        )

        if profile.role == UserProfile.Role.TEACHER:
            TeacherProfile.objects.update_or_create(
                user=user,
                defaults={
                    "institute": self.institute,
                    "is_active": user.is_active,
                },
            )
        elif hasattr(user, "teacher_profile"):
            user.teacher_profile.is_active = False
            user.teacher_profile.save(update_fields=["is_active"])

        if hasattr(user, "student_profile"):
            user.student_profile.is_active = user.is_active
            user.student_profile.save(update_fields=["is_active"])

        return profile


class StudentForm(forms.Form):
    CASTE_CATEGORY_CHOICES = [
        ("", "Select category"),
        ("GENERAL", "General"),
        ("OBC", "OBC"),
        ("SC", "SC"),
        ("ST", "ST"),
    ]
    MEDIUM_CHOICES = [
        ("", "Select medium"),
        ("English", "English"),
        ("Marathi", "Marathi"),
        ("Hindi", "Hindi"),
    ]
    RESULT_CHOICES = [
        ("", "Select result"),
        ("Pass", "Pass"),
        ("Fail", "Fail"),
    ]
    DOCUMENT_UPLOAD_FIELDS = {
        "birth_certificate_file": (StudentDocument.DocumentType.BIRTH_CERTIFICATE, "Birth Certificate"),
        "student_aadhaar_file": (StudentDocument.DocumentType.AADHAAR, "Aadhaar Card (Student)"),
        "parent_aadhaar_file": (StudentDocument.DocumentType.PARENT_AADHAAR, "Aadhaar Card (Parents)"),
        "caste_certificate_file": (StudentDocument.DocumentType.CASTE_CERTIFICATE, "Caste Certificate"),
        "income_certificate_file": (StudentDocument.DocumentType.INCOME_CERTIFICATE, "Income Certificate"),
        "transfer_certificate_file": (StudentDocument.DocumentType.TRANSFER_CERTIFICATE, "Transfer Certificate (TC)"),
        "leaving_certificate_file": (StudentDocument.DocumentType.LEAVING_CERTIFICATE, "Leaving Certificate (LC)"),
        "bonafide_certificate_file": (StudentDocument.DocumentType.BONAFIDE_CERTIFICATE, "Bonafide Certificate Copy"),
        "address_proof_file": (StudentDocument.DocumentType.ADDRESS_PROOF, "Address Proof"),
        "previous_marksheet_file": (StudentDocument.DocumentType.MARKSHEET, "Marksheet of Previous Class"),
        "passport_photos_file": (StudentDocument.DocumentType.PASSPORT_PHOTOS, "Passport Size Photos"),
        "disability_certificate_file": (StudentDocument.DocumentType.DISABILITY_CERTIFICATE, "Disability Certificate"),
        "migration_certificate_file": (StudentDocument.DocumentType.MIGRATION_CERTIFICATE, "Migration Certificate"),
        "rte_documents_file": (StudentDocument.DocumentType.RTE_DOCUMENTS, "RTE Documents"),
        "bank_passbook_file": (StudentDocument.DocumentType.BANK_PASSBOOK, "Bank Passbook Copy"),
        "vaccination_record_file": (StudentDocument.DocumentType.VACCINATION_RECORD, "Vaccination Record"),
    }
    COACHING_HIDDEN_FIELDS = {
        "pen_no",
        "appar_id",
        "gr_number_udise",
        "udise_number",
        "blood_group",
        "religion",
        "cast",
        "caste_category",
        "nationality",
        "aadhaar_number",
        "birth_certificate_number",
        "place_of_birth",
        "mother_tongue",
        "father_occupation",
        "father_qualification",
        "father_aadhaar_number",
        "father_annual_income",
        "mother_occupation",
        "mother_qualification",
        "mother_aadhaar_number",
        "mother_annual_income",
        "current_house_number",
        "current_street_area",
        "current_village_city",
        "current_taluka",
        "current_district",
        "current_state",
        "current_pin_code",
        "same_as_current_address",
        "permanent_house_number",
        "permanent_street_area",
        "permanent_village_city",
        "permanent_taluka",
        "permanent_district",
        "permanent_state",
        "permanent_pin_code",
        "medium",
        "current_school_name",
        "current_school_address",
        "previous_school_name",
        "previous_school_address",
        "previous_school_udise_code",
        "previous_class",
        "previous_class_passed",
        "last_exam_result",
        "student_status",
        "result",
        "conduct",
        "reason_for_leaving",
        "date_of_leaving_school",
        "tc_issue_date",
        "bonafide_purpose",
        "emergency_contact_number",
    }
    COACHING_DOCUMENT_TYPE_CHOICES = [
        (StudentDocument.DocumentType.STUDENT_PHOTO, "Student Photo"),
        (StudentDocument.DocumentType.PROFILE, "Profile"),
        (StudentDocument.DocumentType.MARKSHEET, "Marksheet"),
        (StudentDocument.DocumentType.ADDRESS_PROOF, "Address Proof"),
        (StudentDocument.DocumentType.OTHER, "Other"),
    ]

    student_full_name = forms.CharField(max_length=320, required=False)
    first_name = forms.CharField(max_length=150)
    middle_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    username = forms.CharField(max_length=150, required=False, disabled=True)
    password = forms.CharField(
        min_length=6,
        required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    confirm_password = forms.CharField(
        min_length=6,
        required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    email = forms.EmailField(required=False)
    phone = forms.CharField(max_length=20, required=False)
    profile_image = forms.ImageField(required=False)
    pen_no = forms.CharField(max_length=80, required=False)
    appar_id = forms.CharField(max_length=80, required=False)
    gr_number_udise = forms.CharField(max_length=80, required=False)
    udise_number = forms.CharField(max_length=80, required=False)
    roll_number = forms.CharField(max_length=40, required=False)
    gender = forms.ChoiceField(choices=[("", "Select gender")] + list(StudentProfile.Gender.choices), required=False)
    date_of_birth = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    blood_group = forms.CharField(max_length=10, required=False)
    religion = forms.CharField(max_length=80, required=False)
    cast = forms.CharField(max_length=80, required=False)
    caste_category = forms.ChoiceField(choices=CASTE_CATEGORY_CHOICES, required=False)
    nationality = forms.CharField(max_length=80, required=False)
    aadhaar_number = forms.CharField(max_length=20, required=False)
    birth_certificate_number = forms.CharField(max_length=80, required=False)
    place_of_birth = forms.CharField(max_length=120, required=False)
    mother_tongue = forms.CharField(max_length=80, required=False)
    father_name = forms.CharField(max_length=160, required=False)
    father_occupation = forms.CharField(max_length=120, required=False)
    father_qualification = forms.CharField(max_length=120, required=False)
    father_mobile_number = forms.CharField(max_length=20, required=False)
    father_email = forms.EmailField(required=False)
    father_aadhaar_number = forms.CharField(max_length=20, required=False)
    father_annual_income = forms.CharField(max_length=40, required=False)
    mother_name = forms.CharField(max_length=160, required=False)
    mother_occupation = forms.CharField(max_length=120, required=False)
    mother_qualification = forms.CharField(max_length=120, required=False)
    mother_mobile_number = forms.CharField(max_length=20, required=False)
    mother_aadhaar_number = forms.CharField(max_length=20, required=False)
    mother_annual_income = forms.CharField(max_length=40, required=False)
    guardian_address = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    current_house_number = forms.CharField(max_length=80, required=False)
    current_street_area = forms.CharField(max_length=160, required=False)
    current_village_city = forms.CharField(max_length=120, required=False)
    current_taluka = forms.CharField(max_length=120, required=False)
    current_district = forms.CharField(max_length=120, required=False)
    current_state = forms.CharField(max_length=120, required=False)
    current_pin_code = forms.CharField(max_length=12, required=False)
    same_as_current_address = forms.BooleanField(required=False)
    permanent_house_number = forms.CharField(max_length=80, required=False)
    permanent_street_area = forms.CharField(max_length=160, required=False)
    permanent_village_city = forms.CharField(max_length=120, required=False)
    permanent_taluka = forms.CharField(max_length=120, required=False)
    permanent_district = forms.CharField(max_length=120, required=False)
    permanent_state = forms.CharField(max_length=120, required=False)
    permanent_pin_code = forms.CharField(max_length=12, required=False)
    joined_on = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    address = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    class_course = forms.ModelChoiceField(queryset=Course.objects.none(), required=False)
    batch = forms.ModelChoiceField(queryset=Batch.objects.none(), required=False)
    class_fee_amount = forms.DecimalField(max_digits=10, decimal_places=2, required=False)
    fee_discount = forms.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.00"), required=False)
    final_fee_amount = forms.DecimalField(max_digits=10, decimal_places=2, required=False)
    admission_class = forms.CharField(max_length=80, required=False)
    current_class = forms.CharField(max_length=80, required=False)
    division = forms.CharField(max_length=40, required=False)
    medium = forms.ChoiceField(choices=MEDIUM_CHOICES, required=False)
    current_school_name = forms.CharField(max_length=160, required=False)
    current_school_address = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    previous_school_name = forms.CharField(max_length=160, required=False)
    previous_school_address = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    previous_school_udise_code = forms.CharField(max_length=80, required=False)
    previous_class = forms.CharField(max_length=80, required=False)
    previous_class_passed = forms.CharField(max_length=80, required=False)
    last_exam_result = forms.CharField(max_length=80, required=False)
    student_status = forms.ChoiceField(choices=StudentProfile.StudentStatus.choices, required=False)
    result = forms.ChoiceField(choices=RESULT_CHOICES, required=False)
    conduct = forms.CharField(max_length=120, required=False)
    reason_for_leaving = forms.CharField(max_length=255, required=False)
    date_of_leaving_school = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    tc_issue_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    bonafide_purpose = forms.CharField(max_length=255, required=False)
    emergency_contact_number = forms.CharField(max_length=20, required=False)
    guardian_name = forms.CharField(max_length=120, required=False)
    guardian_relation = forms.CharField(max_length=60, required=False)
    guardian_phone = forms.CharField(max_length=20, required=False)
    guardian_email = forms.EmailField(required=False)
    document_type = forms.ChoiceField(choices=StudentDocument.DocumentType.choices, required=False)
    document_title = forms.CharField(max_length=120, required=False)
    document_file = forms.FileField(required=False)
    document_note = forms.CharField(max_length=255, required=False)
    birth_certificate_file = forms.FileField(required=False)
    student_aadhaar_file = forms.FileField(required=False)
    parent_aadhaar_file = forms.FileField(required=False)
    caste_certificate_file = forms.FileField(required=False)
    income_certificate_file = forms.FileField(required=False)
    transfer_certificate_file = forms.FileField(required=False)
    leaving_certificate_file = forms.FileField(required=False)
    bonafide_certificate_file = forms.FileField(required=False)
    address_proof_file = forms.FileField(required=False)
    previous_marksheet_file = forms.FileField(required=False)
    passport_photos_file = forms.FileField(required=False)
    disability_certificate_file = forms.FileField(required=False)
    migration_certificate_file = forms.FileField(required=False)
    rte_documents_file = forms.FileField(required=False)
    bank_passbook_file = forms.FileField(required=False)
    vaccination_record_file = forms.FileField(required=False)
    is_active = forms.BooleanField(required=False, initial=True)

    def __init__(self, *args, institute=None, student=None, **kwargs):
        self.institute = institute
        self.student = student
        self.is_school_institute = bool(
            institute and institute.institute_type == Institute.InstituteType.SCHOOL
        )
        self.academic_year = kwargs.pop("academic_year", None)
        initial = kwargs.pop("initial", {})

        if student:
            user = student.user
            profile = getattr(user, "profile", None)
            guardian = student.guardians.filter(is_primary=True).first() or student.guardians.first()
            academic_year = self.academic_year or student.academic_year
            student_session = None
            current_enrollment = None
            if academic_year:
                student_session = student.academic_sessions.filter(academic_year=academic_year).first()
                if student_session:
                    current_enrollment = (
                        student_session.enrollments.exclude(status=StudentEnrollment.Status.CANCELLED)
                        .select_related("batch")
                        .prefetch_related("courses")
                        .order_by("pk")
                        .first()
                    )
            initial.update(
                {
                    "student_full_name": " ".join(
                        part
                        for part in [user.first_name, student.middle_name, user.last_name]
                        if part
                    ),
                    "first_name": user.first_name,
                    "middle_name": student.middle_name,
                    "last_name": user.last_name,
                    "username": user.username,
                    "email": user.email,
                    "phone": profile.phone if profile else "",
                    "pen_no": student.pen_no,
                    "appar_id": student.appar_id,
                    "gr_number_udise": student.gr_number_udise,
                    "udise_number": student.udise_number,
                    "roll_number": student.roll_number,
                    "gender": student.gender,
                    "date_of_birth": student.date_of_birth,
                    "blood_group": student.blood_group,
                    "religion": student.religion,
                    "cast": student.cast,
                    "caste_category": student.caste_category,
                    "nationality": student.nationality,
                    "aadhaar_number": student.aadhaar_number,
                    "birth_certificate_number": student.birth_certificate_number,
                    "place_of_birth": student.place_of_birth,
                    "mother_tongue": student.mother_tongue,
                    "father_name": student.father_name,
                    "father_occupation": student.father_occupation,
                    "father_qualification": student.father_qualification,
                    "father_mobile_number": student.father_mobile_number,
                    "father_email": student.father_email,
                    "father_aadhaar_number": student.father_aadhaar_number,
                    "father_annual_income": student.father_annual_income,
                    "mother_name": student.mother_name,
                    "mother_occupation": student.mother_occupation,
                    "mother_qualification": student.mother_qualification,
                    "mother_mobile_number": student.mother_mobile_number,
                    "mother_aadhaar_number": student.mother_aadhaar_number,
                    "mother_annual_income": student.mother_annual_income,
                    "guardian_address": student.guardian_address,
                    "current_house_number": student.current_house_number,
                    "current_street_area": student.current_street_area,
                    "current_village_city": student.current_village_city,
                    "current_taluka": student.current_taluka,
                    "current_district": student.current_district,
                    "current_state": student.current_state,
                    "current_pin_code": student.current_pin_code,
                    "permanent_house_number": student.permanent_house_number,
                    "permanent_street_area": student.permanent_street_area,
                    "permanent_village_city": student.permanent_village_city,
                    "permanent_taluka": student.permanent_taluka,
                    "permanent_district": student.permanent_district,
                    "permanent_state": student.permanent_state,
                    "permanent_pin_code": student.permanent_pin_code,
                    "joined_on": student_session.joined_on if student_session else student.joined_on,
                    "address": student.address,
                    "admission_class": student.admission_class,
                    "current_class": student.current_class,
                    "division": student.division,
                    "medium": student.medium,
                    "current_school_name": (
                        student_session.current_school_name if student_session else student.current_school_name
                    ),
                    "current_school_address": (
                        student_session.current_school_address if student_session else student.current_school_address
                    ),
                    "previous_school_name": (
                        student_session.previous_school_name if student_session else student.previous_school_name
                    ),
                    "previous_school_address": student.previous_school_address,
                    "previous_school_udise_code": student.previous_school_udise_code,
                    "previous_class": student_session.previous_class if student_session else student.previous_class,
                    "previous_class_passed": student.previous_class_passed,
                    "last_exam_result": student.last_exam_result,
                    "student_status": student.student_status,
                    "result": student.result,
                    "conduct": student.conduct,
                    "reason_for_leaving": student.reason_for_leaving,
                    "date_of_leaving_school": student.date_of_leaving_school,
                    "tc_issue_date": student.tc_issue_date,
                    "bonafide_purpose": student.bonafide_purpose,
                    "emergency_contact_number": student.emergency_contact_number,
                    "guardian_name": guardian.name if guardian else "",
                    "guardian_relation": guardian.relation if guardian else "",
                    "guardian_phone": guardian.phone if guardian else "",
                    "guardian_email": guardian.email if guardian else "",
                    "is_active": student.is_active,
                }
            )
            if current_enrollment:
                initial["batch"] = current_enrollment.batch_id
                selected_course = current_enrollment.courses.first()
                if selected_course:
                    initial["class_course"] = selected_course.pk
                    initial["class_fee_amount"] = selected_course.fee_amount
                    final_fee = (
                        current_enrollment.custom_fee_amount
                        if current_enrollment.custom_fee_amount is not None
                        else selected_course.fee_amount
                    )
                    initial["final_fee_amount"] = final_fee
                    initial["fee_discount"] = max(selected_course.fee_amount - final_fee, Decimal("0.00"))
            elif student.current_class or student.admission_class:
                class_name = student.current_class or student.admission_class
                matching_course = Course.objects.filter(
                    institute=student.institute,
                    academic_year=academic_year,
                    name=class_name,
                ).first()
                if matching_course:
                    initial["class_course"] = matching_course.pk
                    if student.division:
                        matching_batch = Batch.objects.filter(
                            institute=student.institute,
                            academic_year=academic_year,
                            name=student.division,
                            courses=matching_course,
                        ).first()
                        if matching_batch:
                            initial["batch"] = matching_batch.pk

        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        courses = Course.objects.none()
        batches = Batch.objects.none()
        if self.institute:
            courses = Course.objects.filter(institute=self.institute, is_active=True)
            batches = Batch.objects.filter(institute=self.institute, is_active=True).prefetch_related("courses")
            if self.academic_year:
                courses = courses.filter(academic_year=self.academic_year)
                batches = batches.filter(academic_year=self.academic_year)
        self.fields["class_course"].queryset = courses
        self.fields["batch"].queryset = batches
        self.fields["class_course"].empty_label = "Select class"
        self.fields["batch"].empty_label = "Select batch / division"
        self.fields["class_course"].label_from_instance = lambda course: course.name
        self.fields["batch"].label_from_instance = lambda batch: batch.name
        self.fields["class_course"].widget.attrs["data-searchable"] = "false"
        self.fields["batch"].widget.attrs["data-searchable"] = "false"
        self.fields["student_full_name"].widget.attrs["placeholder"] = "Student full name"
        self.fields["student_full_name"].widget.attrs["readonly"] = "readonly"
        self.fields["student_full_name"].widget.attrs["style"] = "background-color:#e9ecef; opacity:1;"
        self.fields["student_full_name"].help_text = "Generated automatically from first name, middle name and surname."
        self.fields["class_fee_amount"].widget.attrs["readonly"] = "readonly"
        self.fields["class_fee_amount"].widget.attrs["placeholder"] = "0.00"
        self.fields["fee_discount"].widget.attrs["min"] = "0"
        self.fields["fee_discount"].widget.attrs["step"] = "0.01"
        self.fields["fee_discount"].widget.attrs["placeholder"] = "0.00"
        self.fields["final_fee_amount"].widget.attrs["readonly"] = "readonly"
        self.fields["final_fee_amount"].widget.attrs["placeholder"] = "0.00"
        self.fields["student_status"].initial = StudentProfile.StudentStatus.ACTIVE
        if not student:
            self.fields["username"].widget.attrs["placeholder"] = "Generated automatically"
            self.fields["username"].help_text = "Generated automatically and identical to the registration number."
            self.fields["password"].widget.attrs["placeholder"] = "Default: Student@123"
            self.fields["confirm_password"].widget.attrs["placeholder"] = "Default: Student@123"
        else:
            self.fields["username"].help_text = "Same as the registration number and cannot be changed."

        for field in self.fields.values():
            css_class = "form-check-input" if isinstance(field.widget, forms.CheckboxInput) else "form-control"
            if isinstance(field.widget, forms.Select):
                css_class = "form-select"
            field.widget.attrs.setdefault("class", css_class)

        if not self.is_school_institute:
            for field_name in self.COACHING_HIDDEN_FIELDS:
                if field_name in self.fields:
                    self.fields[field_name].widget = forms.HiddenInput()
            self.fields["document_type"].choices = self.COACHING_DOCUMENT_TYPE_CHOICES

    def clean(self):
        cleaned_data = super().clean()
        first_name = cleaned_data.get("first_name", "").strip()
        last_name = cleaned_data.get("last_name", "").strip()
        middle_name = cleaned_data.get("middle_name", "").strip()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")

        if not first_name:
            self.add_error("first_name", "Enter first name.")

        cleaned_data["student_full_name"] = " ".join(
            part for part in [first_name, middle_name, last_name] if part
        )

        if cleaned_data.get("same_as_current_address"):
            for field_suffix in [
                "house_number",
                "street_area",
                "village_city",
                "taluka",
                "district",
                "state",
                "pin_code",
            ]:
                cleaned_data[f"permanent_{field_suffix}"] = cleaned_data.get(f"current_{field_suffix}", "")

        if password or confirm_password:
            if password != confirm_password:
                raise ValidationError("Password and confirm password do not match.")

        document_file = cleaned_data.get("document_file")
        document_title = cleaned_data.get("document_title", "").strip()
        if document_file and not document_title:
            raise ValidationError("Enter document title when uploading a document.")

        class_course = cleaned_data.get("class_course")
        batch = cleaned_data.get("batch")
        if batch and not class_course:
            self.add_error("class_course", "Select class before selecting a batch.")
        if class_course and batch and not batch.courses.filter(pk=class_course.pk).exists():
            self.add_error("batch", "Selected batch must belong to the selected class.")

        class_fee_amount = class_course.fee_amount if class_course else Decimal("0.00")
        fee_discount = cleaned_data.get("fee_discount") or Decimal("0.00")
        if fee_discount < Decimal("0.00"):
            self.add_error("fee_discount", "Discount cannot be negative.")
        if fee_discount > class_fee_amount:
            self.add_error("fee_discount", "Discount cannot be greater than the class fee.")
        cleaned_data["class_fee_amount"] = class_fee_amount
        cleaned_data["final_fee_amount"] = max(class_fee_amount - fee_discount, Decimal("0.00"))

        return cleaned_data

    @transaction.atomic
    def save(self):
        academic_year = self.academic_year or (self.student.academic_year if self.student else None)
        academic_year = academic_year or get_or_create_academic_year(self.institute)
        existing_session = (
            self.student.academic_sessions.filter(academic_year=academic_year).first()
            if self.student
            else None
        )
        if self.student:
            student = self.student
            user = student.user
            admission_number = (
                existing_session.admission_number
                if existing_session
                else generate_student_admission_number(self.institute, academic_year)
            )
        else:
            admission_number, username = generate_student_login_credentials(
                self.institute,
                academic_year,
            )
            user = User(username=username)
            student = None

        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.email = self.cleaned_data["email"]
        user.is_active = self.cleaned_data["is_active"]
        if self.cleaned_data.get("password"):
            user.set_password(self.cleaned_data["password"])
        elif not self.student:
            user.set_password("Student@123")
        user.save()

        UserProfile.objects.update_or_create(
            user=user,
            defaults={
                "institute": self.institute,
                "role": UserProfile.Role.STUDENT_PARENT,
                "phone": self.cleaned_data["phone"],
            },
        )

        class_course = self.cleaned_data.get("class_course")
        batch = self.cleaned_data.get("batch")
        admission_class = (
            class_course.name
            if class_course
            else self.cleaned_data["admission_class"] or (self.student.admission_class if self.student else "")
        )
        current_class = (
            class_course.name
            if class_course
            else self.cleaned_data["current_class"] or (self.student.current_class if self.student else "")
        )
        division = (
            batch.name
            if batch
            else self.cleaned_data["division"] or (self.student.division if self.student else "")
        )
        school_name = self.institute.name if self.institute else ""
        school_address = self.institute.address if self.institute else ""

        student, _created = StudentProfile.objects.update_or_create(
            user=user,
            defaults={
                "institute": self.institute,
                "academic_year": academic_year,
                "admission_number": admission_number,
                "pen_no": self.cleaned_data["pen_no"],
                "appar_id": self.cleaned_data["appar_id"],
                "gr_number_udise": self.cleaned_data["gr_number_udise"],
                "udise_number": self.cleaned_data["udise_number"],
                "roll_number": self.cleaned_data["roll_number"],
                "middle_name": self.cleaned_data["middle_name"],
                "gender": self.cleaned_data["gender"],
                "date_of_birth": self.cleaned_data["date_of_birth"],
                "blood_group": self.cleaned_data["blood_group"],
                "religion": self.cleaned_data["religion"],
                "cast": self.cleaned_data["cast"],
                "caste_category": self.cleaned_data["caste_category"],
                "nationality": self.cleaned_data["nationality"],
                "aadhaar_number": self.cleaned_data["aadhaar_number"],
                "birth_certificate_number": self.cleaned_data["birth_certificate_number"],
                "place_of_birth": self.cleaned_data["place_of_birth"],
                "mother_tongue": self.cleaned_data["mother_tongue"],
                "father_name": self.cleaned_data["father_name"],
                "father_occupation": self.cleaned_data["father_occupation"],
                "father_qualification": self.cleaned_data["father_qualification"],
                "father_mobile_number": self.cleaned_data["father_mobile_number"],
                "father_email": self.cleaned_data["father_email"],
                "father_aadhaar_number": self.cleaned_data["father_aadhaar_number"],
                "father_annual_income": self.cleaned_data["father_annual_income"],
                "mother_name": self.cleaned_data["mother_name"],
                "mother_occupation": self.cleaned_data["mother_occupation"],
                "mother_qualification": self.cleaned_data["mother_qualification"],
                "mother_mobile_number": self.cleaned_data["mother_mobile_number"],
                "mother_aadhaar_number": self.cleaned_data["mother_aadhaar_number"],
                "mother_annual_income": self.cleaned_data["mother_annual_income"],
                "guardian_address": self.cleaned_data["guardian_address"],
                "current_house_number": self.cleaned_data["current_house_number"],
                "current_street_area": self.cleaned_data["current_street_area"],
                "current_village_city": self.cleaned_data["current_village_city"],
                "current_taluka": self.cleaned_data["current_taluka"],
                "current_district": self.cleaned_data["current_district"],
                "current_state": self.cleaned_data["current_state"],
                "current_pin_code": self.cleaned_data["current_pin_code"],
                "permanent_house_number": self.cleaned_data["permanent_house_number"],
                "permanent_street_area": self.cleaned_data["permanent_street_area"],
                "permanent_village_city": self.cleaned_data["permanent_village_city"],
                "permanent_taluka": self.cleaned_data["permanent_taluka"],
                "permanent_district": self.cleaned_data["permanent_district"],
                "permanent_state": self.cleaned_data["permanent_state"],
                "permanent_pin_code": self.cleaned_data["permanent_pin_code"],
                "joined_on": self.cleaned_data["joined_on"],
                "address": self.cleaned_data["address"],
                "admission_class": admission_class,
                "current_class": current_class,
                "division": division,
                "medium": self.cleaned_data["medium"],
                "current_school_name": school_name,
                "current_school_address": school_address,
                "previous_school_name": self.cleaned_data["previous_school_name"],
                "previous_school_address": self.cleaned_data["previous_school_address"],
                "previous_school_udise_code": self.cleaned_data["previous_school_udise_code"],
                "previous_class": self.cleaned_data["previous_class"],
                "previous_class_passed": self.cleaned_data["previous_class_passed"],
                "last_exam_result": self.cleaned_data["last_exam_result"],
                "is_active": self.cleaned_data["is_active"],
            },
        )

        if self.cleaned_data.get("profile_image"):
            student.profile_image = self.cleaned_data["profile_image"]
            student.save(update_fields=["profile_image"])

        academic_session, _session_created = StudentAcademicSession.objects.update_or_create(
            student=student,
            academic_year=academic_year,
            defaults={
                "institute": self.institute,
                "admission_number": admission_number,
                "joined_on": self.cleaned_data["joined_on"],
                "status": (
                    StudentAcademicSession.Status.ACTIVE
                    if self.cleaned_data["is_active"]
                    else StudentAcademicSession.Status.LEFT
                ),
                "current_school_name": school_name,
                "current_school_address": school_address,
                "previous_school_name": self.cleaned_data["previous_school_name"],
                "previous_class": self.cleaned_data["previous_class"],
            },
        )

        if class_course and batch:
            enrollment, _enrollment_created = StudentEnrollment.objects.update_or_create(
                academic_session=academic_session,
                batch=batch,
                defaults={
                    "student": student,
                    "enrolled_on": self.cleaned_data["joined_on"],
                    "status": StudentEnrollment.Status.ACTIVE,
                    "custom_fee_amount": self.cleaned_data["final_fee_amount"],
                },
            )
            enrollment.courses.set([class_course])

        if self.cleaned_data.get("guardian_name") or self.cleaned_data.get("guardian_phone"):
            guardian = student.guardians.filter(is_primary=True).first()
            if not guardian:
                guardian = GuardianProfile(student=student, is_primary=True)
            guardian.name = self.cleaned_data["guardian_name"] or "Primary Guardian"
            guardian.relation = self.cleaned_data["guardian_relation"]
            guardian.phone = self.cleaned_data["guardian_phone"] or self.cleaned_data["phone"]
            guardian.email = self.cleaned_data["guardian_email"]
            guardian.is_primary = True
            guardian.save()

        for field_name, (document_type, title) in self.DOCUMENT_UPLOAD_FIELDS.items():
            uploaded_file = self.cleaned_data.get(field_name)
            if uploaded_file:
                StudentDocument.objects.create(
                    student=student,
                    document_type=document_type,
                    title=title,
                    file=uploaded_file,
                )

        if self.cleaned_data.get("document_file"):
            StudentDocument.objects.create(
                student=student,
                document_type=self.cleaned_data.get("document_type") or StudentDocument.DocumentType.OTHER,
                title=self.cleaned_data["document_title"],
                file=self.cleaned_data["document_file"],
                note=self.cleaned_data["document_note"],
            )

        return student


class DummyStudentCreateForm(forms.Form):
    count = forms.IntegerField(
        min_value=1,
        max_value=5000,
        initial=100,
        widget=forms.NumberInput(
            attrs={
                "class": "form-control",
                "min": "1",
                "max": "5000",
                "placeholder": "Number of dummy students",
            }
        ),
    )


class StudentBasicForm(forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150, required=False)
    username = forms.CharField(max_length=150, required=False, disabled=True)
    password = forms.CharField(
        min_length=6,
        required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    confirm_password = forms.CharField(
        min_length=6,
        required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    email = forms.EmailField(required=False)
    phone = forms.CharField(max_length=20, required=False)
    profile_image = forms.ImageField(required=False)
    pen_no = forms.CharField(max_length=80, required=False)
    appar_id = forms.CharField(max_length=80, required=False)
    cast = forms.CharField(max_length=80, required=False)
    date_of_birth = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    joined_on = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    address = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    is_active = forms.BooleanField(required=False, initial=True)

    def __init__(self, *args, institute=None, student=None, **kwargs):
        self.institute = institute
        self.student = student
        self.academic_year = kwargs.pop("academic_year", None)
        initial = kwargs.pop("initial", {})

        if student:
            user = student.user
            profile = getattr(user, "profile", None)
            student_session = None
            if self.academic_year:
                student_session = student.academic_sessions.filter(academic_year=self.academic_year).first()
            initial.update(
                {
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "username": user.username,
                    "email": user.email,
                    "phone": profile.phone if profile else "",
                    "pen_no": student.pen_no,
                    "appar_id": student.appar_id,
                    "cast": student.cast,
                    "date_of_birth": student.date_of_birth,
                    "joined_on": student_session.joined_on if student_session else student.joined_on,
                    "address": student.address,
                    "is_active": student.is_active,
                }
            )

        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        self.fields["username"].help_text = "Same as the registration number and cannot be changed."

        for field in self.fields.values():
            css_class = "form-check-input" if isinstance(field.widget, forms.CheckboxInput) else "form-control"
            if isinstance(field.widget, forms.Select):
                css_class = "form-select"
            field.widget.attrs.setdefault("class", css_class)

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")
        if password or confirm_password:
            if password != confirm_password:
                raise ValidationError("Password and confirm password do not match.")
        return cleaned_data

    def save(self):
        student = self.student
        user = student.user

        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.email = self.cleaned_data["email"]
        user.is_active = self.cleaned_data["is_active"]
        if self.cleaned_data.get("password"):
            user.set_password(self.cleaned_data["password"])
        user.save()

        UserProfile.objects.update_or_create(
            user=user,
            defaults={
                "institute": self.institute,
                "role": UserProfile.Role.STUDENT_PARENT,
                "phone": self.cleaned_data["phone"],
            },
        )

        student.date_of_birth = self.cleaned_data["date_of_birth"]
        student.pen_no = self.cleaned_data["pen_no"]
        student.appar_id = self.cleaned_data["appar_id"]
        student.cast = self.cleaned_data["cast"]
        student.joined_on = self.cleaned_data["joined_on"]
        student.address = self.cleaned_data["address"]
        student.is_active = self.cleaned_data["is_active"]
        if self.cleaned_data.get("profile_image"):
            student.profile_image = self.cleaned_data["profile_image"]
        student.save()
        academic_year = self.academic_year or student.academic_year
        if academic_year:
            current_session = student.academic_sessions.filter(academic_year=academic_year).first()
            StudentAcademicSession.objects.update_or_create(
                student=student,
                academic_year=academic_year,
                defaults={
                    "institute": self.institute,
                    "admission_number": current_session.admission_number if current_session else student.admission_number,
                    "joined_on": self.cleaned_data["joined_on"],
                    "status": (
                        StudentAcademicSession.Status.ACTIVE
                        if self.cleaned_data["is_active"]
                        else StudentAcademicSession.Status.LEFT
                    ),
                    "current_school_name": student.current_school_name,
                    "current_school_address": student.current_school_address,
                    "previous_school_name": student.previous_school_name,
                    "previous_class": student.previous_class,
                },
            )
        return student


class StudentEducationForm(forms.ModelForm):
    class Meta:
        model = StudentAcademicSession
        fields = (
            "current_school_name",
            "current_school_address",
            "previous_school_name",
            "previous_class",
        )
        widgets = {
            "current_school_address": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class StudentGuardianForm(forms.Form):
    guardian_name = forms.CharField(max_length=120)
    guardian_relation = forms.CharField(max_length=60, required=False)
    guardian_phone = forms.CharField(max_length=20)
    guardian_email = forms.EmailField(required=False)

    def __init__(self, *args, student=None, **kwargs):
        self.student = student
        initial = kwargs.pop("initial", {})
        guardian = None
        if student:
            guardian = student.guardians.filter(is_primary=True).first() or student.guardians.first()
        if guardian:
            initial.update(
                {
                    "guardian_name": guardian.name,
                    "guardian_relation": guardian.relation,
                    "guardian_phone": guardian.phone,
                    "guardian_email": guardian.email,
                }
            )
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def save(self):
        guardian = self.student.guardians.filter(is_primary=True).first()
        if not guardian:
            guardian = GuardianProfile(student=self.student, is_primary=True)
        guardian.name = self.cleaned_data["guardian_name"]
        guardian.relation = self.cleaned_data["guardian_relation"]
        guardian.phone = self.cleaned_data["guardian_phone"]
        guardian.email = self.cleaned_data["guardian_email"]
        guardian.is_primary = True
        guardian.save()
        return guardian


class StudentDocumentUploadForm(forms.Form):
    document_type = forms.ChoiceField(choices=StudentDocument.DocumentType.choices, required=False)
    document_title = forms.CharField(max_length=120, required=False)
    files = MultipleFileField(required=True)
    note = forms.CharField(max_length=255, required=False)

    def __init__(self, *args, student=None, **kwargs):
        self.student = student
        super().__init__(*args, **kwargs)
        self.fields["files"].widget.attrs.update({"multiple": True})
        for field in self.fields.values():
            css_class = "form-select" if isinstance(field.widget, forms.Select) else "form-control"
            field.widget.attrs.setdefault("class", css_class)

    def save(self):
        documents = []
        document_type = self.cleaned_data.get("document_type") or StudentDocument.DocumentType.OTHER
        document_title = self.cleaned_data.get("document_title", "").strip()
        note = self.cleaned_data.get("note", "")
        files = self.cleaned_data["files"]
        for uploaded_file in files:
            title = document_title or uploaded_file.name
            documents.append(
                StudentDocument.objects.create(
                    student=self.student,
                    document_type=document_type,
                    title=title,
                    file=uploaded_file,
                    note=note,
                )
            )
        return documents


class StudentTransferCertificateForm(forms.Form):
    RESULT_CHOICES = StudentForm.RESULT_CHOICES

    tc_number = forms.CharField(max_length=60)
    issue_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    leaving_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    reason_for_leaving = forms.CharField(max_length=255)
    conduct = forms.CharField(max_length=120)
    result = forms.ChoiceField(choices=RESULT_CHOICES, required=False)
    last_class_attended = forms.CharField(max_length=80)
    qualified_for_promotion = forms.BooleanField(required=False)
    fees_cleared = forms.BooleanField(required=False)
    remarks = forms.CharField(max_length=255, required=False)
    deactivate_login = forms.BooleanField(
        required=False,
        initial=True,
        label="Deactivate student login after TC generation",
    )

    def __init__(self, *args, student=None, academic_session=None, generated_by=None, **kwargs):
        self.student = student
        self.academic_session = academic_session
        self.generated_by = generated_by
        initial = kwargs.pop("initial", {})
        if student and academic_session:
            today = timezone.localdate()
            sequence = StudentTransferCertificate.objects.filter(
                institute=student.institute,
                generated_at__year=today.year,
            ).count() + 1
            default_tc_number = f"TC-{today:%Y}-{sequence:04d}"
            initial.update(
                {
                    "tc_number": default_tc_number,
                    "issue_date": student.tc_issue_date or today,
                    "leaving_date": student.date_of_leaving_school or today,
                    "reason_for_leaving": student.reason_for_leaving,
                    "conduct": student.conduct or "Good",
                    "result": student.result,
                    "last_class_attended": student.current_class or student.admission_class,
                }
            )
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                css_class = "form-check-input"
            elif isinstance(field.widget, forms.Select):
                css_class = "form-select"
            else:
                css_class = "form-control"
            field.widget.attrs.setdefault("class", css_class)

    def clean(self):
        cleaned_data = super().clean()
        tc_number = cleaned_data.get("tc_number", "").strip()
        issue_date = cleaned_data.get("issue_date")
        leaving_date = cleaned_data.get("leaving_date")
        joined_on = self.academic_session.joined_on if self.academic_session else None

        if tc_number and self.student:
            if StudentTransferCertificate.objects.filter(
                institute=self.student.institute,
                tc_number__iexact=tc_number,
            ).exists():
                self.add_error("tc_number", "This TC number already exists for this institute.")

        if self.student and StudentTransferCertificate.objects.filter(
            student=self.student,
            status=StudentTransferCertificate.Status.GENERATED,
        ).exists():
            raise ValidationError("This student already has a generated TC. Cancel the existing TC before generating another.")

        if joined_on and leaving_date and leaving_date < joined_on:
            self.add_error("leaving_date", "Leaving date cannot be before admission date.")
        if leaving_date and issue_date and issue_date < leaving_date:
            self.add_error("issue_date", "TC issue date cannot be before leaving date.")
        return cleaned_data

    def build_snapshot(self):
        student = self.student
        session = self.academic_session
        primary_guardian = student.guardians.filter(is_primary=True).first() or student.guardians.first()
        enrollments = session.enrollments.select_related("batch").prefetch_related("courses")
        batch_names = []
        course_names = []
        for enrollment in enrollments:
            if enrollment.batch and enrollment.batch.name not in batch_names:
                batch_names.append(enrollment.batch.name)
            for course in enrollment.courses.all():
                if course.name not in course_names:
                    course_names.append(course.name)
        return {
            "institute_name": student.institute.name,
            "institute_address": student.institute.address,
            "institute_phone": student.institute.phone,
            "institute_email": student.institute.email,
            "academic_year": session.academic_year.name,
            "admission_number": session.admission_number,
            "student_name": student.user.get_full_name(),
            "father_name": student.father_name,
            "mother_name": student.mother_name,
            "guardian_name": primary_guardian.name if primary_guardian else "",
            "date_of_birth": student.date_of_birth.isoformat() if student.date_of_birth else "",
            "place_of_birth": student.place_of_birth,
            "nationality": student.nationality,
            "religion": student.religion,
            "caste_category": student.caste_category,
            "gr_number_udise": student.gr_number_udise,
            "udise_number": student.udise_number,
            "aadhaar_number": student.aadhaar_number,
            "admission_date": session.joined_on.isoformat() if session.joined_on else "",
            "current_class": student.current_class,
            "admission_class": student.admission_class,
            "division": student.division,
            "medium": student.medium,
            "batches": ", ".join(batch_names),
            "courses": ", ".join(course_names),
            "previous_school_name": session.previous_school_name,
            "previous_class": session.previous_class,
        }

    @transaction.atomic
    def save(self):
        student = self.student
        session = self.academic_session
        tc = StudentTransferCertificate.objects.create(
            institute=student.institute,
            student=student,
            academic_session=session,
            tc_number=self.cleaned_data["tc_number"].strip(),
            issue_date=self.cleaned_data["issue_date"],
            leaving_date=self.cleaned_data["leaving_date"],
            reason_for_leaving=self.cleaned_data["reason_for_leaving"],
            conduct=self.cleaned_data["conduct"],
            result=self.cleaned_data.get("result", ""),
            last_class_attended=self.cleaned_data["last_class_attended"],
            qualified_for_promotion=self.cleaned_data["qualified_for_promotion"],
            fees_cleared=self.cleaned_data["fees_cleared"],
            remarks=self.cleaned_data["remarks"],
            student_snapshot=self.build_snapshot(),
            generated_by=self.generated_by,
        )
        student.reason_for_leaving = tc.reason_for_leaving
        student.conduct = tc.conduct
        student.result = tc.result
        student.date_of_leaving_school = tc.leaving_date
        student.tc_issue_date = tc.issue_date
        student.student_status = StudentProfile.StudentStatus.TC_ISSUED
        student.is_active = False if self.cleaned_data["deactivate_login"] else student.is_active
        student.save(
            update_fields=[
                "reason_for_leaving",
                "conduct",
                "result",
                "date_of_leaving_school",
                "tc_issue_date",
                "student_status",
                "is_active",
            ]
        )
        if self.cleaned_data["deactivate_login"]:
            student.user.is_active = False
            student.user.save(update_fields=["is_active"])
        session.status = StudentAcademicSession.Status.LEFT
        session.save(update_fields=["status"])
        return tc


class StudentBonafideCertificateForm(forms.Form):
    certificate_number = forms.CharField(max_length=60)
    issue_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    purpose = forms.CharField(max_length=255, widget=forms.Textarea(attrs={"rows": 3}))
    remarks = forms.CharField(max_length=255, required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, student=None, academic_session=None, generated_by=None, **kwargs):
        self.student = student
        self.academic_session = academic_session
        self.generated_by = generated_by
        initial = kwargs.pop("initial", {})
        if student and academic_session:
            today = timezone.localdate()
            sequence = StudentBonafideCertificate.objects.filter(
                institute=student.institute,
                generated_at__year=today.year,
            ).count() + 1
            initial.update(
                {
                    "certificate_number": f"BON-{today:%Y}-{sequence:04d}",
                    "issue_date": today,
                    "purpose": student.bonafide_purpose,
                }
            )
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean(self):
        cleaned_data = super().clean()
        certificate_number = cleaned_data.get("certificate_number", "").strip()
        if certificate_number and self.student:
            if StudentBonafideCertificate.objects.filter(
                institute=self.student.institute,
                certificate_number__iexact=certificate_number,
            ).exists():
                self.add_error("certificate_number", "This Bonafide certificate number already exists.")
        return cleaned_data

    def build_snapshot(self):
        student = self.student
        session = self.academic_session
        primary_guardian = student.guardians.filter(is_primary=True).first() or student.guardians.first()
        return {
            "institute_name": student.institute.name,
            "institute_address": student.institute.address,
            "institute_phone": student.institute.phone,
            "institute_email": student.institute.email,
            "academic_year": session.academic_year.name,
            "admission_number": session.admission_number,
            "student_name": student.user.get_full_name(),
            "father_name": student.father_name,
            "mother_name": student.mother_name,
            "guardian_name": primary_guardian.name if primary_guardian else "",
            "date_of_birth": student.date_of_birth.isoformat() if student.date_of_birth else "",
            "gr_number_udise": student.gr_number_udise,
            "udise_number": student.udise_number,
            "roll_number": student.roll_number,
            "current_class": student.current_class,
            "admission_class": student.admission_class,
            "division": student.division,
            "medium": student.medium,
            "admission_date": session.joined_on.isoformat() if session.joined_on else "",
        }

    @transaction.atomic
    def save(self):
        student = self.student
        session = self.academic_session
        bonafide = StudentBonafideCertificate.objects.create(
            institute=student.institute,
            student=student,
            academic_session=session,
            certificate_number=self.cleaned_data["certificate_number"].strip(),
            issue_date=self.cleaned_data["issue_date"],
            purpose=self.cleaned_data["purpose"],
            remarks=self.cleaned_data["remarks"],
            student_snapshot=self.build_snapshot(),
            generated_by=self.generated_by,
        )
        student.bonafide_purpose = bonafide.purpose
        student.save(update_fields=["bonafide_purpose"])
        return bonafide


class StudentIdCardForm(forms.ModelForm):
    class Meta:
        model = StudentProfile
        fields = ("emergency_contact_number",)
        labels = {"emergency_contact_number": "Emergency Contact Number"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["emergency_contact_number"].required = False
        self.fields["emergency_contact_number"].widget.attrs.setdefault("class", "form-control")


class HomeworkForm(forms.ModelForm):
    files = MultipleFileField(required=False)
    allowed_extensions = {".pdf", ".jpg", ".jpeg", ".png", ".doc", ".docx"}

    class Meta:
        model = Homework
        fields = ("batch", "subject", "course", "title", "instructions", "due_date")
        widgets = {
            "instructions": forms.HiddenInput(),
            "due_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, institute=None, academic_year=None, **kwargs):
        self.institute = institute
        self.academic_year = academic_year
        super().__init__(*args, **kwargs)
        if institute:
            batches = Batch.objects.filter(institute=institute, is_active=True).prefetch_related(
                Prefetch(
                    "courses",
                    queryset=Course.objects.only("id", "name", "fee_amount"),
                )
            )
            subjects = Subject.objects.filter(institute=institute, is_active=True)
            courses = Course.objects.filter(institute=institute, is_active=True)
            if academic_year:
                batches = batches.filter(academic_year=academic_year)
                subjects = subjects.filter(academic_year=academic_year)
                courses = courses.filter(academic_year=academic_year)
            self.fields["batch"].queryset = batches
            self.fields["subject"].queryset = subjects
            self.fields["course"].queryset = courses
        else:
            self.fields["batch"].queryset = Batch.objects.none()
            self.fields["subject"].queryset = Subject.objects.none()
            self.fields["course"].queryset = Course.objects.none()

        self.fields["subject"].required = False
        self.fields["course"].required = False
        self.fields["subject"].empty_label = "General homework"
        self.fields["course"].empty_label = "No course"
        self.fields["files"].widget.attrs.update({"multiple": True, "accept": ".pdf,.jpg,.jpeg,.png,.doc,.docx"})
        self.fields["batch"].label_from_instance = lambda batch: batch.name
        self.fields["subject"].label_from_instance = lambda subject: subject.name
        self.fields["course"].label_from_instance = lambda course: course.name

        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                css_class = "form-select"
            else:
                css_class = "form-control"
            field.widget.attrs.setdefault("class", css_class)

    def clean(self):
        cleaned_data = super().clean()
        batch = cleaned_data.get("batch")
        subject = cleaned_data.get("subject")
        course = cleaned_data.get("course")
        if batch and subject and subject.academic_year_id != batch.academic_year_id:
            raise ValidationError("Selected subject must belong to the selected batch academic year.")
        if batch and course and not batch.courses.filter(pk=course.pk).exists():
            raise ValidationError("Selected course must belong to the selected batch.")
        return cleaned_data

    def clean_files(self):
        files = self.cleaned_data.get("files") or []
        for uploaded_file in files:
            extension = f".{uploaded_file.name.rsplit('.', 1)[-1].lower()}" if "." in uploaded_file.name else ""
            if extension not in self.allowed_extensions:
                raise ValidationError("Only PDF, JPG, PNG, DOC and DOCX files are allowed.")
        return files

    def save_attachments(self, homework):
        attachments = []
        for uploaded_file in self.cleaned_data.get("files") or []:
            attachments.append(HomeworkAttachment.objects.create(homework=homework, file=uploaded_file))
        return attachments


class NoticeForm(forms.ModelForm):
    class Meta:
        model = Notice
        fields = (
            "title",
            "message",
            "audience",
            "category",
            "priority",
            "target_batches",
            "target_courses",
            "target_students",
            "publish_at",
            "expires_at",
            "is_published",
            "push_to_app",
            "pin_on_top",
        )
        widgets = {
            "message": forms.HiddenInput(),
            "publish_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "expires_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "target_students": ajax_student_widget(multiple=True),
        }

    def __init__(self, *args, institute=None, academic_year=None, **kwargs):
        self.institute = institute
        self.academic_year = academic_year
        super().__init__(*args, **kwargs)
        if institute:
            batches = Batch.objects.filter(institute=institute, is_active=True)
            courses = Course.objects.filter(institute=institute, is_active=True)
            if academic_year:
                batches = batches.filter(academic_year=academic_year)
                courses = courses.filter(academic_year=academic_year)
            self.fields["target_batches"].queryset = batches
            self.fields["target_courses"].queryset = courses
            student_ids = selected_student_ids(self, "target_students")
            students = StudentProfile.objects.filter(
                institute=institute,
                is_active=True,
                pk__in=student_ids,
            )
            if academic_year:
                students = students.filter(academic_sessions__academic_year=academic_year)
            self.fields["target_students"].queryset = students.select_related("user").distinct()
        else:
            self.fields["target_batches"].queryset = Batch.objects.none()
            self.fields["target_courses"].queryset = Course.objects.none()
            self.fields["target_students"].queryset = StudentProfile.objects.none()

        self.fields["target_batches"].required = False
        self.fields["target_courses"].required = False
        self.fields["target_students"].required = False
        self.fields["target_students"].label_from_instance = lambda student: str(student)

        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                css_class = "form-check-input"
            elif isinstance(field.widget, forms.SelectMultiple):
                css_class = "form-select"
            elif isinstance(field.widget, forms.Select):
                css_class = "form-select"
            else:
                css_class = "form-control"
            field.widget.attrs.setdefault("class", css_class)

    def clean(self):
        cleaned_data = super().clean()
        publish_at = cleaned_data.get("publish_at")
        expires_at = cleaned_data.get("expires_at")
        if publish_at and expires_at and expires_at <= publish_at:
            raise ValidationError("Expiry date must be after publish date.")
        return cleaned_data


class StudentEnrollmentForm(forms.ModelForm):
    class Meta:
        model = StudentEnrollment
        fields = ("student", "batch", "courses", "enrolled_on", "status", "custom_fee_amount")
        widgets = {
            "enrolled_on": forms.DateInput(attrs={"type": "date"}),
            "student": ajax_student_widget(),
        }

    def __init__(self, *args, institute=None, academic_year=None, **kwargs):
        self.institute = institute
        self.academic_year = academic_year
        super().__init__(*args, **kwargs)

        if institute:
            student_ids = selected_student_ids(self, "student")
            students = StudentProfile.objects.filter(
                institute=institute,
                is_active=True,
                pk__in=student_ids,
            )
            if academic_year:
                students = students.filter(academic_sessions__academic_year=academic_year)
            self.fields["student"].queryset = students.select_related("user").distinct()
            batches = Batch.objects.filter(institute=institute, is_active=True).prefetch_related("courses")
            courses = Course.objects.filter(institute=institute, is_active=True)
            if academic_year:
                batches = batches.filter(academic_year=academic_year)
                courses = courses.filter(academic_year=academic_year)
            self.fields["batch"].queryset = batches
            self.fields["courses"].queryset = courses
        else:
            self.fields["student"].queryset = StudentProfile.objects.none()
            self.fields["batch"].queryset = Batch.objects.none()
            self.fields["courses"].queryset = Course.objects.none()

        self.fields["courses"].required = True
        self.fields["student"].label_from_instance = lambda student: str(student)
        self.fields["batch"].label_from_instance = lambda batch: f"{batch.name} ({batch.total_course_fee})"
        self.fields["custom_fee_amount"].widget.attrs.setdefault("min", "0")
        self.fields["custom_fee_amount"].widget.attrs.setdefault("step", "0.01")

        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                css_class = "form-check-input"
            elif isinstance(field.widget, forms.SelectMultiple):
                css_class = "form-select"
            elif isinstance(field.widget, forms.Select):
                css_class = "form-select"
            else:
                css_class = "form-control"
            field.widget.attrs.setdefault("class", css_class)

    def clean(self):
        cleaned_data = super().clean()
        student = cleaned_data.get("student")
        batch = cleaned_data.get("batch")
        courses = cleaned_data.get("courses")
        custom_fee_amount = cleaned_data.get("custom_fee_amount")

        if student and batch:
            queryset = StudentEnrollment.objects.filter(student=student, batch=batch)
            if self.academic_year:
                queryset = queryset.filter(academic_session__academic_year=self.academic_year)
            if self.instance and self.instance.pk:
                queryset = queryset.exclude(pk=self.instance.pk)
            if queryset.exists():
                raise ValidationError("This student is already enrolled in this batch.")

        if batch and courses:
            if self.academic_year and batch.academic_year_id != self.academic_year.id:
                raise ValidationError("Selected batch must belong to the selected academic year.")
            allowed_course_ids = set(batch.courses.values_list("id", flat=True))
            selected_course_ids = {course.id for course in courses}
            if not selected_course_ids.issubset(allowed_course_ids):
                raise ValidationError("Selected courses must belong to the selected batch.")
            if self.academic_year and courses.exclude(academic_year=self.academic_year).exists():
                raise ValidationError("Selected courses must belong to the selected academic year.")

        if custom_fee_amount is not None and custom_fee_amount < 0:
            raise ValidationError("Custom fee cannot be negative.")

        if self.instance and self.instance.pk:
            active_paid_amount = (
                Payment.objects.filter(
                    invoice__enrollment=self.instance,
                    status=Payment.Status.ACTIVE,
                ).aggregate(total=Sum("amount"))["total"]
                or Decimal("0.00")
            )
            has_fee_records = active_paid_amount > 0 or FeeInvoice.objects.filter(enrollment=self.instance).exists()

            if has_fee_records:
                if student and student != self.instance.student:
                    raise ValidationError("Student cannot be changed after fee records are created.")
                if batch and batch != self.instance.batch:
                    raise ValidationError("Batch cannot be changed after fee records are created.")

            if active_paid_amount > 0:
                status = cleaned_data.get("status")
                if status == StudentEnrollment.Status.CANCELLED:
                    raise ValidationError("Enrollment with active payments cannot be cancelled. Void payments first.")

                if custom_fee_amount is not None:
                    new_total_fee = custom_fee_amount
                elif courses:
                    new_total_fee = sum(course.fee_amount for course in courses)
                else:
                    new_total_fee = Decimal("0.00")

                if new_total_fee < active_paid_amount:
                    raise ValidationError("Enrollment fee cannot be less than already received payments.")

        return cleaned_data


class ReceiveFeeForm(forms.Form):
    existing_invoice = forms.ModelChoiceField(
        queryset=FeeInvoice.objects.none(),
        required=False,
        empty_label="Create new invoice",
        widget=forms.HiddenInput,
    )
    enrollment = forms.ModelChoiceField(queryset=StudentEnrollment.objects.none(), required=False)
    category = forms.ModelChoiceField(queryset=FeeCategory.objects.none(), required=False)
    title = forms.CharField(max_length=120, required=False)
    invoice_amount = forms.DecimalField(max_digits=10, decimal_places=2, min_value=0, required=False)
    payment_amount = forms.DecimalField(max_digits=10, decimal_places=2, min_value=0)
    paid_on = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    method = forms.ChoiceField(choices=Payment.Method.choices)
    receipt_number = forms.CharField(max_length=60, required=False)
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, institute=None, student=None, academic_session=None, **kwargs):
        self.institute = institute
        self.student = student
        self.academic_session = academic_session
        super().__init__(*args, **kwargs)

        self.fields["existing_invoice"].queryset = FeeInvoice.objects.filter(
            student=student,
            status__in=[FeeInvoice.Status.UNPAID, FeeInvoice.Status.PARTIAL],
        )
        if academic_session:
            self.fields["existing_invoice"].queryset = self.fields["existing_invoice"].queryset.filter(
                academic_session=academic_session
            )
        self.fields["enrollment"].queryset = StudentEnrollment.objects.filter(student=student).exclude(
            status=StudentEnrollment.Status.CANCELLED
        ).select_related("batch")
        if academic_session:
            self.fields["enrollment"].queryset = self.fields["enrollment"].queryset.filter(
                academic_session=academic_session
            )
        self.fields["category"].queryset = FeeCategory.objects.filter(institute=institute, is_active=True)
        self.fields["enrollment"].label_from_instance = lambda enrollment: (
            f"{enrollment.batch.name} - {enrollment.total_course_fee}"
        )
        self.fields["existing_invoice"].label_from_instance = lambda invoice: (
            f"{invoice.title} - Due {invoice.due_date} - {invoice.amount}"
        )
        self.fields["payment_amount"].widget.attrs.setdefault("step", "0.01")
        self.fields["invoice_amount"].widget.attrs.setdefault("step", "0.01")

        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                css_class = "form-select"
            else:
                css_class = "form-control"
            field.widget.attrs.setdefault("class", css_class)

    def clean(self):
        cleaned_data = super().clean()
        existing_invoice = None
        enrollment = cleaned_data.get("enrollment")
        category = cleaned_data.get("category")
        title = cleaned_data.get("title", "").strip()
        invoice_amount = cleaned_data.get("invoice_amount")
        payment_amount = cleaned_data.get("payment_amount")

        if payment_amount is not None and payment_amount <= 0:
            raise ValidationError("Payment amount must be greater than zero.")

        if category:
            existing_invoice = self.get_pending_category_invoice(category)
        if not existing_invoice and enrollment:
            existing_invoice = self.get_pending_enrollment_invoice(enrollment)
        cleaned_data["existing_invoice"] = existing_invoice

        if not existing_invoice:
            if not enrollment and not category:
                raise ValidationError("Select enrollment or category before receiving fee.")
            if not title:
                raise ValidationError("Enter invoice title when creating a new invoice.")
            if invoice_amount is None or invoice_amount <= 0:
                raise ValidationError("Enter invoice amount when creating a new invoice.")
            if enrollment:
                enrollment_due_amount = self.get_enrollment_due_amount(enrollment)
                if enrollment_due_amount <= 0:
                    raise ValidationError("Selected enrollment has no due amount.")
                if invoice_amount > enrollment_due_amount:
                    raise ValidationError("Invoice amount cannot be greater than selected enrollment due amount.")
                if payment_amount and payment_amount > enrollment_due_amount:
                    raise ValidationError("Payment amount cannot be greater than selected enrollment due amount.")
            if payment_amount and payment_amount > invoice_amount:
                raise ValidationError("Payment amount cannot be greater than invoice amount.")
        else:
            due_amount = self.get_invoice_due_amount(existing_invoice)
            max_due_amount = due_amount
            if existing_invoice.enrollment_id:
                enrollment_due_amount = self.get_enrollment_due_amount(existing_invoice.enrollment)
                max_due_amount = min(due_amount, enrollment_due_amount)
                if enrollment_due_amount <= 0:
                    raise ValidationError("Selected enrollment has no due amount left.")
            if payment_amount and payment_amount > due_amount:
                raise ValidationError("Payment amount cannot be greater than existing due amount.")
            if payment_amount and payment_amount > max_due_amount:
                raise ValidationError("Payment amount cannot be greater than selected service due amount.")

        return cleaned_data

    def get_invoice_due_amount(self, invoice):
        paid_amount = sum(
            payment.amount
            for payment in invoice.payments.filter(status=Payment.Status.ACTIVE)
        )
        due_amount = invoice.amount - paid_amount
        if due_amount < 0:
            return Decimal("0.00")
        return due_amount

    def get_pending_enrollment_invoice(self, enrollment):
        invoices = (
            FeeInvoice.objects.filter(
                student=self.student,
                academic_session=self.academic_session,
                enrollment=enrollment,
                status__in=[FeeInvoice.Status.UNPAID, FeeInvoice.Status.PARTIAL],
            )
            .prefetch_related("payments")
            .order_by("-created_at", "-pk")
        )
        for invoice in invoices:
            if self.get_invoice_due_amount(invoice) > 0:
                return invoice
        return None

    def get_pending_category_invoice(self, category):
        invoices = (
            FeeInvoice.objects.filter(
                student=self.student,
                academic_session=self.academic_session,
                category=category,
                enrollment__isnull=True,
                status__in=[FeeInvoice.Status.UNPAID, FeeInvoice.Status.PARTIAL],
            )
            .prefetch_related("payments")
            .order_by("-created_at", "-pk")
        )
        for invoice in invoices:
            if self.get_invoice_due_amount(invoice) > 0:
                return invoice
        return None

    def get_enrollment_paid_amount(self, enrollment):
        return sum(
            payment.amount
            for payment in Payment.objects.filter(
                invoice__student=self.student,
                invoice__academic_session=self.academic_session,
                invoice__enrollment=enrollment,
                status=Payment.Status.ACTIVE,
            )
        )

    def get_enrollment_due_amount(self, enrollment):
        due_amount = enrollment.total_course_fee - self.get_enrollment_paid_amount(enrollment)
        if due_amount < 0:
            return Decimal("0.00")
        return due_amount


class AddStudentFeeForm(forms.Form):
    category = forms.ModelChoiceField(queryset=FeeCategory.objects.none())
    title = forms.CharField(max_length=120, required=False)
    amount = forms.DecimalField(max_digits=10, decimal_places=2, min_value=0)
    due_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, institute=None, **kwargs):
        self.institute = institute
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = FeeCategory.objects.filter(institute=institute, is_active=True)
        self.fields["amount"].widget.attrs.setdefault("step", "0.01")
        self.fields["amount"].widget.attrs.setdefault("min", "0")

        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                css_class = "form-select"
            else:
                css_class = "form-control"
            field.widget.attrs.setdefault("class", css_class)

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise ValidationError("Fee amount must be greater than zero.")
        return amount

    def clean(self):
        cleaned_data = super().clean()
        category = cleaned_data.get("category")
        title = (cleaned_data.get("title") or "").strip()
        if category and not title:
            cleaned_data["title"] = category.name
        return cleaned_data


class PaymentUpdateForm(forms.Form):
    amount = forms.DecimalField(max_digits=10, decimal_places=2, min_value=0)
    paid_on = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    method = forms.ChoiceField(choices=Payment.Method.choices)
    receipt_number = forms.CharField(max_length=60, required=False)
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    correction_reason = forms.CharField(max_length=255, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, payment=None, **kwargs):
        self.payment = payment
        initial = kwargs.pop("initial", {})
        if payment:
            initial.update(
                {
                    "amount": payment.amount,
                    "paid_on": payment.paid_on,
                    "method": payment.method,
                    "receipt_number": payment.receipt_number,
                    "note": payment.note,
                }
            )
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        self.fields["amount"].widget.attrs.setdefault("step", "0.01")

        for field in self.fields.values():
            if isinstance(field.widget, forms.Select):
                css_class = "form-select"
            else:
                css_class = "form-control"
            field.widget.attrs.setdefault("class", css_class)

    def clean(self):
        cleaned_data = super().clean()
        amount = cleaned_data.get("amount")
        if self.payment and self.payment.status == Payment.Status.VOIDED:
            raise ValidationError("Voided payment cannot be updated.")

        if self.payment and amount is not None:
            invoice = self.payment.invoice
            invoice_active_paid = (
                invoice.payments.filter(status=Payment.Status.ACTIVE)
                .exclude(pk=self.payment.pk)
                .aggregate(total=Sum("amount"))["total"]
                or Decimal("0.00")
            )
            invoice_remaining = invoice.amount - invoice_active_paid
            if invoice.enrollment:
                active_paid = (
                    Payment.objects.filter(
                        invoice__student=invoice.student,
                        invoice__academic_session=invoice.academic_session,
                        invoice__enrollment=invoice.enrollment,
                        status=Payment.Status.ACTIVE,
                    )
                    .exclude(pk=self.payment.pk)
                    .aggregate(total=Sum("amount"))["total"]
                    or Decimal("0.00")
                )
                enrollment_remaining = invoice.enrollment.total_course_fee - active_paid
                max_amount = min(invoice_remaining, enrollment_remaining)
            else:
                max_amount = invoice_remaining

            if max_amount < 0:
                max_amount = Decimal("0.00")
            if amount > max_amount:
                raise ValidationError("Corrected amount cannot be greater than invoice or enrollment due.")

        return cleaned_data


class PaymentVoidForm(forms.Form):
    void_reason = forms.CharField(max_length=255, widget=forms.Textarea(attrs={"rows": 4}))

    def __init__(self, *args, payment=None, **kwargs):
        self.payment = payment
        super().__init__(*args, **kwargs)
        self.fields["void_reason"].widget.attrs.setdefault("class", "form-control")

    def clean(self):
        cleaned_data = super().clean()
        if self.payment and self.payment.status == Payment.Status.VOIDED:
            raise ValidationError("This payment is already voided.")
        return cleaned_data
