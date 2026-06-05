from django.db import migrations, models
import django.db.models.deletion


def backfill_homework_subjects(apps, schema_editor):
    Homework = apps.get_model("teacher", "Homework")
    Subject = apps.get_model("institute_admin", "Subject")
    for homework in Homework.objects.select_related("course", "batch").filter(subject__isnull=True, course__isnull=False):
        course = homework.course
        batch = homework.batch
        subject, _created = Subject.objects.get_or_create(
            institute_id=batch.institute_id,
            academic_year_id=batch.academic_year_id,
            name=course.name,
            defaults={"description": course.description, "is_active": course.is_active},
        )
        homework.subject_id = subject.pk
        homework.save(update_fields=["subject"])


class Migration(migrations.Migration):

    dependencies = [
        ("institute_admin", "0008_subject"),
        ("teacher", "0012_examattemptactivity"),
    ]

    operations = [
        migrations.AddField(
            model_name="homework",
            name="subject",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="homework",
                to="institute_admin.subject",
            ),
        ),
        migrations.AddIndex(
            model_name="homework",
            index=models.Index(fields=["subject", "due_date"], name="hw_subject_due_idx"),
        ),
        migrations.RunPython(backfill_homework_subjects, migrations.RunPython.noop),
    ]
