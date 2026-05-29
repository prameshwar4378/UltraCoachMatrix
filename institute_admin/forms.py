from decimal import Decimal
from datetime import date
import re

from django import forms
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from django.db.models import Sum
from django.utils import timezone

from accountant.models import FeeCategory, FeeInvoice, Payment, PaymentActivity
from super_admin.models import UserProfile
from student_parent.models import (
    GuardianProfile,
    StudentAcademicSession,
    StudentDocument,
    StudentEnrollment,
    StudentProfile,
)
from teacher.models import Homework, HomeworkAttachment, TeacherProfile

from .models import AcademicYear, Batch, Course, Notice


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


def generate_student_admission_number(institute, academic_year=None):
    academic_year = academic_year or get_or_create_academic_year(institute)
    prefix = f"{get_institute_initials(institute)}-{academic_year.name}-"
    existing_numbers = StudentAcademicSession.objects.filter(
        institute=institute,
        academic_year=academic_year,
        admission_number__startswith=prefix,
    ).values_list("admission_number", flat=True)
    last_sequence = 0
    for admission_number in existing_numbers:
        try:
            last_sequence = max(last_sequence, int(admission_number.rsplit("-", 1)[-1]))
        except (TypeError, ValueError):
            continue
    return f"{prefix}{last_sequence + 1:04d}"


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
    teachers = forms.ModelMultipleChoiceField(
        queryset=UserProfile.objects.none(),
        required=False,
    )

    class Meta:
        model = Batch
        fields = ("courses", "name", "teachers", "start_date", "end_date", "timing", "is_active")
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
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
    profile_image = forms.ImageField(required=False)
    date_of_birth = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    joined_on = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    address = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    current_school_name = forms.CharField(max_length=160, required=False)
    current_school_address = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    previous_school_name = forms.CharField(max_length=160, required=False)
    previous_class = forms.CharField(max_length=80, required=False)
    guardian_name = forms.CharField(max_length=120, required=False)
    guardian_relation = forms.CharField(max_length=60, required=False)
    guardian_phone = forms.CharField(max_length=20, required=False)
    guardian_email = forms.EmailField(required=False)
    document_type = forms.ChoiceField(choices=StudentDocument.DocumentType.choices, required=False)
    document_title = forms.CharField(max_length=120, required=False)
    document_file = forms.FileField(required=False)
    document_note = forms.CharField(max_length=255, required=False)
    is_active = forms.BooleanField(required=False, initial=True)

    def __init__(self, *args, institute=None, student=None, **kwargs):
        self.institute = institute
        self.student = student
        self.academic_year = kwargs.pop("academic_year", None)
        initial = kwargs.pop("initial", {})

        if student:
            user = student.user
            profile = getattr(user, "profile", None)
            guardian = student.guardians.filter(is_primary=True).first() or student.guardians.first()
            academic_year = self.academic_year or student.academic_year
            student_session = None
            if academic_year:
                student_session = student.academic_sessions.filter(academic_year=academic_year).first()
            initial.update(
                {
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "username": user.username,
                    "email": user.email,
                    "phone": profile.phone if profile else "",
                    "date_of_birth": student.date_of_birth,
                    "joined_on": student_session.joined_on if student_session else student.joined_on,
                    "address": student.address,
                    "current_school_name": (
                        student_session.current_school_name if student_session else student.current_school_name
                    ),
                    "current_school_address": (
                        student_session.current_school_address if student_session else student.current_school_address
                    ),
                    "previous_school_name": (
                        student_session.previous_school_name if student_session else student.previous_school_name
                    ),
                    "previous_class": student_session.previous_class if student_session else student.previous_class,
                    "guardian_name": guardian.name if guardian else "",
                    "guardian_relation": guardian.relation if guardian else "",
                    "guardian_phone": guardian.phone if guardian else "",
                    "guardian_email": guardian.email if guardian else "",
                    "is_active": student.is_active,
                }
            )

        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        if not student:
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
        if self.student:
            queryset = queryset.exclude(pk=self.student.user_id)
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

        document_file = cleaned_data.get("document_file")
        document_title = cleaned_data.get("document_title", "").strip()
        if document_file and not document_title:
            raise ValidationError("Enter document title when uploading a document.")

        return cleaned_data

    def save(self):
        if self.student:
            student = self.student
            user = student.user
        else:
            user = User()
            student = None

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
                "role": UserProfile.Role.STUDENT_PARENT,
                "phone": self.cleaned_data["phone"],
            },
        )

        academic_year = self.academic_year or (self.student.academic_year if self.student else None)
        academic_year = academic_year or get_or_create_academic_year(self.institute)
        existing_session = (
            self.student.academic_sessions.filter(academic_year=academic_year).first()
            if self.student
            else None
        )
        admission_number = (
            existing_session.admission_number
            if existing_session
            else generate_student_admission_number(self.institute, academic_year)
        )
        student, _created = StudentProfile.objects.update_or_create(
            user=user,
            defaults={
                "institute": self.institute,
                "academic_year": academic_year,
                "admission_number": admission_number,
                "date_of_birth": self.cleaned_data["date_of_birth"],
                "joined_on": self.cleaned_data["joined_on"],
                "address": self.cleaned_data["address"],
                "current_school_name": self.cleaned_data["current_school_name"],
                "current_school_address": self.cleaned_data["current_school_address"],
                "previous_school_name": self.cleaned_data["previous_school_name"],
                "previous_class": self.cleaned_data["previous_class"],
                "is_active": self.cleaned_data["is_active"],
            },
        )

        if self.cleaned_data.get("profile_image"):
            student.profile_image = self.cleaned_data["profile_image"]
            student.save(update_fields=["profile_image"])

        StudentAcademicSession.objects.update_or_create(
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
                "current_school_name": self.cleaned_data["current_school_name"],
                "current_school_address": self.cleaned_data["current_school_address"],
                "previous_school_name": self.cleaned_data["previous_school_name"],
                "previous_class": self.cleaned_data["previous_class"],
            },
        )

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

        if self.cleaned_data.get("document_file"):
            StudentDocument.objects.create(
                student=student,
                document_type=self.cleaned_data.get("document_type") or StudentDocument.DocumentType.OTHER,
                title=self.cleaned_data["document_title"],
                file=self.cleaned_data["document_file"],
                note=self.cleaned_data["document_note"],
            )

        return student


