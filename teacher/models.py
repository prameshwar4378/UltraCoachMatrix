from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class TeacherProfile(models.Model):
    class TeacherType(models.TextChoices):
        FULL_TIME = "FULL_TIME", "Full Time"
        PART_TIME = "PART_TIME", "Part Time"

    institute = models.ForeignKey(
        "super_admin.Institute",
        on_delete=models.CASCADE,
        related_name="teacher_profiles",
    )
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="teacher_profile")
    employee_id = models.CharField(max_length=40, blank=True)
    teacher_type = models.CharField(
        max_length=20,
        choices=TeacherType.choices,
        default=TeacherType.FULL_TIME,
    )
    qualification = models.CharField(max_length=160, blank=True)
    specialization = models.CharField(max_length=160, blank=True)
    max_classes_per_day = models.PositiveIntegerField(default=6)
    max_classes_per_week = models.PositiveIntegerField(default=30)
    joined_on = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["user__first_name", "user__username"]
        indexes = [
            models.Index(fields=["institute", "is_active"], name="teacher_inst_active_idx"),
        ]

    def __str__(self):
        return self.user.get_full_name() or self.user.username


class Attendance(models.Model):
    class Status(models.TextChoices):
        PRESENT = "PRESENT", "Present"
        ABSENT = "ABSENT", "Absent"
        LATE = "LATE", "Late"

    student = models.ForeignKey(
        "student_parent.StudentProfile",
        on_delete=models.CASCADE,
        related_name="attendance_records",
    )
    academic_session = models.ForeignKey(
        "student_parent.StudentAcademicSession",
        on_delete=models.CASCADE,
        related_name="attendance_records",
    )
    batch = models.ForeignKey(
        "institute_admin.Batch",
        on_delete=models.CASCADE,
        related_name="attendance_records",
    )
    date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PRESENT)
    marked_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="marked_attendance",
    )
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-date"]
        unique_together = ["academic_session", "batch", "date"]
        indexes = [
            models.Index(fields=["academic_session", "-date", "status"], name="att_session_date_idx"),
            models.Index(fields=["student", "-date"], name="att_student_date_idx"),
            models.Index(fields=["batch", "date", "status"], name="att_batch_date_idx"),
        ]

    def __str__(self):
        return f"{self.student} - {self.date} - {self.status}"

    def save(self, *args, **kwargs):
        if self.academic_session_id:
            self.student = self.academic_session.student
        super().save(*args, **kwargs)


class Homework(models.Model):
    batch = models.ForeignKey(
        "institute_admin.Batch",
        on_delete=models.CASCADE,
        related_name="homework",
    )
    course = models.ForeignKey(
        "institute_admin.Course",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="homework",
    )
    subject = models.ForeignKey(
        "institute_admin.Subject",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="homework",
    )
    title = models.CharField(max_length=160)
    instructions = models.TextField(blank=True)
    due_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_homework",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["batch", "due_date", "-created_at"], name="hw_batch_due_idx"),
            models.Index(fields=["course", "due_date"], name="hw_course_due_idx"),
            models.Index(fields=["subject", "due_date"], name="hw_subject_due_idx"),
        ]

    def __str__(self):
        return self.title


class HomeworkAttachment(models.Model):
    homework = models.ForeignKey(Homework, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to="homework/attachments/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]
        indexes = [
            models.Index(fields=["homework", "-uploaded_at"], name="hw_attach_uploaded_idx"),
        ]

    def __str__(self):
        return self.file.name


class Exam(models.Model):
    academic_year = models.ForeignKey(
        "institute_admin.AcademicYear",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="exams",
    )
    batch = models.ForeignKey(
        "institute_admin.Batch",
        on_delete=models.CASCADE,
        related_name="exams",
    )
    course = models.ForeignKey(
        "institute_admin.Course",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="exams",
    )
    subject = models.ForeignKey(
        "institute_admin.Subject",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="exams",
    )
    title = models.CharField(max_length=160)
    exam_date = models.DateField()
    total_marks = models.PositiveIntegerField(default=100)
    duration_minutes = models.PositiveIntegerField(default=60)
    instructions = models.TextField(blank=True)
    allow_rough_work_uploads = models.BooleanField(default=True)
    is_published = models.BooleanField(default=False)
    show_result_after_submit = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_exams",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-exam_date"]
        indexes = [
            models.Index(fields=["academic_year", "batch", "-exam_date"], name="exam_year_batch_date_idx"),
            models.Index(fields=["batch", "-exam_date"], name="exam_batch_date_idx"),
        ]

    def __str__(self):
        return f"{self.title} - {self.batch}"

    def save(self, *args, **kwargs):
        if self.batch_id and not self.academic_year_id:
            self.academic_year = self.batch.academic_year
        super().save(*args, **kwargs)

    @property
    def question_marks_total(self):
        return sum(question.marks for question in self.questions.all())


