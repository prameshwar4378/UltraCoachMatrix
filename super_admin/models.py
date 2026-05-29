from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class Institute(models.Model):
    class Status(models.TextChoices):
        TRIAL = "TRIAL", "Trial"
        ACTIVE = "ACTIVE", "Active"
        SUSPENDED = "SUSPENDED", "Suspended"

    name = models.CharField(max_length=160)
    code = models.SlugField(max_length=40, unique=True)
    owner_name = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TRIAL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class SubscriptionPlan(models.Model):
    name = models.CharField(max_length=80)
    monthly_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    max_students = models.PositiveIntegerField(default=100)
    max_teachers = models.PositiveIntegerField(default=10)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["monthly_price", "name"]

    def __str__(self):
        return self.name


class InstituteSubscription(models.Model):
    class Status(models.TextChoices):
        TRIAL = "TRIAL", "Trial"
        ACTIVE = "ACTIVE", "Active"
        EXPIRED = "EXPIRED", "Expired"
        CANCELLED = "CANCELLED", "Cancelled"

    institute = models.OneToOneField(
        Institute,
        on_delete=models.CASCADE,
        related_name="subscription",
    )
    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.PROTECT,
        related_name="subscriptions",
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TRIAL)
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["institute__name"]

    def __str__(self):
        return f"{self.institute} - {self.plan}"


class UserProfile(models.Model):
    class Role(models.TextChoices):
        SUPER_ADMIN = "SUPER_ADMIN", "Super Admin"
        INSTITUTE_ADMIN = "INSTITUTE_ADMIN", "Institute Admin"
        TEACHER = "TEACHER", "Teacher"
        ACCOUNTANT = "ACCOUNTANT", "Accountant"
        STUDENT_PARENT = "STUDENT_PARENT", "Student/Parent"

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

    class Meta:
        ordering = ["user__username"]

    def __str__(self):
        return f"{self.user.username} - {self.get_role_display()}"


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
