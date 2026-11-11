"""Remove stored files when the rows that own them are deleted.

Django deletes rows (including cascades from deleting a user) but never the
files in storage. These handlers cover every deletion path: in-app account
deletion, admin deletions, and the bulk clean-up of unfinished sign-ups.
Files are removed only after the database transaction commits, so a rolled
back deletion never loses files.
"""
import logging

from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from api.models import DirectMessage, UserPhoto, UserProfile

logger = logging.getLogger(__name__)


def _delete_after_commit(storage, name):
    if not name:
        return

    def _delete():
        try:
            storage.delete(name)
        except Exception:
            logger.exception("Could not delete stored file %s", name)

    transaction.on_commit(_delete)


@receiver(post_delete, sender=UserPhoto, dispatch_uid="delete_user_photo_file")
def delete_user_photo_file(sender, instance, **kwargs):
    if instance.image:
        _delete_after_commit(instance.image.storage, instance.image.name)


@receiver(post_delete, sender=UserProfile, dispatch_uid="delete_profile_verification_files")
def delete_profile_verification_files(sender, instance, **kwargs):
    for field_file in (instance.face_selfie, instance.face_selfie_left, instance.face_selfie_right):
        if field_file:
            _delete_after_commit(field_file.storage, field_file.name)


@receiver(post_delete, sender=DirectMessage, dispatch_uid="delete_direct_message_media")
def delete_direct_message_media(sender, instance, **kwargs):
    from api.chat_media import audio_storage_key, image_storage_key

    _delete_after_commit(default_storage, image_storage_key(instance.image_url))
    _delete_after_commit(default_storage, audio_storage_key(instance.audio_url))
