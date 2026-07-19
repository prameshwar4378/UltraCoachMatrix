from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from .media_utils import institute_logo_upload_path


class Institute(models.Model):
    class InstituteType(models.TextChoices):
        COACHING_CLASSES = "COACHING_CLASSES", "Coaching Classes"
        SCHOOL = "SCHOOL", "School"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending approval"
        TRIAL = "TRIAL", "Trial"
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"
        EXPIRED = "EXPIRED", "Expired"
        CANCELLED = "CANCELLED", "Cancelled"

    name = models.CharField(max_length=160)
    code = models.SlugField(max_length=40, unique=True)
    institute_type = models.CharField(
        max_length=20,
        choices=InstituteType.choices,
        default=InstituteType.COACHING_CLASSES,
    )
    owner_name = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    logo = models.ImageField(upload_to=institute_logo_upload_path, blank=True)
    address = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.TRIAL,
        help_text="Use Active or Trial to allow access. Suspended and Cancelled block access.",
    )
    internal_notes = models.TextField(blank=True)
    left_school_login_active = models.BooleanField(
        default=True,
        help_text="Keep student/parent login active when student status is Left School.",
    )
    passed_out_login_active = models.BooleanField(
        default=True,
        help_text="Keep student/parent login active when student status is Passed Out.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Institute account"
        verbose_name_plural = "Institute accounts"

    def __str__(self):
        return self.name


class InstituteSubscription(models.Model):
    class Plan(models.TextChoices):
        FREE_TRIAL = "FREE_TRIAL", "Free Trial"
        PREMIUM = "PREMIUM", "Premium"

    institute = models.OneToOneField(
        Institute,
        on_delete=models.CASCADE,
        related_name="subscription",
    )
    plan = models.CharField(
        max_length=20,
        choices=Plan.choices,
        default=Plan.FREE_TRIAL,
        help_text="Choose Free Trial for trial access or Premium for paid access.",
    )
    starts_on = models.DateField(
        null=True,
        blank=True,
        verbose_name="Access start date",
        help_text="The school can use the software from this date.",
    )
    ends_on = models.DateField(
        null=True,
        blank=True,
        verbose_name="Access expiry date",
        help_text="Access is blocked automatically after this date.",
    )
    notes = models.TextField(
        blank=True,
        help_text="Optional internal notes about renewal or subscription.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["institute__name"]
        verbose_name = "Software subscription"
        verbose_name_plural = "Software subscriptions"

    def __str__(self):
        return f"{self.institute} - {self.get_plan_display()}"

    def clean(self):
        super().clean()
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValidationError({"ends_on": "Expiry date cannot be before the start date."})

    @property
    def expiry_date(self):
        return self.ends_on

    @property
    def is_expired(self):
        return bool(self.expiry_date and self.expiry_date < timezone.localdate())

    @property
    def is_active(self):
        today = timezone.localdate()
        return (
            (not self.starts_on or self.starts_on <= today)
            and (not self.ends_on or self.ends_on >= today)
        )


class SubscriptionPayment(models.Model):
    class Method(models.TextChoices):
        CASH = "CASH", "Cash"
        UPI = "UPI", "UPI"
        CARD = "CARD", "Card"
        BANK_TRANSFER = "BANK_TRANSFER", "Bank transfer"
        OTHER = "OTHER", "Other"

    institute = models.ForeignKey(
        Institute,
        on_delete=models.CASCADE,
        related_name="subscription_payments",
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    paid_on = models.DateField(default=timezone.localdate)
    method = models.CharField(max_length=30, choices=Method.choices)
    transaction_id = models.CharField(max_length=120, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-paid_on", "-pk"]
        verbose_name = "Subscription payment"
        verbose_name_plural = "Subscription payment history"

    def __str__(self):
        return f"{self.institute} - {self.amount}"


class UserProfile(models.Model):
    class Role(models.TextChoices):
        SUPER_ADMIN = "SUPER_ADMIN", "Super Admin"
        INSTITUTE_ADMIN = "INSTITUTE_ADMIN", "Institute Admin"
        TEACHER = "TEACHER", "Teacher"
        ACCOUNTANT = "ACCOUNTANT", "Accountant"
        STUDENT_PARENT = "STUDENT_PARENT", "Student/Parent"
        UCM_PARTNER = "UCM_PARTNER", "UCM Partner"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    institute = models.ForeignKey(
        Institute,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="user_profiles",
    )
    role = models.CharField(max_length=30, choices=Role.choices)
    phone = models.CharField(max_length=20, blank=True)
    onboarding_completed_at = models.DateTimeField(default=timezone.now, null=True, blank=True)

    class Meta:
        ordering = ["user__username"]
        indexes = [
            models.Index(fields=["institute", "role"], name="profile_inst_role_idx"),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.get_role_display()}"


class InstituteRegistration(UserProfile):
    class Meta:
        proxy = True
        verbose_name = "Institute registration"
        verbose_name_plural = "Institute registrations"


class MobileRefreshToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="mobile_refresh_tokens")
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username} mobile refresh token"

    @property
    def is_active(self):
        return self.revoked_at is None and self.expires_at > timezone.now()
