import json
import logging
import time
from django.core.serializers.json import DjangoJSONEncoder
from django.core.cache import cache
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.db import transaction
from django.db.models import Q
from api.subscriptions import consume_usage, quota_snapshot
from django.utils import timezone
from api.models import (
    UserProfile, Match, Friendship, DirectMessage, ChatRoom, ChatRoomMessage, Block,
    DirectMessageReaction, ChatRoomMessageReaction,
)
from api.serializers import DirectMessageSerializer, ChatRoomMessageSerializer, reaction_summary
from api.chat_media import audio_storage_key, image_storage_key, verify_audio_upload, verify_image_upload
from api.push_notifications import notify_direct_message

logger = logging.getLogger(__name__)
PRESENCE_TIMEOUT = 50  # 2× heartbeat interval (25s) for faster online/offline accuracy
RELATIONSHIP_CACHE_TTL = 30  # seconds to cache the allow/block result per recipient


def _presence_online(profile_id):
    key = f"online_{profile_id}"
    if cache.add(key, 1, PRESENCE_TIMEOUT):
        return True
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, PRESENCE_TIMEOUT)
        return True
    cache.touch(key, PRESENCE_TIMEOUT)
    return False


def _presence_offline(profile_id):
    key = f"online_{profile_id}"
    try:
        remaining = cache.decr(key)
    except ValueError:
        return False
    if remaining <= 0:
        cache.delete(key)
        return True
    cache.touch(key, PRESENCE_TIMEOUT)
    return False


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope.get('user')
        if not self.user or not self.user.is_authenticated:
            await self.close()
            return

        # Fetch the user's profile
        self.profile = await self.get_user_profile(self.user)
        if not self.profile:
            await self.close()
            return

        self.inbox_group_name = f"inbox_{self.profile.id}"

        # Per-connection caches — avoids repeated DB queries for the same data
        # { recipient_id: (is_valid: bool, error_msg: str, cached_at: float) }
        self._relationship_cache: dict = {}
        # Cached list of partner IDs for presence broadcasts, refreshed lazily
        self._partner_ids_cache: list | None = None
        self._partner_ids_cached_at: float = 0

        # Join personal inbox group
        await self.channel_layer.group_add(
            self.inbox_group_name,
            self.channel_name
        )
        # Join global system broadcast group
        await self.channel_layer.group_add(
            "global_system",
            self.channel_name
        )

        await self.accept()

        became_online = await database_sync_to_async(_presence_online)(self.profile.id)

        # Send initial list of online users who have a thread with this user
        await self.send_initial_presence()

        # Broadcast online status to everyone who has a thread with this user
        if became_online:
            await self.broadcast_presence('online')

    async def disconnect(self, close_code):
        if hasattr(self, 'inbox_group_name'):
            await self.channel_layer.group_discard(
                self.inbox_group_name,
                self.channel_name
            )
            await self.channel_layer.group_discard(
                "global_system",
                self.channel_name
            )
            became_offline = await database_sync_to_async(_presence_offline)(self.profile.id)
            if became_offline:
                await self.broadcast_presence('offline')

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        msg_type = data.get('type', 'direct_message')

        if msg_type == 'ping':
            def _refresh_presence(pid):
                k = f"online_{pid}"
                if not cache.get(k):
                    cache.set(k, 1, PRESENCE_TIMEOUT)
                else:
                    cache.touch(k, PRESENCE_TIMEOUT)
            await database_sync_to_async(_refresh_presence)(self.profile.id)
            await self.send(text_data=json.dumps({'type': 'pong'}))
            return

        elif msg_type == 'query_presence':
            user_id = data.get('user_id')
            if user_id:
                is_online = bool(await database_sync_to_async(cache.get)(f"online_{user_id}"))
                await self.send(text_data=json.dumps({
                    'type': 'status_update',
                    'profile_id': str(user_id),
                    'status': 'online' if is_online else 'offline',
                }))
            return

        # --- Handle Direct Messages ---
        if msg_type == 'direct_message':
            recipient_id = data.get('recipient_id')
            content = data.get('content')
            image_url = data.get('image_url')
            image_ref = data.get('image_ref')
            audio_url = data.get('audio_url')
            audio_ref = data.get('audio_ref')
            audio_duration = data.get('audio_duration')
            reply_to_id = data.get('reply_to_id')

            if not recipient_id or (not content and not image_url and not audio_url):
                return

            # Check relationship & blocks — cached per connection to avoid repeated DB hits
            is_valid, error_msg = await self._get_relationship_allowed(recipient_id)
            if not is_valid:
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': error_msg,
                    'temp_id': data.get('temp_id'),
                }))
                return

            # Save and serialize message
            msg_data = await self.save_direct_message(
                self.profile, recipient_id, content, image_url, audio_url,
                audio_duration, reply_to_id, audio_ref, image_ref,
            )
            if msg_data and msg_data.get('message'):
                payload = {
                    'type': 'direct_message',
                    'message': msg_data['message'],
                    'temp_id': data.get('temp_id'),
                    'quota': msg_data['quota'],
                    'quota_owner_id': str(self.profile.id),
                }
                # Broadcast to both sender and recipient inbox groups
                await self.channel_layer.group_send(f"inbox_{self.profile.id}", payload)
                await self.channel_layer.group_send(f"inbox_{recipient_id}", payload)
            else:
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': (msg_data or {}).get('error', 'Message could not be saved. Please try again.'),
                    'code': (msg_data or {}).get('code'),
                    'quota': (msg_data or {}).get('quota'),
                    'quota_kind': 'personal_messages',
                    'temp_id': data.get('temp_id'),
                }, cls=DjangoJSONEncoder))


        elif msg_type == 'mark_read':
            partner_id = data.get('partner_id')
            if partner_id:
                read_count = await self.mark_thread_read(self.profile.id, partner_id)
                if read_count > 0:
                    # Notify the sender their messages were read
                    await self.channel_layer.group_send(
                        f"inbox_{partner_id}",
                        {
                            'type': 'read_receipt',
                            'message_ids': [],
                            'reader_id': str(self.profile.id),
                            'partner_id': str(self.profile.id),
                        }
                    )

        elif msg_type == 'message_reaction':
            message_id = data.get('message_id')
            reaction = data.get('reaction')
            if message_id and (reaction is None or len(str(reaction)) <= 20):
                result = await self.save_message_reaction(message_id, reaction, self.profile.id)
                if result:
                    participant_ids, reactions = result
                    payload = {
                        'type': 'message_reaction_broadcast',
                        'message_id': message_id,
                        'reaction': reaction,
                        'reactions': reactions,
                    }
                    for participant_id in participant_ids:
                        await self.channel_layer.group_send(f"inbox_{participant_id}", payload)

        elif msg_type == 'room_message_reaction':
            message_id = data.get('message_id')
            reaction = data.get('reaction')
            room_id = data.get('room_id')
            if message_id and room_id and (reaction is None or len(str(reaction)) <= 20):
                reactions = await self.save_room_message_reaction(
                    message_id, reaction, self.profile.id, room_id
                )
                if reactions is not None:
                    payload = {
                        'type': 'room_message_reaction',
                        'message_id': message_id,
                        'room_id': room_id,
                        'reaction': reaction,
                        'reactions': reactions,
                    }
                    await self.channel_layer.group_send(f"room_{room_id}", payload)
                    await self.channel_layer.group_send(f"inbox_{self.profile.id}", payload)

        elif msg_type == 'typing':
            recipient_id = data.get('recipient_id')
            is_typing = data.get('is_typing', False)
            if recipient_id:
                # Use cached result — no DB query if we've already checked this recipient
                is_valid, _ = await self._get_relationship_allowed(recipient_id)
                if is_valid:
                    await self.channel_layer.group_send(
                        f"inbox_{recipient_id}",
                        {
                            'type': 'typing_indicator',
                            'sender_id': str(self.profile.id),
                            'is_typing': is_typing,
                        }
                    )

        # --- Handle Direct Message Read Receipts ---
        elif msg_type == 'read_receipt':
            message_id = data.get('message_id')
            message_ids = data.get('message_ids', [])

            to_process = [message_id] if message_id else message_ids
            if not to_process:
                return

            sender_id = await self.process_read_receipts(to_process, self.profile.id)
            if sender_id:
                # Broadcast back to the original sender
                await self.channel_layer.group_send(
                    f"inbox_{sender_id}",
                    {
                        'type': 'read_receipt',
                        'message_ids': to_process,
                        'reader_id': str(self.profile.id)
                    }
                )

        # --- Handle Community Room actions ---
        elif msg_type == 'enter_room':
            room_id = data.get('room_id')
            if not room_id:
                return
            
            if not await self.verify_room_access(self.profile.id, room_id):
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': 'You do not have access to this room.'
                }))
                return

            room_group = f"room_{room_id}"
            await self.channel_layer.group_add(
                room_group,
                self.channel_name
            )

        elif msg_type == 'leave_room':
            room_id = data.get('room_id')
            if not room_id:
                return

            room_group = f"room_{room_id}"
            await self.channel_layer.group_discard(
                room_group,
                self.channel_name
            )

        elif msg_type == 'room_message':
            room_id = data.get('room_id')
            content = data.get('content')
            temp_id = data.get('temp_id')
            reply_to_id = data.get('reply_to_id')

            if not room_id or not content:
                return

            is_member = await self.verify_room_membership(self.profile.id, room_id)
            if not is_member:
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': 'Must join the room before you can send messages.',
                    'temp_id': temp_id,
                }))
                return

            msg_data = await self.save_room_message(self.profile, room_id, content, reply_to_id)
            if msg_data and msg_data.get('message'):
                payload = {
                    'type': 'room_message',
                    'message': msg_data['message'],
                    'temp_id': temp_id,
                    'quota': msg_data['quota'],
                    'quota_owner_id': str(self.profile.id),
                }
                # Broadcast to all room members
                await self.channel_layer.group_send(f"room_{room_id}", payload)
                # Also echo back to the sender's personal inbox so they see their own message
                # even if they are not yet registered in the room group (race condition safety)
                await self.channel_layer.group_send(f"inbox_{self.profile.id}", payload)
            else:
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': (msg_data or {}).get('error', 'Message could not be saved. Please try again.'),
                    'code': (msg_data or {}).get('code'),
                    'quota': (msg_data or {}).get('quota'),
                    'quota_kind': 'community_messages',
                    'temp_id': temp_id,
                }, cls=DjangoJSONEncoder))

    # --- WebSocket Event Handlers ---
    async def direct_message(self, event):
        message = event.get('message') or {}
        participants = {str(message.get('sender')), str(message.get('receiver'))}
        if str(self.profile.id) not in participants:
            logger.warning("Blocked misrouted direct message for profile %s", self.profile.id)
            return
        await self.send(text_data=json.dumps({
            'type': 'direct_message',
            'message': message,
            'temp_id': event.get('temp_id'),
            'quota': event.get('quota') if str(self.profile.id) == event.get('quota_owner_id') else None,
        }, cls=DjangoJSONEncoder))

    async def typing_indicator(self, event):
        await self.send(text_data=json.dumps({
            'type': 'typing',
            'sender_id': event['sender_id'],
            'is_typing': event['is_typing'],
        }, cls=DjangoJSONEncoder))

    async def read_receipt(self, event):
        await self.send(text_data=json.dumps({
            'type': 'read_receipt',
            'message_ids': event['message_ids'],
            'reader_id': event['reader_id']
        }))

    async def room_message(self, event):
        room_id = event['message'].get('room')
        if not room_id or not await self.verify_room_access(self.profile.id, room_id):
            return
        await self.send(text_data=json.dumps({
            'type': 'room_message',
            'message': event['message'],
            'temp_id': event.get('temp_id'),
            'quota': event.get('quota') if str(self.profile.id) == event.get('quota_owner_id') else None,
        }, cls=DjangoJSONEncoder))

    async def status_update(self, event):
        await self.send(text_data=json.dumps({
            'type': 'status_update',
            'profile_id': event['profile_id'],
            'status': event['status'],
        }, cls=DjangoJSONEncoder))

    async def threads_changed(self, event):
        try:
            await self.send(text_data=json.dumps({
                'type': 'threads_changed',
                'thread_type': event.get('thread_type'),
            }))
        except Exception:
            pass

    async def message_reaction_broadcast(self, event):
        await self.send(text_data=json.dumps({
            'type': 'message_reaction',
            'message_id': event['message_id'],
            'reaction': event['reaction'],
        }, cls=DjangoJSONEncoder))

    async def subscription_policy_updated(self, event):
        await self.send(text_data=json.dumps({
            'type': 'subscription_policy_updated',
            'timestamp': event.get('timestamp')
        }))

    # --- Presence helpers ---
    async def _get_partner_ids(self) -> list:
        """Return cached partner IDs, refreshing from DB only once per connection."""
        now = time.monotonic()
        if self._partner_ids_cache is None or (now - self._partner_ids_cached_at) > 300:
            self._partner_ids_cache = await self.get_connected_partner_ids(self.profile.id)
            self._partner_ids_cached_at = now
        return self._partner_ids_cache

    async def send_initial_presence(self):
        """Send the list of online user IDs who have a thread with this user."""
        partner_ids = await self._get_partner_ids()
        keys = {f"online_{pid}": str(pid) for pid in partner_ids}
        cached = await database_sync_to_async(cache.get_many)(keys)
        online_ids = [keys[key] for key, count in cached.items() if count]

        await self.send(text_data=json.dumps({
            'type': 'initial_presence',
            'online_ids': online_ids
        }, cls=DjangoJSONEncoder))

    async def broadcast_presence(self, status: str):
        """Send online/offline status to everyone who has a DM thread with this user."""
        partner_ids = await self._get_partner_ids()
        for pid in partner_ids:
            await self.channel_layer.group_send(
                f"inbox_{pid}",
                {
                    'type': 'status_update',
                    'profile_id': str(self.profile.id),
                    'status': status,
                }
            )

    # --- Database Helpers ---
    @database_sync_to_async
    def get_user_profile(self, user):
        try:
            return user.profile
        except UserProfile.DoesNotExist:
            return None

    @database_sync_to_async
    def save_message_reaction(self, message_id, reaction, actor_id):
        msg = DirectMessage.objects.filter(
            Q(id=message_id), Q(sender_id=actor_id) | Q(receiver_id=actor_id)
        ).first()
        if not msg:
            return None
        existing = DirectMessageReaction.objects.filter(message=msg, actor_id=actor_id).first()
        if reaction is None:
            if existing:
                existing.delete()
        elif existing:
            if existing.emoji == reaction:
                existing.delete()          # tapping the same emoji again removes it
            else:
                existing.emoji = reaction
                existing.save(update_fields=['emoji'])
        else:
            DirectMessageReaction.objects.create(message=msg, actor_id=actor_id, emoji=reaction)
        reactions = reaction_summary(DirectMessageReaction.objects.filter(message=msg))
        # Keep the legacy single-reaction field in sync for older clients.
        msg.reaction = reactions[-1]['emoji'] if reactions else None
        msg.save(update_fields=['reaction'])
        return [str(msg.sender_id), str(msg.receiver_id)], reactions

    @database_sync_to_async
    @transaction.atomic
    def save_room_message_reaction(self, message_id, reaction, actor_id, room_id):
        msg = ChatRoomMessage.objects.filter(id=message_id, room_id=room_id).first()
        if not msg:
            return None
        existing = ChatRoomMessageReaction.objects.filter(message=msg, actor_id=actor_id).first()
        if reaction is None:
            if existing:
                existing.delete()
        elif existing:
            if existing.emoji == reaction:
                existing.delete()          # toggle off
            else:
                existing.emoji = reaction
                existing.save(update_fields=['emoji'])
        else:
            ChatRoomMessageReaction.objects.create(message=msg, actor_id=actor_id, emoji=reaction)
        return reaction_summary(ChatRoomMessageReaction.objects.filter(message=msg))

    @database_sync_to_async
    def get_connected_partner_ids(self, profile_id):
        """Return accepted friends, active matches, and direct message partners allowed to see presence."""
        friends_from = list(Friendship.objects.filter(sender_id=profile_id, status='accepted').values_list('receiver_id', flat=True).distinct())
        friends_to = list(Friendship.objects.filter(receiver_id=profile_id, status='accepted').values_list('sender_id', flat=True).distinct())
        
        # Matches
        matches_user1 = list(Match.objects.filter(user1_id=profile_id, status='matched').values_list('user2_id', flat=True).distinct())
        matches_user2 = list(Match.objects.filter(user2_id=profile_id, status='matched').values_list('user1_id', flat=True).distinct())

        # Direct message partners (anyone this user has a conversation with)
        dm_sent = list(DirectMessage.objects.filter(sender_id=profile_id).values_list('receiver_id', flat=True).distinct())
        dm_recv = list(DirectMessage.objects.filter(receiver_id=profile_id).values_list('sender_id', flat=True).distinct())

        return list(set(friends_from + friends_to + matches_user1 + matches_user2 + dm_sent + dm_recv))

    @database_sync_to_async
    def mark_thread_read(self, reader_id, partner_id):
        """Mark all messages from partner_id to reader_id as read. Returns count updated."""
        return DirectMessage.objects.filter(
            sender_id=partner_id,
            receiver_id=reader_id,
            read_at__isnull=True
        ).update(read_at=timezone.now())

    async def _get_relationship_allowed(self, recipient_id: str) -> tuple[bool, str]:
        """
        Returns (is_valid, error_msg) for sending to recipient_id.
        Result is cached on this WebSocket connection for RELATIONSHIP_CACHE_TTL seconds.
        This avoids hitting the DB on every single message and typing event.
        """
        now = time.monotonic()
        cached = self._relationship_cache.get(recipient_id)
        if cached:
            is_valid, error_msg, cached_at = cached
            if (now - cached_at) < RELATIONSHIP_CACHE_TTL:
                return is_valid, error_msg

        # Cache miss or expired — run the real check
        is_valid, error_msg = await self.verify_direct_message_relationship(
            self.profile.id, recipient_id
        )
        self._relationship_cache[recipient_id] = (is_valid, error_msg, now)
        return is_valid, error_msg

    @database_sync_to_async
    def verify_direct_message_relationship(self, my_profile_id, partner_profile_id):
        if not UserProfile.objects.filter(id=partner_profile_id).exists():
            return False, "Recipient not found."

        # Must not be blocked
        is_blocked = Block.objects.filter(
            Q(blocker_id=my_profile_id, blocked_user_id=partner_profile_id) |
            Q(blocker_id=partner_profile_id, blocked_user_id=my_profile_id)
        ).exists()
        if is_blocked:
            return False, "You are blocked from sending messages to this user."

        is_connected = Friendship.objects.filter(
            Q(sender_id=my_profile_id, receiver_id=partner_profile_id) |
            Q(sender_id=partner_profile_id, receiver_id=my_profile_id),
            status='accepted'
        ).exists() or Match.objects.filter(
            Q(user1_id=my_profile_id, user2_id=partner_profile_id) |
            Q(user1_id=partner_profile_id, user2_id=my_profile_id),
            status='matched'
        ).exists()
        if not is_connected:
            return False, "You can only message accepted friends or matches."

        return True, ""

    @database_sync_to_async
    @transaction.atomic
    def save_direct_message(self, sender_profile, receiver_id, content, image_url=None, audio_url=None, audio_duration=None, reply_to_id=None, audio_ref=None, image_ref=None):
        try:
            receiver = UserProfile.objects.get(id=receiver_id)
            locked = {p.id: p for p in UserProfile.objects.select_for_update().filter(id__in=[sender_profile.id, receiver.id]).order_by('id')}
            sender_profile = locked[sender_profile.id]
            if audio_url:
                audio_url = verify_audio_upload(audio_ref, sender_profile.id) if audio_ref else (audio_storage_key(audio_url) or audio_url)
            if image_url:
                image_url = verify_image_upload(image_ref, sender_profile.id) if image_ref else (image_storage_key(image_url) or image_url)
            reply_to = None
            if reply_to_id:
                reply_to = DirectMessage.objects.filter(
                    Q(id=reply_to_id),
                    Q(sender=sender_profile, receiver=receiver) |
                    Q(sender=receiver, receiver=sender_profile)
                ).first()
                if not reply_to:
                    return None
            if not consume_usage(sender_profile, 'personal_messages'):
                return {
                    'error': 'Daily personal-message limit reached. Upgrade to keep messaging.',
                    'code': 'DAILY_PERSONAL_MESSAGE_LIMIT_REACHED',
                    'quota': quota_snapshot(sender_profile, 'personal_messages'),
                }
            msg = DirectMessage.objects.create(
                sender=sender_profile,
                receiver=receiver,
                content=content or '',
                image_url=image_url,
                audio_url=audio_url,
                audio_duration=audio_duration,
                reply_to=reply_to
            )
            transaction.on_commit(lambda: notify_direct_message(msg))
            # Use DjangoJSONEncoder to handle UUIDs, datetimes etc.
            data = DirectMessageSerializer(msg).data
            return {
                'message': json.loads(json.dumps(data, cls=DjangoJSONEncoder)),
                'quota': quota_snapshot(sender_profile, 'personal_messages'),
            }
        except Exception as e:
            import logging
            transaction.set_rollback(True)
            logging.getLogger(__name__).error(f'save_direct_message error: {e}')
            return None

    @database_sync_to_async
    def process_read_receipts(self, message_ids, reader_profile_id):
        msgs = DirectMessage.objects.filter(
            id__in=message_ids,
            receiver_id=reader_profile_id,
            read_at__isnull=True
        )
        if not msgs.exists():
            return None

        first_sender_id = msgs.first().sender_id
        msgs.update(read_at=timezone.now())
        return str(first_sender_id)

    @database_sync_to_async
    def verify_room_membership(self, profile_id, room_id):
        try:
            room = ChatRoom.objects.get(id=room_id)
            return room.members.filter(id=profile_id).exists() and self._profile_can_access_room(profile_id, room_id)
        except ChatRoom.DoesNotExist:
            return False

    @database_sync_to_async
    def verify_room_access(self, profile_id, room_id):
        return self._profile_can_access_room(profile_id, room_id)

    @staticmethod
    def _profile_can_access_room(profile_id, room_id):
        from api.subscriptions import accessible_rooms
        try:
            profile = UserProfile.objects.get(id=profile_id)
            return accessible_rooms(profile).filter(id=room_id).exists()
        except (UserProfile.DoesNotExist, ValueError):
            return False

    @database_sync_to_async
    @transaction.atomic
    def save_room_message(self, sender_profile, room_id, content, reply_to_id=None):
        room = ChatRoom.objects.get(id=room_id)
        sender_profile = UserProfile.objects.select_for_update().get(id=sender_profile.id)
        if not consume_usage(sender_profile, 'community_messages'):
            return {
                'error': 'Daily community-message limit reached. Upgrade to keep messaging.',
                'code': 'DAILY_COMMUNITY_MESSAGE_LIMIT_REACHED',
                'quota': quota_snapshot(sender_profile, 'community_messages'),
            }
        # Only allow replying to a message that belongs to the same room.
        reply_to = None
        if reply_to_id:
            reply_to = ChatRoomMessage.objects.filter(id=reply_to_id, room=room).first()
        msg = ChatRoomMessage.objects.create(
            room=room,
            sender=sender_profile,
            content=content,
            reply_to=reply_to
        )
        return {
            'message': ChatRoomMessageSerializer(msg).data,
            'quota': quota_snapshot(sender_profile, 'community_messages'),
        }


class StatusConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope.get('user')
        if not self.user or not self.user.is_authenticated:
            await self.close()
            return

        # Fetch profile
        self.profile = await self.get_user_profile(self.user)
        if not self.profile:
            await self.close()
            return

        self.user_group_name = f"status_{self.profile.id}"
        await self.channel_layer.group_add(
            self.user_group_name,
            self.channel_name
        )

        await self.accept()
        await self.broadcast_status('online')

    async def disconnect(self, close_code):
        if hasattr(self, 'user_group_name'):
            await self.channel_layer.group_discard(
                self.user_group_name,
                self.channel_name
            )
            await self.broadcast_status('offline')

    @database_sync_to_async
    def get_user_profile(self, user):
        try:
            return user.profile
        except UserProfile.DoesNotExist:
            return None

    @database_sync_to_async
    def get_friend_ids(self):
        friendships = Friendship.objects.filter(
            Q(sender_id=self.profile.id) | Q(receiver_id=self.profile.id),
            status='accepted'
        )
        friend_ids = []
        for f in friendships:
            friend_ids.append(f.receiver_id if f.sender_id == self.profile.id else f.sender_id)
        return friend_ids

    async def broadcast_status(self, status):
        friend_ids = await self.get_friend_ids()
        for friend_id in friend_ids:
            await self.channel_layer.group_send(
                f"status_{friend_id}",
                {
                    'type': 'status_update',
                    'profile_id': str(self.profile.id),
                    'status': status
                }
            )

    async def status_update(self, event):
        await self.send(text_data=json.dumps({
            'type': 'status_update',
            'profile_id': event['profile_id'],
            'status': event['status']
        }))

    async def subscription_policy_updated(self, event):
        await self.send(text_data=json.dumps({
            'type': 'subscription_policy_updated',
            'timestamp': event.get('timestamp')
        }))
