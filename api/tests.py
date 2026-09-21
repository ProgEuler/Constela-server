from unittest.mock import patch

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from api.models import DirectMessage, Friendship, Match, Notification, User, UserPhoto, UserProfile
from api.push_notifications import send_push_notification_to_user


@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class FeedQueryCountTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(email='me@example.com', username='me', is_verified=True)
        self.profile = UserProfile.objects.create(
            user=self.user,
            username='me',
            is_verified=True,
            gender='man',
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def add_candidates(self, count, start=0):
        profiles = []
        for number in range(start, start + count):
            user = User.objects.create(
                email=f'user{number}@example.com',
                username=f'user{number}',
                is_verified=True,
            )
            profile = UserProfile.objects.create(
                user=user,
                username=f'user{number}',
                is_verified=True,
                gender='woman',
            )
            UserPhoto.objects.create(
                profile=profile,
                image=f'profile_photos/user{number}.jpg',
                is_main=True,
            )
            profiles.append(profile)
        return profiles

    def count_queries(self, path):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
        return len(queries)

    def test_feed_queries_do_not_grow_per_profile(self):
        self.add_candidates(6)
        small_feed_queries = self.count_queries('/api/matching/perfect-match/?page_size=50')
        small_friend_queries = self.count_queries('/api/friends/suggestions/?limit=50')

        self.add_candidates(10, start=6)

        self.assertLessEqual(
            self.count_queries('/api/matching/perfect-match/?page_size=50'),
            small_feed_queries + 1,
        )
        self.assertLessEqual(
            self.count_queries('/api/friends/suggestions/?limit=50'),
            small_friend_queries + 1,
        )

    def test_thread_queries_do_not_grow_per_conversation(self):
        first_profiles = self.add_candidates(6)
        for profile in first_profiles:
            Match.objects.create(user1=self.profile, user2=profile, status='matched')
            DirectMessage.objects.create(sender=self.profile, receiver=profile, content='hello')

        small_query_count = self.count_queries('/api/chat/direct/threads/?type=dating')

        more_profiles = self.add_candidates(10, start=6)
        for profile in more_profiles:
            Match.objects.create(user1=self.profile, user2=profile, status='matched')
            DirectMessage.objects.create(sender=self.profile, receiver=profile, content='hello')

        self.assertLessEqual(
            self.count_queries('/api/chat/direct/threads/?type=dating'),
            small_query_count + 1,
        )

    def test_friend_request_queries_do_not_grow_per_request(self):
        first_profiles = self.add_candidates(6)
        for profile in first_profiles:
            Friendship.objects.create(sender=profile, receiver=self.profile, status='pending')

        small_query_count = self.count_queries('/api/friends/requests/')

        more_profiles = self.add_candidates(10, start=6)
        for profile in more_profiles:
            Friendship.objects.create(sender=profile, receiver=self.profile, status='pending')

        self.assertLessEqual(
            self.count_queries('/api/friends/requests/'),
            small_query_count + 1,
        )

    def test_friend_suggestions_searches_visible_name_and_username(self):
        named_user = User.objects.create(
            email='alicia@example.com',
            username='quiet-star',
            first_name='Alicia',
            is_verified=True,
        )
        named_profile = UserProfile.objects.create(
            user=named_user,
            username='quiet-star',
            is_verified=True,
            gender='woman',
        )

        for search_term in ('Alicia', 'quiet-star'):
            response = self.client.get('/api/friends/suggestions/', {'search': search_term})
            self.assertEqual(response.status_code, 200)
            self.assertEqual([item['id'] for item in response.data['results']], [named_profile.id])


class PushNotificationTests(TestCase):
    def test_push_is_queued_without_blocking_notification_creation(self):
        user = User.objects.create(email='recipient@example.com', username='recipient')
        UserProfile.objects.create(user=user, username='recipient', push_token='device-token')

        with patch('api.push_notifications._push_executor.submit') as submit:
            queued = send_push_notification_to_user(
                user,
                title='New Friend Request',
                body='Someone sent you a friend request',
                data={'type': 'friend_request_received'},
            )

        self.assertTrue(queued)
        self.assertTrue(Notification.objects.filter(recipient=user).exists())
        submit.assert_called_once()


@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class VoiceMessageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(email='voice@example.com', username='voice', is_verified=True)
        self.profile = UserProfile.objects.create(user=self.user, username='voice', is_verified=True)
        self.recipient_user = User.objects.create(email='listener@example.com', username='listener', is_verified=True)
        self.recipient = UserProfile.objects.create(user=self.recipient_user, username='listener', is_verified=True)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_audio_upload_and_message_are_serialized(self):
        upload = self.client.post(
            '/api/chat/upload-audio/',
            {'audio': SimpleUploadedFile('voice.m4a', b'audio', content_type='audio/mp4')},
            format='multipart',
        )
        self.assertEqual(upload.status_code, 201)

        message = self.client.post('/api/chat/direct/', {
            'receiver': str(self.recipient.id),
            'content': '',
            'audio_url': upload.data['audio_url'],
            'audio_duration': 12,
        }, format='json')
        self.assertEqual(message.status_code, 201)
        self.assertEqual(message.data['audio_url'], upload.data['audio_url'])
        self.assertEqual(message.data['audio_duration'], 12)
