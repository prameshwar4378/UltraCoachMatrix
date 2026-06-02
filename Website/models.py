from django.db import models

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
