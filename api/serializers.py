import random
from rest_framework import serializers
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView
from api.models import (
    User, UserProfile, UserPhoto, Match, Friendship, 
    DirectMessage, ChatRoom, ChatRoomMessage, SupportTicket, 
    SupportTicketReply, Report, Block, Transaction, OTPLog, SavedMatch,
    AdminActionLog, Notification
)
from api.chat_media import (
    audio_url_expires_at,
    fresh_audio_url,
    fresh_image_url,
    image_url_expires_at,
)



MIN_AGE = 18
MAX_AGE = 120

class ChahiraTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Custom JWT login serializer that injects the user's role and serialized profile into the response.
    Returns: { access, refresh, role, user, profile }
    """
    def validate(self, attrs):
        data = super().validate(attrs)
        data['role'] = self.user.role
        profile = getattr(self.user, 'profile', None)
        if profile:
            data['profile'] = UserProfileSerializer(profile, context=self.context).data
            data['user'] = data['profile'].get('user', UserSerializer(self.user, context=self.context).data)
        else:
            data['user'] = UserSerializer(self.user, context=self.context).data
            data['profile'] = None
        return data


class ChahiraTokenObtainPairView(TokenObtainPairView):
    serializer_class = ChahiraTokenObtainPairSerializer


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'email', 'role', 'is_verified', 'date_joined', 'first_name', 'is_active')
        read_only_fields = ('id', 'role', 'is_verified', 'date_joined')

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        request = self.context.get('request')
        # Expose sensitive fields only to the owner or admins
        if request and getattr(request, 'user', None) != instance:
            if not (request.user.is_staff or request.user.is_superuser):
                ret.pop('email', None)
                ret.pop('is_active', None)
        return ret

class UserRegisterSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(required=True)
    password = serializers.CharField(write_only=True, required=True, style={'input_type': 'password'})
    first_name = serializers.CharField(required=True)

    class Meta:
        model = User
        fields = ('email', 'password', 'first_name')

    def validate_email(self, value):
        email = value.strip().lower()
        try:
            user = User.objects.get(email__iexact=email)
            if user.is_verified:
                raise serializers.ValidationError("A user with this email already exists.")
        except User.DoesNotExist:
            pass
        return email

    def create(self, validated_data):
        email = validated_data['email']

        # Delete existing unverified user to prevent unique constraints and send a fresh OTP
        User.objects.filter(email__iexact=email, is_verified=False).delete()

        # Generate 4-digit OTP code for email verification
        otp_code = f"{random.randint(1000, 9999)}"
        user = User.objects.create_user(
            email=email,
            username=email,
            password=validated_data['password'],
            first_name=validated_data['first_name'],
            role='member',
            otp=otp_code,
            otp_created_at=timezone.now(),
            is_active=False,  # Starts inactive until OTP verification
            is_verified=False
        )
        
        # Log the generated OTP in OTPLog
        OTPLog.objects.create(
            email=user.email,
            otp=otp_code,
            action='generated'
        )

        # Send actual email via SMTP with HTML template
        from api.email_service import send_signup_verification_email
        send_signup_verification_email(user.email, otp_code, username=user.username)
        
        # Initialize default user profile
        UserProfile.objects.create(
            user=user,
            username=user.username,
            profile_completion_pct=0
        )
        return user

class OTPVerifySerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    otp = serializers.CharField(max_length=6, required=True)

    def validate(self, attrs):
        email = attrs.get('email')
        otp = attrs.get('otp')
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise serializers.ValidationError("User with this email does not exist.")

        if user.otp != otp:
            OTPLog.objects.create(
                email=email,
                otp=otp,
                action='failed_verification'
            )
            raise serializers.ValidationError("Invalid OTP code.")

        # Check OTP age (e.g., must be under 15 minutes)
        if user.otp_created_at:
            time_difference = timezone.now() - user.otp_created_at
            if time_difference.total_seconds() > 900:  # 15 minutes
                OTPLog.objects.create(
                    email=email,
                    otp=otp,
                    action='failed_verification'
                )
                raise serializers.ValidationError("OTP code has expired. Please request a new one.")

        attrs['user'] = user
        return attrs

class UserPhotoSerializer(serializers.ModelSerializer):
    # Write-only: accepts the uploaded image file
    image_upload = serializers.ImageField(write_only=True, required=False)
    # Read-only: returns the full Cloudinary CDN URL
    image = serializers.SerializerMethodField()

    def to_internal_value(self, data):
        # Allow client to supply file in 'image', 'photo', or 'image_upload'
        if hasattr(data, 'copy'):
            data = data.copy()
        file_obj = data.get('image') or data.get('photo')
        if file_obj and not data.get('image_upload'):
            data['image_upload'] = file_obj
        return super().to_internal_value(data)

    def get_image(self, obj):
        if not obj.image:
            return None
        if obj.image.name.startswith('http://') or obj.image.name.startswith('https://'):
            return obj.image.name
            
        url = obj.image.url
        # If django-cloudinary-storage returned a local /media/ path,
        # build the Cloudinary CDN URL directly from the stored public_id
        if not (url.startswith('https://') or url.startswith('http://')):
            try:
                import cloudinary.utils
                cdn_url, _ = cloudinary.utils.cloudinary_url(obj.image.name, secure=True)
                return cdn_url
            except Exception:
                pass
        return url

    def create(self, validated_data):
        # Move image_upload → image before saving
        image_file = validated_data.pop('image_upload', None)
        if image_file:
            validated_data['image'] = image_file
        return super().create(validated_data)

    def update(self, instance, validated_data):
        image_file = validated_data.pop('image_upload', None)
        if image_file:
            validated_data['image'] = image_file
        return super().update(instance, validated_data)

    class Meta:
        model = UserPhoto
        fields = ('id', 'profile', 'image', 'image_upload', 'is_main', 'is_verified', 'uploaded_at')
        read_only_fields = ('id', 'is_verified', 'uploaded_at', 'profile')


class UserProfileSerializer(serializers.ModelSerializer):
    def to_representation(self, instance):
        data = super().to_representation(instance)
        access = instance.subscription_access
        expiry = access['subscription_expires']
        data.update(access, subscription_expires=expiry.isoformat() if expiry else None)
        request = self.context.get('request')
        if request and request.user.is_authenticated and instance.user_id == request.user.id:
            from api.subscriptions import access_snapshot
            data['access'] = access_snapshot(instance)
        return data

    user = UserSerializer(read_only=True)
    photos = UserPhotoSerializer(many=True, read_only=True)
    connection_status = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()

    class Meta:
        model = UserProfile
        fields = (
            'id', 'user', 'username', 'age', 'height_cm', 'weight_kg', 
            'gender', 'gender_preference', 'looking_for', 'marital_status', 'education_level', 
            'spoken_languages',
            'city', 'country', 'latitude', 'longitude', 'profile_completion_pct', 'is_verified', 'face_verification_status', 'face_verification_note', 'must_verify_face', 'onboarding_part1_completed',
            'subscription_tier', 'subscription_expires', 'subscription_product_id', 'has_match_analysis', 'neurotype_labels',
            'is_neurodivergent', 'open_to_meet_neurodivergent', 'qualities', 
            'interests', 'recharge_methods', 'exhaust_triggers', 
            'emotional_needs', 'second_degree_humor', 'soothe_methods', 
            'smoking', 'alcohol', 'pets', 'sport', 'eating_habits',
            'has_children', 'wants_children',
            'likes_push', 'messages_push', 'is_dark_mode', 
            'preferred_language', 'is_deactivated', 'photos', 'connection_status', 'name'
        )
        read_only_fields = ('id', 'user', 'profile_completion_pct', 'is_verified', 'face_verification_status', 'face_verification_note', 'must_verify_face', 'subscription_tier', 'subscription_expires', 'subscription_product_id', 'has_match_analysis', 'photos', 'connection_status', 'name')

    def validate_age(self, value):
        # Constela is for adults only (Terms §2, Google Play dating-app policy).
        if value is not None and value < MIN_AGE:
            raise serializers.ValidationError(f"You must be at least {MIN_AGE} years old to use Constela.")
        if value is not None and value > MAX_AGE:
            raise serializers.ValidationError("Please enter a valid age.")
        return value

    def get_name(self, obj):
        return obj.display_name

    def get_connection_status(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return 'none'
        if getattr(request.user, 'role', 'member') != 'member':
            return 'none'
        
        try:
            me = UserProfile.objects.get(user=request.user)
            if me.id == obj.id:
                return 'self'
            
            # Check Match
            from api.models import Match, Friendship
            from django.db.models import Q
            is_match = Match.objects.filter(
                (Q(user1=me, user2=obj) | Q(user1=obj, user2=me)),
                status='matched'
            ).exists()
            if is_match:
                return 'match'
                
            # Check Friendship
            is_friend = Friendship.objects.filter(
                (Q(sender=me, receiver=obj) | Q(sender=obj, receiver=me)),
                status='accepted'
            ).exists()
            if is_friend:
                return 'friend'
                
        except UserProfile.DoesNotExist:
            pass
            
        return 'none'



    def update(self, instance, validated_data):
        request = self.context.get('request')
        if request and 'first_name' in request.data:
            instance.user.first_name = request.data.get('first_name')
            instance.user.save()

        # Update and dynamically compute profile completeness percentage
        profile = super().update(instance, validated_data)
        profile.profile_completion_pct = profile.calculate_completion_pct()
        profile.save()
        return profile


class UserProfileBasicSerializer(serializers.ModelSerializer):
    photos = UserPhotoSerializer(many=True, read_only=True)
    
    name = serializers.SerializerMethodField()

    class Meta:
        model = UserProfile
        fields = (
            'id', 'username', 'name', 'age', 'gender', 'city', 'country', 'latitude', 'longitude', 
            'subscription_tier', 'subscription_product_id', 'neurotype_labels', 'qualities', 
            'interests', 'recharge_methods', 'soothe_methods', 
            'sport', 'spoken_languages', 'is_verified', 'photos'
        )
        
    def get_name(self, obj):
        return obj.display_name

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        ret['subscription_tier'] = instance.subscription_access['subscription_tier']
        ret['subscription_product_id'] = instance.subscription_access['subscription_product_id']
        ret['username'] = instance.display_name
        return ret

class MatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Match
        fields = ('id', 'user1', 'user2', 'status', 'created_at')
        read_only_fields = ('id', 'created_at', 'user1')

class FriendshipSerializer(serializers.ModelSerializer):
    sender = UserProfileBasicSerializer(read_only=True)
    receiver = UserProfileBasicSerializer(read_only=True)

    class Meta:
        model = Friendship
        fields = ('id', 'sender', 'receiver', 'status', 'created_at')
        read_only_fields = ('id', 'sender', 'receiver', 'created_at')

class DirectMessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.ReadOnlyField(source='sender.display_name')
    receiver_name = serializers.ReadOnlyField(source='receiver.display_name')
    sender_photo = serializers.SerializerMethodField()
    receiver_photo = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()
    image_url_expires_at = serializers.SerializerMethodField()
    audio_url = serializers.SerializerMethodField()
    audio_url_expires_at = serializers.SerializerMethodField()
    reply_to_info = serializers.SerializerMethodField(read_only=True)
    reactions = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = DirectMessage
        fields = ('id', 'sender', 'receiver', 'sender_name', 'receiver_name', 'sender_photo', 'receiver_photo', 'content', 'timestamp', 'read_at', 'image_url', 'image_url_expires_at', 'audio_url', 'audio_url_expires_at', 'audio_duration', 'reply_to', 'reply_to_info', 'reaction', 'reactions')
        read_only_fields = ('id', 'sender', 'timestamp', 'read_at')

    def get_reactions(self, obj):
        return reaction_summary(obj.reactions.all())

    def get_reply_to_info(self, obj):
        if obj.reply_to:
            return {
                'id': str(obj.reply_to.id),
                'content': obj.reply_to.content,
                'image_url': fresh_image_url(obj.reply_to.image_url),
                'image_url_expires_at': image_url_expires_at(obj.reply_to.image_url),
                'audio_url': fresh_audio_url(obj.reply_to.audio_url),
                'sender_id': str(obj.reply_to.sender_id),
                'sender_name': obj.reply_to.sender.display_name,
            }
        return None

    def get_audio_url(self, obj):
        return fresh_audio_url(obj.audio_url)

    def get_audio_url_expires_at(self, obj):
        return audio_url_expires_at(obj.audio_url)

    def get_image_url(self, obj):
        return fresh_image_url(obj.image_url)

    def get_image_url_expires_at(self, obj):
        return image_url_expires_at(obj.image_url)

    def get_sender_photo(self, obj):
        photos = list(obj.sender.photos.all())
        main_photo = next((photo for photo in photos if photo.is_main), photos[0] if photos else None)
        if main_photo:
            request = self.context.get('request')
            if request is not None:
                return request.build_absolute_uri(main_photo.image.url)
            return main_photo.image.url
        return None

    def get_receiver_photo(self, obj):
        photos = list(obj.receiver.photos.all())
        main_photo = next((photo for photo in photos if photo.is_main), photos[0] if photos else None)
        if main_photo:
            request = self.context.get('request')
            if request is not None:
                return request.build_absolute_uri(main_photo.image.url)
            return main_photo.image.url
        return None

class ChatRoomSerializer(serializers.ModelSerializer):
    member_count = serializers.SerializerMethodField()
    is_joined = serializers.SerializerMethodField()
    member_avatars = serializers.SerializerMethodField()

    class Meta:
        model = ChatRoom
        fields = ('id', 'name', 'member_count', 'member_avatars', 'is_joined')

    def get_member_count(self, obj):
        return obj.members.count()

    def get_is_joined(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        if hasattr(request.user, 'profile'):
            return obj.members.filter(id=request.user.profile.id).exists()
        return False

    def get_member_avatars(self, obj):
        from .views import get_cloudinary_url
        avatars = []
        # Get up to 3 members with main photos
        members = obj.members.all().prefetch_related('photos')[:10]  
        for member in members:
            if len(avatars) >= 3:
                break
            photos = list(member.photos.all())
            main_photo = next((photo for photo in photos if photo.is_main), photos[0] if photos else None)
            if main_photo:
                url = get_cloudinary_url(main_photo.image)
                if url:
                    avatars.append(url)
        return avatars

class ChatRoomMessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.ReadOnlyField(source='sender.display_name')
    sender_photo = serializers.SerializerMethodField()
    reply_to_info = serializers.SerializerMethodField(read_only=True)
    reactions = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = ChatRoomMessage
        fields = ('id', 'room', 'sender', 'sender_name', 'sender_photo', 'content', 'timestamp', 'reply_to', 'reply_to_info', 'reactions')
        read_only_fields = ('id', 'sender', 'timestamp')

    def get_reactions(self, obj):
        return reaction_summary(obj.reactions.all())

    def get_reply_to_info(self, obj):
        if not obj.reply_to_id:
            return None
        replied = obj.reply_to
        return {
            'id': str(replied.id),
            'content': replied.content,
            'sender_id': str(replied.sender_id),
            'sender_name': replied.sender.display_name,
        }

    def get_sender_photo(self, obj):
        from .views import get_cloudinary_url
        photos = list(obj.sender.photos.all())
        main_photo = next((photo for photo in photos if photo.is_main), photos[0] if photos else None)
        if main_photo:
            return get_cloudinary_url(main_photo.image)
        return None

class SupportTicketReplySerializer(serializers.ModelSerializer):
    sender_email = serializers.ReadOnlyField(source='sender.email')

    class Meta:
        model = SupportTicketReply
        fields = ('id', 'ticket', 'sender', 'sender_email', 'content', 'created_at')
        read_only_fields = ('id', 'sender', 'created_at')

class SupportTicketSerializer(serializers.ModelSerializer):
    user_name = serializers.ReadOnlyField(source='user.username')
    user_email = serializers.ReadOnlyField(source='user.user.email')
    replies = SupportTicketReplySerializer(many=True, read_only=True)

    class Meta:
        model = SupportTicket
        fields = ('id', 'user', 'user_name', 'user_email', 'email', 'subject', 'description', 'priority', 'status', 'created_at', 'updated_at', 'replies')
        read_only_fields = ('id', 'user', 'created_at', 'updated_at', 'replies')

def reaction_summary(reactions):
    """Group reaction rows into [{emoji, count, actor_ids}] for the client."""
    grouped = {}
    for reaction in reactions:
        entry = grouped.setdefault(
            reaction.emoji, {'emoji': reaction.emoji, 'count': 0, 'actor_ids': []}
        )
        entry['count'] += 1
        entry['actor_ids'].append(str(reaction.actor_id))
    return list(grouped.values())


class ReportSerializer(serializers.ModelSerializer):
    reporter_name = serializers.ReadOnlyField(source='reporter.username')
    reported_user_name = serializers.ReadOnlyField(source='reported_user.username')
    assign_to_name = serializers.CharField(source='assign_to.username', read_only=True, default=None)

    class Meta:
        model = Report
        fields = ('id', 'reporter', 'reporter_name', 'reported_user', 'reported_user_name', 'reason', 'description', 'status', 'action_taken', 'priority', 'assign_to', 'assign_to_name', 'resolved_by', 'created_at')
        read_only_fields = ('id', 'reporter', 'status', 'created_at', 'resolved_by')

class BlockSerializer(serializers.ModelSerializer):
    blocked_user_detail = UserProfileBasicSerializer(source='blocked_user', read_only=True)

    class Meta:
        model = Block
        fields = ('id', 'blocker', 'blocked_user', 'blocked_user_detail', 'created_at')
        read_only_fields = ('id', 'blocker', 'created_at')

class TransactionSerializer(serializers.ModelSerializer):
    def to_representation(self, instance):
        data = super().to_representation(instance)
        if data.get('payment_method') == 'Visa **** 4242':
            data['payment_method'] = 'Unknown'
        return data

    class Meta:
        model = Transaction
        fields = ('id', 'user', 'plan_name', 'amount', 'status', 'stripe_charge_id', 'payment_method', 'created_at')
        read_only_fields = ('id', 'created_at')


class SavedMatchSerializer(serializers.ModelSerializer):
    profile = UserProfileBasicSerializer(source='target_profile', read_only=True)
    saved_at = serializers.DateTimeField(source='created_at', read_only=True)

    class Meta:
        model = SavedMatch
        fields = ('id', 'saved_at', 'profile')


class AdminActionLogSerializer(serializers.ModelSerializer):
    admin_name = serializers.CharField(source='admin_user.username', read_only=True)
    admin_email = serializers.CharField(source='admin_user.email', read_only=True)
    target_name = serializers.CharField(source='target_user.username', read_only=True, default=None)
    
    class Meta:
        model = AdminActionLog
        fields = ('id', 'admin_user', 'admin_name', 'admin_email', 'target_user', 'target_name', 'action', 'details', 'timestamp')
        read_only_fields = ('id', 'timestamp')


class NotificationSerializer(serializers.ModelSerializer):
    data = serializers.SerializerMethodField()

    def get_data(self, obj):
        data = dict(obj.data) if isinstance(obj.data, dict) else {}
        profile_id = str(data.get('profile_id') or '')
        sender_photos = self.context.get('sender_photos')
        if profile_id and sender_photos is not None:
            data['sender_photo'] = sender_photos.get(profile_id)
        return data

    class Meta:
        model = Notification
        fields = ('id', 'recipient', 'title', 'body', 'type', 'data', 'is_read', 'created_at')
        read_only_fields = ('id', 'recipient', 'created_at')
