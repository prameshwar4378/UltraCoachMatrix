from django.db import models
from django.core.validators import MaxValueValidator, MinValueValidator

class ContactEnquiry(models.Model):
    ENQUIRY_TYPE_CHOICES = (
        ("demo", "Book product demo"),
        ("pricing", "Pricing and plan details"),
        ("implementation", "Implementation support"),
        ("technical", "Technical support"),
        ("enterprise", "Enterprise or partnership query"),
    )

    INSTITUTION_SIZE_CHOICES = (
        ("1-25", "Up to 100 students"),
        ("26-75", "100-500 students"),
        ("76-150", "500-1000 students"),
        ("150+", "1000+ students"),
    )

    STATUS_CHOICES = (
        ("new", "New"),
        ("contacted", "Contacted"),
        ("in_progress", "In progress"),
        ("closed", "Closed"),
    )

    name = models.CharField(max_length=120)
    school = models.CharField("School or institute", max_length=180)
    phone = models.CharField(max_length=30)
    email = models.EmailField()
    enquiry_type = models.CharField(max_length=30, choices=ENQUIRY_TYPE_CHOICES)
    institution_size = models.CharField(max_length=20, choices=INSTITUTION_SIZE_CHOICES, blank=True)
    message = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="new")
    admin_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Contact enquiry"
        verbose_name_plural = "Contact enquiries"

    def __str__(self):
        return f"{self.name} - {self.school}"


class WebsiteFeedback(models.Model):
    name = models.CharField(max_length=120)
    institute = models.CharField("School or institute", max_length=180, blank=True)
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    feedback = models.TextField(max_length=1000)
    is_visible = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Website feedback"
        verbose_name_plural = "Website feedback"

    def __str__(self):
        return f"{self.name} - {self.rating} stars"

    @property
    def filled_star_range(self):
        return range(self.rating)

    @property
    def empty_star_range(self):
        return range(5 - self.rating)


class CareerApplication(models.Model):
    ROLE_CHOICES = (
        ("sales_executive", "Sales Executive"),
    )

    EXPERIENCE_CHOICES = (
        ("fresher", "Fresher"),
        ("0-1", "0-1 year"),
        ("1-3", "1-3 years"),
        ("3-5", "3-5 years"),
        ("5+", "5+ years"),
    )

    STATUS_CHOICES = (
        ("new", "New"),
        ("reviewing", "Reviewing"),
        ("shortlisted", "Shortlisted"),
        ("rejected", "Rejected"),
        ("hired", "Hired"),
    )

    full_name = models.CharField(max_length=140)
    email = models.EmailField()
    phone = models.CharField(max_length=30)
    role = models.CharField(max_length=40, choices=ROLE_CHOICES)
    experience = models.CharField(max_length=20, choices=EXPERIENCE_CHOICES)
    qualification = models.CharField(max_length=160)
    city = models.CharField(max_length=100)
    notice_period = models.CharField(max_length=80, blank=True)
    resume = models.FileField(upload_to="career_resumes/", default="")
    portfolio_link = models.URLField(blank=True)
    cover_letter = models.TextField(max_length=1500, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="new")
    admin_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Career application"
        verbose_name_plural = "Career applications"

    def __str__(self):
        return f"{self.full_name} - {self.get_role_display()}"
