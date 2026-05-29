from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("student_parent", "0010_alter_studentenrollment_options"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="UserDevice",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token", models.CharField(max_length=512, unique=True)),
                (
                    "platform",
                    models.CharField(
                        choices=[
                            ("ANDROID", "Android"),
                            ("IOS", "iOS"),
                            ("WEB", "Web"),
                            ("DESKTOP", "Desktop"),
                            ("UNKNOWN", "Unknown"),
                        ],
                        default="UNKNOWN",
                        max_length=20,
                    ),
                ),
                ("device_id", models.CharField(blank=True, max_length=120)),
                ("app_version", models.CharField(blank=True, max_length=40)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("last_seen_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="devices", to=settings.AUTH_USER_MODEL),
                ),
            ],
            options={
                "ordering": ["-last_seen_at"],
            },
        ),
        migrations.CreateModel(
            name="PushNotification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "notification_type",
                    models.CharField(
                        choices=[
                            ("FEE_PAID", "Fee Paid"),
                            ("RESULT_DECLARED", "Result Declared"),
                            ("NOTICE", "Notice"),
                            ("CUSTOM", "Custom"),
                        ],
                        max_length=30,
                    ),
                ),
                ("title", models.CharField(max_length=160)),
                ("body", models.TextField()),
                ("data", models.JSONField(blank=True, default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PENDING", "Pending"),
                            ("SENT", "Sent"),
                            ("SKIPPED", "Skipped"),
                            ("FAILED", "Failed"),
                        ],
                        default="PENDING",
                        max_length=20,
                    ),
                ),
                ("firebase_message_id", models.CharField(blank=True, max_length=255)),
                ("error_message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                (
                    "user",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="push_notifications", to=settings.AUTH_USER_MODEL),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
