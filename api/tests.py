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
        Friendship.objects.create(sender=named_profile, receiver=self.profile, status='declined')

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
                data={
                    'type': 'friend_request_received',
                    'profile_id': 'sender-id',
                    'sender_photo': 'https://expired.example/photo.jpg',
                },
            )

        self.assertTrue(queued)
        notification = Notification.objects.get(recipient=user)
        self.assertNotIn('sender_photo', notification.data)
        submit.assert_called_once()

    def test_notification_list_returns_a_fresh_sender_photo(self):
        recipient = User.objects.create(email='recipient@example.com', username='recipient')
        UserProfile.objects.create(user=recipient, username='recipient')
        sender = User.objects.create(email='sender@example.com', username='sender')
        sender_profile = UserProfile.objects.create(user=sender, username='sender')
        UserPhoto.objects.create(
            profile=sender_profile,
            image='profile_photos/sender.jpg',
            is_main=True,
        )
        Notification.objects.create(
            recipient=recipient,
            title='New Friend Request',
            body='Sender sent you a friend request',
            type='friend_request_received',
            data={
                'profile_id': str(sender_profile.id),
                'sender_photo': 'https://expired.example/photo.jpg',
            },
        )
        client = APIClient()
        client.force_authenticate(recipient)

        with patch('api.views.get_cloudinary_url', return_value='https://fresh.example/photo.jpg'):
            response = client.get('/api/notifications/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data['results'][0]['data']['sender_photo'],
            'https://fresh.example/photo.jpg',
        )


@override_settings(
    GOOGLE_OAUTH_WEB_CLIENT_ID='constela-android-web-client.apps.googleusercontent.com',
)
class GoogleAuthTests(TestCase):
    def test_google_token_must_match_constela_client_id(self):
        with patch('firebase_admin.auth.verify_id_token', side_effect=ValueError), patch('requests.get') as get:
            get.return_value.status_code = 200
            get.return_value.json.return_value = {
                'aud': 'constela-android-web-client.apps.googleusercontent.com',
                'email': 'google-user@example.com',
                'name': 'Google User',
            }
            accepted = self.client.post('/api/auth/google/', {'id_token': 'valid-token'}, format='json')

            get.return_value.json.return_value['aud'] = 'another-app.apps.googleusercontent.com'
            rejected = self.client.post('/api/auth/google/', {'id_token': 'wrong-audience'}, format='json')

        self.assertEqual(accepted.status_code, 200)
        self.assertTrue(User.objects.filter(email='google-user@example.com').exists())
        self.assertEqual(rejected.status_code, 400)


