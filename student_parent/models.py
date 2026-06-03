from django.contrib.auth.models import User
from django.db import models


class StudentProfile(models.Model):
    institute = models.ForeignKey(
        "super_admin.Institute",
        on_delete=models.CASCADE,
        related_name="students",
    )
    academic_year = models.ForeignKey(
        "institute_admin.AcademicYear",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="students",
    )
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="student_profile")
    admission_number = models.CharField(max_length=40)
    profile_image = models.ImageField(upload_to="students/profile_images/", blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    joined_on = models.DateField(null=True, blank=True)
    address = models.TextField(blank=True)
    current_school_name = models.CharField(max_length=160, blank=True)
    current_school_address = models.TextField(blank=True)
    previous_school_name = models.CharField(max_length=160, blank=True)
    previous_class = models.CharField(max_length=80, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["admission_number"]
        unique_together = ["institute", "academic_year", "admission_number"]
        indexes = [
            models.Index(fields=["institute", "academic_year", "is_active"], name="sp_inst_year_active_idx"),
            models.Index(fields=["institute", "admission_number"], name="sp_inst_adm_idx"),
        ]

    def __str__(self):
        name = self.user.get_full_name() or self.user.username
        return f"{self.admission_number} - {name}"


class StudentAcademicSession(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        COMPLETED = "COMPLETED", "Completed"
        LEFT = "LEFT", "Left"
        CANCELLED = "CANCELLED", "Cancelled"

    institute = models.ForeignKey(
        "super_admin.Institute",
        on_delete=models.CASCADE,
        related_name="student_academic_sessions",
    )
    student = models.ForeignKey(
        StudentProfile,
        on_delete=models.CASCADE,
        related_name="academic_sessions",
    )
    academic_year = models.ForeignKey(
        "institute_admin.AcademicYear",
        on_delete=models.PROTECT,
        related_name="student_sessions",
    )
    admission_number = models.CharField(max_length=40)
    joined_on = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    current_school_name = models.CharField(max_length=160, blank=True)
    current_school_address = models.TextField(blank=True)
    previous_school_name = models.CharField(max_length=160, blank=True)
    previous_class = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ["academic_year__name", "admission_number"]
        unique_together = [
            ["institute", "academic_year", "admission_number"],
            ["student", "academic_year"],
        ]
        indexes = [
            models.Index(fields=["student", "status"], name="sas_student_status_idx"),
            models.Index(fields=["institute", "academic_year", "status"], name="sas_inst_year_status_idx"),
        ]

    def __str__(self):
        return f"{self.admission_number} - {self.student} - {self.academic_year.name}"


class StudentEnrollment(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    student = models.ForeignKey(
        StudentProfile,
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    academic_session = models.ForeignKey(
        StudentAcademicSession,
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    batch = models.ForeignKey(
        "institute_admin.Batch",
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    courses = models.ManyToManyField(
        "institute_admin.Course",
        blank=True,
        related_name="student_enrollments",
    )
    enrolled_on = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    custom_fee_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["academic_session__admission_number", "batch__name"]
        unique_together = ["academic_session", "batch"]
        indexes = [
            models.Index(fields=["student", "status"], name="se_student_status_idx"),
            models.Index(fields=["academic_session", "status"], name="se_session_status_idx"),
            models.Index(fields=["batch", "status"], name="se_batch_status_idx"),
        ]

    def __str__(self):
        return f"{self.student} - {self.batch}"

    def save(self, *args, **kwargs):
        if self.academic_session_id:
            self.student = self.academic_session.student
        super().save(*args, **kwargs)

    @property
    def total_course_fee(self):
        if self.custom_fee_amount is not None:
            return self.custom_fee_amount
        return sum(course.fee_amount for course in self.courses.all())


class GuardianProfile(models.Model):
    student = models.ForeignKey(
        StudentProfile,
        on_delete=models.CASCADE,
        related_name="guardians",
    )
    name = models.CharField(max_length=120)
    relation = models.CharField(max_length=60, blank=True)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    is_primary = models.BooleanField(default=True)

    class Meta:
        ordering = ["student__admission_number", "name"]
        indexes = [
            models.Index(fields=["student", "is_primary"], name="guardian_primary_idx"),
        ]

    def __str__(self):
        return f"{self.name} - {self.student}"


class StudentDocument(models.Model):
    class DocumentType(models.TextChoices):
        AADHAAR = "AADHAAR", "Aadhaar"
        PROFILE = "PROFILE", "Profile"
        TRANSFER_CERTIFICATE = "TRANSFER_CERTIFICATE", "Transfer Certificate"
        MARKSHEET = "MARKSHEET", "Marksheet"
        OTHER = "OTHER", "Other"

    student = models.ForeignKey(
        StudentProfile,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    document_type = models.CharField(max_length=40, choices=DocumentType.choices, default=DocumentType.OTHER)
    title = models.CharField(max_length=120)
    file = models.FileField(upload_to="students/documents/")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-uploaded_at"]
        indexes = [
            models.Index(fields=["student", "-uploaded_at"], name="stud_doc_uploaded_idx"),
        ]

    def __str__(self):
        return f"{self.student} - {self.title}"


class UserDevice(models.Model):
    class Platform(models.TextChoices):
        ANDROID = "ANDROID", "Android"
        IOS = "IOS", "iOS"
        WEB = "WEB", "Web"
        DESKTOP = "DESKTOP", "Desktop"
        UNKNOWN = "UNKNOWN", "Unknown"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="devices")
    token = models.CharField(max_length=512, unique=True)
    platform = models.CharField(max_length=20, choices=Platform.choices, default=Platform.UNKNOWN)
    device_id = models.CharField(max_length=120, blank=True)
    app_version = models.CharField(max_length=40, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_seen_at"]
        indexes = [
            models.Index(fields=["user", "is_active", "-last_seen_at"], name="device_user_active_idx"),
        ]

    def __str__(self):
        return f"{self.user} - {self.platform}"


class PushNotification(models.Model):
    class NotificationType(models.TextChoices):
        FEE_PAID = "FEE_PAID", "Fee Paid"
        RESULT_DECLARED = "RESULT_DECLARED", "Result Declared"
        NOTICE = "NOTICE", "Notice"
        CUSTOM = "CUSTOM", "Custom"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        SENT = "SENT", "Sent"
        SKIPPED = "SKIPPED", "Skipped"
        FAILED = "FAILED", "Failed"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="push_notifications")
    notification_type = models.CharField(max_length=30, choices=NotificationType.choices)
    title = models.CharField(max_length=160)
    body = models.TextField()
    data = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    firebase_message_id = models.CharField(max_length=255, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"], name="push_user_created_idx"),
            models.Index(fields=["user", "status", "-created_at"], name="push_user_status_idx"),
        ]

    def __str__(self):
        return f"{self.user} - {self.notification_type} - {self.status}"
