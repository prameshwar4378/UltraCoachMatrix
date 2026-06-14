from datetime import datetime

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.shortcuts import redirect, render

from UltraCoachMatrix.email_notifications import queue_template_email

from .models import ContactEnquiry


def index(request):
    return render(request, "index.html")


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

        enquiry = ContactEnquiry.objects.create(
            name=name,
            school=school,
            phone=phone,
            email=email,
            enquiry_type=enquiry_type,
            institution_size=institution_size,
            message=message,
        )

        email_context = {
            "enquiry": enquiry,
            "full_name": name,
            "name": name,
            "school": school,
            "phone": phone,
            "email": email,
            "enquiry_type": enquiry.get_enquiry_type_display(),
            "institution_size": enquiry.get_institution_size_display() if enquiry.institution_size else "N/A",
            "message": message or "No message provided.",
            "submitted_on": datetime.now().strftime("%d %B %Y, %I:%M %p"),
        }
        queue_template_email(
            subject="New UltraCoachMatrix Coaching Software Enquiry",
            template_name="Enquiry_Mail.html",
            recipients=["prameshwar4378@gmail.com"],
            context=email_context,
            reply_to=[email],
        )

        messages.success(request, "Thank you. Your enquiry has been submitted successfully.")
        return redirect("web_contact_us")

    return render(request, "web_contact_us.html")



def features(request):
    return render(request, 'features.html')


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
