from django.db import migrations, models
import django.db.models.deletion


def _fallback_year(AcademicYear, institute_id, reference_date=None):
    if reference_date:
        academic_year = (
            AcademicYear.objects.filter(
                institute_id=institute_id,
                start_date__lte=reference_date,
                end_date__gte=reference_date,
            )
            .order_by("-start_date", "-pk")
            .first()
        )
        if academic_year:
            return academic_year
    return (
        AcademicYear.objects.filter(institute_id=institute_id, is_active=True)
        .order_by("-start_date", "-pk")
        .first()
        or AcademicYear.objects.filter(institute_id=institute_id)
        .order_by("-start_date", "-pk")
        .first()
    )


def backfill_accounting_academic_years(apps, schema_editor):
    AcademicYear = apps.get_model("institute_admin", "AcademicYear")
    Expense = apps.get_model("accountant", "Expense")
    FeeCategory = apps.get_model("accountant", "FeeCategory")
    FeeInvoice = apps.get_model("accountant", "FeeInvoice")

    for expense in Expense.objects.filter(academic_year__isnull=True).order_by("pk"):
        academic_year = _fallback_year(AcademicYear, expense.institute_id, expense.spent_on)
        if academic_year:
            Expense.objects.filter(pk=expense.pk).update(academic_year=academic_year)

    for category in FeeCategory.objects.filter(academic_year__isnull=True).order_by("pk"):
        invoice = (
            FeeInvoice.objects.filter(category_id=category.pk, academic_session__isnull=False)
            .select_related("academic_session")
            .order_by("-created_at", "-pk")
            .first()
        )
        academic_year = invoice.academic_session.academic_year if invoice else None
        if academic_year is None:
            academic_year = _fallback_year(AcademicYear, category.institute_id)
        if academic_year:
            FeeCategory.objects.filter(pk=category.pk).update(academic_year=academic_year)


class Migration(migrations.Migration):

    dependencies = [
        ("accountant", "0009_alter_expensedocument_file"),
        ("institute_admin", "0024_notice_academic_year"),
    ]

    operations = [
        migrations.AddField(
            model_name="expense",
            name="academic_year",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="expenses",
                to="institute_admin.academicyear",
            ),
        ),
        migrations.AddField(
            model_name="feecategory",
            name="academic_year",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="fee_categories",
                to="institute_admin.academicyear",
            ),
        ),
        migrations.RunPython(backfill_accounting_academic_years, migrations.RunPython.noop),
        migrations.AlterUniqueTogether(
            name="feecategory",
            unique_together={("institute", "academic_year", "name")},
        ),
        migrations.AddIndex(
            model_name="expense",
            index=models.Index(fields=["institute", "academic_year", "-spent_on"], name="expense_inst_year_idx"),
        ),
        migrations.AddIndex(
            model_name="feecategory",
            index=models.Index(fields=["institute", "academic_year", "is_active"], name="feecat_inst_year_idx"),
        ),
    ]
