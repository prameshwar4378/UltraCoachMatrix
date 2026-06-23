from pathlib import Path

from django.conf import settings
from django.utils.text import get_valid_filename, slugify


INSTITUTE_MEDIA_SUBFOLDERS = (
    "logos",
    "students/profile_images",
    "students/documents",
    "homework/attachments",
    "exams/questions",
    "exams/rough-work",
    "visitors/id_scans",
    "expenses/documents",
    "background_jobs/input",
    "print_templates",
)


def institute_media_code(institute):
    code = getattr(institute, "code", "") or ""
    return slugify(code) or f"institute-{getattr(institute, 'pk', 'unknown')}"


def create_institute_media_folders(institute):
    base_path = Path(settings.MEDIA_ROOT) / "institutes" / institute_media_code(institute)
    for subfolder in INSTITUTE_MEDIA_SUBFOLDERS:
        (base_path / subfolder).mkdir(parents=True, exist_ok=True)


def resolve_institute(instance):
    if instance.__class__.__name__ == "Institute":
        return instance

    direct = getattr(instance, "institute", None)
    if direct is not None:
        return direct

    student = getattr(instance, "student", None)
    if student is not None:
        return getattr(student, "institute", None)

    homework = getattr(instance, "homework", None)
    if homework is not None:
        return resolve_institute(homework)

    expense = getattr(instance, "expense", None)
    if expense is not None:
        return getattr(expense, "institute", None)

    exam = getattr(instance, "exam", None)
    if exam is not None:
        return resolve_institute(exam)

    attempt = getattr(instance, "attempt", None)
    if attempt is not None:
        return resolve_institute(attempt)

    batch = getattr(instance, "batch", None)
    if batch is not None:
        return getattr(batch, "institute", None)

    question = getattr(instance, "question", None)
    if question is not None:
        return resolve_institute(question)

    return None


def institute_upload_path(instance, subfolder, filename):
    institute = resolve_institute(instance)
    safe_filename = get_valid_filename(filename)
    if institute is None:
        return f"unscoped/{subfolder}/{safe_filename}"
    return f"institutes/{institute_media_code(institute)}/{subfolder}/{safe_filename}"


def institute_logo_upload_path(instance, filename):
    return institute_upload_path(instance, "logos", filename)


def student_profile_image_upload_path(instance, filename):
    return institute_upload_path(instance, "students/profile_images", filename)


def student_document_upload_path(instance, filename):
    return institute_upload_path(instance, "students/documents", filename)


def homework_attachment_upload_path(instance, filename):
    return institute_upload_path(instance, "homework/attachments", filename)


def exam_question_image_upload_path(instance, filename):
    return institute_upload_path(instance, "exams/questions", filename)


def exam_rough_work_upload_path(instance, filename):
    return institute_upload_path(instance, "exams/rough-work", filename)


def visitor_attachment_upload_path(instance, filename):
    return institute_upload_path(instance, "visitors/id_scans", filename)


def expense_document_upload_path(instance, filename):
    return institute_upload_path(instance, "expenses/documents", filename)


def background_job_input_upload_path(instance, filename):
    return institute_upload_path(instance, "background_jobs/input", filename)


def institute_print_template_upload_path(instance, filename):
    document_type = getattr(instance, "document_type", "UNKNOWN")
    return institute_upload_path(instance, f"print_templates/{document_type}", filename)
