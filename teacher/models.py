from django.contrib.auth.models import User
from django.db import models


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
    batch = models.ForeignKey(
        "institute_admin.Batch",
        on_delete=models.CASCADE,
        related_name="exams",
    )
    title = models.CharField(max_length=160)
    exam_date = models.DateField()
    total_marks = models.PositiveIntegerField(default=100)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_exams",
    )

    class Meta:
        ordering = ["-exam_date"]
        indexes = [
            models.Index(fields=["batch", "-exam_date"], name="exam_batch_date_idx"),
        ]

    def __str__(self):
        return f"{self.title} - {self.batch}"


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
