from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("institute_admin", "0017_notice_push_notification_queued_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="notice",
            name="push_notification_version",
            field=models.PositiveIntegerField(default=1),
        ),
    ]
