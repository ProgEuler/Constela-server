from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from api.models import PushDevice, User, UserProfile


class PushDeviceAdminTests(TestCase):
    def setUp(self):
        member = User.objects.create_user(username='member', email='member@example.com')
        self.profile = UserProfile.objects.create(user=member, username='member')
        self.device = PushDevice.objects.create(profile=self.profile, token='fcm-token-' + 'x' * 140, platform='android')
        admin_user = User.objects.create_superuser(username='root', email='root@example.com', password='x-Test-123')
        self.client.force_login(admin_user)

    def test_list_and_profile_page_show_devices(self):
        page = self.client.get(reverse('admin:api_pushdevice_changelist'))
        self.assertEqual(page.status_code, 200)
        html = page.content.decode()
        self.assertIn('member@example.com', html)
        self.assertIn('fcm-token-', html)

        profile_page = self.client.get(reverse('admin:api_userprofile_change', args=[self.profile.pk]))
        self.assertEqual(profile_page.status_code, 200)
        self.assertIn('Push devices', profile_page.content.decode())

    @patch('api.push_notifications.send_fcm_push', return_value={'status': 'completed', 'success': 1, 'failures': 0})
    def test_row_button_sends_test_push(self, send):
        url = reverse('admin:api_pushdevice_send_test_push_row', args=[self.device.pk])
        response = self.client.get(url, follow=True)
        self.assertEqual(response.status_code, 200)
        send.assert_called_once()
        self.assertEqual(send.call_args.args[0], [self.device.token])
        self.assertIn('Test push delivered to 1 device', response.content.decode())

    @patch('api.push_notifications.send_fcm_push',
           return_value={'status': 'error', 'message': 'Firebase Admin SDK not initialized.'})
    def test_reports_missing_firebase_configuration(self, _send):
        url = reverse('admin:api_pushdevice_send_test_push_row', args=[self.device.pk])
        response = self.client.get(url, follow=True)
        self.assertIn('Firebase Admin SDK not initialized', response.content.decode())
