from django.db.models.signals import post_save
from django.dispatch import receiver

from .media_utils import create_institute_media_folders
from .models import Institute


@receiver(post_save, sender=Institute)
def create_media_folders_for_institute(sender, instance, created, **kwargs):
    if created:
        create_institute_media_folders(instance)
