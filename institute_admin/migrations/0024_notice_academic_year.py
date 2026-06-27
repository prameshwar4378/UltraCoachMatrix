from django.db import migrations, models
import django.db.models.deletion


def backfill_notice_academic_year(apps, schema_editor):
    AcademicYear = apps.get_model("institute_admin", "AcademicYear")
    Notice = apps.get_model("institute_admin", "Notice")

    for notice in Notice.objects.filter(academic_year__isnull=True).order_by("pk"):
        academic_year = None

        batch = notice.target_batches.order_by("academic_year__start_date", "pk").first()
        if batch:
            academic_year = batch.academic_year

        if academic_year is None:
            course = notice.target_courses.order_by("academic_year__start_date", "pk").first()
            if course:
                academic_year = course.academic_year

        if academic_year is None:
            reference_time = notice.publish_at or notice.created_at
            reference_date = reference_time.date() if reference_time else None
            if reference_date:
                academic_year = (
                    AcademicYear.objects.filter(
                        institute_id=notice.institute_id,
                        start_date__lte=reference_date,
                        end_date__gte=reference_date,
                    )
                    .order_by("-start_date", "-pk")
                    .first()
                )

        if academic_year is None:
            academic_year = (
                AcademicYear.objects.filter(institute_id=notice.institute_id, is_active=True)
                .order_by("-start_date", "-pk")
                .first()
                or AcademicYear.objects.filter(institute_id=notice.institute_id)
                .order_by("-start_date", "-pk")
                .first()
            )

        if academic_year is not None:
            Notice.objects.filter(pk=notice.pk).update(academic_year=academic_year)


class Migration(migrations.Migration):

    dependencies = [
        ("institute_admin", "0023_payment_receipt_print_template_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="notice",
            name="academic_year",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="notices",
                to="institute_admin.academicyear",
            ),
        ),
        migrations.RunPython(backfill_notice_academic_year, migrations.RunPython.noop),
        migrations.AddIndex(
            model_name="notice",
            index=models.Index(fields=["institute", "academic_year", "-created_at"], name="notice_inst_year_idx"),
        ),
    ]
