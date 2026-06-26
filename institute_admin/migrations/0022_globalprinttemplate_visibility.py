from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("institute_admin", "0021_alter_backgroundjob_input_file_and_more"),
        ("super_admin", "0014_userprofile_profile_inst_role_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="instituteglobalprinttemplate",
            name="is_global",
            field=models.BooleanField(
                default=True,
                help_text="Show this template to every institute. Turn off to choose specific institutes.",
            ),
        ),
        migrations.AddField(
            model_name="instituteglobalprinttemplate",
            name="visible_to_institutes",
            field=models.ManyToManyField(
                blank=True,
                help_text="Institutes that can see this template when it is not global.",
                related_name="visible_global_print_templates",
                to="super_admin.institute",
            ),
        ),
    ]
