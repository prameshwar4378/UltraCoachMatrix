from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.db import transaction
from openpyxl import load_workbook

from student_parent.models import GuardianProfile, StudentAcademicSession, StudentProfile
from super_admin.models import UserProfile

from .models import AcademicYear
from UltraCoachMatrix.email_notifications import on_commit_email, send_bulk_student_welcomes


def process_student_import_job(job):
    from .forms import build_student_username, get_last_student_admission_sequence, get_student_admission_prefix
    from .views import (
        bool_from_excel,
        match_student_import_headers,
        parse_excel_date_value,
        student_import_columns,
    )

    institute = job.institute
    academic_year = AcademicYear.objects.get(pk=job.academic_year_id, institute=institute)
    workbook = load_workbook(job.input_file.path, data_only=True)
    sheet = workbook["Students"] if "Students" in workbook.sheetnames else workbook.active
    expected = student_import_columns()
    headers = [str(cell.value or "").strip() for cell in sheet[3]]
    headers_match, _missing_headers = match_student_import_headers(headers)
    if not headers_match:
        raise ValueError("Invalid student import template.")

    rows = []
    for row_number in range(4, sheet.max_row + 1):
        values = [sheet.cell(row=row_number, column=column).value for column in range(1, len(expected) + 1)]
        if not any(value not in (None, "") for value in values):
            continue
        data = dict(zip(expected, values))
        first_name = str(data["First Name *"] or "").strip()
        if not first_name:
            raise ValueError(f"Row {row_number}: First Name is required.")
        rows.append(
            {
                "first_name": first_name,
                "last_name": str(data["Last Name"] or "").strip(),
                "password": str(data["Password"] or "Student@123"),
                "email": str(data["Email"] or "").strip(),
                "phone": str(data["Phone"] or "").strip(),
                "date_of_birth": parse_excel_date_value(data["Date of Birth"]),
                "joined_on": parse_excel_date_value(data["Joined On"]),
                "address": str(data["Address"] or "").strip(),
                "current_school_name": str(data["Current School / College"] or "").strip(),
                "current_school_address": str(data["Current School Address"] or "").strip(),
                "previous_school_name": str(data["Previous School / College"] or "").strip(),
                "previous_class": str(data["Previous Class"] or "").strip(),
                "guardian_name": str(data["Guardian Name"] or "").strip(),
                "guardian_relation": str(data["Guardian Relation"] or "").strip(),
                "guardian_phone": str(data["Guardian Phone"] or data["Phone"] or "").strip(),
                "guardian_email": str(data["Guardian Email"] or "").strip(),
                "is_active": bool_from_excel(data["Active"]),
            }
        )

    with transaction.atomic():
        academic_year = AcademicYear.objects.select_for_update().get(pk=academic_year.pk)
        prefix = get_student_admission_prefix(institute, academic_year)
        sequence = get_last_student_admission_sequence(institute, academic_year) + 1
        username_prefix = build_student_username(institute, prefix)
        reserved_usernames = set(
            User.objects.filter(username__startswith=username_prefix).values_list("username", flat=True)
        )
        password_hashes = {}
        users = []
        for row in rows:
            while True:
                admission_number = f"{prefix}{sequence:04d}"
                username = build_student_username(institute, admission_number)
                sequence += 1
                if username not in reserved_usernames:
                    reserved_usernames.add(username)
                    break
            row["admission_number"] = admission_number
            row["username"] = username
            password_hashes.setdefault(row["password"], make_password(row["password"]))
            users.append(
                User(
                    username=username,
                    first_name=row["first_name"],
                    last_name=row["last_name"],
                    email=row["email"],
                    password=password_hashes[row["password"]],
                    is_active=row["is_active"],
                )
            )

        User.objects.bulk_create(users, batch_size=500)
        users_by_username = User.objects.in_bulk(
            [row["username"] for row in rows],
            field_name="username",
        )
        UserProfile.objects.bulk_create(
            [
                UserProfile(
                    user=users_by_username[row["username"]],
                    institute=institute,
                    role=UserProfile.Role.STUDENT_PARENT,
                    phone=row["phone"],
                )
                for row in rows
            ],
            batch_size=500,
        )
        StudentProfile.objects.bulk_create(
            [
                StudentProfile(
                    institute=institute,
                    academic_year=academic_year,
                    user=users_by_username[row["username"]],
                    admission_number=row["admission_number"],
                    date_of_birth=row["date_of_birth"],
                    joined_on=row["joined_on"],
                    address=row["address"],
                    current_school_name=row["current_school_name"],
                    current_school_address=row["current_school_address"],
                    previous_school_name=row["previous_school_name"],
                    previous_class=row["previous_class"],
                    is_active=row["is_active"],
                )
                for row in rows
            ],
            batch_size=500,
        )
        students_by_user_id = StudentProfile.objects.in_bulk(
            [user.pk for user in users_by_username.values()],
            field_name="user_id",
        )
        StudentAcademicSession.objects.bulk_create(
            [
                StudentAcademicSession(
                    institute=institute,
                    student=students_by_user_id[users_by_username[row["username"]].pk],
                    academic_year=academic_year,
                    admission_number=row["admission_number"],
                    joined_on=row["joined_on"],
                    status=(
                        StudentAcademicSession.Status.ACTIVE
                        if row["is_active"]
                        else StudentAcademicSession.Status.LEFT
                    ),
                    current_school_name=row["current_school_name"],
                    current_school_address=row["current_school_address"],
                    previous_school_name=row["previous_school_name"],
                    previous_class=row["previous_class"],
                )
                for row in rows
            ],
            batch_size=500,
        )
        guardians = [
            GuardianProfile(
                student=students_by_user_id[users_by_username[row["username"]].pk],
                name=row["guardian_name"] or "Primary Guardian",
                relation=row["guardian_relation"],
                phone=row["guardian_phone"],
                email=row["guardian_email"],
                is_primary=True,
            )
            for row in rows
            if row["guardian_name"] or row["guardian_phone"]
        ]
        if guardians:
            GuardianProfile.objects.bulk_create(guardians, batch_size=500)
        student_credentials = [
            (
                students_by_user_id[users_by_username[row["username"]].pk].pk,
                row["password"],
            )
            for row in rows
        ]
        on_commit_email(send_bulk_student_welcomes, student_credentials)

    return {"created_count": len(rows)}
