from django.db import migrations, models


PRINT_DOCUMENT_CHOICES = [
    ("ADMISSION_FORM", "Admission Form"),
    ("TRANSFER_CERTIFICATE", "TC"),
    ("BONAFIDE_CERTIFICATE", "Bonafide"),
    ("PAYMENT_RECEIPT", "Payment Receipt"),
]


class Migration(migrations.Migration):

    dependencies = [
        ("institute_admin", "0022_globalprinttemplate_visibility"),
    ]

    operations = [
        migrations.AlterField(
            model_name="instituteglobalprinttemplate",
            name="document_type",
            field=models.CharField(choices=PRINT_DOCUMENT_CHOICES, max_length=40),
        ),
        migrations.AlterField(
            model_name="instituteprinttemplate",
            name="document_type",
            field=models.CharField(choices=PRINT_DOCUMENT_CHOICES, max_length=40),
        ),
    ]
