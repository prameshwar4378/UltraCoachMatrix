import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("institute_admin", "0009_batch_weekly_timetable"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Enquiry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("phone", models.CharField(max_length=20)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("source", models.CharField(choices=[("WALK_IN", "Walk In"), ("PHONE", "Phone"), ("WEBSITE", "Website"), ("REFERRAL", "Referral"), ("OTHER", "Other")], default="WALK_IN", max_length=20)),
                ("status", models.CharField(choices=[("NEW", "New"), ("CONTACTED", "Contacted"), ("FOLLOW_UP", "Follow Up"), ("CONVERTED", "Converted"), ("CLOSED", "Closed")], default="NEW", max_length=20)),
                ("follow_up_on", models.DateField(blank=True, null=True)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_enquiries", to=settings.AUTH_USER_MODEL)),
                ("institute", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="enquiries", to="super_admin.institute")),
                ("interested_course", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="enquiries", to="institute_admin.course")),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [models.Index(fields=["institute", "status", "-created_at"], name="enquiry_inst_status_idx")],
            },
        ),
    ]
