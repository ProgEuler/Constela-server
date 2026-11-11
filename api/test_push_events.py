from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from api.models import Friendship, User, UserProfile


@patch('api.views.send_push_notification_to_user', return_value=True)
class PushEventTests(TestCase):
    def member(self, name, lang='en'):
        user = User.objects.create_user(username=name, email=f'{name}@example.com')
        profile = UserProfile.objects.create(user=user, username=name, is_verified=True,
                                             preferred_language=lang, face_verification_status='approved')
        return user, profile

    def setUp(self):
        self.a_user, self.a = self.member('alice')
        self.b_user, self.b = self.member('bruno', lang='fr')

    def act(self, user, target, action):
        client = APIClient()
        client.force_authenticate(user)
        return client.post(f'/api/matching/{target.id}/action/', {'action': action}, format='json')

    def test_like_sends_anonymous_push_in_recipients_language(self, push):
        self.assertEqual(self.act(self.a_user, self.b, 'liked').status_code, 200)
        push.assert_called_once()
        kwargs = push.call_args.kwargs
        self.assertEqual(kwargs['user'], self.b_user)
        self.assertEqual(kwargs['title'], "Quelqu'un vous a liké 💜")  # Bruno uses French
        self.assertEqual(kwargs['data'], {'type': 'like'})  # no profile id: who it is stays premium

    def test_superlike_push(self, push):
        self.act(self.b_user, self.a, 'superliked')
        self.assertEqual(push.call_args.kwargs['data'], {'type': 'superlike'})
        self.assertIn('Super Like', push.call_args.kwargs['title'])

    def test_mutual_like_sends_match_not_like(self, push):
        self.act(self.a_user, self.b, 'liked')
        push.reset_mock()
        self.act(self.b_user, self.a, 'liked')
        types = [c.kwargs['data']['type'] for c in push.call_args_list]
        self.assertEqual(sorted(types), ['match', 'match'])

    def test_liking_again_does_not_repeat_push(self, push):
        self.act(self.a_user, self.b, 'liked')
        self.act(self.a_user, self.b, 'liked')
        self.assertEqual(push.call_count, 1)

    def test_like_push_respects_toggle(self, push):
        self.b.likes_push = False
        self.b.save()
        self.act(self.a_user, self.b, 'liked')
        push.assert_not_called()

    def test_auto_accepted_request_notifies_original_sender(self, push):
        Friendship.objects.create(sender=self.a, receiver=self.b, status='pending')
        client = APIClient()
        client.force_authenticate(self.b_user)
        response = client.post('/api/friends/send_request/', {'user_id': str(self.a.id)}, format='json')
        self.assertEqual(response.status_code, 200)
        push.assert_called_once()
        self.assertEqual(push.call_args.kwargs['user'], self.a_user)
        self.assertEqual(push.call_args.kwargs['data']['type'], 'friend_request_accepted')
        self.assertEqual(push.call_args.kwargs['title'], 'Friend Request Accepted')
