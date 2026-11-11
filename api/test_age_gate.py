from django.test import TestCase
from rest_framework.test import APIClient

from api.models import User, UserProfile


class AgeGateTests(TestCase):
    """Constela is adults-only: the API must refuse ages under 18."""

    def setUp(self):
        self.user = User.objects.create_user(username='member', email='member@example.com')
        self.profile = UserProfile.objects.create(user=self.user, username='member', age=25,
                                                  face_verification_status='approved')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def patch_age(self, age):
        return self.client.patch('/api/profile/me/', {'age': age}, format='json')

    def test_under_18_is_rejected(self):
        response = self.patch_age(16)
        self.assertEqual(response.status_code, 400)
        self.assertIn('age', response.data)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.age, 25)

    def test_18_and_over_is_accepted(self):
        self.assertEqual(self.patch_age(18).status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.age, 18)

    def test_absurd_age_is_rejected(self):
        self.assertEqual(self.patch_age(200).status_code, 400)
