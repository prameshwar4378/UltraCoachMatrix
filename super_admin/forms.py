from datetime import timedelta

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from .models import Institute, InstituteSubscription, UserProfile


FREE_TRIAL_DAYS = 14


class InstituteSignupForm(UserCreationForm):
    institute_name = forms.CharField(max_length=160, label="Institute name")
    institute_code = forms.SlugField(max_length=40, label="Institute code")
    institute_type = forms.ChoiceField(
        label="Select institute type",
        choices=Institute.InstituteType.choices,
        initial=Institute.InstituteType.COACHING_CLASSES,
    )
    institute_logo = forms.ImageField(label="Institute logo", required=False)
    owner_name = forms.CharField(max_length=120, label="Owner name")
    phone = forms.CharField(max_length=20, label="Contact number")
    email = forms.EmailField(label="Email")
    address = forms.CharField(
        label="Institute address",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    class Meta:
        model = User
        fields = (
            "institute_name",
            "institute_code",
            "institute_type",
            "institute_logo",
            "owner_name",
            "phone",
            "email",
            "address",
            "username",
            "password1",
            "password2",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        self.fields["password1"].help_text = None
        self.fields["password2"].help_text = None
        self.fields["username"].help_text = None



    def clean_institute_code(self):
        code = self.cleaned_data["institute_code"]
        if Institute.objects.filter(code=code).exists():
            raise forms.ValidationError("This institute code is already used.")
        return code

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.first_name = self.cleaned_data["owner_name"]

        if commit:
            user.save()
            institute = Institute.objects.create(
                name=self.cleaned_data["institute_name"],
                code=self.cleaned_data["institute_code"],
                institute_type=self.cleaned_data["institute_type"],
                logo=self.cleaned_data.get("institute_logo"),
                owner_name=self.cleaned_data["owner_name"],
                phone=self.cleaned_data["phone"],
                email=self.cleaned_data["email"],
                address=self.cleaned_data["address"].strip(),
            )
            UserProfile.objects.create(
                user=user,
                institute=institute,
                role=UserProfile.Role.INSTITUTE_ADMIN,
                phone=self.cleaned_data["phone"],
                onboarding_completed_at=None,
            )
            trial_starts_on = timezone.localdate()
            InstituteSubscription.objects.create(
                institute=institute,
                plan=InstituteSubscription.Plan.FREE_TRIAL,
                starts_on=trial_starts_on,
                ends_on=trial_starts_on + timedelta(days=FREE_TRIAL_DAYS),
            )

        return user
