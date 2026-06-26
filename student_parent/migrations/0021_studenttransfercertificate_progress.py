from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("student_parent", "0020_alter_studentdocument_file_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="studenttransfercertificate",
            name="progress",
            field=models.CharField(blank=True, max_length=120),
        ),
    ]