class StudentBasicForm(forms.Form):
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
    profile_image = forms.ImageField(required=False)
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
                    "date_of_birth": student.date_of_birth,
                    "joined_on": student_session.joined_on if student_session else student.joined_on,
                    "address": student.address,
                    "is_active": student.is_active,
                }
            )

        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            css_class = "form-check-input" if isinstance(field.widget, forms.CheckboxInput) else "form-control"
            if isinstance(field.widget, forms.Select):
                css_class = "form-select"
            field.widget.attrs.setdefault("class", css_class)

    def clean_username(self):
        username = self.cleaned_data["username"]
        queryset = User.objects.filter(username=username)
        if self.student:
            queryset = queryset.exclude(pk=self.student.user_id)
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

    def save(self):
        student = self.student
        user = student.user

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
                "role": UserProfile.Role.STUDENT_PARENT,
                "phone": self.cleaned_data["phone"],
            },
        )

        student.date_of_birth = self.cleaned_data["date_of_birth"]
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


class HomeworkForm(forms.ModelForm):
    files = MultipleFileField(required=False)
    allowed_extensions = {".pdf", ".jpg", ".jpeg", ".png", ".doc", ".docx"}

    class Meta:
        model = Homework
        fields = ("batch", "course", "title", "instructions", "due_date")
        widgets = {
            "instructions": forms.HiddenInput(),
            "due_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, institute=None, academic_year=None, **kwargs):
        self.institute = institute
        self.academic_year = academic_year
        super().__init__(*args, **kwargs)
        if institute:
            batches = Batch.objects.filter(institute=institute, is_active=True).prefetch_related("courses")
            courses = Course.objects.filter(institute=institute, is_active=True)
            if academic_year:
                batches = batches.filter(academic_year=academic_year)
                courses = courses.filter(academic_year=academic_year)
            self.fields["batch"].queryset = batches
            self.fields["course"].queryset = courses
        else:
            self.fields["batch"].queryset = Batch.objects.none()
            self.fields["course"].queryset = Course.objects.none()

        self.fields["course"].required = False
        self.fields["files"].widget.attrs.update({"multiple": True, "accept": ".pdf,.jpg,.jpeg,.png,.doc,.docx"})
        self.fields["batch"].label_from_instance = lambda batch: batch.name
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
        course = cleaned_data.get("course")
        if batch and course and not batch.courses.filter(pk=course.pk).exists():
            raise ValidationError("Selected subject/course must belong to the selected batch.")
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
        }

    def __init__(self, *args, institute=None, academic_year=None, **kwargs):
        self.institute = institute
        self.academic_year = academic_year
        super().__init__(*args, **kwargs)
        if institute:
            batches = Batch.objects.filter(institute=institute, is_active=True)
            courses = Course.objects.filter(institute=institute, is_active=True)
            students = StudentProfile.objects.filter(institute=institute, is_active=True)
            if academic_year:
                batches = batches.filter(academic_year=academic_year)
                courses = courses.filter(academic_year=academic_year)
                students = students.filter(academic_sessions__academic_year=academic_year).distinct()
            self.fields["target_batches"].queryset = batches
            self.fields["target_courses"].queryset = courses
            self.fields["target_students"].queryset = students.select_related("user")
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
        }

    def __init__(self, *args, institute=None, academic_year=None, **kwargs):
        self.institute = institute
        self.academic_year = academic_year
        super().__init__(*args, **kwargs)

        if institute:
            students = StudentProfile.objects.filter(institute=institute, is_active=True)
            if academic_year:
                students = students.filter(academic_sessions__academic_year=academic_year).distinct()
            self.fields["student"].queryset = students
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
