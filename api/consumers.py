import json
from django.core.serializers.json import DjangoJSONEncoder
from django.core.cache import cache
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.db.models import Q
from django.utils import timezone
from api.models import UserProfile, Match, Friendship, DirectMessage, ChatRoom, ChatRoomMessage, Block
from api.serializers import DirectMessageSerializer, ChatRoomMessageSerializer

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

        # Join personal inbox group
        await self.channel_layer.group_add(
            self.inbox_group_name,
            self.channel_name
        )

        await self.accept()

        # Set user as online in Django cache
        cache.set(f"online_{self.profile.id}", True, 86400)

        # Send initial list of online users who have a thread with this user
        await self.send_initial_presence()

        # Broadcast online status to everyone who has a thread with this user
        await self.broadcast_presence('online')

    async def disconnect(self, close_code):
        if hasattr(self, 'inbox_group_name'):
            await self.channel_layer.group_discard(
                self.inbox_group_name,
                self.channel_name
            )
            cache.delete(f"online_{self.profile.id}")
            await self.broadcast_presence('offline')

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        msg_type = data.get('type', 'direct_message')

        if msg_type == 'ping':
            await self.send(text_data=json.dumps({'type': 'pong'}))
            return

        # --- Handle Direct Messages ---
        if msg_type == 'direct_message':
            recipient_id = data.get('recipient_id')
            content = data.get('content')
            image_url = data.get('image_url')
            reply_to_id = data.get('reply_to_id')

            if not recipient_id or (not content and not image_url):
                return

            # Check relationship & blocks
            is_valid, error_msg = await self.verify_direct_message_relationship(self.profile.id, recipient_id)
            if not is_valid:
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': error_msg
                }))
                return

            # Save and serialize message
            msg_data = await self.save_direct_message(self.profile, recipient_id, content, image_url, reply_to_id)
            if msg_data:
                payload = {
                    'type': 'direct_message',
                    'message': msg_data,
                    'temp_id': data.get('temp_id')
                }
                # Broadcast to both sender and recipient inbox groups
                await self.channel_layer.group_send(f"inbox_{self.profile.id}", payload)
                await self.channel_layer.group_send(f"inbox_{recipient_id}", payload)
            else:
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': 'Message could not be saved. Please try again.'
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
            recipient_id = data.get('recipient_id')
            if message_id and recipient_id:
                success = await self.save_message_reaction(message_id, reaction)
                if success:
                    # Broadcast to both sender and recipient inboxes
                    payload = {
                        'type': 'message_reaction_broadcast',
                        'message_id': message_id,
                        'reaction': reaction,
                        'recipient_id': recipient_id,
                    }
                    await self.channel_layer.group_send(f"inbox_{self.profile.id}", payload)
                    await self.channel_layer.group_send(f"inbox_{recipient_id}", payload)

        elif msg_type == 'typing':
            recipient_id = data.get('recipient_id')
            is_typing = data.get('is_typing', False)
            if recipient_id:
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
            
            # Join the room's channels group
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

            if not room_id or not content:
                return

            is_member = await self.verify_room_membership(self.profile.id, room_id)
            if not is_member:
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': 'Must join the room before you can send messages.'
                }))
                return

            msg_data = await self.save_room_message(self.profile, room_id, content)
            if msg_data:
                payload = {
                    'type': 'room_message',
                    'message': msg_data,
                    'temp_id': data.get('temp_id')
                }
                # Broadcast to all room members
                await self.channel_layer.group_send(f"room_{room_id}", payload)
                # Also echo back to the sender's personal inbox so they see their own message
                # even if they are not yet registered in the room group (race condition safety)
                await self.channel_layer.group_send(f"inbox_{self.profile.id}", payload)

    # --- WebSocket Event Handlers ---
    async def direct_message(self, event):
        await self.send(text_data=json.dumps({
            'type': 'direct_message',
            'message': event['message'],
            'temp_id': event.get('temp_id')
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
        await self.send(text_data=json.dumps({
            'type': 'room_message',
            'message': event['message'],
            'temp_id': event.get('temp_id')
        }, cls=DjangoJSONEncoder))

    async def status_update(self, event):
        await self.send(text_data=json.dumps({
            'type': 'status_update',
            'profile_id': event['profile_id'],
            'status': event['status'],
        }, cls=DjangoJSONEncoder))

    async def message_reaction_broadcast(self, event):
        await self.send(text_data=json.dumps({
            'type': 'message_reaction',
            'message_id': event['message_id'],
            'reaction': event['reaction'],
        }, cls=DjangoJSONEncoder))

    # --- Presence helpers ---
    async def send_initial_presence(self):
        """Send the list of online user IDs who have a thread with this user."""
        partner_ids = await self.get_connected_partner_ids(self.profile.id)
        online_ids = []
        for pid in partner_ids:
            if cache.get(f"online_{pid}"):
                online_ids.append(str(pid))
        
        await self.send(text_data=json.dumps({
            'type': 'initial_presence',
            'online_ids': online_ids
        }, cls=DjangoJSONEncoder))

    async def broadcast_presence(self, status: str):
        """Send online/offline status to everyone who has a DM thread with this user."""
        partner_ids = await self.get_connected_partner_ids(self.profile.id)
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
    def save_message_reaction(self, message_id, reaction):
        try:
            msg = DirectMessage.objects.get(id=message_id)
            msg.reaction = reaction
            msg.save()
            return True
        except DirectMessage.DoesNotExist:
            return False

    @database_sync_to_async
    def get_connected_partner_ids(self, profile_id):
        """Return IDs of all users this profile is connected to (Friends, Matches, or DM history)."""
        # DM History
        sent = list(DirectMessage.objects.filter(sender_id=profile_id).values_list('receiver_id', flat=True).distinct())
        received = list(DirectMessage.objects.filter(receiver_id=profile_id).values_list('sender_id', flat=True).distinct())
        
        # Friends (Friendship model uses sender/receiver)
        friends_from = list(Friendship.objects.filter(sender_id=profile_id, status='accepted').values_list('receiver_id', flat=True).distinct())
        friends_to = list(Friendship.objects.filter(receiver_id=profile_id, status='accepted').values_list('sender_id', flat=True).distinct())
        
        # Matches
        matches_user1 = list(Match.objects.filter(user1_id=profile_id).values_list('user2_id', flat=True).distinct())
        matches_user2 = list(Match.objects.filter(user2_id=profile_id).values_list('user1_id', flat=True).distinct())
        
        return list(set(sent + received + friends_from + friends_to + matches_user1 + matches_user2))

    @database_sync_to_async
    def mark_thread_read(self, reader_id, partner_id):
        """Mark all messages from partner_id to reader_id as read. Returns count updated."""
        return DirectMessage.objects.filter(
            sender_id=partner_id,
            receiver_id=reader_id,
            read_at__isnull=True
        ).update(read_at=timezone.now())

    @database_sync_to_async
    def verify_direct_message_relationship(self, my_profile_id, partner_profile_id):
        # Must not be blocked
        is_blocked = Block.objects.filter(
            Q(blocker_id=my_profile_id, blocked_user_id=partner_profile_id) |
            Q(blocker_id=partner_profile_id, blocked_user_id=my_profile_id)
        ).exists()
        if is_blocked:
            return False, "You are blocked from sending messages to this user."

        # Check Subscription Limits
        my_profile = UserProfile.objects.get(id=my_profile_id)
        
        thread_exists = DirectMessage.objects.filter(
            Q(sender_id=my_profile_id, receiver_id=partner_profile_id) | 
            Q(sender_id=partner_profile_id, receiver_id=my_profile_id)
        ).exists()

        if not thread_exists:
            current_month = timezone.now().month
            new_threads = DirectMessage.objects.filter(
                sender_id=my_profile_id, 
                timestamp__month=current_month
            ).values('receiver').distinct().count()
            
            if my_profile.subscription_tier == 'freemium' and new_threads >= 1:
                return False, "Freemium tier allows only 1 new message thread initiation per month. Upgrade to send more."
            if my_profile.subscription_tier == 'light' and new_threads >= 3:
                return False, "Premium Light allows only 3 new message thread initiations per month. Upgrade to Premium Plus for unlimited."

        return True, ""

    @database_sync_to_async
    def save_direct_message(self, sender_profile, receiver_id, content, image_url=None, reply_to_id=None):
        try:
            receiver = UserProfile.objects.get(id=receiver_id)
            msg = DirectMessage.objects.create(
                sender=sender_profile,
                receiver=receiver,
                content=content or '',
                image_url=image_url,
                reply_to_id=reply_to_id
            )
            # Use DjangoJSONEncoder to handle UUIDs, datetimes etc.
            data = DirectMessageSerializer(msg).data
            return json.loads(json.dumps(data, cls=DjangoJSONEncoder))
        except Exception as e:
            import logging
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
            first = DirectMessage.objects.filter(id__in=message_ids).first()
            return str(first.sender_id) if first else None

        first_sender_id = msgs.first().sender_id
        msgs.update(read_at=timezone.now())
        return str(first_sender_id)

    @database_sync_to_async
    def verify_room_membership(self, profile_id, room_id):
        try:
            room = ChatRoom.objects.get(id=room_id)
            return room.members.filter(id=profile_id).exists()
        except ChatRoom.DoesNotExist:
            return False

    @database_sync_to_async
    def save_room_message(self, sender_profile, room_id, content):
        room = ChatRoom.objects.get(id=room_id)
        msg = ChatRoomMessage.objects.create(
            room=room,
            sender=sender_profile,
            content=content
        )
        return ChatRoomMessageSerializer(msg).data


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
