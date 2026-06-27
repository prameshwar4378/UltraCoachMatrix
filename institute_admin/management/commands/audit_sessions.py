from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, F, Q, Sum
from django.db.models.functions import Coalesce

from accountant.models import Expense, FeeCategory, FeeInvoice, Payment
from institute_admin.models import AcademicYear, Batch, Course, Notice
from student_parent.models import StudentAcademicSession, StudentEnrollment, StudentProfile
from super_admin.models import Institute, UserProfile
from teacher.models import Attendance, Homework


class Command(BaseCommand):
    help = "Audit academic-session and tenant data consistency without changing records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--institute-code",
            help="Limit the audit to a single institute code.",
        )
        parser.add_argument(
            "--fail-on-issues",
            action="store_true",
            help="Return a non-zero exit code when error-level issues are found.",
        )

    def handle(self, *args, **options):
        institute_code = options.get("institute_code")
        institutes = Institute.objects.all()
        if institute_code:
            institutes = institutes.filter(code=institute_code)
            if not institutes.exists():
                raise CommandError(f'Institute with code "{institute_code}" was not found.')

        institute_ids = list(institutes.values_list("id", flat=True))
        checks = []

        self._add_error_checks(checks, institute_ids)
        self._add_warning_checks(checks, institute_ids)
        self._write_summary(checks, institutes)

        error_count = sum(check["count"] for check in checks if check["level"] == "ERROR")
        warning_count = sum(check["count"] for check in checks if check["level"] == "WARNING")
        self.stdout.write("")
        if error_count:
            self.stdout.write(self.style.ERROR(f"Audit completed with {error_count} error(s) and {warning_count} warning(s)."))
        elif warning_count:
            self.stdout.write(self.style.WARNING(f"Audit completed with 0 errors and {warning_count} warning(s)."))
        else:
            self.stdout.write(self.style.SUCCESS("Audit completed with 0 errors and 0 warnings."))

        if options.get("fail_on_issues") and error_count:
            raise CommandError("Session audit found error-level data issues.")

    def _add_error_checks(self, checks, institute_ids):
        sessions = StudentAcademicSession.objects.filter(institute_id__in=institute_ids)
        students = StudentProfile.objects.filter(institute_id__in=institute_ids)
        enrollments = StudentEnrollment.objects.filter(academic_session__institute_id__in=institute_ids)
        invoices = FeeInvoice.objects.filter(institute_id__in=institute_ids)
        fee_categories = FeeCategory.objects.filter(institute_id__in=institute_ids)
        expenses = Expense.objects.filter(institute_id__in=institute_ids)
        attendance = Attendance.objects.filter(academic_session__institute_id__in=institute_ids)
        notices = Notice.objects.filter(institute_id__in=institute_ids)
        homework = Homework.objects.filter(batch__institute_id__in=institute_ids)
        courses = Course.objects.filter(institute_id__in=institute_ids)
        batches = Batch.objects.filter(institute_id__in=institute_ids)

        self._add_check(
            checks,
            "ERROR",
            "Courses with institute/year mismatch",
            courses.exclude(academic_year__institute_id=F("institute_id")).count(),
            "Course academic year must belong to the same institute.",
        )
        self._add_check(
            checks,
            "ERROR",
            "Batches with institute/year mismatch",
            batches.exclude(academic_year__institute_id=F("institute_id")).count(),
            "Batch academic year must belong to the same institute.",
        )
        self._add_check(
            checks,
            "ERROR",
            "Batches with courses from another academic year",
            batches.filter(courses__isnull=False)
            .exclude(courses__academic_year_id=F("academic_year_id"))
            .distinct()
            .count(),
            "Batch courses must belong to the same academic year as the batch.",
        )
        self._add_check(
            checks,
            "ERROR",
            "Student sessions with institute/student mismatch",
            sessions.exclude(student__institute_id=F("institute_id")).count(),
            "StudentAcademicSession.institute must match StudentProfile.institute.",
        )
        self._add_check(
            checks,
            "ERROR",
            "Student sessions with institute/year mismatch",
            sessions.exclude(academic_year__institute_id=F("institute_id")).count(),
            "AcademicYear must belong to the same institute as the student session.",
        )
        self._add_check(
            checks,
            "ERROR",
            "Legacy student academic years with institute mismatch",
            students.filter(academic_year__isnull=False).exclude(academic_year__institute_id=F("institute_id")).count(),
            "StudentProfile.academic_year is legacy, but if present it must stay inside the institute.",
        )
        self._add_check(
            checks,
            "ERROR",
            "Enrollments with session/student mismatch",
            enrollments.exclude(student_id=F("academic_session__student_id")).count(),
            "Enrollment student must come from the selected academic session.",
        )
        self._add_check(
            checks,
            "ERROR",
            "Enrollments with batch institute mismatch",
            enrollments.exclude(batch__institute_id=F("academic_session__institute_id")).count(),
            "Enrollment batch must belong to the same institute as the academic session.",
        )
        self._add_check(
            checks,
            "ERROR",
            "Enrollments with batch academic-year mismatch",
            enrollments.exclude(batch__academic_year_id=F("academic_session__academic_year_id")).count(),
            "Enrollment batch must belong to the same academic year as the student session.",
        )
        self._add_check(
            checks,
            "ERROR",
            "Enrollments with course institute mismatch",
            enrollments.filter(courses__isnull=False)
            .exclude(courses__institute_id=F("academic_session__institute_id"))
            .distinct()
            .count(),
            "Enrollment courses must belong to the same institute as the academic session.",
        )
        self._add_check(
            checks,
            "ERROR",
            "Enrollments with course academic-year mismatch",
            enrollments.filter(courses__isnull=False)
            .exclude(courses__academic_year_id=F("academic_session__academic_year_id"))
            .distinct()
            .count(),
            "Enrollment courses must belong to the same academic year as the student session.",
        )
        self._add_check(
            checks,
            "ERROR",
            "Invoices with session/student mismatch",
            invoices.exclude(student_id=F("academic_session__student_id")).count(),
            "Invoice student must come from the selected academic session.",
        )
        self._add_check(
            checks,
            "ERROR",
            "Invoices with session/institute mismatch",
            invoices.exclude(institute_id=F("academic_session__institute_id")).count(),
            "Invoice institute must match the selected academic session.",
        )
        self._add_check(
            checks,
            "ERROR",
            "Invoices linked to enrollment from another session",
            invoices.filter(enrollment__isnull=False).exclude(enrollment__academic_session_id=F("academic_session_id")).count(),
            "Enrollment invoices must stay attached to the same academic session.",
        )
        self._add_check(
            checks,
            "ERROR",
            "Invoices with batch institute mismatch",
            invoices.filter(batch__isnull=False).exclude(batch__institute_id=F("institute_id")).count(),
            "Invoice batch must belong to the invoice institute.",
        )
        self._add_check(
            checks,
            "ERROR",
            "Invoices with batch academic-year mismatch",
            invoices.filter(batch__isnull=False)
            .exclude(batch__academic_year_id=F("academic_session__academic_year_id"))
            .count(),
            "Invoice batch must belong to the same academic year as the invoice session.",
        )
        self._add_check(
            checks,
            "ERROR",
            "Invoices with category institute mismatch",
            invoices.filter(category__isnull=False).exclude(category__institute_id=F("institute_id")).count(),
            "Fee category must belong to the invoice institute.",
        )
        self._add_check(
            checks,
            "ERROR",
            "Invoices with category academic-year mismatch",
            invoices.filter(category__isnull=False)
            .exclude(category__academic_year_id=F("academic_session__academic_year_id"))
            .count(),
            "Fee category must belong to the same academic year as the invoice session.",
        )
        self._add_check(
            checks,
            "ERROR",
            "Invoices with course institute mismatch",
            invoices.filter(course__isnull=False).exclude(course__institute_id=F("institute_id")).count(),
            "Invoice course must belong to the invoice institute.",
        )
        self._add_check(
            checks,
            "ERROR",
            "Invoices with course academic-year mismatch",
            invoices.filter(course__isnull=False)
            .exclude(course__academic_year_id=F("academic_session__academic_year_id"))
            .count(),
            "Invoice course must belong to the same academic year as the invoice session.",
        )
        self._add_check(
            checks,
            "ERROR",
            "Invoices with active payment total greater than invoice amount",
            self._invoice_amounts()
            .filter(institute_id__in=institute_ids)
            .exclude(status=FeeInvoice.Status.CANCELLED)
            .filter(active_paid_amount__gt=F("amount"))
            .count(),
            "Active payments should never exceed the invoice amount.",
        )
        self._add_check(
            checks,
            "ERROR",
            "Invoices with wrong payment status",
            self._wrong_invoice_status_count(institute_ids),
            "Invoice status should match active paid amount: unpaid, partial, or paid.",
        )
        self._add_check(
            checks,
            "ERROR",
            "Attendance with session/student mismatch",
            attendance.exclude(student_id=F("academic_session__student_id")).count(),
            "Attendance student must come from the selected academic session.",
        )
        self._add_check(
            checks,
            "ERROR",
            "Attendance with batch institute mismatch",
            attendance.exclude(batch__institute_id=F("academic_session__institute_id")).count(),
            "Attendance batch must belong to the same institute as the academic session.",
        )
        self._add_check(
            checks,
            "ERROR",
            "Attendance with batch academic-year mismatch",
            attendance.exclude(batch__academic_year_id=F("academic_session__academic_year_id")).count(),
            "Attendance batch must belong to the same academic year as the student session.",
        )
        self._add_check(
            checks,
            "ERROR",
            "Fee categories with institute/year mismatch",
            fee_categories.filter(academic_year__isnull=False)
            .exclude(academic_year__institute_id=F("institute_id"))
            .count(),
            "Fee category academic year must belong to the same institute.",
        )
        self._add_check(
            checks,
            "ERROR",
            "Expenses with institute/year mismatch",
            expenses.filter(academic_year__isnull=False)
            .exclude(academic_year__institute_id=F("institute_id"))
            .count(),
            "Expense academic year must belong to the same institute.",
        )
        self._add_check(
            checks,
            "ERROR",
            "Homework with course institute mismatch",
            homework.filter(course__isnull=False).exclude(course__institute_id=F("batch__institute_id")).count(),
            "Homework course must belong to the same institute as the batch.",
        )
        self._add_check(
            checks,
            "ERROR",
            "Notices targeting batches from another institute",
            notices.filter(target_batches__isnull=False)
            .exclude(target_batches__institute_id=F("institute_id"))
            .distinct()
            .count(),
            "Notice batch targets must stay inside the notice institute.",
        )
        self._add_check(
            checks,
            "ERROR",
            "Notices targeting courses from another institute",
            notices.filter(target_courses__isnull=False)
            .exclude(target_courses__institute_id=F("institute_id"))
            .distinct()
            .count(),
            "Notice course targets must stay inside the notice institute.",
        )
        self._add_check(
            checks,
            "ERROR",
            "Notices targeting students from another institute",
            notices.filter(target_students__isnull=False)
            .exclude(target_students__institute_id=F("institute_id"))
            .distinct()
            .count(),
            "Notice student targets must stay inside the notice institute.",
        )

    def _add_warning_checks(self, checks, institute_ids):
        active_invoices = FeeInvoice.objects.filter(institute_id__in=institute_ids).exclude(status=FeeInvoice.Status.CANCELLED)

        duplicate_session_admissions = (
            StudentAcademicSession.objects.filter(institute_id__in=institute_ids)
            .values("institute_id", "academic_year_id", "admission_number")
            .annotate(row_count=Count("id"))
            .filter(row_count__gt=1)
            .count()
        )
        duplicate_legacy_admissions = (
            StudentProfile.objects.filter(institute_id__in=institute_ids, academic_year__isnull=False)
            .values("institute_id", "academic_year_id", "admission_number")
            .annotate(row_count=Count("id"))
            .filter(row_count__gt=1)
            .count()
        )
        duplicate_receipts = (
            Payment.objects.filter(
                invoice__institute_id__in=institute_ids,
                status=Payment.Status.ACTIVE,
            )
            .exclude(receipt_number="")
            .values("invoice__institute_id", "receipt_number")
            .annotate(row_count=Count("id"))
            .filter(row_count__gt=1)
            .count()
        )
        duplicate_student_parent_phones = (
            UserProfile.objects.filter(
                institute_id__in=institute_ids,
                role=UserProfile.Role.STUDENT_PARENT,
            )
            .exclude(phone="")
            .values("institute_id", "phone")
            .annotate(row_count=Count("id"))
            .filter(row_count__gt=1)
            .count()
        )

        self._add_check(
            checks,
            "WARNING",
            "Duplicate session admission number groups",
            duplicate_session_admissions,
            "Database constraints should prevent this; investigate if any appear.",
        )
        self._add_check(
            checks,
            "WARNING",
            "Duplicate legacy admission number groups",
            duplicate_legacy_admissions,
            "Legacy student profile admission numbers should stay tidy for old references.",
        )
        self._add_check(
            checks,
            "WARNING",
            "Duplicate active receipt number groups",
            duplicate_receipts,
            "Receipt numbers are not database-unique yet; duplicate active receipts should be reviewed.",
        )
        self._add_check(
            checks,
            "WARNING",
            "Duplicate student/parent mobile groups",
            duplicate_student_parent_phones,
            "Import validation expects student/parent mobile numbers to be unique inside an institute.",
        )
        self._add_check(
            checks,
            "WARNING",
            "Active invoices with zero or negative amount",
            active_invoices.filter(amount__lte=0).count(),
            "Zero invoices may be intentional, but they should be reviewed.",
        )

    def _invoice_amounts(self):
        return FeeInvoice.objects.annotate(
            active_paid_amount=Coalesce(
                Sum("payments__amount", filter=Q(payments__status=Payment.Status.ACTIVE)),
                Decimal("0.00"),
            )
        )

    def _wrong_invoice_status_count(self, institute_ids):
        invoices = (
            self._invoice_amounts()
            .filter(institute_id__in=institute_ids)
            .exclude(status=FeeInvoice.Status.CANCELLED)
        )
        wrong_status = (
            Q(status=FeeInvoice.Status.UNPAID, active_paid_amount__gt=Decimal("0.00"))
            | Q(status=FeeInvoice.Status.PARTIAL, active_paid_amount__lte=Decimal("0.00"))
            | Q(status=FeeInvoice.Status.PARTIAL, active_paid_amount__gte=F("amount"))
            | Q(status=FeeInvoice.Status.PAID, active_paid_amount__lt=F("amount"))
        )
        return invoices.filter(wrong_status).count()

    def _add_check(self, checks, level, name, count, detail):
        checks.append(
            {
                "level": level,
                "name": name,
                "count": count,
                "detail": detail,
            }
        )

    def _write_summary(self, checks, institutes):
        self.stdout.write("Academic session audit")
        self.stdout.write("======================")
        self.stdout.write(f"Institutes checked: {institutes.count()}")
        self.stdout.write(f"Academic years: {AcademicYear.objects.filter(institute__in=institutes).count()}")
        self.stdout.write(f"Student sessions: {StudentAcademicSession.objects.filter(institute__in=institutes).count()}")
        self.stdout.write("")

        for check in checks:
            line = f"{check['level']:7} {check['count']:>5}  {check['name']}"
            if check["level"] == "ERROR" and check["count"]:
                self.stdout.write(self.style.ERROR(line))
                self.stdout.write(f"         {check['detail']}")
            elif check["level"] == "WARNING" and check["count"]:
                self.stdout.write(self.style.WARNING(line))
                self.stdout.write(f"         {check['detail']}")
            else:
                self.stdout.write(line)
