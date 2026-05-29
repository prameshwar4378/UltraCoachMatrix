from django import forms

from institute_admin.models import Batch, Course
from .models import Exam, ExamResult, Homework, HomeworkAttachment


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class TeacherHomeworkForm(forms.ModelForm):
    attachments = forms.FileField(
        required=False,
        widget=MultipleFileInput(attrs={"multiple": True}),
    )

    class Meta:
        model = Homework
        fields = ("batch", "course", "title", "instructions", "due_date")
        widgets = {
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "instructions": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, batches=None, **kwargs):
        super().__init__(*args, **kwargs)
        batches = batches or Batch.objects.none()
        courses = Course.objects.filter(batches__in=batches).distinct()
        self.fields["batch"].queryset = batches
        self.fields["course"].queryset = courses
        self.fields["course"].required = False
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        self.fields["batch"].widget.attrs["class"] = "form-select"
        self.fields["course"].widget.attrs["class"] = "form-select"

    def save_attachments(self, homework):
        files = self.files.getlist("attachments")
        for file in files:
            HomeworkAttachment.objects.create(homework=homework, file=file)


class TeacherExamForm(forms.ModelForm):
    class Meta:
        model = Exam
        fields = ("batch", "title", "exam_date", "total_marks")
        widgets = {
            "exam_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, batches=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["batch"].queryset = batches or Batch.objects.none()
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        self.fields["batch"].widget.attrs["class"] = "form-select"


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
