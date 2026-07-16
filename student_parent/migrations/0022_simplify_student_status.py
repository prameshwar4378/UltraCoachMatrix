from django.db import migrations, models


def map_tc_issued_to_left_school(apps, schema_editor):
    StudentProfile = apps.get_model("student_parent", "StudentProfile")
    StudentProfile.objects.filter(student_status="TC_ISSUED").update(student_status="LEFT_SCHOOL")


class Migration(migrations.Migration):

    dependencies = [
        ("student_parent", "0021_studenttransfercertificate_progress"),
    ]

    operations = [
        migrations.RunPython(map_tc_issued_to_left_school, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="studentprofile",
            name="student_status",
            field=models.CharField(
                choices=[
                    ("ACTIVE", "Active"),
                    ("INACTIVE", "Inactive"),
                    ("LEFT_SCHOOL", "Left School"),
                    ("PASSED_OUT", "Passed Out"),
                ],
                default="ACTIVE",
                max_length=20,
            ),
        ),
    ]
