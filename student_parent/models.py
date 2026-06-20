from django.contrib.auth.models import User
from django.db import models


class StudentProfile(models.Model):
    class Gender(models.TextChoices):
        MALE = "MALE", "Male"
        FEMALE = "FEMALE", "Female"
        OTHER = "OTHER", "Other"

    class StudentStatus(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"
        TC_ISSUED = "TC_ISSUED", "TC Issued"
        LEFT_SCHOOL = "LEFT_SCHOOL", "Left School"
        PASSED_OUT = "PASSED_OUT", "Passed Out"

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
    pen_no = models.CharField("PEN No", max_length=80, blank=True)
    appar_id = models.CharField("Appar ID", max_length=80, blank=True)
    gr_number_udise = models.CharField("GR Number", max_length=80, blank=True)
    udise_number = models.CharField("UDISE Number", max_length=80, blank=True)
    roll_number = models.CharField(max_length=40, blank=True)
    middle_name = models.CharField(max_length=150, blank=True)
    gender = models.CharField(max_length=20, choices=Gender.choices, blank=True)
    profile_image = models.ImageField(upload_to="students/profile_images/", blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    blood_group = models.CharField(max_length=10, blank=True)
    religion = models.CharField(max_length=80, blank=True)
    cast = models.CharField("Cast", max_length=80, blank=True)
    caste_category = models.CharField(max_length=40, blank=True)
    nationality = models.CharField(max_length=80, blank=True)
    aadhaar_number = models.CharField(max_length=20, blank=True)
    birth_certificate_number = models.CharField(max_length=80, blank=True)
    place_of_birth = models.CharField(max_length=120, blank=True)
    mother_tongue = models.CharField(max_length=80, blank=True)
    father_name = models.CharField(max_length=160, blank=True)
    father_occupation = models.CharField(max_length=120, blank=True)
    father_qualification = models.CharField(max_length=120, blank=True)
    father_mobile_number = models.CharField(max_length=20, blank=True)
    father_email = models.EmailField(blank=True)
    father_aadhaar_number = models.CharField(max_length=20, blank=True)
    father_annual_income = models.CharField(max_length=40, blank=True)
    mother_name = models.CharField(max_length=160, blank=True)
    mother_occupation = models.CharField(max_length=120, blank=True)
    mother_qualification = models.CharField(max_length=120, blank=True)
    mother_mobile_number = models.CharField(max_length=20, blank=True)
    mother_aadhaar_number = models.CharField(max_length=20, blank=True)
    mother_annual_income = models.CharField(max_length=40, blank=True)
    guardian_address = models.TextField(blank=True)
    current_house_number = models.CharField(max_length=80, blank=True)
    current_street_area = models.CharField(max_length=160, blank=True)
    current_village_city = models.CharField(max_length=120, blank=True)
    current_taluka = models.CharField(max_length=120, blank=True)
    current_district = models.CharField(max_length=120, blank=True)
    current_state = models.CharField(max_length=120, blank=True)
    current_pin_code = models.CharField(max_length=12, blank=True)
    permanent_house_number = models.CharField(max_length=80, blank=True)
    permanent_street_area = models.CharField(max_length=160, blank=True)
    permanent_village_city = models.CharField(max_length=120, blank=True)
    permanent_taluka = models.CharField(max_length=120, blank=True)
    permanent_district = models.CharField(max_length=120, blank=True)
    permanent_state = models.CharField(max_length=120, blank=True)
    permanent_pin_code = models.CharField(max_length=12, blank=True)
    joined_on = models.DateField(null=True, blank=True)
    address = models.TextField(blank=True)
    admission_class = models.CharField(max_length=80, blank=True)
    current_class = models.CharField(max_length=80, blank=True)
    division = models.CharField(max_length=40, blank=True)
    medium = models.CharField(max_length=40, blank=True)
    current_school_name = models.CharField(max_length=160, blank=True)
    current_school_address = models.TextField(blank=True)
    previous_school_name = models.CharField(max_length=160, blank=True)
    previous_school_address = models.TextField(blank=True)
    previous_school_udise_code = models.CharField(max_length=80, blank=True)
    previous_class = models.CharField(max_length=80, blank=True)
    previous_class_passed = models.CharField(max_length=80, blank=True)
    last_exam_result = models.CharField(max_length=80, blank=True)
    result = models.CharField(max_length=40, blank=True)
    conduct = models.CharField(max_length=120, blank=True)
    reason_for_leaving = models.CharField(max_length=255, blank=True)
    date_of_leaving_school = models.DateField(null=True, blank=True)
    tc_issue_date = models.DateField(null=True, blank=True)
    bonafide_purpose = models.CharField(max_length=255, blank=True)
    emergency_contact_number = models.CharField(max_length=20, blank=True)
    student_status = models.CharField(
        max_length=20,
        choices=StudentStatus.choices,
        default=StudentStatus.ACTIVE,
    )
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
            models.Index(
                fields=["institute", "academic_year", "status", "admission_number"],
                name="sas_scope_status_adm_idx",
            ),
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


class StudentTransferCertificate(models.Model):
    class Status(models.TextChoices):
        GENERATED = "GENERATED", "Generated"
        CANCELLED = "CANCELLED", "Cancelled"

    institute = models.ForeignKey(
        "super_admin.Institute",
        on_delete=models.CASCADE,
        related_name="student_transfer_certificates",
    )
    student = models.ForeignKey(
        StudentProfile,
        on_delete=models.CASCADE,
        related_name="transfer_certificates",
    )
    academic_session = models.ForeignKey(
        StudentAcademicSession,
        on_delete=models.PROTECT,
        related_name="transfer_certificates",
    )
    tc_number = models.CharField(max_length=60)
    issue_date = models.DateField()
    leaving_date = models.DateField()
    reason_for_leaving = models.CharField(max_length=255)
    conduct = models.CharField(max_length=120)
    result = models.CharField(max_length=80, blank=True)
    last_class_attended = models.CharField(max_length=80)
    qualified_for_promotion = models.BooleanField(default=False)
    fees_cleared = models.BooleanField(default=False)
    remarks = models.CharField(max_length=255, blank=True)
    student_snapshot = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.GENERATED)
    generated_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="generated_transfer_certificates",
    )
    generated_at = models.DateTimeField(auto_now_add=True)
    cancelled_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cancelled_transfer_certificates",
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-generated_at", "-pk"]
        unique_together = ["institute", "tc_number"]
        indexes = [
            models.Index(fields=["student", "status", "-generated_at"], name="stc_student_status_idx"),
            models.Index(fields=["institute", "tc_number"], name="stc_inst_tc_idx"),
        ]

    def __str__(self):
        return f"{self.tc_number} - {self.student}"


