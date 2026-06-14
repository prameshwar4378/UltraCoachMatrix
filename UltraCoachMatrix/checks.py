from django.conf import settings
from django.core.checks import Warning, register


@register()
def email_configuration_check(app_configs, **kwargs):
    if settings.EMAIL_BACKEND != "django.core.mail.backends.smtp.EmailBackend":
        return []

    errors = []
    if not settings.EMAIL_HOST_USER:
        errors.append(
            Warning(
                "EMAIL_HOST_USER is not configured.",
                hint="Configure SMTP environment variables before sending email.",
                id="ultracoachmatrix.W001",
            )
        )
    if not settings.EMAIL_HOST_PASSWORD:
        errors.append(
            Warning(
                "EMAIL_HOST_PASSWORD is not configured.",
                hint="Configure SMTP environment variables before sending email.",
                id="ultracoachmatrix.W002",
            )
        )
    if (
        settings.EMAIL_HOST == "smtp.gmail.com"
        and settings.EMAIL_HOST_PASSWORD
        and len(settings.EMAIL_HOST_PASSWORD.replace(" ", "")) != 16
    ):
        errors.append(
            Warning(
                "The Gmail app password must contain exactly 16 characters.",
                hint="Generate a new Google app password and copy all four groups of four characters.",
                id="ultracoachmatrix.W003",
            )
        )
    return errors
