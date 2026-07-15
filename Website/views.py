from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db.models import Avg
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.urls import reverse

from UltraCoachMatrix.email_notifications import (
    on_commit_email,
    send_career_application_notification,
)

from .models import CareerApplication, ContactEnquiry, WebsiteFeedback


def index(request):
    if request.method == "POST" and request.POST.get("form_type") == "website_feedback":
        name = request.POST.get("name", "").strip()
        institute = request.POST.get("institute", "").strip()
        rating = request.POST.get("rating", "").strip()
        feedback = request.POST.get("feedback", "").strip()

        if not name or not rating or not feedback:
            messages.error(request, "Please add your name, star rating and feedback.")
            return redirect(f"{reverse('index')}#reviews")

        try:
            rating_value = int(rating)
        except ValueError:
            rating_value = 0

        if rating_value < 1 or rating_value > 5:
            messages.error(request, "Please select a rating between 1 and 5 stars.")
            return redirect(f"{reverse('index')}#reviews")

        WebsiteFeedback.objects.create(
            name=name,
            institute=institute,
            rating=rating_value,
            feedback=feedback,
        )

        messages.success(request, "Thank you. Your feedback has been added.")
        return redirect(f"{reverse('index')}#reviews")

    visible_feedback = WebsiteFeedback.objects.filter(is_visible=True)
    recent_feedback = visible_feedback[:12]
    feedback_count = visible_feedback.count()
    average_rating = visible_feedback.aggregate(avg_rating=Avg("rating"))["avg_rating"] or 0

    return render(
        request,
        "index.html",
        {
            "recent_feedback": recent_feedback,
            "feedback_count": feedback_count,
            "average_rating": average_rating,
        },
    )


def download_android_app(request):
    configured_path = Path(settings.STUDENT_APP_APK_PATH)
    apk_path = configured_path
    if not apk_path.is_file():
        fallback_path = Path(settings.BASE_DIR) / "static" / "apk" / "UltraCoachMatrix.apk"
        if fallback_path.is_file():
            apk_path = fallback_path
    if not apk_path.is_file():
        raise Http404("The Android application is not available.")
    return FileResponse(
        apk_path.open("rb"),
        as_attachment=True,
        filename="UltraCoachMatrix.apk",
        content_type="application/vnd.android.package-archive",
    )


def contact_us(request):
    if request.method == "POST":
        required_fields = ("name", "school", "phone", "email", "enquiry_type")
        missing_fields = [field for field in required_fields if not request.POST.get(field, "").strip()]

        if missing_fields:
            messages.error(request, "Please fill all required fields.")
            return render(request, "web_contact_us.html", {"form_data": request.POST})

        email = request.POST.get("email", "").strip()
        try:
            validate_email(email)
        except ValidationError:
            messages.error(request, "Please enter a valid email address.")
            return render(request, "web_contact_us.html", {"form_data": request.POST})

        enquiry_type = request.POST.get("enquiry_type", "").strip()
        institution_size = request.POST.get("student_count", "").strip()

        if enquiry_type not in dict(ContactEnquiry.ENQUIRY_TYPE_CHOICES):
            messages.error(request, "Please select a valid enquiry type.")
            return render(request, "web_contact_us.html", {"form_data": request.POST})

        if institution_size and institution_size not in dict(ContactEnquiry.INSTITUTION_SIZE_CHOICES):
            messages.error(request, "Please select a valid institution size.")
            return render(request, "web_contact_us.html", {"form_data": request.POST})

        name = request.POST.get("name", "").strip()
        school = request.POST.get("school", "").strip()
        phone = request.POST.get("phone", "").strip()
        message = request.POST.get("message", "").strip()

        ContactEnquiry.objects.create(
            name=name,
            school=school,
            phone=phone,
            email=email,
            enquiry_type=enquiry_type,
            institution_size=institution_size,
            message=message,
        )

        messages.success(request, "Thank you. Your enquiry has been submitted successfully.")
        return redirect("web_contact_us")

    return render(request, "web_contact_us.html")



def features(request):
    return render(request, 'features.html')


