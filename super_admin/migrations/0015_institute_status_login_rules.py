from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("super_admin", "0014_userprofile_profile_inst_role_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="institute",
            name="left_school_login_active",
            field=models.BooleanField(
                default=True,
                help_text="Keep student/parent login active when student status is Left School.",
            ),
        ),
        migrations.AddField(
            model_name="institute",
            name="passed_out_login_active",
            field=models.BooleanField(
                default=True,
                help_text="Keep student/parent login active when student status is Passed Out.",
            ),
        ),
    ]
