from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.forms import inlineformset_factory

from institute_admin.models import Batch, Course, Subject
from .models import Exam, ExamQuestion, ExamQuestionOption, ExamResult, Homework, HomeworkAttachment


class YearAwareSelect(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        instance = getattr(value, "instance", None)
        if instance and getattr(instance, "academic_year_id", None):
            option["attrs"]["data-year-id"] = str(instance.academic_year_id)
        return option


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    widget = MultipleFileInput

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            return [single_file_clean(item, initial) for item in data if item]
        cleaned = single_file_clean(data, initial)
        return [cleaned] if cleaned else []


class TeacherHomeworkForm(forms.ModelForm):
    files = MultipleFileField(
        required=False,
        widget=MultipleFileInput(attrs={"multiple": True, "accept": ".pdf,.jpg,.jpeg,.png,.doc,.docx"}),
    )
    allowed_extensions = {".pdf", ".jpg", ".jpeg", ".png", ".doc", ".docx"}

    class Meta:
        model = Homework
        fields = ("batch", "subject", "course", "title", "instructions", "due_date")
        widgets = {
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "instructions": forms.HiddenInput(),
        }

    def __init__(self, *args, batches=None, **kwargs):
        super().__init__(*args, **kwargs)
        batches = batches or Batch.objects.none()
        courses = Course.objects.filter(batches__in=batches).distinct()
        institute_ids = batches.values_list("institute_id", flat=True).distinct()
        academic_year_ids = batches.values_list("academic_year_id", flat=True).distinct()
        subject_filter = Q(is_active=True)
        if self.instance and self.instance.pk and self.instance.subject_id:
            subject_filter |= Q(pk=self.instance.subject_id)
        subjects = Subject.objects.filter(
            institute_id__in=institute_ids,
            academic_year_id__in=academic_year_ids,
        ).filter(subject_filter).distinct()
        self.fields["batch"].queryset = batches
        self.fields["subject"].queryset = subjects
        self.fields["course"].queryset = courses
        self.fields["subject"].required = False
        self.fields["course"].required = False
        self.fields["subject"].empty_label = "General homework"
        self.fields["course"].empty_label = "No course"
        self.fields["batch"].label_from_instance = lambda batch: batch.name
        self.fields["subject"].label_from_instance = lambda subject: subject.name
        self.fields["course"].label_from_instance = lambda course: course.name
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        self.fields["batch"].widget.attrs["class"] = "form-select"
        self.fields["subject"].widget.attrs["class"] = "form-select"
        self.fields["course"].widget.attrs["class"] = "form-select"

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
        files = self.cleaned_data.get("files") or []
        for file in files:
            HomeworkAttachment.objects.create(homework=homework, file=file)


class TeacherExamForm(forms.ModelForm):
    class Meta:
        model = Exam
        fields = (
            "batch",
            "subject",
            "title",
            "exam_date",
            "duration_minutes",
            "instructions",
            "allow_rough_work_uploads",
            "is_published",
            "show_result_after_submit",
        )
        widgets = {
            "batch": YearAwareSelect(),
            "subject": YearAwareSelect(),
            "exam_date": forms.DateInput(attrs={"type": "date"}),
            "instructions": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, batches=None, **kwargs):
        super().__init__(*args, **kwargs)
        batches = batches or Batch.objects.none()
        self.fields["batch"].queryset = batches
        institute_ids = batches.values_list("institute_id", flat=True).distinct()
        academic_year_ids = batches.values_list("academic_year_id", flat=True)
        subject_filter = Q(is_active=True)
        if self.instance and self.instance.pk and self.instance.subject_id:
            subject_filter |= Q(pk=self.instance.subject_id)
        subject_queryset = Subject.objects.filter(
            institute_id__in=institute_ids,
            academic_year_id__in=academic_year_ids,
        ).filter(subject_filter).distinct()
        self.fields["subject"].queryset = subject_queryset
        self.fields["subject"].required = False
        self.fields["batch"].empty_label = "Select batch"
        self.fields["subject"].empty_label = "Select subject"
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        self.fields["batch"].widget.attrs["class"] = "form-select"
        self.fields["subject"].widget.attrs["class"] = "form-select"
        self.fields["allow_rough_work_uploads"].widget.attrs["class"] = "form-check-input"
        self.fields["is_published"].widget.attrs["class"] = "form-check-input"
        self.fields["show_result_after_submit"].widget.attrs["class"] = "form-check-input"

    def clean(self):
        cleaned_data = super().clean()
        batch = cleaned_data.get("batch")
        subject = cleaned_data.get("subject")
        if batch and subject and subject.academic_year_id != batch.academic_year_id:
            self.add_error("subject", "Selected subject must belong to the same academic year as this batch.")
        return cleaned_data


class ExamQuestionForm(forms.ModelForm):
    class Meta:
        model = ExamQuestion
        fields = ("text", "image", "marks")
        widgets = {
            "text": forms.Textarea(attrs={"rows": 4, "placeholder": "Optional question text. Upload an image for diagrams or complex problems."}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["text"].required = False
        self.fields["image"].required = False
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean(self):
        cleaned_data = super().clean()
        text = (cleaned_data.get("text") or "").strip()
        image = cleaned_data.get("image") or getattr(self.instance, "image", None)
        if not text and not image:
            raise forms.ValidationError("Add question text or upload a question image.")
        return cleaned_data


class ExamQuestionOptionForm(forms.ModelForm):
    class Meta:
        model = ExamQuestionOption
        fields = ("text", "is_correct")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["text"].widget.attrs.setdefault("class", "form-control")
        self.fields["is_correct"].widget.attrs["class"] = "form-check-input"


ExamQuestionOptionFormSet = inlineformset_factory(
    ExamQuestion,
    ExamQuestionOption,
    form=ExamQuestionOptionForm,
    extra=4,
    min_num=4,
    max_num=4,
    validate_min=True,
    validate_max=True,
    can_delete=False,
)


class TeacherExamResultForm(forms.ModelForm):
    class Meta:
        model = ExamResult
        fields = ("exam", "student", "marks_obtained", "remark")

    def __init__(self, *args, exams=None, students=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["exam"].queryset = exams or Exam.objects.none()
        self.fields["student"].queryset = students or self.fields["student"].queryset.none()
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        self.fields["exam"].widget.attrs["class"] = "form-select"
        self.fields["student"].widget.attrs["class"] = "form-select"
