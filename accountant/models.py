from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class FeeCategory(models.Model):
    institute = models.ForeignKey(
        "super_admin.Institute",
        on_delete=models.CASCADE,
        related_name="fee_categories",
    )
    name = models.CharField(max_length=120)
    default_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        unique_together = ["institute", "name"]

    def __str__(self):
        return self.name


class FeeInvoice(models.Model):
    class Status(models.TextChoices):
        UNPAID = "UNPAID", "Unpaid"
        PARTIAL = "PARTIAL", "Partial"
        PAID = "PAID", "Paid"
        CANCELLED = "CANCELLED", "Cancelled"

    institute = models.ForeignKey(
        "super_admin.Institute",
        on_delete=models.CASCADE,
        related_name="fee_invoices",
    )
    student = models.ForeignKey(
        "student_parent.StudentProfile",
        on_delete=models.CASCADE,
        related_name="fee_invoices",
    )
    academic_session = models.ForeignKey(
        "student_parent.StudentAcademicSession",
        on_delete=models.CASCADE,
        related_name="fee_invoices",
    )
    enrollment = models.ForeignKey(
        "student_parent.StudentEnrollment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fee_invoices",
    )
    course = models.ForeignKey(
        "institute_admin.Course",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fee_invoices",
    )
    batch = models.ForeignKey(
        "institute_admin.Batch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fee_invoices",
    )
    category = models.ForeignKey(
        FeeCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices",
    )
    title = models.CharField(max_length=120)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    due_date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UNPAID)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-due_date"]

    def __str__(self):
        return f"{self.student} - {self.title}"

    def save(self, *args, **kwargs):
        if self.academic_session_id:
            self.student = self.academic_session.student
            self.institute = self.academic_session.institute
        if self.enrollment_id and self.enrollment.academic_session_id != self.academic_session_id:
            self.academic_session = self.enrollment.academic_session
            self.student = self.academic_session.student
            self.institute = self.academic_session.institute
        super().save(*args, **kwargs)


class Payment(models.Model):
    class Method(models.TextChoices):
        CASH = "CASH", "Cash"
        UPI = "UPI", "UPI"
        CARD = "CARD", "Card"
        BANK_TRANSFER = "BANK_TRANSFER", "Bank Transfer"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        VOIDED = "VOIDED", "Voided"

    invoice = models.ForeignKey(FeeInvoice, on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    paid_on = models.DateField()
    method = models.CharField(max_length=30, choices=Method.choices, default=Method.CASH)
    received_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="received_payments",
    )
    receipt_number = models.CharField(max_length=60, blank=True)
    note = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(default=timezone.now)
    voided_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="voided_payments",
    )
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-paid_on"]

    def __str__(self):
        return f"{self.invoice} - {self.amount}"

    def void(self, user, reason):
        self.status = self.Status.VOIDED
        self.voided_by = user
        self.voided_at = timezone.now()
        self.void_reason = reason
        self.save(update_fields=["status", "voided_by", "voided_at", "void_reason"])


class PaymentActivity(models.Model):
    class Action(models.TextChoices):
        CREATED = "CREATED", "Created"
        UPDATED = "UPDATED", "Updated"
        VOIDED = "VOIDED", "Voided"

    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name="activities")
    action = models.CharField(max_length=20, choices=Action.choices)
    performed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payment_activities",
    )
    performed_at = models.DateTimeField(auto_now_add=True)
    old_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    new_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    old_method = models.CharField(max_length=30, blank=True)
    new_method = models.CharField(max_length=30, blank=True)
    old_receipt_number = models.CharField(max_length=60, blank=True)
    new_receipt_number = models.CharField(max_length=60, blank=True)
    note = models.CharField(max_length=255)

    class Meta:
        ordering = ["-performed_at"]

    def __str__(self):
        return f"{self.payment} - {self.get_action_display()}"


class Expense(models.Model):
    institute = models.ForeignKey(
        "super_admin.Institute",
        on_delete=models.CASCADE,
        related_name="expenses",
    )
    title = models.CharField(max_length=160)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    spent_on = models.DateField()
    recorded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_expenses",
    )
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-spent_on"]

    def __str__(self):
        return f"{self.title} - {self.amount}"
