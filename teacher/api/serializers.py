from datetime import date

from rest_framework import serializers

from .services import student_display_name
from ..models import Attendance
from ..views import teacher_attempt_percentage


class CourseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class SubjectSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class AcademicYearSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="pk")
    name = serializers.CharField()
    is_active = serializers.BooleanField()


class BatchSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="pk")
    name = serializers.CharField()
    academic_year_id = serializers.IntegerField()
    academic_year = serializers.CharField(source="academic_year.name", allow_blank=True)
    active_students = serializers.SerializerMethodField()
    course_total = serializers.SerializerMethodField()
    courses = serializers.SerializerMethodField()
    subjects = serializers.SerializerMethodField()

    def get_active_students(self, batch):
        return getattr(batch, "active_students", 0)

    def get_course_total(self, batch):
        return getattr(batch, "course_total", batch.courses.count())

    def get_courses(self, batch):
        return CourseSerializer(batch.courses.all(), many=True).data

    def get_subjects(self, batch):
        subjects = self.context.get("subjects_by_year", {}).get(batch.academic_year_id)
        if subjects is None:
            subjects = []
        return SubjectSerializer(subjects, many=True).data


class StudentSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="pk")
    student_id = serializers.IntegerField()
    name = serializers.SerializerMethodField()
    admission_number = serializers.CharField()
    roll_number = serializers.CharField(source="student.roll_number", allow_blank=True)
    batch_id = serializers.SerializerMethodField()
    batch_name = serializers.SerializerMethodField()

    def get_name(self, session):
        return student_display_name(session.student)

    def get_batch_id(self, _session):
        return self.context["batch"].pk

    def get_batch_name(self, _session):
        return self.context["batch"].name


class StudentDetailSerializer(StudentSerializer):
    email = serializers.SerializerMethodField()
    phone = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()

    def get_email(self, session):
        return session.student.user.email

    def get_phone(self, session):
        return getattr(session.student, "phone", "") or getattr(session.student, "mobile", "")

    def get_summary(self, _session):
        return self.context.get("summary", {})


class AttendanceRowSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="pk")
    academic_session_id = serializers.IntegerField()
    student_id = serializers.IntegerField()
    student_name = serializers.SerializerMethodField()
    roll_number = serializers.CharField(source="student.roll_number", allow_blank=True)
    batch_id = serializers.IntegerField()
    batch_name = serializers.CharField(source="batch.name")
    date = serializers.DateField(format="%Y-%m-%d")
    status = serializers.CharField()
    note = serializers.CharField()

    def get_student_name(self, record):
        return student_display_name(record.student)


class AttendanceSaveRowSerializer(serializers.Serializer):
    academic_session_id = serializers.IntegerField(required=False)
    student_id = serializers.IntegerField(required=False)
    status = serializers.ChoiceField(choices=Attendance.Status.values)
    note = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if not attrs.get("academic_session_id") and not attrs.get("student_id"):
            raise serializers.ValidationError("academic_session_id is required.")
        return attrs


class AttendanceSaveSerializer(serializers.Serializer):
    class_id = serializers.IntegerField(required=False)
    batch_id = serializers.IntegerField(required=False)
    date = serializers.DateField(required=False, default=date.today)
    rows = AttendanceSaveRowSerializer(many=True, allow_empty=False)

    def validate(self, attrs):
        attrs["batch_id"] = attrs.get("class_id") or attrs.get("batch_id")
        if not attrs["batch_id"]:
            raise serializers.ValidationError({"class_id": "Class is required."})
        return attrs


class HomeworkSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="pk")
    title = serializers.CharField()
    instructions = serializers.CharField()
    batch_id = serializers.IntegerField()
    batch_name = serializers.CharField(source="batch.name")
    course_id = serializers.IntegerField(allow_null=True)
    course_name = serializers.SerializerMethodField()
    subject_id = serializers.IntegerField(allow_null=True)
    subject_name = serializers.SerializerMethodField()
    due_date = serializers.DateField(format="%Y-%m-%d", allow_null=True)
    created_at = serializers.DateTimeField()
    attachment_count = serializers.SerializerMethodField()
    attachments = serializers.SerializerMethodField()

    def get_course_name(self, homework):
        return homework.course.name if homework.course_id else ""

    def get_subject_name(self, homework):
        return homework.subject.name if homework.subject_id else ""

    def get_attachment_count(self, homework):
        return homework.attachments.count()

    def get_attachments(self, homework):
        request = self.context.get("request")
        rows = []
        for attachment in homework.attachments.all():
            url = attachment.file.url if attachment.file else ""
            if request and url:
                url = request.build_absolute_uri(url)
            rows.append(
                {
                    "id": attachment.pk,
                    "name": attachment.file.name.rsplit("/", 1)[-1] if attachment.file else "",
                    "url": url,
                }
            )
        return rows


