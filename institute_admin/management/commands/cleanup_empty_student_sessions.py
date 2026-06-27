from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count

from institute_admin.models import AcademicYear
from student_parent.models import StudentAcademicSession
from super_admin.models import Institute


class Command(BaseCommand):
    help = (
        "Find or delete empty student academic-session rows for one institute session. "
        "Use this to clean students that were accidentally synced into a session."
    )

    def add_arguments(self, parser):
        parser.add_argument("--institute-code", required=True, help="Institute code to clean.")
        parser.add_argument("--session", required=True, help="Academic session name, for example 2025-26.")
        parser.add_argument(
            "--commit",
            action="store_true",
            help="Actually delete safe empty rows. Without this flag the command only reports what it would delete.",
        )

    def handle(self, *args, **options):
        institute = Institute.objects.filter(code__iexact=options["institute_code"]).first()
        if not institute:
            raise CommandError(f'Institute with code "{options["institute_code"]}" was not found.')

        academic_year = AcademicYear.objects.filter(
            institute=institute,
            name__iexact=options["session"],
        ).first()
        if not academic_year:
            raise CommandError(
                f'Academic session "{options["session"]}" was not found for institute "{institute.code}".'
            )

        candidates = (
            StudentAcademicSession.objects.filter(institute=institute, academic_year=academic_year)
            .annotate(
                enrollment_count=Count("enrollments", distinct=True),
                invoice_count=Count("fee_invoices", distinct=True),
                attendance_count=Count("attendance_records", distinct=True),
                exam_attempt_count=Count("exam_attempts", distinct=True),
                transfer_certificate_count=Count("transfer_certificates", distinct=True),
                bonafide_certificate_count=Count("bonafide_certificates", distinct=True),
            )
            .filter(
                enrollment_count=0,
                invoice_count=0,
                attendance_count=0,
                exam_attempt_count=0,
                transfer_certificate_count=0,
                bonafide_certificate_count=0,
            )
            .order_by("admission_number", "pk")
        )

        total_sessions = StudentAcademicSession.objects.filter(
            institute=institute,
            academic_year=academic_year,
        ).count()
        safe_count = candidates.count()

        self.stdout.write(f"Institute: {institute.name} ({institute.code})")
        self.stdout.write(f"Session: {academic_year.name}")
        self.stdout.write(f"Student session rows: {total_sessions}")
        self.stdout.write(f"Safe empty rows: {safe_count}")

        sample = list(candidates.select_related("student", "student__user")[:20])
        if sample:
            self.stdout.write("")
            self.stdout.write("Sample rows:")
            for session in sample:
                self.stdout.write(f"  {session.pk}: {session.admission_number} - {session.student}")
            if safe_count > len(sample):
                self.stdout.write(f"  ... and {safe_count - len(sample)} more")

        if not options["commit"]:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Dry run only. Re-run with --commit to delete these safe empty rows."))
            return

        with transaction.atomic():
            deleted_count, _details = candidates.delete()
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted_count} empty student session row(s)."))
