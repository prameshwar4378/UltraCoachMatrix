from django.conf import settings
from django.core.checks import Error, Warning, register


@register()
def email_configuration_check(app_configs, **kwargs):
    if settings.EMAIL_BACKEND != "django.core.mail.backends.smtp.EmailBackend":
        return []

    errors = []
    if not settings.EMAIL_HOST_USER:
        errors.append(
            Error(
                "EMAIL_HOST_USER is not configured.",
                id="ultracoachmatrix.E001",
            )
        )
    if not settings.EMAIL_HOST_PASSWORD:
        errors.append(
            Error(
                "EMAIL_HOST_PASSWORD is not configured.",
                id="ultracoachmatrix.E002",
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
                id="ultracoachmatrix.E003",
            )
        )
    return errors