class StudentBonafideCertificate(models.Model):
    class Status(models.TextChoices):
        GENERATED = "GENERATED", "Generated"
        CANCELLED = "CANCELLED", "Cancelled"

    institute = models.ForeignKey(
        "super_admin.Institute",
        on_delete=models.CASCADE,
        related_name="student_bonafide_certificates",
    )
    student = models.ForeignKey(
        StudentProfile,
        on_delete=models.CASCADE,
        related_name="bonafide_certificates",
    )
    academic_session = models.ForeignKey(
        StudentAcademicSession,
        on_delete=models.PROTECT,
        related_name="bonafide_certificates",
    )
    certificate_number = models.CharField(max_length=60)
    issue_date = models.DateField()
    purpose = models.CharField(max_length=255)
    remarks = models.CharField(max_length=255, blank=True)
    student_snapshot = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.GENERATED)
    generated_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="generated_bonafide_certificates",
    )
    generated_at = models.DateTimeField(auto_now_add=True)
    cancelled_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cancelled_bonafide_certificates",
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-generated_at", "-pk"]
        unique_together = ["institute", "certificate_number"]
        indexes = [
            models.Index(fields=["student", "status", "-generated_at"], name="sbc_student_status_idx"),
            models.Index(fields=["institute", "certificate_number"], name="sbc_inst_cert_idx"),
        ]

    def __str__(self):
        return f"{self.certificate_number} - {self.student}"


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
        STUDENT_PHOTO = "STUDENT_PHOTO", "Student Photo"
        BIRTH_CERTIFICATE = "BIRTH_CERTIFICATE", "Birth Certificate"
        AADHAAR = "AADHAAR", "Aadhaar"
        PARENT_AADHAAR = "PARENT_AADHAAR", "Parent Aadhaar"
        CASTE_CERTIFICATE = "CASTE_CERTIFICATE", "Caste Certificate"
        INCOME_CERTIFICATE = "INCOME_CERTIFICATE", "Income Certificate"
        PROFILE = "PROFILE", "Profile"
        TRANSFER_CERTIFICATE = "TRANSFER_CERTIFICATE", "Transfer Certificate"
        LEAVING_CERTIFICATE = "LEAVING_CERTIFICATE", "Leaving Certificate"
        BONAFIDE_CERTIFICATE = "BONAFIDE_CERTIFICATE", "Bonafide Certificate"
        ADDRESS_PROOF = "ADDRESS_PROOF", "Address Proof"
        MARKSHEET = "MARKSHEET", "Marksheet"
        PASSPORT_PHOTOS = "PASSPORT_PHOTOS", "Passport Size Photos"
        DISABILITY_CERTIFICATE = "DISABILITY_CERTIFICATE", "Disability Certificate"
        MIGRATION_CERTIFICATE = "MIGRATION_CERTIFICATE", "Migration Certificate"
        RTE_DOCUMENTS = "RTE_DOCUMENTS", "RTE Documents"
        BANK_PASSBOOK = "BANK_PASSBOOK", "Bank Passbook"
        VACCINATION_RECORD = "VACCINATION_RECORD", "Vaccination Record"
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
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"], name="push_user_created_idx"),
            models.Index(fields=["user", "status", "-created_at"], name="push_user_status_idx"),
            models.Index(fields=["user", "read_at", "-created_at"], name="push_user_read_idx"),
        ]

    def __str__(self):
        return f"{self.user} - {self.notification_type} - {self.status}"
