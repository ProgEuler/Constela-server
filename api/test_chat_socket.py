from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase, override_settings
from rest_framework_simplejwt.tokens import AccessToken

from api.models import Friendship, User, UserProfile
from api.chat_media import sign_audio_upload, sign_image_upload
from core.asgi import application


@override_settings(
    CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}},
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)
class ChatSocketPrivacyTest(TransactionTestCase):
    def setUp(self):
        self.profiles = []
        self.tokens = []
        for index in range(3):
            user = User.objects.create_user(
                email=f'chat{index}@example.com',
                username=f'chat{index}',
                password='test-password',
                is_verified=True,
            )
            self.profiles.append(UserProfile.objects.create(user=user, username=f'chat{index}'))
            self.tokens.append(str(AccessToken.for_user(user)))
        Friendship.objects.create(
            sender=self.profiles[0], receiver=self.profiles[1], status='accepted'
        )

    def test_direct_messages_only_reach_their_two_participants(self):
        async_to_sync(self._privacy_scenario)()

    async def _privacy_scenario(self):
        sockets = []
        for token in self.tokens:
            socket = WebsocketCommunicator(application, f'/ws/chat/?token={token}')
            connected, _ = await socket.connect(timeout=10)
            self.assertTrue(connected)
            self.assertEqual((await socket.receive_json_from(timeout=10))['type'], 'initial_presence')
            sockets.append(socket)

        sender, recipient, stranger = sockets
        self.assertEqual((await sender.receive_json_from(timeout=10))['type'], 'status_update')

        await sender.send_json_to({
            'type': 'direct_message',
            'temp_id': 'temp-private',
            'recipient_id': str(self.profiles[1].id),
            'content': 'private',
        })
        sender_message = await sender.receive_json_from(timeout=10)
        self.assertEqual(sender_message['message']['content'], 'private')
        self.assertEqual(sender_message['temp_id'], 'temp-private')
        self.assertEqual((await recipient.receive_json_from(timeout=10))['message']['content'], 'private')
        self.assertTrue(await stranger.receive_nothing(timeout=0.1))

        audio_key = 'chat_audio/socket-voice.m4a'
        await sender.send_json_to({
            'type': 'direct_message',
            'temp_id': 'temp-voice',
            'recipient_id': str(self.profiles[1].id),
            'content': '',
            'audio_url': f'/media/{audio_key}',
            'audio_ref': sign_audio_upload(audio_key, self.profiles[0].id),
            'audio_duration': 3,
        })
        sender_voice = await sender.receive_json_from(timeout=10)
        recipient_voice = await recipient.receive_json_from(timeout=10)
        self.assertEqual(sender_voice['temp_id'], 'temp-voice')
        self.assertTrue(sender_voice['message']['audio_url'].endswith(audio_key))
        self.assertEqual(recipient_voice['message']['audio_url'], sender_voice['message']['audio_url'])
        self.assertTrue(await stranger.receive_nothing(timeout=0.1))

        image_key = 'chat_images/socket-photo.jpg'
        await sender.send_json_to({
            'type': 'direct_message',
            'temp_id': 'temp-image',
            'recipient_id': str(self.profiles[1].id),
            'content': '',
            'image_url': f'/media/{image_key}',
            'image_ref': sign_image_upload(image_key, self.profiles[0].id),
        })
        sender_image = await sender.receive_json_from(timeout=10)
        recipient_image = await recipient.receive_json_from(timeout=10)
        self.assertEqual(sender_image['temp_id'], 'temp-image')
        self.assertTrue(sender_image['message']['image_url'].endswith(image_key))
        self.assertEqual(recipient_image['message']['image_url'], sender_image['message']['image_url'])
        self.assertTrue(await stranger.receive_nothing(timeout=0.1))

        # Even an accidental server-side send to the wrong inbox is filtered.
        await get_channel_layer().group_send(f'inbox_{self.profiles[2].id}', {
            'type': 'direct_message',
            'message': {
                'sender': str(self.profiles[0].id),
                'receiver': str(self.profiles[1].id),
                'content': 'misrouted',
            },
        })
        self.assertTrue(await stranger.receive_nothing(timeout=0.1))

        await sender.send_json_to({
            'type': 'direct_message',
            'temp_id': 'temp-rejected',
            'recipient_id': str(self.profiles[2].id),
            'content': 'not connected',
        })
        rejection = await sender.receive_json_from(timeout=10)
        self.assertEqual(rejection['type'], 'error')
        self.assertEqual(rejection['temp_id'], 'temp-rejected')
        self.assertTrue(await stranger.receive_nothing(timeout=0.1))

        second_sender_device = WebsocketCommunicator(
            application, f'/ws/chat/?token={self.tokens[0]}'
        )
        connected, _ = await second_sender_device.connect(timeout=10)
        self.assertTrue(connected)
        self.assertEqual(
            (await second_sender_device.receive_json_from(timeout=10))['type'], 'initial_presence'
        )
        self.assertTrue(await recipient.receive_nothing(timeout=0.1))
        await second_sender_device.disconnect()
        self.assertTrue(await recipient.receive_nothing(timeout=0.1))

        for socket in reversed(sockets):
            await socket.disconnect()

    def test_subscription_policy_updated_broadcasts_to_open_sockets(self):
        async_to_sync(self._subscription_policy_scenario)()

    async def _subscription_policy_scenario(self):
        socket = WebsocketCommunicator(application, f'/ws/chat/?token={self.tokens[0]}')
        connected, _ = await socket.connect(timeout=10)
        self.assertTrue(connected)
        self.assertEqual((await socket.receive_json_from(timeout=10))['type'], 'initial_presence')

        # Broadcast event through channel layer
        channel_layer = get_channel_layer()
        await channel_layer.group_send(
            "global_system",
            {
                "type": "subscription_policy_updated",
                "timestamp": "2026-09-28T17:00:00Z",
            }
        )

        # Socket should receive the event live
        received = await socket.receive_json_from(timeout=10)
        self.assertEqual(received['type'], 'subscription_policy_updated')
        self.assertEqual(received['timestamp'], '2026-09-28T17:00:00Z')

        await socket.disconnect()