def careers(request):
    open_role = "sales_executive"
    resume_extensions = {".pdf", ".doc", ".docx"}
    max_resume_size = 5 * 1024 * 1024

    if request.method == "POST":
        required_fields = ("full_name", "email", "phone", "experience", "qualification", "city")
        missing_fields = [field for field in required_fields if not request.POST.get(field, "").strip()]
        resume = request.FILES.get("resume")

        if missing_fields or not resume:
            messages.error(request, "Please fill all required career application fields and upload your resume.")
            return render(
                request,
                "career.html",
                {
                    "form_data": request.POST,
                    "experience_choices": CareerApplication.EXPERIENCE_CHOICES,
                },
            )

        resume_extension = Path(resume.name).suffix.lower()
        if resume_extension not in resume_extensions:
            messages.error(request, "Please upload your resume as a PDF, DOC or DOCX file.")
            return render(
                request,
                "career.html",
                {
                    "form_data": request.POST,
                    "experience_choices": CareerApplication.EXPERIENCE_CHOICES,
                },
            )

        if resume.size > max_resume_size:
            messages.error(request, "Resume file size must be 5 MB or smaller.")
            return render(
                request,
                "career.html",
                {
                    "form_data": request.POST,
                    "experience_choices": CareerApplication.EXPERIENCE_CHOICES,
                },
            )

        email = request.POST.get("email", "").strip()
        try:
            validate_email(email)
        except ValidationError:
            messages.error(request, "Please enter a valid email address.")
            return render(
                request,
                "career.html",
                {
                    "form_data": request.POST,
                    "experience_choices": CareerApplication.EXPERIENCE_CHOICES,
                },
            )

        experience = request.POST.get("experience", "").strip()
        if experience not in dict(CareerApplication.EXPERIENCE_CHOICES):
            messages.error(request, "Please select a valid experience range.")
            return render(
                request,
                "career.html",
                {
                    "form_data": request.POST,
                    "experience_choices": CareerApplication.EXPERIENCE_CHOICES,
                },
            )

        application = CareerApplication.objects.create(
            full_name=request.POST.get("full_name", "").strip(),
            email=email,
            phone=request.POST.get("phone", "").strip(),
            role=open_role,
            experience=experience,
            qualification=request.POST.get("qualification", "").strip(),
            city=request.POST.get("city", "").strip(),
            notice_period=request.POST.get("notice_period", "").strip(),
            resume=resume,
            portfolio_link=request.POST.get("portfolio_link", "").strip(),
            cover_letter=request.POST.get("cover_letter", "").strip(),
        )
        on_commit_email(send_career_application_notification, application.pk)

        messages.success(request, "Thank you. Your career application has been submitted successfully.")
        return redirect(f"{reverse('web_careers')}#career-application")

    return render(
        request,
        "career.html",
        {
            "experience_choices": CareerApplication.EXPERIENCE_CHOICES,
        },
    )


def privacy_policy(request):
    return render(request, "legal_page.html", {
        "eyebrow": "Privacy Policy",
        "title": "Privacy Policy",
        "intro": "How UltraCoachMatrix handles enquiry, institute and communication data shared through the public website.",
        "sections": [
            {
                "heading": "Information we collect",
                "body": "When you submit an enquiry, we collect details such as your name, institute name, phone number, email address, enquiry type, institute size and message."
            },
            {
                "heading": "How we use information",
                "body": "We use this information to respond to demo requests, pricing questions, onboarding needs and product support conversations."
            },
            {
                "heading": "Data sharing",
                "body": "We do not sell enquiry information. Details may be shared internally only with team members who need them to respond to your request."
            },
            {
                "heading": "Contact",
                "body": "For privacy questions, email ultoxy.tech@gmail.com or call +91 7776824564."
            },
        ],
    })


def terms(request):
    return render(request, "legal_page.html", {
        "eyebrow": "Terms",
        "title": "Terms of Use",
        "intro": "Basic terms for using the UltraCoachMatrix public website and requesting product information.",
        "sections": [
            {
                "heading": "Website use",
                "body": "The public website is provided for product information, demo enquiries and support contact. Do not misuse the site, forms or communication channels."
            },
            {
                "heading": "Product information",
                "body": "Feature, pricing and service information may change as the platform evolves. Final commercial terms should be confirmed during the demo or onboarding discussion."
            },
            {
                "heading": "Accounts and access",
                "body": "Dashboard and login access are intended only for authorized users connected with registered institutes."
            },
            {
                "heading": "Support",
                "body": "For questions about these terms, email ultoxy.tech@gmail.com or call +91 7776824564."
            },
        ],
    })


def support(request):
    return render(request, "legal_page.html", {
        "eyebrow": "Support",
        "title": "Support Center",
        "intro": "Get help with demos, onboarding, institute setup, fees, attendance, exams, reports and mobile apps.",
        "sections": [
            {
                "heading": "Call support",
                "body": "Call +91 7776824564 from Monday to Saturday, 9:30 AM to 6:30 PM."
            },
            {
                "heading": "Email support",
                "body": "Send your query to ultoxy.tech@gmail.com with your institute name and contact number."
            },
            {
                "heading": "Product demos",
                "body": "Use the enquiry form to request a guided walkthrough of the admin dashboard, student app, teacher app and reports."
            },
            {
                "heading": "Setup help",
                "body": "The team can guide you through courses, batches, students, teachers, fee plans, attendance and exam setup."
            },
        ],
    })
