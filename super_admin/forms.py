from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.db import transaction

from .models import Institute, UserProfile


class InstituteSignupForm(UserCreationForm):
    institute_name = forms.CharField(max_length=160, label="Institute name")
    institute_code = forms.SlugField(max_length=40, label="Institute code")
    owner_name = forms.CharField(max_length=120, label="Owner name")
    phone = forms.CharField(max_length=20, label="Contact number")
    email = forms.EmailField(label="Email")

    class Meta:
        model = User
        fields = (
            "institute_name",
            "institute_code",
            "owner_name",
            "phone",
            "email",
            "username",
            "password1",
            "password2",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
            self.fields['password1'].help_text = None
            self.fields['password2'].help_text = None
            self.fields['username'].help_text = None



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
                owner_name=self.cleaned_data["owner_name"],
                phone=self.cleaned_data["phone"],
                email=self.cleaned_data["email"],
            )
            UserProfile.objects.create(
                user=user,
                institute=institute,
                role=UserProfile.Role.INSTITUTE_ADMIN,
                phone=self.cleaned_data["phone"],
            )

        return user
