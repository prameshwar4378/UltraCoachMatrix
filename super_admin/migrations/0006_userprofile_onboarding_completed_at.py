import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("super_admin", "0005_instituteregistration"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="onboarding_completed_at",
            field=models.DateTimeField(
                blank=True,
                default=django.utils.timezone.now,
                null=True,
            ),
        ),
    ]
