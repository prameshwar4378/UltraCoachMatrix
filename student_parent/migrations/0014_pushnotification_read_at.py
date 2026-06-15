from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("student_parent", "0013_studentacademicsession_sas_scope_status_adm_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="pushnotification",
            name="read_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name="pushnotification",
            index=models.Index(
                fields=["user", "read_at", "-created_at"],
                name="push_user_read_idx",
            ),
        ),
    ]
