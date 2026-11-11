import io
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image
from rest_framework.test import APIClient

from api.models import User, UserPhoto, UserProfile

STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


def jpeg(name='photo.jpg'):
    buf = io.BytesIO()
    Image.new('RGB', (600, 800), (200, 120, 140)).save(buf, format='JPEG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/jpeg')


@override_settings(STORAGES=STORAGES)
@patch('api.push_notifications.send_push_notification_to_user', return_value=True)
class PhotoVerificationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='member', email='member@example.com')
        self.profile = UserProfile.objects.create(user=self.user, username='member', is_verified=True)
        UserPhoto.objects.create(profile=self.profile, image='profile_photos/main.jpg', is_main=True)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def submit(self, **files):
        return self.client.post('/api/auth/face-verify/', files, format='multipart')

    def test_single_live_photo_goes_to_pending_review(self, _push):
        response = self.submit(photo=jpeg())
        self.assertEqual(response.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.face_verification_status, 'pending')
        self.assertTrue(self.profile.face_selfie)
        self.assertFalse(self.profile.face_selfie_left)
        self.assertIsNotNone(self.profile.face_submitted_at)

    def test_old_app_builds_sending_front_photo_still_work(self, _push):
        self.assertEqual(self.submit(front=jpeg(), left=jpeg(), right=jpeg()).status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.face_verification_status, 'pending')

    def test_missing_photo_is_rejected(self, _push):
        self.assertEqual(self.submit().status_code, 400)

    def test_dashboard_api_decisions(self, push):
        moderator = User.objects.create_user(username='mod', email='mod@example.com', role='moderator', is_staff=True)
        self.submit(photo=jpeg())
        api = APIClient()
        api.force_authenticate(moderator)
        url = f'/api/admin/verifications/{self.profile.id}/action/'
        listing = api.get('/api/admin/verifications/')
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(len(listing.data['pending']), 1)
        row = listing.data['pending'][0]
        self.assertTrue(row['selfie_url'])
        self.assertEqual(len(row['profile_photo_urls']), 1)

        api.post(url, {'action': 'reject', 'reason': 'Face not visible'}, format='json')
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.face_verification_status, 'rejected')
        self.assertEqual(self.profile.face_verification_note, 'Face not visible')
        self.assertEqual(api.get('/api/admin/verifications/').data['rejected'][0]['reason'], 'Face not visible')
        self.assertFalse(self.profile.is_verified)

        api.post(url, {'action': 'approve'}, format='json')
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.face_verification_status, 'approved')
        self.assertTrue(self.profile.is_verified)
        self.assertEqual(self.profile.face_verification_note, '')
        self.assertTrue(self.profile.photos.filter(is_verified=True).exists())
        self.assertTrue(push.called)

    def test_admin_review_page_compares_and_decides(self, push):
        self.submit(photo=jpeg())
        admin_user = User.objects.create_superuser(username='root', email='root@example.com', password='x-Test-123')
        web = self.client_class()
        web.force_login(admin_user)

        changelist = reverse('admin:api_photoverification_changelist')
        # Opens on the pending queue by default.
        self.assertIn('face_verification_status__exact=pending', web.get(changelist)['Location'])
        page = web.get(changelist + '?face_verification_status__exact=pending')
        self.assertEqual(page.status_code, 200)
        html = page.content.decode()
        self.assertIn('Verification photo', html)
        self.assertIn('member', html)

        detail = reverse('admin:api_photoverification_change', args=[self.profile.pk])
        self.assertEqual(web.get(detail).status_code, 200)

        # Row "Approve" button.
        approve = reverse('admin:api_photoverification_approve_row', args=[self.profile.pk])
        self.assertEqual(web.get(approve).status_code, 302)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.face_verification_status, 'approved')

        # Reject with a reason from the detail form.
        response = web.post(detail, {'face_verification_status': 'rejected',
                                     'face_verification_note': 'Different person'})
        self.assertEqual(response.status_code, 302)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.face_verification_status, 'rejected')
        self.assertEqual(self.profile.face_verification_note, 'Different person')
        self.assertFalse(self.profile.is_verified)
