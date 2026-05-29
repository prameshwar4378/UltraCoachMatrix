from datetime import date

from django.db import migrations, models
import django.db.models.deletion


def academic_year_label(today=None):
    today = today or date.today()
    start_year = today.year if today.month >= 4 else today.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def academic_year_dates(name):
    start_year = int(str(name).split("-", 1)[0])
    return date(start_year, 4, 1), date(start_year + 1, 3, 31)


def assign_current_year(apps, schema_editor):
    AcademicYear = apps.get_model("institute_admin", "AcademicYear")
    Course = apps.get_model("institute_admin", "Course")
    Batch = apps.get_model("institute_admin", "Batch")

    year_name = academic_year_label()
    start_date, end_date = academic_year_dates(year_name)
    institute_ids = set(Course.objects.values_list("institute_id", flat=True))
    institute_ids.update(Batch.objects.values_list("institute_id", flat=True))

    year_by_institute = {}
    for institute_id in institute_ids:
        academic_year, _created = AcademicYear.objects.get_or_create(
            institute_id=institute_id,
            name=year_name,
            defaults={
                "start_date": start_date,
                "end_date": end_date,
                "is_active": True,
            },
        )
        year_by_institute[institute_id] = academic_year.pk

    for course in Course.objects.filter(academic_year__isnull=True).only("id", "institute_id"):
        course.academic_year_id = year_by_institute.get(course.institute_id)
        course.save(update_fields=["academic_year"])

    for batch in Batch.objects.filter(academic_year__isnull=True).only("id", "institute_id"):
        batch.academic_year_id = year_by_institute.get(batch.institute_id)
        batch.save(update_fields=["academic_year"])


class Migration(migrations.Migration):

    dependencies = [
        ("institute_admin", "0005_backfill_session_links"),
    ]

    operations = [
        migrations.AddField(
            model_name="course",
            name="academic_year",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="courses",
                to="institute_admin.academicyear",
            ),
        ),
        migrations.AddField(
            model_name="batch",
            name="academic_year",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="batches",
                to="institute_admin.academicyear",
            ),
        ),
        migrations.RunPython(assign_current_year, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="course",
            name="academic_year",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="courses",
                to="institute_admin.academicyear",
            ),
        ),
        migrations.AlterField(
            model_name="batch",
            name="academic_year",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="batches",
                to="institute_admin.academicyear",
            ),
        ),
        migrations.AlterUniqueTogether(
            name="course",
            unique_together={("institute", "academic_year", "name")},
        ),
        migrations.AlterUniqueTogether(
            name="batch",
            unique_together={("institute", "academic_year", "name")},
        ),
        migrations.AlterModelOptions(
            name="course",
            options={"ordering": ["academic_year__start_date", "name"]},
        ),
        migrations.AlterModelOptions(
            name="batch",
            options={"ordering": ["academic_year__start_date", "name"]},
        ),
    ]