@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class VoiceMessageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(email='voice@example.com', username='voice', is_verified=True)
        self.profile = UserProfile.objects.create(user=self.user, username='voice', is_verified=True)
        self.recipient_user = User.objects.create(email='listener@example.com', username='listener', is_verified=True)
        self.recipient = UserProfile.objects.create(user=self.recipient_user, username='listener', is_verified=True)
        Friendship.objects.create(sender=self.profile, receiver=self.recipient, status='accepted')
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
            'audio_ref': upload.data['audio_ref'],
            'audio_duration': 12,
        }, format='json')
        self.assertEqual(message.status_code, 201)
        self.assertEqual(message.data['audio_url'], upload.data['audio_url'])
        self.assertIsNotNone(message.data['audio_url_expires_at'])
        self.assertEqual(message.data['audio_duration'], 12)
        self.assertTrue(DirectMessage.objects.get(id=message.data['id']).audio_url.startswith('chat_audio/'))

    def test_image_upload_and_message_store_a_stable_key(self):
        upload = self.client.post(
            '/api/chat/upload-image/',
            {'image': SimpleUploadedFile('photo.jpg', b'image', content_type='image/jpeg')},
            format='multipart',
        )
        self.assertEqual(upload.status_code, 201)

        message = self.client.post('/api/chat/direct/', {
            'receiver': str(self.recipient.id),
            'image_url': upload.data['image_url'],
            'image_ref': upload.data['image_ref'],
        }, format='json')
        self.assertEqual(message.status_code, 201)
        self.assertEqual(message.data['image_url'], upload.data['image_url'])
        self.assertIsNotNone(message.data['image_url_expires_at'])
        self.assertTrue(DirectMessage.objects.get(id=message.data['id']).image_url.startswith('chat_images/'))

    def test_expired_legacy_r2_url_is_refreshed_in_history(self):
        legacy_url = (
            'https://account.r2.cloudflarestorage.com/bucket/chat_audio/old.m4a'
            '?X-Amz-Date=20260924T120000Z&X-Amz-Expires=3600&X-Amz-Signature=expired'
        )
        DirectMessage.objects.create(
            sender=self.profile,
            receiver=self.recipient,
            audio_url=legacy_url,
            audio_duration=4,
        )

        with override_settings(
            AWS_S3_ENDPOINT_URL='https://account.r2.cloudflarestorage.com',
            AWS_STORAGE_BUCKET_NAME='bucket',
        ), patch('api.chat_media.default_storage.url', return_value='https://fresh.example/audio') as storage_url:
            history = self.client.get(f'/api/chat/direct/history/{self.recipient.id}/')

        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.data[0]['audio_url'], 'https://fresh.example/audio')
        self.assertIsNotNone(history.data[0]['audio_url_expires_at'])
        storage_url.assert_called_once_with('chat_audio/old.m4a')

    def test_expired_legacy_image_url_is_refreshed_in_history(self):
        legacy_url = (
            'https://account.r2.cloudflarestorage.com/bucket/chat_images/old.jpg'
            '?X-Amz-Date=20260924T120000Z&X-Amz-Expires=3600&X-Amz-Signature=expired'
        )
        DirectMessage.objects.create(
            sender=self.profile,
            receiver=self.recipient,
            image_url=legacy_url,
        )

        with override_settings(
            AWS_S3_ENDPOINT_URL='https://account.r2.cloudflarestorage.com',
            AWS_STORAGE_BUCKET_NAME='bucket',
        ), patch('api.chat_media.default_storage.url', return_value='https://fresh.example/image') as storage_url:
            history = self.client.get(f'/api/chat/direct/history/{self.recipient.id}/')

        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.data[0]['image_url'], 'https://fresh.example/image')
        self.assertIsNotNone(history.data[0]['image_url_expires_at'])
        storage_url.assert_called_once_with('chat_images/old.jpg')

    def test_audio_refresh_requires_a_conversation_participant(self):
        message = DirectMessage.objects.create(
            sender=self.profile,
            receiver=self.recipient,
            audio_url='chat_audio/private.m4a',
            audio_duration=3,
        )
        allowed = self.client.get(f'/api/chat/direct/{message.id}/')
        self.assertEqual(allowed.status_code, 200)
        self.assertIsNotNone(allowed.data['audio_url_expires_at'])

        outsider_user = User.objects.create(email='outsider@example.com', username='outsider', is_verified=True)
        UserProfile.objects.create(user=outsider_user, username='outsider', is_verified=True)
        self.client.force_authenticate(outsider_user)
        denied = self.client.get(f'/api/chat/direct/{message.id}/')
        self.assertEqual(denied.status_code, 404)

    def test_invalid_audio_reference_is_rejected(self):
        response = self.client.post('/api/chat/direct/', {
            'receiver': str(self.recipient.id),
            'audio_url': '/media/chat_audio/voice.m4a',
            'audio_ref': 'tampered',
            'audio_duration': 2,
        }, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertFalse(DirectMessage.objects.exists())

    def test_invalid_image_reference_is_rejected(self):
        response = self.client.post('/api/chat/direct/', {
            'receiver': str(self.recipient.id),
            'image_url': '/media/chat_images/photo.jpg',
            'image_ref': 'tampered',
        }, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertFalse(DirectMessage.objects.exists())

    def test_history_prefetch_does_not_mark_messages_read(self):
        message = DirectMessage.objects.create(
            sender=self.recipient,
            receiver=self.profile,
            content='unread',
        )

        prefetched = self.client.get(
            f'/api/chat/direct/history/{self.recipient.id}/?prefetch=1'
        )
        self.assertEqual(prefetched.status_code, 200)
        message.refresh_from_db()
        self.assertIsNone(message.read_at)

        opened = self.client.get(f'/api/chat/direct/history/{self.recipient.id}/')
        self.assertEqual(opened.status_code, 200)
        message.refresh_from_db()
        self.assertIsNotNone(message.read_at)

    def test_history_loads_fifty_messages_then_fetches_older_page(self):
        created = [
            DirectMessage.objects.create(
                sender=self.profile,
                receiver=self.recipient,
                content=f'message {index}',
            )
            for index in range(55)
        ]

        first_page = self.client.get(f'/api/chat/direct/history/{self.recipient.id}/')
        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(len(first_page.data), 50)
        self.assertEqual(first_page.data[0]['id'], str(created[-1].id))

        second_page = self.client.get(
            f'/api/chat/direct/history/{self.recipient.id}/',
            {'before': first_page.data[-1]['timestamp']},
        )
        self.assertEqual(second_page.status_code, 200)
        self.assertEqual(len(second_page.data), 5)
        self.assertFalse(
            {message['id'] for message in first_page.data}
            & {message['id'] for message in second_page.data}
        )
