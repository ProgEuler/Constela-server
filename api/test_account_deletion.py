from decimal import Decimal

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from api.models import DirectMessage, Transaction, User, UserPhoto, UserProfile

STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


@override_settings(STORAGES=STORAGES)
class AccountDeletionTests(TestCase):
    def make_member(self, name):
        user = User.objects.create_user(username=name, email=f'{name}@example.com')
        profile = UserProfile.objects.create(user=user, username=name)
        return user, profile

    def setUp(self):
        self.user, self.profile = self.make_member('leaving')
        _, self.other = self.make_member('staying')

        self.photo_key = default_storage.save('profile_photos/leaving.jpg', ContentFile(b'photo'))
        UserPhoto.objects.create(profile=self.profile, image=self.photo_key, is_main=True)

        self.profile.face_selfie.save('verification.jpg', ContentFile(b'selfie'), save=True)
        self.selfie_key = self.profile.face_selfie.name

        self.chat_image = default_storage.save('chat_images/pic.jpg', ContentFile(b'img'))
        self.chat_audio = default_storage.save('chat_audio/voice.m4a', ContentFile(b'aud'))
        DirectMessage.objects.create(sender=self.profile, receiver=self.other, image_url=self.chat_image)
        DirectMessage.objects.create(sender=self.other, receiver=self.profile, audio_url=self.chat_audio)

        self.tx = Transaction.objects.create(user=self.profile, plan_name='premium_plus:monthly',
                                             amount=Decimal('9.99'), status='successful')

    def assert_files_gone(self):
        for key in (self.photo_key, self.selfie_key, self.chat_image, self.chat_audio):
            self.assertFalse(default_storage.exists(key), key)

    def test_in_app_deletion_removes_files_and_keeps_anonymous_payment(self):
        client = APIClient()
        client.force_authenticate(self.user)
        with self.captureOnCommitCallbacks(execute=True):
            response = client.post('/api/settings/delete-account/')
        self.assertEqual(response.status_code, 200)

        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        self.assertFalse(DirectMessage.objects.exists())
        self.assert_files_gone()

        self.tx.refresh_from_db()
        self.assertIsNone(self.tx.user)
        self.assertEqual(self.tx.amount, Decimal('9.99'))
        self.assertIn('deleted account', str(self.tx))

        # The other member's account and files are untouched.
        self.assertTrue(UserProfile.objects.filter(pk=self.other.pk).exists())

    def test_bulk_deletion_also_removes_files(self):
        # e.g. the automatic clean-up of unfinished sign-ups deletes users in bulk.
        with self.captureOnCommitCallbacks(execute=True):
            User.objects.filter(pk=self.user.pk).delete()
        self.assert_files_gone()
        self.assertTrue(Transaction.objects.filter(pk=self.tx.pk, user__isnull=True).exists())