class HomeworkWriteSerializer(serializers.Serializer):
    class_id = serializers.IntegerField(required=False)
    batch_id = serializers.IntegerField(required=False)
    course_id = serializers.IntegerField(required=False, allow_null=True)
    subject_id = serializers.IntegerField(required=False, allow_null=True)
    title = serializers.CharField(required=False, allow_blank=True, default="Homework")
    instructions = serializers.CharField(required=False, allow_blank=True, default="")
    due_date = serializers.DateField(required=False, allow_null=True)

    def validate(self, attrs):
        attrs["batch_id"] = attrs.get("class_id") or attrs.get("batch_id")
        if not attrs["batch_id"]:
            raise serializers.ValidationError({"class_id": "Class is required."})
        return attrs


class HomeworkUpdateSerializer(serializers.Serializer):
    class_id = serializers.IntegerField(required=False)
    batch_id = serializers.IntegerField(required=False)
    course_id = serializers.IntegerField(required=False, allow_null=True)
    subject_id = serializers.IntegerField(required=False, allow_null=True)
    title = serializers.CharField(required=False, allow_blank=True)
    instructions = serializers.CharField(required=False, allow_blank=True)
    due_date = serializers.DateField(required=False, allow_null=True)
    remove_attachment_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        allow_empty=True,
    )

    def validate(self, attrs):
        if attrs.get("class_id") and not attrs.get("batch_id"):
            attrs["batch_id"] = attrs["class_id"]
        return attrs


class ExamWriteSerializer(serializers.Serializer):
    batch_id = serializers.IntegerField()
    course_id = serializers.IntegerField(required=False, allow_null=True)
    subject_id = serializers.IntegerField(required=False, allow_null=True)
    title = serializers.CharField(max_length=160)
    exam_date = serializers.DateField()
    duration_minutes = serializers.IntegerField(min_value=1, default=60)
    instructions = serializers.CharField(required=False, allow_blank=True, default="")
    allow_rough_work_uploads = serializers.BooleanField(required=False, default=True)
    is_published = serializers.BooleanField(required=False, default=False)
    show_result_after_submit = serializers.BooleanField(required=False, default=True)


class ExamUpdateSerializer(serializers.Serializer):
    batch_id = serializers.IntegerField(required=False)
    course_id = serializers.IntegerField(required=False, allow_null=True)
    subject_id = serializers.IntegerField(required=False, allow_null=True)
    title = serializers.CharField(required=False, max_length=160)
    exam_date = serializers.DateField(required=False)
    duration_minutes = serializers.IntegerField(required=False, min_value=1)
    instructions = serializers.CharField(required=False, allow_blank=True)
    allow_rough_work_uploads = serializers.BooleanField(required=False)
    is_published = serializers.BooleanField(required=False)
    show_result_after_submit = serializers.BooleanField(required=False)


class NoticeSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="pk")
    title = serializers.CharField()
    message = serializers.CharField()
    category = serializers.CharField()
    priority = serializers.CharField()
    is_read = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField()
    publish_at = serializers.DateTimeField(allow_null=True)
    expires_at = serializers.DateTimeField(allow_null=True)

    def get_is_read(self, notice):
        return notice.pk in self.context.get("read_ids", set())


class ExamSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="pk")
    title = serializers.CharField()
    batch_id = serializers.IntegerField()
    batch_name = serializers.CharField(source="batch.name")
    course_id = serializers.IntegerField(allow_null=True)
    course_name = serializers.SerializerMethodField()
    subject_id = serializers.IntegerField(allow_null=True)
    subject_name = serializers.SerializerMethodField()
    exam_date = serializers.DateField(format="%Y-%m-%d")
    total_marks = serializers.IntegerField()
    duration_minutes = serializers.IntegerField()
    is_published = serializers.BooleanField()
    show_result_after_submit = serializers.BooleanField()
    instructions = serializers.CharField()
    allow_rough_work_uploads = serializers.BooleanField()
    question_count = serializers.SerializerMethodField()
    submission_count = serializers.SerializerMethodField()
    result_count = serializers.SerializerMethodField()

    def get_course_name(self, exam):
        return exam.course.name if exam.course_id else ""

    def get_subject_name(self, exam):
        return exam.subject.name if exam.subject_id else ""

    def get_question_count(self, exam):
        return getattr(exam, "question_count", exam.questions.count())

    def get_submission_count(self, exam):
        return getattr(exam, "submission_count", exam.attempts.filter(submitted_at__isnull=False).count())

    def get_result_count(self, exam):
        return getattr(exam, "result_count", exam.attempts.filter(submitted_at__isnull=False).count())


class QuestionSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="pk")
    exam_id = serializers.IntegerField()
    exam_title = serializers.CharField(source="exam.title")
    text = serializers.CharField()
    image_url = serializers.SerializerMethodField()
    marks = serializers.IntegerField()
    order = serializers.IntegerField()
    question_type = serializers.SerializerMethodField()
    options = serializers.SerializerMethodField()

    def get_image_url(self, question):
        if not question.image:
            return ""
        request = self.context.get("request")
        url = question.image.url
        return request.build_absolute_uri(url) if request else url

    def get_question_type(self, _question):
        return "MCQ"

    def get_options(self, question):
        return [
            {
                "id": option.pk,
                "text": option.text,
                "is_correct": option.is_correct,
                "order": option.order,
            }
            for option in question.options.all()
        ]


class QuestionOptionWriteSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False)
    text = serializers.CharField(max_length=500)
    is_correct = serializers.BooleanField(required=False, default=False)
    order = serializers.IntegerField(required=False, min_value=1)


class QuestionWriteSerializer(serializers.Serializer):
    exam_id = serializers.IntegerField(required=False)
    text = serializers.CharField(required=False, allow_blank=True)
    marks = serializers.IntegerField(min_value=1, default=1)
    order = serializers.IntegerField(required=False, min_value=1)
    options = QuestionOptionWriteSerializer(many=True)

    def validate(self, attrs):
        options = attrs.get("options") or []
        if len(options) != 4:
            raise serializers.ValidationError({"options": "Exactly four options are required."})
        if not any(option.get("is_correct") for option in options):
            raise serializers.ValidationError({"options": "At least one option must be correct."})
        return attrs


class QuestionUpdateSerializer(serializers.Serializer):
    exam_id = serializers.IntegerField(required=False)
    text = serializers.CharField(required=False, allow_blank=True)
    marks = serializers.IntegerField(required=False, min_value=1)
    order = serializers.IntegerField(required=False, min_value=1)
    remove_image = serializers.BooleanField(required=False, default=False)
    options = QuestionOptionWriteSerializer(required=False, many=True)

    def validate(self, attrs):
        if "options" in attrs:
            options = attrs.get("options") or []
            if len(options) != 4:
                raise serializers.ValidationError({"options": "Exactly four options are required."})
            if not any(option.get("is_correct") for option in options):
                raise serializers.ValidationError({"options": "At least one option must be correct."})
        return attrs


class AttemptSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="pk")
    exam_id = serializers.IntegerField()
    exam_title = serializers.CharField(source="exam.title")
    student_id = serializers.IntegerField()
    student_name = serializers.SerializerMethodField()
    roll_number = serializers.CharField(source="student.roll_number", allow_blank=True)
    admission_number = serializers.CharField(source="academic_session.admission_number")
    score = serializers.DecimalField(max_digits=7, decimal_places=2, coerce_to_string=False)
    total_marks = serializers.DecimalField(max_digits=7, decimal_places=2, coerce_to_string=False)
    percentage = serializers.SerializerMethodField()
    correct_count = serializers.IntegerField()
    wrong_count = serializers.IntegerField()
    unattempted_count = serializers.IntegerField()
    submitted_at = serializers.DateTimeField(allow_null=True)
    status = serializers.SerializerMethodField()

    def get_student_name(self, attempt):
        return student_display_name(attempt.student)

    def get_percentage(self, attempt):
        return float(teacher_attempt_percentage(attempt))

    def get_status(self, attempt):
        return "submitted" if attempt.is_submitted else "in_progress"


class MessageSerializer(serializers.Serializer):
    recipient_id = serializers.IntegerField(required=False)
    batch_id = serializers.IntegerField(required=False)
    subject = serializers.CharField(required=False, allow_blank=True, default="")
    message = serializers.CharField()