class ExamQuestion(models.Model):
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="questions")
    text = models.TextField(blank=True)
    image = models.ImageField(upload_to="exams/questions/", blank=True)
    marks = models.PositiveIntegerField(default=1)
    order = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["order", "id"]
        indexes = [
            models.Index(fields=["exam", "order"], name="exam_question_order_idx"),
        ]

    def __str__(self):
        return f"{self.exam} - Question {self.order}"

    @property
    def correct_option(self):
        return self.options.filter(is_correct=True).first()


class ExamQuestionOption(models.Model):
    question = models.ForeignKey(ExamQuestion, on_delete=models.CASCADE, related_name="options")
    text = models.CharField(max_length=500)
    is_correct = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["order", "id"]
        indexes = [
            models.Index(fields=["question", "order"], name="exam_option_order_idx"),
        ]

    def __str__(self):
        return self.text


class ExamAttempt(models.Model):
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="attempts")
    academic_session = models.ForeignKey(
        "student_parent.StudentAcademicSession",
        on_delete=models.CASCADE,
        related_name="exam_attempts",
    )
    student = models.ForeignKey(
        "student_parent.StudentProfile",
        on_delete=models.CASCADE,
        related_name="exam_attempts",
    )
    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    score = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    total_marks = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    correct_count = models.PositiveIntegerField(default=0)
    wrong_count = models.PositiveIntegerField(default=0)
    unattempted_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-started_at"]
        unique_together = ["exam", "academic_session"]
        indexes = [
            models.Index(fields=["student", "-started_at"], name="exam_attempt_student_idx"),
            models.Index(fields=["exam", "submitted_at"], name="exam_attempt_submit_idx"),
        ]

    def __str__(self):
        return f"{self.student} - {self.exam}"

    @property
    def is_submitted(self):
        return self.submitted_at is not None


class ExamQuestionAttempt(models.Model):
    attempt = models.ForeignKey(ExamAttempt, on_delete=models.CASCADE, related_name="question_attempts")
    question = models.ForeignKey(ExamQuestion, on_delete=models.CASCADE, related_name="attempts")
    selected_option = models.ForeignKey(
        ExamQuestionOption,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="selected_attempts",
    )
    is_correct = models.BooleanField(default=False)
    marks_awarded = models.DecimalField(max_digits=7, decimal_places=2, default=0)

    class Meta:
        unique_together = ["attempt", "question"]
        indexes = [
            models.Index(fields=["attempt", "question"], name="exam_q_attempt_idx"),
        ]

    def __str__(self):
        return f"{self.attempt} - {self.question}"


class ExamAttemptUpload(models.Model):
    attempt = models.ForeignKey(ExamAttempt, on_delete=models.CASCADE, related_name="uploads")
    question = models.ForeignKey(
        ExamQuestion,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="rough_work_uploads",
    )
    image = models.ImageField(upload_to="exams/rough-work/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["question__order", "uploaded_at"]
        indexes = [
            models.Index(fields=["attempt", "question"], name="exam_upload_attempt_idx"),
        ]

    def __str__(self):
        return self.image.name


class ExamAttemptActivity(models.Model):
    attempt = models.ForeignKey(ExamAttempt, on_delete=models.CASCADE, related_name="activities")
    event_type = models.CharField(max_length=50)
    detail = models.CharField(max_length=255, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["occurred_at", "id"]
        indexes = [
            models.Index(fields=["attempt", "event_type"], name="exam_activity_type_idx"),
            models.Index(fields=["attempt", "occurred_at"], name="exam_activity_time_idx"),
        ]

    def __str__(self):
        return f"{self.attempt} - {self.event_type}"


class ExamResult(models.Model):
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="results")
    student = models.ForeignKey(
        "student_parent.StudentProfile",
        on_delete=models.CASCADE,
        related_name="exam_results",
    )
    marks_obtained = models.DecimalField(max_digits=6, decimal_places=2)
    remark = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["exam", "student__user__first_name", "student__user__username"]
        unique_together = ["exam", "student"]
        indexes = [
            models.Index(fields=["student"], name="exam_result_student_idx"),
        ]

    def __str__(self):
        return f"{self.student} - {self.exam}"
