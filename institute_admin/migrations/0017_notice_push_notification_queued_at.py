from django.db import migrations, models


def mark_existing_immediate_notices_as_queued(apps, schema_editor):
    Notice = apps.get_model("institute_admin", "Notice")
    Notice.objects.filter(publish_at__isnull=True).update(
        push_notification_queued_at=models.F("created_at")
    )


class Migration(migrations.Migration):

    dependencies = [
        ("institute_admin", "0016_backgroundjob"),
    ]

    operations = [
        migrations.AddField(
            model_name="notice",
            name="push_notification_queued_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(
            mark_existing_immediate_notices_as_queued,
            migrations.RunPython.noop,
        ),
        migrations.AddIndex(
            model_name="notice",
            index=models.Index(
                fields=[
                    "is_published",
                    "push_to_app",
                    "push_notification_queued_at",
                    "publish_at",
                ],
                name="notice_push_due_idx",
            ),
        ),
    ]
