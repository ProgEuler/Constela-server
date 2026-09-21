from collections import Counter, defaultdict

from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db.models import Count, IntegerField, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.core.mail import send_mail
from django.conf import settings
from rest_framework import viewsets, status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework_simplejwt.tokens import RefreshToken
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from api.models import (
    User, UserProfile, UserPhoto, Match, Friendship, 
    DirectMessage, ChatRoom, ChatRoomMessage, SupportTicket, 
    SupportTicketReply, Report, Block, Transaction, OTPLog, SavedMatch,
    AdminActionLog
)
from api.serializers import (
    UserSerializer, UserRegisterSerializer, OTPVerifySerializer,
    UserProfileSerializer, UserProfileBasicSerializer, UserPhotoSerializer,
    MatchSerializer, FriendshipSerializer, DirectMessageSerializer,
    ChatRoomSerializer, ChatRoomMessageSerializer, SupportTicketSerializer,
    SupportTicketReplySerializer, ReportSerializer, BlockSerializer,
    TransactionSerializer, SavedMatchSerializer, AdminActionLogSerializer
)
from api.permissions import IsMember, IsSupportAgent, IsModerator, IsAdminUser, IsSuperAdmin
from api.matching_engine import calculate_compatibility
from api.push_notifications import send_push_notification_to_user

def get_cloudinary_url(image_field):
    """Return a guaranteed Cloudinary CDN URL for a stored ImageField."""
    if not image_field:
        return None
    if image_field.name.startswith('http://') or image_field.name.startswith('https://'):
        return image_field.name
        
    url = image_field.url
    if url.startswith('https://') or url.startswith('http://'):
        return url
    # Fallback: build CDN URL from the stored public_id
    try:
        import cloudinary.utils
        cdn_url, _ = cloudinary.utils.cloudinary_url(image_field.name, secure=True)
        return cdn_url
    except Exception:
        return url


def get_main_photo(profile):
    """Use prefetched photos when available and avoid two queries per profile."""
    photos = list(profile.photos.all())
    return next((photo for photo in photos if photo.is_main), photos[0] if photos else None)


def get_friend_ids(profile_ids):
    friend_ids = defaultdict(set)
    connections = Friendship.objects.filter(
        Q(sender_id__in=profile_ids) | Q(receiver_id__in=profile_ids),
        status='accepted',
    ).values_list('sender_id', 'receiver_id')
    for sender_id, receiver_id in connections:
        friend_ids[sender_id].add(receiver_id)
        friend_ids[receiver_id].add(sender_id)
    return friend_ids

# 1. AUTH & ONBOARDING VIEWS
class UserRegisterView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = UserRegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            return Response({
                "message": "Registration successful. OTP sent to email.",
                "email": user.email
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class OTPVerifyView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = OTPVerifySerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.validated_data['user']
            user.is_verified = True
            user.is_active = True  # Activate user upon successful verification
            user.otp = None  # Clear OTP code
            user.save()
            
            # Activate verification flag on profile
            profile = user.profile
            profile.is_verified = True
            profile.save()
            
            # Log successful verification
            OTPLog.objects.create(
                email=user.email,
                otp='',
                action='verified'
            )
            
            # Generate JWT Tokens
            refresh = RefreshToken.for_user(user)
            return Response({
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": {
                    "email": user.email,
                    "username": user.username,
                    "is_verified": user.is_verified,
                }
            }, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class GoogleAuthView(APIView):
    """
    POST /api/auth/google/
    Exchanges Google id_token or access_token for App JWT Access & Refresh tokens.
    Automatically provisions new User & UserProfile if not exists, maintaining
    the exact same onboarding flow for new and existing users.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        from django.contrib.auth import get_user_model
        import firebase_admin
        from firebase_admin import auth as firebase_auth

        User = get_user_model()

        id_token = request.data.get('id_token')

        if not id_token:
            return Response(
                {"error": "id_token is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        email = None
        first_name = ""
        last_name = ""

        try:
            # First, try to verify using Firebase Admin SDK
            decoded_token = firebase_auth.verify_id_token(id_token)
            email = decoded_token.get("email")
            full_name = decoded_token.get("name", "")
        except Exception as e:
            # If Firebase fails (e.g. it's a raw Google OAuth token instead of a Firebase token),
            # verify it directly using Google's tokeninfo endpoint
            import requests
            response = requests.get(f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token}")
            if response.status_code == 200:
                decoded_token = response.json()
                email = decoded_token.get("email")
                full_name = decoded_token.get("name", "")
            else:
                return Response(
                    {"error": f"Invalid or expired Google token: {response.json().get('error_description', str(e))}"},
                    status=status.HTTP_400_BAD_REQUEST
                )

        if full_name:
            parts = full_name.split(' ', 1)
            first_name = parts[0]
            if len(parts) > 1:
                last_name = parts[1]

        if not email:
            return Response(
                {"error": "Google token does not contain an email address."},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = User.objects.filter(email__iexact=email).first()
        is_new_user = False
        is_login = request.data.get('is_login', False)

        if not user:
            if is_login:
                return Response(
                    {"error": "Account not found. Please sign up to create an account."},
                    status=status.HTTP_404_NOT_FOUND
                )

            is_new_user = True
            base_username = email.split("@")[0].replace(".", "_")
            username = base_username
            counter = 1
            while User.objects.filter(username__iexact=username).exists():
                username = f"{base_username}_{counter}"
                counter += 1

            user = User.objects.create(
                email=email.lower(),
                username=username,
                first_name=first_name,
                last_name=last_name,
                is_verified=True,
                is_active=True,
            )
            user.set_unusable_password()
            user.save()

            # Ensure UserProfile exists with initial onboarding state
            UserProfile.objects.get_or_create(
                user=user,
                defaults={
                    "username": username,
                    "profile_completion_pct": 0,
                    "onboarding_part1_completed": False,
                    "face_verification_status": "not_submitted",
                    "is_verified": True,
                }
            )

        # Generate JWT Tokens
        refresh = RefreshToken.for_user(user)
        profile = getattr(user, 'profile', None)

        return Response({
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "is_new_user": is_new_user,
            "user": {
                "id": str(user.id),
                "email": user.email,
                "username": user.username,
                "first_name": user.first_name,
                "is_verified": user.is_verified,
            },
            "profile": {
                "profile_completion_pct": profile.profile_completion_pct if profile else 0,
                "face_verification_status": profile.face_verification_status if profile else "not_submitted",
                "onboarding_part1_completed": profile.onboarding_part1_completed if profile else False,
            } if profile else None
        }, status=status.HTTP_200_OK)


class RegisterPushTokenView(APIView):
    """
    POST /api/auth/push-token/
    Registers or updates the Expo / FCM push token for the authenticated user profile.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        push_token = request.data.get('push_token', '').strip()
        if not push_token:
            return Response({"error": "push_token is required."}, status=status.HTTP_400_BAD_REQUEST)

        profile, created = UserProfile.objects.get_or_create(user=request.user)
        profile.push_token = push_token
        profile.save()

        return Response({"message": "Push token registered successfully."}, status=status.HTTP_200_OK)

class ResendOTPView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip()
        if not email:
            return Response({"error": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        if user.is_verified:
            return Response({"error": "User is already verified."}, status=status.HTTP_400_BAD_REQUEST)

        import random
        from django.utils import timezone
        otp_code = f"{random.randint(1000, 9999)}"
        user.otp = otp_code
        user.otp_created_at = timezone.now()
        user.save()

        OTPLog.objects.create(
            email=user.email,
            otp=otp_code,
            action='generated'
        )

        from api.email_service import send_resend_otp_email
        send_resend_otp_email(user.email, otp_code, username=user.username)

        return Response({"message": "New OTP sent to email."}, status=status.HTTP_200_OK)


class ForgotPasswordView(APIView):
    """
    POST /api/auth/forgot-password/
    Generates a 6-digit OTP code to reset password.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip()
        if not email:
            return Response({"error": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            # Return success to prevent email enumeration
            return Response({"message": "If the account exists, a reset code has been sent."}, status=status.HTTP_200_OK)

        if not user.has_usable_password():
            return Response({"error": "This account was created with Google. Please log in using 'Continue with Google'."}, status=status.HTTP_400_BAD_REQUEST)

        # Generate 6-digit reset code
        import random
        code = f"{random.randint(100000, 999999)}"
        user.otp = code
        user.otp_created_at = timezone.now()
        user.save()

        # Log OTP generation
        OTPLog.objects.create(
            email=user.email,
            otp=code,
            action='generated'
        )

        # Send actual email via SMTP with HTML template
        from api.email_service import send_password_reset_email
        send_password_reset_email(user.email, code, username=user.username)

        return Response({"message": "If the account exists, a reset code has been sent."}, status=status.HTTP_200_OK)


class ResetPasswordView(APIView):
    """
    POST /api/auth/reset-password/
    Verifies reset code and updates the password.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip()
        code = request.data.get('code', '').strip()
        new_password = request.data.get('new_password', '')

        if not email or not code or not new_password:
            return Response({"error": "email, code, and new_password are required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return Response({"error": "Invalid email or verification code."}, status=status.HTTP_400_BAD_REQUEST)

        # Check reset code
        if not user.otp or user.otp != code:
            OTPLog.objects.create(
                email=email,
                otp=code,
                action='failed_verification'
            )
            return Response({"error": "Invalid email or verification code."}, status=status.HTTP_400_BAD_REQUEST)

        # Check expiration (10 minutes)
        if user.otp_created_at:
            delta = timezone.now() - user.otp_created_at
            if delta.total_seconds() > 600:
                return Response({"error": "Verification code has expired. Please request a new one."}, status=status.HTTP_400_BAD_REQUEST)

        # Verify and set new password
        user.set_password(new_password)
        user.otp = None
        user.otp_created_at = None
        user.save()

        # Log success
        OTPLog.objects.create(
            email=email,
            otp='',
            action='verified'
        )

        return Response({"message": "Password has been reset successfully."}, status=status.HTTP_200_OK)

# 2. MEMBER PROFILE API
class UserProfileViewSet(viewsets.ModelViewSet):
    serializer_class = UserProfileSerializer

    def get_queryset(self):
        # Prevent viewing deactivated profiles
        return UserProfile.objects.filter(is_deactivated=False).select_related('user').prefetch_related('photos')

    @action(detail=False, methods=['get', 'put', 'patch'])
    def me(self, request):
        if request.user.is_staff:
            profile, _ = UserProfile.objects.get_or_create(
                user=request.user,
                defaults={
                    'username': request.user.username,
                    'is_verified': True,
                    'face_verification_status': 'approved'
                }
            )
        else:
            profile = get_object_or_404(
                UserProfile.objects.select_related('user').prefetch_related('photos'),
                user=request.user,
            )
        if request.method == 'GET':
            # Auto-cleanup user accounts that haven't completed face verification within 3 days
            cutoff = timezone.now() - timezone.timedelta(days=3)
            User.objects.filter(
                profile__face_verification_status='not_submitted',
                date_joined__lt=cutoff
            ).delete()

            serializer = self.get_serializer(profile)
            return Response(serializer.data)
        
        # Support multipart form-data preprocessing for lists
        import json

        data = {}
        
        list_fields = [
            'neurotype_labels', 'qualities', 'interests', 
            'recharge_methods', 'exhaust_triggers', 
            'emotional_needs', 'soothe_methods', 'spoken_languages'
        ]
        
        for key in request.data.keys():
            if key in list_fields:
                val = request.data.get(key)
                if isinstance(val, str):
                    val_stripped = val.strip()
                    if val_stripped.startswith('[') and val_stripped.endswith(']'):
                        try:
                            data[key] = json.loads(val_stripped)
                        except json.JSONDecodeError:
                            data[key] = [val_stripped]
                    elif ',' in val_stripped:
                        data[key] = [x.strip() for x in val_stripped.split(',')]
                    else:
                        data[key] = [val_stripped]
                elif hasattr(request.data, 'getlist'):
                    list_val = request.data.getlist(key)
                    if list_val:
                        if len(list_val) == 1 and list_val[0].startswith('[') and list_val[0].endswith(']'):
                            try:
                                data[key] = json.loads(list_val[0])
                            except json.JSONDecodeError:
                                data[key] = list_val
                        elif len(list_val) == 1 and ',' in list_val[0]:
                            data[key] = [x.strip() for x in list_val[0].split(',')]
                        else:
                            data[key] = list_val
            else:
                val = request.data.get(key)
                if isinstance(val, str):
                    val = val.strip()
                    if val.startswith('"') and val.endswith('"'):
                        val = val[1:-1]
                        
                    # Normalize specific frontend values in case mapping failed or casing was wrong
                    if key == 'gender':
                        if val.lower() == 'non-binary':
                            val = 'non_binary'
                        else:
                            val = val.lower()
                    elif key == 'looking_for':
                        lf_map = {
                            'Friendship': 'friendship',
                            'Serious Relationship': 'serious',
                            "We'll See": 'undecided',
                            'Going Out': 'casual'
                        }
                        if val in lf_map:
                            val = lf_map[val]
                            
                data[key] = val

        serializer = self.get_serializer(profile, data=data, partial=True)
        if serializer.is_valid():
            profile_obj = serializer.save()
            
            if 'face_verification_status' in request.data:
                new_status = request.data.get('face_verification_status')
                if new_status == 'skipped' and profile_obj.face_verification_status in ['not_submitted', 'skipped']:
                    profile_obj.face_verification_status = 'skipped'
                    profile_obj.save()
            
            # Process profile photos uploaded simultaneously in this FormData request
            uploaded_files = []
            if 'photos' in request.FILES:
                uploaded_files = request.FILES.getlist('photos')
            else:
                for key, file in request.FILES.items():
                    if 'photo' in key or 'image' in key or 'file' in key:
                        uploaded_files.append(file)
            
            for i, file in enumerate(uploaded_files):
                has_main = UserPhoto.objects.filter(profile=profile_obj, is_main=True).exists()
                UserPhoto.objects.create(
                    profile=profile_obj,
                    image=file,
                    is_main=not has_main and (i == 0),
                    is_verified=False
                )
                
            # Recalculate completeness after photo creation
            photos_count = UserPhoto.objects.filter(profile=profile_obj).count()
            if photos_count >= 3:
                profile_obj.profile_completion_pct = min(100, profile_obj.profile_completion_pct + 10)
                profile_obj.save()

            # Refresh serializer data
            serializer = self.get_serializer(profile_obj)
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UserPhotoViewSet(viewsets.ModelViewSet):
    serializer_class = UserPhotoSerializer

    def get_queryset(self):
        return UserPhoto.objects.filter(profile__user=self.request.user)

    def _delete_cloudinary_asset(self, image_field):
        """Delete a Cloudinary asset by its stored public_id."""
        if not image_field or not image_field.name:
            return
        try:
            import cloudinary.uploader
            cloudinary.uploader.destroy(image_field.name)
        except Exception:
            pass

    def perform_create(self, serializer):
        profile = get_object_or_404(UserProfile, user=self.request.user)
        photo = serializer.save(profile=profile)

        # Recalculate completeness
        photos_count = UserPhoto.objects.filter(profile=profile).count()
        if photos_count >= 3 and profile.profile_completion_pct < 100:
            profile.profile_completion_pct = min(100, profile.profile_completion_pct + 10)
            profile.save()

    def perform_update(self, serializer):
        """Delete the old Cloudinary image before saving the replacement."""
        old_image = serializer.instance.image
        # Only delete if the image field is actually being changed
        new_image = serializer.validated_data.get('image')
        if new_image and old_image:
            self._delete_cloudinary_asset(old_image)
        serializer.save()

    def perform_destroy(self, instance):
        """Delete the Cloudinary asset when the photo record is removed."""
        self._delete_cloudinary_asset(instance.image)
        instance.delete()

import math

def calculate_haversine_distance(lat1, lon1, lat2, lon2):
    # Radius of the Earth in kilometers
    R = 6371.0
    
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    
    a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c

# 3. MATCHING (DATING) API
class PerfectMatchView(APIView):
    """
    Computes and returns compatible profiles sorted by score descending.
    Excludes blocked users and profiles that have already been liked/disliked.
    Supports basic and advanced search filters (with Premium subscription tier limits).
    """
    def get(self, request):
        me = get_object_or_404(UserProfile, user=request.user)
        
        # Check distance filter query param
        distance_max = request.query_params.get('distance_max')
        if distance_max:
            try:
                distance_max = float(distance_max)
            except ValueError:
                distance_max = None
                
        if distance_max is not None and (me.latitude is None or me.longitude is None):
            return Response(
                {"error": "Please set your location coordinates to filter by distance."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check for advanced filters if user is freemium
        advanced_params = [
            'education_level', 'smoking', 'alcohol', 'pets', 'sport', 'eating_habits',
            'emotional_needs', 'soothe_methods', 'recharge_methods', 'exhaust_triggers',
            'interests', 'second_degree_humor'
        ]
        has_advanced_filter = any(param in request.query_params for param in advanced_params)
        
        if has_advanced_filter and me.subscription_tier == 'freemium' and not me.has_advanced_filters:
            return Response(
                {"error": "Upgrade to Premium or purchase the Advanced Filters add-on to access these filters."},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get list of blocked users
        blocked_by_me = Block.objects.filter(blocker=me).values_list('blocked_user', flat=True)
        blocked_me = Block.objects.filter(blocked_user=me).values_list('blocker', flat=True)
        
        # Get list of friends (pending or accepted) to exclude from dating
        friends_sent = Friendship.objects.filter(sender=me).values_list('receiver', flat=True)
        friends_received = Friendship.objects.filter(receiver=me).values_list('sender', flat=True)
        
        base_exclude = set(blocked_by_me).union(set(blocked_me)).union(set(friends_sent)).union(set(friends_received))
        base_exclude.add(me.id)
        
        # Get profiles already swiped
        swiped_users = Match.objects.filter(user1=me).values_list('user2', flat=True)
        
        # Check if we ran out of profiles (excluding me, blocked, and liked/matched profiles)
        liked_or_matched_users = Match.objects.filter(user1=me, status__in=['liked', 'matched']).values_list('user2', flat=True)
        active_exclude = base_exclude.union(set(liked_or_matched_users))
        
        # Count remaining candidates that have not been swiped at all
        candidates_count = UserProfile.objects.filter(
            is_deactivated=False,
            is_verified=True,
            user__role='member',
            user__is_staff=False,
            user__is_superuser=False
        ).exclude(id__in=active_exclude).exclude(id__in=swiped_users).count()
        
        # If 5 or fewer profiles are left, recycle the 'disliked' matches to give them another chance
        if candidates_count <= 5:
            Match.objects.filter(user1=me, status='disliked').delete()
            swiped_users = Match.objects.filter(user1=me).values_list('user2', flat=True)
            
        exclude_users = base_exclude.union(set(swiped_users))
        
        # Filter potential matches
        candidates = UserProfile.objects.filter(
            is_deactivated=False,
            is_verified=True,
            user__role='member',
            user__is_staff=False,
            user__is_superuser=False
        ).exclude(id__in=exclude_users).select_related('user').prefetch_related('photos')
        
        # 1. Apply Basic Filters
        age_min = request.query_params.get('age_min')
        if age_min:
            try:
                candidates = candidates.filter(age__gte=int(age_min))
            except ValueError:
                pass

        age_max = request.query_params.get('age_max')
        if age_max:
            try:
                candidates = candidates.filter(age__lte=int(age_max))
            except ValueError:
                pass

        gender = request.query_params.get('gender')
        if gender:
            genders = [g.strip().lower() for g in gender.split(',')]
            candidates = candidates.filter(gender__in=genders)

        marital_status = request.query_params.get('marital_status')
        if marital_status:
            statuses = [s.strip().lower() for s in marital_status.split(',')]
            # Handle user friendly label mapping if needed (e.g. widowed to widow, etc.)
            mapped_statuses = []
            for status_val in statuses:
                if status_val in ['widow', 'widowed']:
                    mapped_statuses.append('widowed')
                elif status_val in ['divorce', 'divorced']:
                    mapped_statuses.append('divorced')
                else:
                    mapped_statuses.append(status_val)
            candidates = candidates.filter(marital_status__in=mapped_statuses)

        city = request.query_params.get('city')
        if city:
            candidates = candidates.filter(city__icontains=city)

        country = request.query_params.get('country')
        if country:
            candidates = candidates.filter(country__icontains=country)

        height_min = request.query_params.get('height_min')
        if height_min:
            try:
                # E.g. strip "cm" if passed
                h_min = int(height_min.replace('cm', '').strip())
                candidates = candidates.filter(height_cm__gte=h_min)
            except ValueError:
                pass

        height_max = request.query_params.get('height_max')
        if height_max:
            try:
                h_max = int(height_max.replace('cm', '').strip())
                candidates = candidates.filter(height_cm__lte=h_max)
            except ValueError:
                pass

        looking_for = request.query_params.get('looking_for')
        if looking_for:
            looking_for_list = [l.strip().lower() for l in looking_for.split(',')]
            mapped_looking_for = []
            for item in looking_for_list:
                if item in ['serious', 'serious relationship', 'serious relationship / long-term bonds']:
                    mapped_looking_for.append('serious')
                elif item in ['friendship', 'friendship / platonic first']:
                    mapped_looking_for.append('friendship')
                elif item in ["we'll see", "we will see", "undecided", "open to options"]:
                    mapped_looking_for.append('undecided')
                elif item in ['going out', 'casual', 'casual fun']:
                    mapped_looking_for.append('casual')
                else:
                    mapped_looking_for.append(item)
            candidates = candidates.filter(looking_for__in=mapped_looking_for)

        # 2. Apply Advanced Filters (Only if user has premium)
        if me.subscription_tier != 'freemium':
            education_level = request.query_params.get('education_level')
            if education_level:
                edu_list = [el.strip().lower() for el in education_level.split(',')]
                mapped_edu = []
                for edu in edu_list:
                    if edu in ['masters', 'master']:
                        mapped_edu.append('master')
                    elif edu in ['bachelors', 'bachelor']:
                        mapped_edu.append('bachelor')
                    elif edu in ['phd', 'doctorate']:
                        mapped_edu.append('phd')
                    elif edu in ['below bachelor', 'below']:
                        mapped_edu.append('below')
                    else:
                        mapped_edu.append(edu)
                # Filter if education_level matches any of these mapped values
                q_edu = Q()
                for e in mapped_edu:
                    q_edu |= Q(education_level__icontains=e)
                candidates = candidates.filter(q_edu)

            smoking = request.query_params.get('smoking')
            if smoking:
                candidates = candidates.filter(smoking=(smoking.lower() == 'true'))

            alcohol = request.query_params.get('alcohol')
            if alcohol:
                candidates = candidates.filter(alcohol=(alcohol.lower() == 'true'))

            pets = request.query_params.get('pets')
            if pets:
                candidates = candidates.filter(pets=(pets.lower() == 'true'))

            sport = request.query_params.get('sport')
            if sport:
                sport_list = [s.strip().lower() for s in sport.split(',')]
                mapped_sport = []
                for sp in sport_list:
                    if sp in ['sedentary', 'no sport']:
                        mapped_sport.append('No Sport')
                    elif sp == 'moderate':
                        mapped_sport.append('Moderate')
                    elif sp == 'intense':
                        mapped_sport.append('Intense')
                    else:
                        mapped_sport.append(sp.title())
                candidates = candidates.filter(sport__in=mapped_sport)

            eating_habits = request.query_params.get('eating_habits')
            if eating_habits:
                candidates = candidates.filter(eating_habits__iexact=eating_habits)

            second_degree_humor = request.query_params.get('second_degree_humor')
            if second_degree_humor:
                candidates = candidates.filter(second_degree_humor=(second_degree_humor.lower() == 'true'))

        # 3. Apply JSON-list Python-level intersection filters
        req_neurotypes = request.query_params.get('neurotype')
        filter_neurotypes = [n.strip().lower() for n in req_neurotypes.split(',')] if req_neurotypes else []

        req_languages = request.query_params.get('spoken_languages') or request.query_params.get('languages')
        filter_languages = [l.strip().lower() for l in req_languages.split(',')] if req_languages else []

        # Advanced profile options (Requires premium check already covered)
        filter_interests = []
        filter_emotional_needs = []
        filter_soothe_methods = []
        filter_recharge_methods = []
        filter_exhaust_triggers = []

        if me.subscription_tier != 'freemium':
            req_interests = request.query_params.get('interests')
            if req_interests:
                filter_interests = [i.strip().lower() for i in req_interests.split(',')]

            req_needs = request.query_params.get('emotional_needs')
            if req_needs:
                filter_emotional_needs = [x.strip().lower() for x in req_needs.split(',')]

            req_soothe = request.query_params.get('soothe_methods')
            if req_soothe:
                filter_soothe_methods = [x.strip().lower() for x in req_soothe.split(',')]

            req_recharge = request.query_params.get('recharge_methods')
            if req_recharge:
                filter_recharge_methods = [x.strip().lower() for x in req_recharge.split(',')]

            req_exhaust = request.query_params.get('exhaust_triggers')
            if req_exhaust:
                filter_exhaust_triggers = [x.strip().lower() for x in req_exhaust.split(',')]

        # Execute python-level filters if any are active
        if (filter_neurotypes or filter_languages or filter_interests or 
                filter_emotional_needs or filter_soothe_methods or 
                filter_recharge_methods or filter_exhaust_triggers):
            filtered_candidates = []
            for candidate in candidates:
                if filter_neurotypes:
                    c_neuro = [n.lower() for n in (candidate.neurotype_labels or [])]
                    if not any(nt in c_neuro for nt in filter_neurotypes):
                        continue

                if filter_languages:
                    c_langs = [l.lower() for l in (candidate.spoken_languages or [])]
                    if not any(lang in c_langs for lang in filter_languages):
                        continue

                if filter_interests:
                    c_interests = [i.lower() for i in (candidate.interests or [])]
                    if not any(interest in c_interests for interest in filter_interests):
                        continue

                if filter_emotional_needs:
                    c_needs = [x.lower() for x in (candidate.emotional_needs or [])]
                    if not any(x in c_needs for x in filter_emotional_needs):
                        continue

                if filter_soothe_methods:
                    c_soothe = [x.lower() for x in (candidate.soothe_methods or [])]
                    if not any(x in c_soothe for x in filter_soothe_methods):
                        continue

                if filter_recharge_methods:
                    c_recharge = [x.lower() for x in (candidate.recharge_methods or [])]
                    if not any(x in c_recharge for x in filter_recharge_methods):
                        continue

                if filter_exhaust_triggers:
                    c_exhaust = [x.lower() for x in (candidate.exhaust_triggers or [])]
                    if not any(x in c_exhaust for x in filter_exhaust_triggers):
                        continue

                filtered_candidates.append(candidate)
            candidates = filtered_candidates

        # Compute compatibility score and check for super likes
        superliked_by_ids = set(Match.objects.filter(user2=me, status='superliked').values_list('user1_id', flat=True))
        
        matches = []
        for candidate in candidates:
            # Calculate distance if coordinates are set
            distance = None
            if me.latitude is not None and me.longitude is not None and candidate.latitude is not None and candidate.longitude is not None:
                distance = calculate_haversine_distance(me.latitude, me.longitude, candidate.latitude, candidate.longitude)
                
            # Filter by max distance if requested
            if distance_max is not None:
                if distance is None or distance > distance_max:
                    continue  # Skip profiles outside distance range or missing coordinates

            score = calculate_compatibility(me, candidate)
            
            # Find main photo url
            main_photo = get_main_photo(candidate)
            photo_url = get_cloudinary_url(main_photo.image) if main_photo else None

            # Generate dynamic bio
            qualities_display = candidate.qualities or []
            interests_list = [i.lower() for i in (candidate.interests or [])]
            interests_list = ["video games" if i == "gaming" else i for i in interests_list]
            
            if len(interests_list) >= 3:
                interests_text = f"Loves {interests_list[0]}, {interests_list[1]}, {interests_list[2]}, and random fact"
            elif len(interests_list) == 2:
                interests_text = f"Loves {interests_list[0]}, {interests_list[1]}, and random fact"
            elif len(interests_list) == 1:
                interests_text = f"Loves {interests_list[0]} and random fact"
            else:
                interests_text = "Loves video games, coffee, space, and random fact"

            if qualities_display:
                bio = f"{qualities_display[0]} • {interests_text}"
            else:
                bio = interests_text

            matches.append({
                "id": candidate.id,
                "name": candidate.display_name,
                "age": candidate.age,
                "gender": candidate.gender,
                "city": candidate.city,
                "country": candidate.country,
                "bio": bio,
                "tags": qualities_display,
                "photo": photo_url,
                "compatibility_score": score,
                "distance": round(distance, 1) if distance is not None else None,
                "has_superliked_me": candidate.id in superliked_by_ids,
                "is_verified": candidate.is_verified
            })
            
        # Shuffle results first to randomize the base deck
        import random
        random.shuffle(matches)
        
        # Then stable sort so that anyone who superliked you floats to the very top
        matches = sorted(matches, key=lambda x: x['has_superliked_me'], reverse=True)

        # Pagination
        try:
            page = int(request.query_params.get('page', 1))
            if page < 1:
                page = 1
        except ValueError:
            page = 1

        try:
            page_size = int(request.query_params.get('page_size', 10))
            if page_size < 1 or page_size > 50:
                page_size = 10
        except ValueError:
            page_size = 10

        total_count = len(matches)
        total_pages = max(1, math.ceil(total_count / page_size))
        start = (page - 1) * page_size
        end = start + page_size
        paginated_matches = matches[start:end]

        # Build base URL for next/previous links
        base_url = request.build_absolute_uri(request.path)
        # Forward all existing query params except 'page'
        query_params = request.query_params.dict()
        query_params.pop('page', None)
        param_str = '&'.join([f"{k}={v}" for k, v in query_params.items()])
        base_with_params = f"{base_url}?{param_str}&" if param_str else f"{base_url}?"

        next_page = f"{base_with_params}page={page + 1}" if page < total_pages else None
        prev_page = f"{base_with_params}page={page - 1}" if page > 1 else None

        # Check if limit is already reached
        limit_reached = False
        daily_likes = Match.objects.filter(
            user1=me, 
            status__in=['liked', 'superliked', 'matched'], 
            created_at__date=timezone.now().date()
        ).count()
        
        if me.subscription_tier == 'freemium' and daily_likes >= 20:
            limit_reached = True
        elif me.subscription_tier == 'light' and daily_likes >= 50:
            limit_reached = True

        return Response({
            "total_count": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "next": next_page,
            "previous": prev_page,
            "results": paginated_matches,
            "limit_reached": limit_reached
        }, status=status.HTTP_200_OK)



class MatchAnalysisView(APIView):
    """
    GET /api/matching/analysis/
    Returns the top 5 highest-scored matches for the user.
    Requires Perfect Match Analysis add-on.
    """
    def get(self, request):
        me = get_object_or_404(UserProfile, user=request.user)
        
        if not me.has_match_analysis:
            return Response(
                {"error": "You need the Perfect Match Analysis add-on to access this feature."},
                status=status.HTTP_403_FORBIDDEN
            )
            
        # Get list of blocked users and friends to exclude
        blocked_by_me = Block.objects.filter(blocker=me).values_list('blocked_user', flat=True)
        blocked_me = Block.objects.filter(blocked_user=me).values_list('blocker', flat=True)
        friends_sent = Friendship.objects.filter(sender=me).values_list('receiver', flat=True)
        friends_received = Friendship.objects.filter(receiver=me).values_list('sender', flat=True)
        
        base_exclude = set(blocked_by_me).union(set(blocked_me)).union(set(friends_sent)).union(set(friends_received))
        base_exclude.add(me.id)
        
        # Exclude users already swiped
        swiped_users = Match.objects.filter(user1=me).values_list('user2', flat=True)
        exclude_users = base_exclude.union(set(swiped_users))
        
        # Filter potential matches
        candidates = UserProfile.objects.filter(
            is_deactivated=False,
            is_verified=True,
            user__role='member',
            user__is_staff=False,
            user__is_superuser=False
        ).exclude(id__in=exclude_users).select_related('user').prefetch_related('photos')

        # Filter by opposite gender based on user's profile
        if me.gender.lower() == 'man':
            candidates = candidates.filter(gender__iexact='woman')
        elif me.gender.lower() == 'woman':
            candidates = candidates.filter(gender__iexact='man')
        
        matches = []
        for candidate in candidates:
            comp_score = calculate_compatibility(me, candidate)
            
            # Fetch photo URL
            photo_url = None
            if candidate.photos.exists():
                main_photo = get_main_photo(candidate)
                photo_url = request.build_absolute_uri(main_photo.image.url)

            # Build tags
            qualities_display = candidate.qualities if candidate.qualities else []
            interests_list = candidate.interests if candidate.interests else []

            matches.append({
                "id": candidate.id,
                "name": candidate.display_name,
                "age": candidate.age,
                "gender": candidate.gender,
                "city": candidate.city,
                "country": candidate.country,
                "tags": qualities_display + interests_list,
                "photo": photo_url,
                "compatibility_score": comp_score
            })
            
        # Sort strictly by score, descending
        matches = sorted(matches, key=lambda x: x['compatibility_score'], reverse=True)
        
        # Take exactly top 5
        top_matches = matches[:5]
        
        return Response({"results": top_matches}, status=status.HTTP_200_OK)


class MatchActionView(APIView):
    """
    POST to like/dislike a profile. Enforces subscription limits.
    """
    def post(self, request, target_profile_id):
        me = get_object_or_404(UserProfile, user=request.user)
        target = get_object_or_404(UserProfile, id=target_profile_id)
        action_type = request.data.get('action') # 'liked', 'disliked', 'superliked', or 'undo'
        
        if action_type not in ['liked', 'disliked', 'superliked', 'undo']:
            return Response({"error": "Invalid action. Use 'liked', 'disliked', 'superliked', or 'undo'."}, status=status.HTTP_400_BAD_REQUEST)
            
        if action_type == 'undo':
            if me.subscription_tier == 'freemium':
                return Response({"error": "Undo is a premium feature. Upgrade to Premium to rewind your swipes."}, status=status.HTTP_403_FORBIDDEN)
                
            match_obj = Match.objects.filter(user1=me, user2=target).first()
            if match_obj:
                if match_obj.status == 'matched':
                    # Revert mutual match back to a pending like for the other user
                    mutual = Match.objects.filter(user1=target, user2=me, status='matched').first()
                    if mutual:
                        mutual.status = 'liked'
                        mutual.save()
                match_obj.delete()
            return Response({"status": "undone", "is_mutual_match": False}, status=status.HTTP_200_OK)
            
        # 1. Enforce Subscription Likes Limits (Only for likes/superlikes)
        if action_type in ['liked', 'superliked']:
            daily_likes = Match.objects.filter(
                user1=me, 
                status__in=['liked', 'superliked', 'matched'], 
                created_at__date=timezone.now().date()
            ).count()
            
            if me.subscription_tier == 'freemium' and daily_likes >= 20:
                return Response({"error": "Daily like limit (20) reached. Upgrade to Premium for more."}, status=status.HTTP_403_FORBIDDEN)
            if me.subscription_tier == 'light' and daily_likes >= 50:
                return Response({"error": "Daily like limit (50) reached. Upgrade to Premium Plus for more."}, status=status.HTTP_403_FORBIDDEN)

        # 2. Check Block status
        if Block.objects.filter(Q(blocker=me, blocked_user=target) | Q(blocker=target, blocked_user=me)).exists():
            return Response({"error": "Unable to perform action. Communication is blocked."}, status=status.HTTP_400_BAD_REQUEST)

        # 3. Create or update match status
        match_obj, created = Match.objects.get_or_create(user1=me, user2=target, defaults={'status': action_type})
        if not created:
            match_obj.status = action_type
            match_obj.save()
            
        # 4. Check if mutual match exists
        is_mutual = False
        if action_type in ['liked', 'superliked']:
            mutual = Match.objects.filter(user1=target, user2=me, status__in=['liked', 'superliked', 'matched']).first()
            if mutual:
                # Update status of both to matched
                match_obj.status = 'matched'
                match_obj.save()
                mutual.status = 'matched'
                mutual.save()
                is_mutual = True
                
                if getattr(target, 'likes_push', True):
                    send_push_notification_to_user(
                        user=target.user,
                        title="It's a Match! 🎉",
                        body=f"You and {me.name or me.username} have liked each other.",
                        data={"type": "match", "profile_id": me.id}
                    )
                
        return Response({
            "status": match_obj.status,
            "is_mutual_match": is_mutual
        }, status=status.HTTP_200_OK)

class LikesReceivedView(APIView):
    """
    GET users who liked you. Blocked for Freemium users.
    """
    def get(self, request):
        me = get_object_or_404(UserProfile, user=request.user)
        
        # Enforce restriction
        if me.subscription_tier == 'freemium':
            return Response({"error": "Upgrade to Premium to see who liked you."}, status=status.HTTP_403_FORBIDDEN)
            
        likes = Match.objects.filter(user2=me, status='liked').select_related('user1__user').prefetch_related('user1__photos')
        profiles = [like.user1 for like in likes]
        serializer = UserProfileBasicSerializer(profiles, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

class LikesSentView(APIView):
    def get(self, request):
        me = get_object_or_404(UserProfile, user=request.user)
        likes = Match.objects.filter(user1=me, status__in=['liked', 'matched']).select_related('user2__user').prefetch_related('user2__photos')
        
        data = []
        for l in likes:
            data.append({
                "profile": UserProfileBasicSerializer(l.user2, context={'request': request}).data,
                "status": "SENT" if l.status == 'liked' else "MATCHED",
                "created_at": l.created_at
            })
        return Response(data, status=status.HTTP_200_OK)

class MutualMatchesView(APIView):
    """
    GET /api/matching/matches/
    Returns all profiles you've mutually matched with (both liked each other).
    These are the conversations the user can open in the Matches tab.
    """
    def get(self, request):
        me = get_object_or_404(UserProfile, user=request.user)

        # A mutual match is recorded on both sides with status='matched'
        matched = Match.objects.filter(
            Q(user1=me) | Q(user2=me),
            status='matched'
        ).select_related('user1__user', 'user2__user').prefetch_related('user1__photos', 'user2__photos').order_by('-created_at')

        results = []
        for m in matched:
            other = m.user2 if m.user1 == me else m.user1
            results.append({
                "match_id": m.id,
                "matched_at": m.created_at,
                "profile": UserProfileBasicSerializer(other, context={'request': request}).data,
            })

        return Response(results, status=status.HTTP_200_OK)


class SaveMatchView(APIView):
    """
    POST /api/matching/<target_profile_id>/save/
    Saves a profile to the user's saved list.
    """
    def post(self, request, target_profile_id):
        me = get_object_or_404(UserProfile, user=request.user)
        target = get_object_or_404(UserProfile, id=target_profile_id)

        if me == target:
            return Response({"error": "You cannot save your own profile."}, status=status.HTTP_400_BAD_REQUEST)

        saved_match, created = SavedMatch.objects.get_or_create(user=me, target_profile=target)
        if created:
            message = "Profile saved successfully."
        else:
            message = "Profile was already saved."

        return Response({"message": message, "target_profile_id": target_profile_id}, status=status.HTTP_200_OK)


class UnsaveMatchView(APIView):
    """
    POST /api/matching/<target_profile_id>/unsave/
    Removes a profile from the user's saved list.
    """
    def post(self, request, target_profile_id):
        me = get_object_or_404(UserProfile, user=request.user)
        target = get_object_or_404(UserProfile, id=target_profile_id)

        deleted_count, _ = SavedMatch.objects.filter(user=me, target_profile=target).delete()
        if deleted_count > 0:
            message = "Profile unsaved successfully."
        else:
            message = "Profile was not in your saved list."

        return Response({"message": message, "target_profile_id": target_profile_id}, status=status.HTTP_200_OK)

class UnmatchUserView(APIView):
    """
    POST /api/matching/<target_profile_id>/unmatch/
    Removes a match entirely (dating mode).
    """
    def post(self, request, target_profile_id):
        me = get_object_or_404(UserProfile, user=request.request.user if hasattr(request, 'request') else request.user)
        target = get_object_or_404(UserProfile, id=target_profile_id)
        
        deleted, _ = Match.objects.filter(
            Q(user1=me, user2=target) | Q(user1=target, user2=me)
        ).delete()

        if deleted:
            DirectMessage.objects.filter(
                Q(sender=me, receiver=target) | Q(sender=target, receiver=me)
            ).delete()
        
        return Response({
            "message": "Unmatched successfully" if deleted else "No match existed.",
            "target_profile_id": str(target_profile_id)
        }, status=status.HTTP_200_OK)


class SavedMatchesListView(APIView):
    """
    GET /api/matching/saved/
    Returns a list of saved matches (profiles you bookmarked).
    """
    def get(self, request):
        me = get_object_or_404(UserProfile, user=request.user)
        saved = SavedMatch.objects.filter(user=me).select_related('target_profile__user').prefetch_related('target_profile__photos').order_by('-created_at')
        serializer = SavedMatchSerializer(saved, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


# 4. FRIENDS API
class FriendshipViewSet(viewsets.ModelViewSet):
    serializer_class = FriendshipSerializer

    def get_queryset(self):
        me = get_object_or_404(UserProfile, user=self.request.user)
        return Friendship.objects.filter(Q(sender=me) | Q(receiver=me))

    @action(detail=False, methods=['get'])
    def requests(self, request):
        me = get_object_or_404(UserProfile, user=request.user)
        incoming = list(
            Friendship.objects.filter(receiver=me, status='pending')
            .select_related('sender__user')
            .prefetch_related('sender__photos')
        )
        friend_ids = get_friend_ids([me.id, *(req.sender_id for req in incoming)])

        requests_data = []
        for req in incoming:
            sender = req.sender
            
            mutual_count = len(friend_ids[me.id].intersection(friend_ids[sender.id]))

            # Main photo
            main_photo = get_main_photo(sender)
            photo_url = get_cloudinary_url(main_photo.image) if main_photo else None

            # Subtitle text: "2 mutual friends • North Bondi" or just "North Bondi"
            location = sender.city or sender.country or ""
            if mutual_count > 0:
                subtitle = f"{mutual_count} mutual friend{'s' if mutual_count > 1 else ''}"
                if location:
                    subtitle += f" • {location}"
            else:
                subtitle = location

            requests_data.append({
                "id": req.id,
                "sender_id": sender.id,
                "name": sender.display_name,
                "photo": photo_url,
                "subtitle": subtitle,
                "mutual_friends_count": mutual_count,
                "location": location
            })
            
        return Response(requests_data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def sent_requests(self, request):
        me = get_object_or_404(UserProfile, user=request.user)
        outgoing = list(
            Friendship.objects.filter(sender=me, status='pending')
            .select_related('receiver__user')
            .prefetch_related('receiver__photos')
        )
        friend_ids = get_friend_ids([me.id, *(req.receiver_id for req in outgoing)])

        requests_data = []
        for req in outgoing:
            receiver = req.receiver
            
            mutual_count = len(friend_ids[me.id].intersection(friend_ids[receiver.id]))

            # Main photo
            main_photo = get_main_photo(receiver)
            photo_url = get_cloudinary_url(main_photo.image) if main_photo else None

            # Subtitle text
            location = receiver.city or receiver.country or ""
            if mutual_count > 0:
                subtitle = f"{mutual_count} mutual friend{'s' if mutual_count > 1 else ''}"
                if location:
                    subtitle += f" • {location}"
            else:
                subtitle = location

            requests_data.append({
                "id": req.id,
                "receiver_id": receiver.id,
                "name": receiver.display_name,
                "photo": photo_url,
                "subtitle": subtitle,
                "mutual_friends_count": mutual_count,
                "location": location
            })
            
        return Response(requests_data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def suggestions(self, request):
        me = get_object_or_404(UserProfile, user=request.user)

        # Get blocked and blocking users
        blocked_by_me = Block.objects.filter(blocker=me).values_list('blocked_user', flat=True)
        blocked_me = Block.objects.filter(blocked_user=me).values_list('blocker', flat=True)
        exclude_ids = set(blocked_by_me).union(set(blocked_me))

        # Get existing friendships (pending or accepted)
        existing_friends_sender = Friendship.objects.filter(sender=me).values_list('receiver', flat=True)
        existing_friends_receiver = Friendship.objects.filter(receiver=me).values_list('sender', flat=True)
        exclude_ids = exclude_ids.union(set(existing_friends_sender)).union(set(existing_friends_receiver))

        # Exclude self
        exclude_ids.add(me.id)

        # Base suggestions queryset
        queryset = UserProfile.objects.filter(
            is_deactivated=False,
            is_verified=True,
            user__role='member',
            user__is_staff=False,
            user__is_superuser=False
        ).exclude(id__in=exclude_ids)

        # Apply search bar query (?search=Name)
        search_query = request.query_params.get('search')
        if search_query:
            queryset = queryset.filter(username__icontains=search_query)

        # Apply filters (age_min, age_max, gender)
        age_min = request.query_params.get('age_min')
        if age_min:
            try:
                queryset = queryset.filter(age__gte=int(age_min))
            except ValueError:
                pass

        age_max = request.query_params.get('age_max')
        if age_max:
            try:
                queryset = queryset.filter(age__lte=int(age_max))
            except ValueError:
                pass

        gender = request.query_params.get('gender')
        if gender:
            genders = [g.strip().lower() for g in gender.split(',')]
            queryset = queryset.filter(gender__in=genders)

        # Get limit and offset for pagination
        limit = int(request.query_params.get('limit', 20))
        offset = int(request.query_params.get('offset', 0))

        # Order suggestions
        queryset = queryset.order_by('-profile_completion_pct', '-id').select_related('user').prefetch_related('photos')
        
        # Total count
        total = queryset.count()
        
        # Apply pagination
        queryset = queryset[offset:offset+limit]

        suggestions_data = []
        for candidate in queryset:
            # Get main photo URL
            main_photo = candidate.photos.filter(is_main=True).first()
            if not main_photo:
                main_photo = candidate.photos.first()
            photo_url = get_cloudinary_url(main_photo.image) if main_photo else None

            # Generate up to 2 unique tags from qualities & interests
            tags = []
            if candidate.qualities:
                tags.append(candidate.qualities[0])
            if candidate.interests:
                tags.append(candidate.interests[0])
            tags = list(dict.fromkeys(tags))[:2]

            # Generate clean dynamic bio sentence
            interests_list = [i.lower() for i in (candidate.interests or [])]
            if len(interests_list) >= 3:
                bio = f"Loves {interests_list[0]}, {interests_list[1]}, and {interests_list[2]}"
            elif len(interests_list) == 2:
                bio = f"Loves {interests_list[0]} and {interests_list[1]}"
            elif len(interests_list) == 1:
                bio = f"Loves {interests_list[0]}"
            else:
                bio = "Open-minded and ready to connect"

            suggestions_data.append({
                "id": candidate.id,
                "name": candidate.display_name,
                "age": candidate.age,
                "tags": tags,
                "bio": bio,
                "photo": photo_url
            })

        return Response({
            "results": suggestions_data,
            "next": (offset + limit) < total,
            "total": total
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'])
    def send_request(self, request):
        me = get_object_or_404(UserProfile, user=request.user)
        target_id = request.data.get('user_id')
        target = get_object_or_404(UserProfile, id=target_id)
        
        if Block.objects.filter(Q(blocker=me, blocked_user=target) | Q(blocker=target, blocked_user=me)).exists():
            return Response({"error": "Blocked."}, status=status.HTTP_400_BAD_REQUEST)
            
        friendship, created = Friendship.objects.get_or_create(sender=me, receiver=target, defaults={'status': 'pending'})
        if not created and friendship.status == 'declined':
            friendship.status = 'pending'
            friendship.save()
            
        if getattr(target, 'messages_push', True):
            send_push_notification_to_user(
                user=target.user,
                title="New Friend Request",
                body=f"{me.name or me.username} sent you a friend request!",
                data={"type": "friend_request_received", "profile_id": me.id}
            )
            
        return Response({"message": "Request sent."}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def accept(self, request, pk=None):
        friendship = self.get_object()
        if friendship.receiver.user != request.user:
            return Response({"error": "Unauthorized."}, status=status.HTTP_403_FORBIDDEN)
        friendship.status = 'accepted'
        friendship.save()
        
        if getattr(friendship.sender, 'messages_push', True):
            send_push_notification_to_user(
                user=friendship.sender.user,
                title="Friend Request Accepted",
                body=f"{friendship.receiver.name or friendship.receiver.username} accepted your friend request!",
                data={"type": "friend_request_accepted", "profile_id": friendship.receiver.id}
            )
        
        return Response({"message": "Friend request accepted."})

    @action(detail=True, methods=['post'])
    def decline(self, request, pk=None):
        friendship = self.get_object()
        if friendship.receiver.user != request.user:
            return Response({"error": "Unauthorized."}, status=status.HTTP_430_FORBIDDEN)
        friendship.status = 'declined'
        friendship.save()
        return Response({"message": "Friend request declined."})

class UnfriendUserView(APIView):
    """
    DELETE /api/friends/<target_profile_id>/unfriend/
    Removes a friend completely.
    """
    def delete(self, request, target_profile_id):
        me = get_object_or_404(UserProfile, user=request.request.user if hasattr(request, 'request') else request.user)
        target = get_object_or_404(UserProfile, id=target_profile_id)
        
        deleted, _ = Friendship.objects.filter(
            Q(sender=me, receiver=target) | Q(sender=target, receiver=me)
        ).delete()

        if deleted:
            DirectMessage.objects.filter(
                Q(sender=me, receiver=target) | Q(sender=target, receiver=me)
            ).delete()
        
        return Response({
            "message": "Unfriended successfully" if deleted else "Not friends.",
            "target_profile_id": str(target_profile_id)
        }, status=status.HTTP_200_OK)

# 5. CHAT & MESSAGING API
class ChatRoomViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ChatRoomSerializer

    def get_queryset(self):
        # Order by created_at to ensure consistent chat rooms are returned for restricted tiers
        queryset = ChatRoom.objects.prefetch_related('members__photos').order_by('created_at')
        
        if hasattr(self.request, 'user') and self.request.user.is_authenticated:
            try:
                me = UserProfile.objects.get(user=self.request.user)
                has_full_access = (me.subscription_tier == 'plus' or me.has_all_chat_rooms)
                if not has_full_access:
                    # Freemium and Premium Light only get access to the first 3 chat rooms
                    allowed_ids = list(ChatRoom.objects.order_by('created_at').values_list('id', flat=True)[:3])
                    queryset = queryset.filter(id__in=allowed_ids)
            except UserProfile.DoesNotExist:
                pass

        search_query = self.request.query_params.get('search')
        if search_query:
            queryset = queryset.filter(Q(name__icontains=search_query) | Q(description__icontains=search_query))
        return queryset

    def list(self, request, *args, **kwargs):
        # Freemium restriction: no chat room access
        me = get_object_or_404(UserProfile, user=request.user)
        if me.subscription_tier == 'freemium' and not me.has_all_chat_rooms:
            return Response({"error": "Upgrade to Premium or purchase the All Chat Rooms add-on to access Community Chat Rooms."}, status=status.HTTP_403_FORBIDDEN)
        return super().list(request, *args, **kwargs)

    @action(detail=True, methods=['get'])
    def messages(self, request, pk=None):
        room = self.get_object()
        # Production grade: 
        # 1. Fetch newest 50 messages by timestamp descending
        # 2. Use select_related and prefetch_related to eliminate N+1 DB queries on the sender & their photos
        messages_qs = room.messages.select_related('sender').prefetch_related('sender__photos').order_by('-timestamp')[:50]
        
        # Reverse the list so the frontend gets them in chronological order (oldest -> newest in the payload)
        messages_list = list(messages_qs)
        messages_list.reverse()
        
        serializer = ChatRoomMessageSerializer(messages_list, many=True, context={'request': request})
        return Response(serializer.data)



    @action(detail=True, methods=['post'])
    def join(self, request, pk=None):
        me = get_object_or_404(UserProfile, user=request.user)
        if me.subscription_tier == 'freemium' and not me.has_all_chat_rooms:
            return Response({"error": "Upgrade to Premium or purchase the All Chat Rooms add-on to access Community Chat Rooms."}, status=status.HTTP_403_FORBIDDEN)
        room = self.get_object()
        room.members.add(me)
        room.member_count = room.members.count()
        room.save()
        return Response({
            "message": f"Successfully joined {room.name}.", 
            "room_id": room.id,
            "member_count": room.member_count
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def leave(self, request, pk=None):
        me = get_object_or_404(UserProfile, user=request.user)
        if me.subscription_tier == 'freemium' and not me.has_all_chat_rooms:
            return Response({"error": "Upgrade to Premium or purchase the All Chat Rooms add-on to access Community Chat Rooms."}, status=status.HTTP_403_FORBIDDEN)
        room = self.get_object()
        room.members.remove(me)
        room.member_count = room.members.count()
        room.save()
        return Response({
            "message": f"Successfully left {room.name}.", 
            "room_id": room.id,
            "member_count": room.member_count
        }, status=status.HTTP_200_OK)

class ChatRoomMessageCreateView(APIView):
    def post(self, request, room_id):
        me = get_object_or_404(UserProfile, user=request.user)
        if me.subscription_tier == 'freemium' and not me.has_all_chat_rooms:
            return Response({"error": "No chat room access."}, status=status.HTTP_403_FORBIDDEN)
            
        room = get_object_or_404(ChatRoom, id=room_id)
        
        # Enforce that user must have joined the room to send a message
        if not room.members.filter(id=me.id).exists():
            return Response(
                {"error": "You must join this room before you can send messages."},
                status=status.HTTP_403_FORBIDDEN
            )
            
        content = request.data.get('content')
        if not content:
            return Response({"error": "Content required."}, status=status.HTTP_400_BAD_REQUEST)
            
        message = ChatRoomMessage.objects.create(room=room, sender=me, content=content)
        serializer = ChatRoomMessageSerializer(message)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

class DirectMessageViewSet(viewsets.ModelViewSet):
    serializer_class = DirectMessageSerializer

    def get_queryset(self):
        me = get_object_or_404(UserProfile, user=self.request.user)
        return DirectMessage.objects.filter(
            Q(sender=me) | Q(receiver=me)
        ).select_related('sender__user', 'receiver__user').prefetch_related(
            'sender__photos', 'receiver__photos'
        ).order_by('timestamp')

    @action(detail=False, methods=['get'])
    def threads(self, request):
        me = get_object_or_404(UserProfile, user=request.user)
        thread_type = request.query_params.get('type', 'dating').lower().strip()

        relationship_dates = {}
        if thread_type == 'friends':
            relationships = Friendship.objects.filter(
                Q(sender=me) | Q(receiver=me), status='accepted'
            ).values('sender_id', 'receiver_id', 'created_at')
            empty_message = "You are now friends! Say hi."
            for relationship in relationships:
                partner_id = relationship['receiver_id'] if relationship['sender_id'] == me.id else relationship['sender_id']
                relationship_dates.setdefault(partner_id, relationship['created_at'])
        else:
            relationships = Match.objects.filter(
                Q(user1=me) | Q(user2=me), status='matched'
            ).values('user1_id', 'user2_id', 'created_at')
            empty_message = "You've matched! Say hi."
            for relationship in relationships:
                partner_id = relationship['user2_id'] if relationship['user1_id'] == me.id else relationship['user1_id']
                relationship_dates.setdefault(partner_id, relationship['created_at'])

        latest_message = DirectMessage.objects.filter(
            Q(sender=me, receiver=OuterRef('pk')) |
            Q(sender=OuterRef('pk'), receiver=me)
        ).order_by('-timestamp')
        unread_messages = DirectMessage.objects.filter(
            sender=OuterRef('pk'), receiver=me, read_at__isnull=True
        ).values('sender').annotate(total=Count('id')).values('total')

        partners = UserProfile.objects.filter(id__in=relationship_dates).select_related('user').prefetch_related('photos').annotate(
            last_message_content=Subquery(latest_message.values('content')[:1]),
            last_message_image=Subquery(latest_message.values('image_url')[:1]),
            last_message_time=Subquery(latest_message.values('timestamp')[:1]),
            unread_count=Coalesce(
                Subquery(unread_messages[:1], output_field=IntegerField()),
                Value(0),
            ),
        )

        thread_data = []
        for partner in partners:
            if partner.last_message_image:
                last_message = f"📷 Photo: {partner.last_message_content}" if partner.last_message_content else "📷 Photo"
            else:
                last_message = partner.last_message_content or empty_message

            main_photo = get_main_photo(partner)
            thread_data.append({
                "profile": {
                    "id": partner.id,
                    "name": partner.display_name,
                    "photo": get_cloudinary_url(main_photo.image) if main_photo else None,
                },
                "last_message": last_message,
                "last_message_time": partner.last_message_time or relationship_dates[partner.id],
                "unread_count": partner.unread_count,
            })

        # Sort descending by last message time
        thread_data = sorted(
            thread_data,
            key=lambda x: x['last_message_time'] if x['last_message_time'] else timezone.now(),
            reverse=True
        )
        return Response(thread_data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='history/(?P<recipient_id>[^/.]+)')
    def history(self, request, recipient_id=None):
        me = get_object_or_404(UserProfile, user=request.user)
        recipient = get_object_or_404(UserProfile, id=recipient_id)
        
        # Mark incoming messages as read
        DirectMessage.objects.filter(
            sender=recipient,
            receiver=me,
            read_at__isnull=True
        ).update(read_at=timezone.now())
        
        messages = DirectMessage.objects.filter(
            Q(sender=me, receiver=recipient) | Q(sender=recipient, receiver=me)
        ).select_related('sender__user', 'receiver__user').prefetch_related(
            'sender__photos', 'receiver__photos'
        ).order_by('timestamp')
        
        serializer = self.get_serializer(messages, many=True)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        me = get_object_or_404(UserProfile, user=request.user)
        recipient_id = request.data.get('receiver')
        recipient = get_object_or_404(UserProfile, id=recipient_id)
        content = request.data.get('content')
        image_url = request.data.get('image_url')
        reply_to_id = request.data.get('reply_to_id')

        # Check Block status
        if Block.objects.filter(Q(blocker=me, blocked_user=recipient) | Q(blocker=recipient, blocked_user=me)).exists():
            return Response({"error": "Blocked."}, status=status.HTTP_400_BAD_REQUEST)

        # Enforce Subscription Messaging limits
        # Find if thread already exists
        thread_exists = DirectMessage.objects.filter(
            Q(sender=me, receiver=recipient) | Q(sender=recipient, receiver=me)
        ).exists()

        if not thread_exists:
            # We are creating a new thread. Check monthly limit.
            current_month = timezone.now().month
            new_threads_this_month = DirectMessage.objects.filter(
                sender=me, 
                timestamp__month=current_month
            ).values('receiver').distinct().count()
            
            if me.subscription_tier == 'freemium' and new_threads_this_month >= 1:
                return Response({"error": "Freemium tier allows only 1 new message thread initiation per month. Upgrade to send more."}, status=status.HTTP_403_FORBIDDEN)
            if me.subscription_tier == 'light' and new_threads_this_month >= 3:
                return Response({"error": "Premium Light allows only 3 new message thread initiations per month. Upgrade to Premium Plus for unlimited."}, status=status.HTTP_403_FORBIDDEN)

        reply_msg = None
        if reply_to_id:
            reply_msg = DirectMessage.objects.filter(id=reply_to_id).first()

        message = DirectMessage.objects.create(
            sender=me, 
            receiver=recipient, 
            content=content,
            image_url=image_url,
            reply_to=reply_msg
        )
        serializer = self.get_serializer(message)

        # Broadcast via WebSocket Channel Layer so the receiver gets the live update
        channel_layer = get_channel_layer()
        if channel_layer:
            payload = {
                'type': 'direct_message',
                'message': serializer.data,
            }
            async_to_sync(channel_layer.group_send)(f"inbox_{me.id}", payload)
            async_to_sync(channel_layer.group_send)(f"inbox_{recipient.id}", payload)

        return Response(serializer.data, status=status.HTTP_201_CREATED)

# 6. SAFETY & SETTINGS API
class BlockViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_my_profile(self, request):
        return get_object_or_404(UserProfile, user=request.user)

    # GET /api/blocks/ — list all profiles I've blocked
    def list(self, request):
        me = self.get_my_profile(request)
        blocked = Block.objects.filter(blocker=me).select_related('blocked_user')
        data = [
            {
                "block_id": str(b.id),
                "profile_id": str(b.blocked_user.id),
                "username": b.blocked_user.username,
                "blocked_at": b.created_at,
            }
            for b in blocked
        ]
        return Response(data)

    # POST /api/blocks/<profile_uuid>/block/ — block a user
    # DELETE /api/blocks/<profile_uuid>/block/ — unblock a user
    @action(detail=True, methods=['post', 'delete'], url_path='block')
    def block_action(self, request, pk=None):
        me = self.get_my_profile(request)
        target = get_object_or_404(UserProfile, id=pk)

        if request.method == 'POST':
            if target == me:
                return Response({"error": "You cannot block yourself."}, status=status.HTTP_400_BAD_REQUEST)

            if Block.objects.filter(blocker=me, blocked_user=target).exists():
                return Response({"message": "Already blocked."}, status=status.HTTP_200_OK)

            # Remove any existing match and friendship
            Match.objects.filter(Q(user1=me, user2=target) | Q(user1=target, user2=me)).delete()
            Friendship.objects.filter(Q(sender=me, receiver=target) | Q(sender=target, receiver=me)).delete()

            # Delete all direct messages
            DirectMessage.objects.filter(
                Q(sender=me, receiver=target) | Q(sender=target, receiver=me)
            ).delete()

            Block.objects.create(blocker=me, blocked_user=target)
            return Response({"message": f"{target.username} has been blocked."}, status=status.HTTP_201_CREATED)

        elif request.method == 'DELETE':
            block = Block.objects.filter(blocker=me, blocked_user=target).first()
            if not block:
                return Response({"error": "This user is not blocked."}, status=status.HTTP_404_NOT_FOUND)
            block.delete()
            return Response({"message": f"{target.username} has been unblocked."})

    # GET /api/blocks/<profile_uuid>/status/ — check if a specific profile is blocked
    @action(detail=True, methods=['get'], url_path='status')
    def block_status(self, request, pk=None):
        me = self.get_my_profile(request)
        target = get_object_or_404(UserProfile, id=pk)
        is_blocked = Block.objects.filter(blocker=me, blocked_user=target).exists()
        return Response({"profile_id": str(target.id), "is_blocked": is_blocked})



class DeactivateAccountView(APIView):
    def post(self, request):
        profile = get_object_or_404(UserProfile, user=request.user)
        profile.is_deactivated = True
        profile.save()
        
        # Also deactivate underlying auth account
        user = request.user
        user.is_active = False
        user.save()
        return Response({"message": "Account deactivated successfully."})

class ChangePasswordView(APIView):
    def post(self, request):
        user = request.user
        current_password = request.data.get('current_password')
        new_password = request.data.get('new_password')
        
        if not user.check_password(current_password):
            return Response({"error": "Invalid current password."}, status=status.HTTP_400_BAD_REQUEST)
            
        user.set_password(new_password)
        user.save()
        return Response({"message": "Password changed successfully."})

class RequestEmailChangeView(APIView):
    def post(self, request):
        import random
        from django.core.cache import cache
        from django.conf import settings
        from django.core.mail import send_mail
        from django.utils import timezone
        
        user = request.user
        new_email = request.data.get('new_email', '').strip()
        
        if not new_email:
            return Response({"error": "new_email is required."}, status=status.HTTP_400_BAD_REQUEST)
            
        # Check if email is already in use by another account
        from django.contrib.auth import get_user_model
        User = get_user_model()
        if User.objects.filter(email__iexact=new_email).exclude(id=user.id).exists():
            return Response({"error": "Email is already in use by another account."}, status=status.HTTP_400_BAD_REQUEST)
            
        otp_code = f"{random.randint(1000, 999999):06d}"
        user.otp = otp_code
        user.otp_created_at = timezone.now()
        user.save()
        
        # Cache the new email for 10 minutes
        cache.set(f"pending_email_{user.id}", new_email, timeout=600)
        
        from api.email_service import send_email_change_email
        send_email_change_email(new_email, otp_code, username=user.username)
            
        return Response({"message": "OTP sent to new email."})

class VerifyEmailChangeView(APIView):
    def post(self, request):
        from django.core.cache import cache
        
        user = request.user
        otp = request.data.get('otp', '').strip()
        new_email = request.data.get('new_email', '').strip()
        
        if not otp or not new_email:
            return Response({"error": "otp and new_email are required."}, status=status.HTTP_400_BAD_REQUEST)
            
        if not user.otp or user.otp != otp:
            return Response({"error": "Invalid verification code."}, status=status.HTTP_400_BAD_REQUEST)
            
        cached_email = cache.get(f"pending_email_{user.id}")
        if not cached_email or cached_email != new_email:
            return Response({"error": "Session expired or email mismatch. Please request a new code."}, status=status.HTTP_400_BAD_REQUEST)
            
        # Update email and clear OTP
        user.email = new_email
        user.otp = None
        user.otp_created_at = None
        user.save()
        
        cache.delete(f"pending_email_{user.id}")
        
        return Response({"message": "Email changed successfully.", "new_email": user.email})

class TransactionHistoryView(APIView):
    def get(self, request):
        me = get_object_or_404(UserProfile, user=request.user)
        tx = Transaction.objects.filter(user=me).order_by('-created_at')
        serializer = TransactionSerializer(tx, many=True)
        return Response(serializer.data)


class UpgradeSubscriptionView(APIView):
    """
    POST /api/subscription/upgrade/
    Mocks upgrading/downgrading the user's subscription tier.
    """
    def post(self, request):
        me = get_object_or_404(UserProfile, user=request.user)
        tier = request.data.get('tier')
        amount = request.data.get('amount')
        stripe_charge_id = request.data.get('stripe_charge_id', f"mock_ch_{int(timezone.now().timestamp())}")

        valid_tiers = ['light', 'plus', 'freemium', 'add_on_filters', 'add_on_chatrooms', 'add_on_perfect_match']
        if tier not in valid_tiers:
            return Response({"error": "Invalid subscription tier."}, status=status.HTTP_400_BAD_REQUEST)

        # Set default pricing
        tier_pricing = {
            'freemium': 0.00,
            'light': 9.99,
            'plus': 19.99,
            'add_on_filters': 2.99,
            'add_on_chatrooms': 3.99,
            'add_on_perfect_match': 14.99
        }
        charge_amount = amount if amount is not None else tier_pricing[tier]

        # Update profile tier or add-on
        if tier == 'add_on_filters':
            me.has_advanced_filters = True
        elif tier == 'add_on_chatrooms':
            me.has_all_chat_rooms = True
        elif tier == 'add_on_perfect_match':
            me.has_match_analysis = True
        else:
            me.subscription_tier = tier
            if tier != 'freemium':
                me.subscription_expires = timezone.now() + timezone.timedelta(days=30)
            else:
                me.subscription_expires = None
        me.save()

        # Log transaction
        tx = Transaction.objects.create(
            user=me,
            plan_name=f"Premium {tier.title()}" if tier != 'freemium' else "Freemium Downgrade",
            amount=charge_amount,
            status='successful',
            stripe_charge_id=stripe_charge_id
        )

        return Response({
            "message": f"Subscription tier updated to {tier}.",
            "subscription_tier": me.subscription_tier,
            "subscription_expires": me.subscription_expires,
            "transaction": TransactionSerializer(tx).data
        }, status=status.HTTP_200_OK)


class CreateReportView(APIView):
    def post(self, request):
        me = get_object_or_404(UserProfile, user=request.user)
        reported_user_id = request.data.get('reported_user')
        reported_user = get_object_or_404(UserProfile, id=reported_user_id)
        reason = request.data.get('reason')
        description = request.data.get('description', '')

        # Enforce validation reasons
        valid_reasons = ['fake_profile', 'offensive_language', 'harassment', 'sexually_explicit_content', 'impersonation', 'other']
        if reason not in valid_reasons:
            return Response({"error": f"Invalid reason. Must be one of: {', '.join(valid_reasons)}"}, status=status.HTTP_400_BAD_REQUEST)

        report = Report.objects.create(
            reporter=me,
            reported_user=reported_user,
            reason=reason,
            description=description
        )
        
        # Check if the user needs mandatory verification (3 unique reporters)
        if reported_user.face_verification_status != 'approved':
            unique_reporters_count = Report.objects.filter(reported_user=reported_user).values('reporter').distinct().count()
            if unique_reporters_count >= 3:
                reported_user.must_verify_face = True
                reported_user.save()

        serializer = ReportSerializer(report)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

class CreateSupportTicketView(APIView):
    """
    POST /api/support/create/
    Allows users to submit a support ticket.
    """
    def post(self, request):
        me = get_object_or_404(UserProfile, user=request.user)
        subject = request.data.get('subject', 'General Support')
        description = request.data.get('description', '')
        email = request.data.get('email', request.user.email)

        if not description:
            return Response({"error": "Description is required."}, status=status.HTTP_400_BAD_REQUEST)

        ticket = SupportTicket.objects.create(
            user=me,
            email=email,
            subject=subject,
            description=description,
            priority='medium',
            status='received'
        )
        serializer = SupportTicketSerializer(ticket)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

class MySupportTicketsView(APIView):
    """
    GET /api/support/my-tickets/
    Returns the support tickets created by the current user.
    """
    def get(self, request):
        me = get_object_or_404(UserProfile, user=request.user)
        tickets = SupportTicket.objects.filter(user=me).order_by('-created_at')
        serializer = SupportTicketSerializer(tickets, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

# 7. ADMIN DASHBOARD API
class AdminTicketViewSet(viewsets.ModelViewSet):
    serializer_class = SupportTicketSerializer
    permission_classes = [IsSupportAgent]
    queryset = SupportTicket.objects.all().order_by('-created_at')

    @action(detail=True, methods=['post'])
    def reply(self, request, pk=None):
        ticket = self.get_object()
        content = request.data.get('content')
        if not content:
            return Response({"error": "Reply content required."}, status=status.HTTP_400_BAD_REQUEST)

        reply = SupportTicketReply.objects.create(
            ticket=ticket,
            sender=request.user,
            content=content
        )
        
        # Update ticket status to In Progress
        ticket.status = 'in_progress'
        ticket.save()

        # Send actual email via SMTP
        try:
            send_mail(
                subject=f"Update on Support Ticket #{ticket.id}",
                message=content,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[ticket.email],
                fail_silently=False,
            )
            print(f"✅ Support response email sent to {ticket.email}")
        except Exception as e:
            print(f"❌ Failed to send support response email to {ticket.email}: {e}")
        
        serializer = SupportTicketReplySerializer(reply)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        ticket = self.get_object()
        ticket.status = 'resolved'
        ticket.save()
        return Response({"message": "Ticket resolved."})

class AdminReportViewSet(viewsets.ModelViewSet):
    serializer_class = ReportSerializer
    permission_classes = [IsModerator]
    queryset = Report.objects.all().order_by('-created_at')

    @action(detail=True, methods=['post'])
    def take_action(self, request, pk=None):
        report = self.get_object()
        action_type = request.data.get('action') # 'ban', 'suspend', 'dismiss', 'warning'
        
        target_profile = report.reported_user
        target_user = target_profile.user
        
        if action_type == 'ban':
            target_user.is_active = False
            target_user.save()
            target_profile.is_deactivated = True
            target_profile.save()
            report.status = 'resolved'
            report.action_taken = 'ban'
            report.resolved_by = request.user
            report.save()
            return Response({"message": "User banned and profile deactivated."})
            
        elif action_type == 'suspend':
            target_user.is_active = False
            target_user.save()
            report.status = 'under_review'
            report.action_taken = 'suspend'
            report.save()
            return Response({"message": "User account temporarily suspended for review."})
            
        elif action_type == 'dismiss':
            report.status = 'resolved'
            report.action_taken = 'dismiss'
            report.resolved_by = request.user
            report.save()
            return Response({"message": "Report dismissed."})

        elif action_type == 'warning':
            report.status = 'resolved'
            report.action_taken = 'warning'
            report.resolved_by = request.user
            report.save()
            return Response({"message": "User warned and report resolved."})
            
        return Response({"error": "Invalid action. Use 'ban', 'suspend', 'dismiss', or 'warning'."}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def request_selfie(self, request, pk=None):
        report = self.get_object()
        reported_user = report.reported_user
        
        # Reset verification status to force them to upload a new selfie
        reported_user.is_verified = False
        reported_user.face_verification_status = 'not_submitted'
        reported_user.save()
        
        # Mark report as under_review
        report.status = 'under_review'
        report.action_taken = 'request_selfie'
        report.save()
        
        return Response({
            "message": f"Successfully requested selfie verification for {reported_user.username}.",
            "report_status": report.status,
            "user_verification_status": reported_user.face_verification_status
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def dashboard(self, request):
        now_dt = timezone.now()
        
        # 1. Stats calculation
        total_reports = Report.objects.count()
        pending_reports = Report.objects.filter(status='pending').count()
        resolved_reports = Report.objects.filter(status='resolved').count()

        # 2. Weekly chart data (Mon to Sun counts for the current week)
        today = now_dt.date()
        start_of_week = today - timezone.timedelta(days=today.weekday())
        weekly_data = []
        days_map = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        for i in range(7):
            day_dt = start_of_week + timezone.timedelta(days=i)
            count = Report.objects.filter(created_at__date=day_dt).count()
            weekly_data.append({
                "day": days_map[i],
                "count": count
            })

        # 3. Recent reports (last 5 reports)
        recent_qs = Report.objects.all().select_related('reporter', 'reported_user', 'reported_user__user').order_by('-created_at')[:5]
        recent_reports = []
        for r in recent_qs:
            status_display = r.get_action_taken_display() if r.action_taken else r.get_status_display()
            recent_reports.append({
                "id": r.id,
                "reporter": {
                    "id": r.reporter.id,
                    "username": r.reporter.username
                },
                "reported_user": {
                    "id": r.reported_user.id,
                    "username": r.reported_user.username
                },
                "reason": r.get_reason_display(),
                "date": r.created_at.strftime('%Y-%m-%d'),
                "status": status_display
            })

        # 4. All Fake reports (reason='fake_profile')
        fake_qs = Report.objects.filter(reason='fake_profile').select_related('reporter', 'reported_user', 'reported_user__user').order_by('-created_at')
        fake_reports = []
        for r in fake_qs:
            u_photo = r.reported_user.photos.filter(is_main=True).first()
            u_photo_url = get_cloudinary_url(u_photo.image) if u_photo else None
            
            fake_reports.append({
                "id": r.id,
                "reporter": {
                    "id": r.reporter.id,
                    "username": r.reporter.username
                },
                "reported_user": {
                    "id": r.reported_user.id,
                    "username": r.reported_user.username,
                    "photo": u_photo_url
                },
                "reason": r.get_reason_display(),
                "date": r.created_at.strftime('%Y-%m-%d'),
                "status": r.get_status_display()
            })

        return Response({
            "stats": {
                "total_reports": total_reports,
                "pending": pending_reports,
                "resolved_this_week": resolved_reports
            },
            "weekly_chart": weekly_data,
            "recent_reports": recent_reports,
            "fake_reports": fake_reports
        }, status=status.HTTP_200_OK)

class AdminChatRoomViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Super Admin / Admin Chat Room Management.
    """
    permission_classes = [IsAdminUser]
    serializer_class = ChatRoomSerializer
    queryset = ChatRoom.objects.all().order_by('-created_at')

    def list(self, request, *args, **kwargs):
        # Stats
        active_rooms = ChatRoom.objects.filter(status='active').count()
        total_members = UserProfile.objects.filter(chat_rooms__status='active').distinct().count()

        # Filter rooms by search parameter
        search_query = request.query_params.get('search', '').strip()
        rooms_qs = ChatRoom.objects.all().order_by('-created_at')
        if search_query:
            rooms_qs = rooms_qs.filter(Q(name__icontains=search_query) | Q(description__icontains=search_query))

        serialized_rooms = []
        for r in rooms_qs:
            serialized_rooms.append({
                "id": r.id,
                "name": r.name,
                "description": r.description,
                "member_count": r.members.count(),
                "messages_count": r.messages.count(),
                "status": r.status,
                "created_at": r.created_at.strftime('%Y-%m-%d') if r.created_at else None
            })

        return Response({
            "stats": {
                "active_rooms": active_rooms,
                "total_members": total_members
            },
            "rooms": serialized_rooms
        }, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        name = request.data.get('name')
        description = request.data.get('description', '')
        if not name:
            return Response({"error": "Room name is required."}, status=status.HTTP_400_BAD_REQUEST)
        
        room = ChatRoom.objects.create(name=name, description=description, status='active')
        return Response(ChatRoomSerializer(room).data, status=status.HTTP_201_CREATED)

    def retrieve(self, request, pk=None):
        room = self.get_object()
        
        # Get members of this room
        members_qs = room.members.all().select_related('user')
        
        # Filter members by search query
        search_query = request.query_params.get('search', '').strip()
        if search_query:
            members_qs = members_qs.filter(username__icontains=search_query)
            
        serialized_members = []
        for profile in members_qs:
            is_blocked = not profile.user.is_active or profile.is_deactivated
            main_photo = profile.photos.filter(is_main=True).first()
            photo_url = get_cloudinary_url(main_photo.image) if main_photo else None
            
            serialized_members.append({
                "id": profile.id,
                "username": profile.username,
                "email": profile.user.email,
                "photo": photo_url,
                "role": "Admin" if (profile.user.role in ['admin', 'superadmin', 'support', 'moderator'] or profile.user.is_staff) else "Member",
                "is_blocked": is_blocked,
                "status": "Blocked" if is_blocked else "Active",
                "join_date": profile.user.date_joined.strftime('%Y-%m-%d') if profile.user.date_joined else None
            })
            
        return Response({
            "id": room.id,
            "name": room.name,
            "description": room.description,
            "member_count": room.members.count(),
            "messages_count": room.messages.count(),
            "status": room.status,
            "created_at": room.created_at.strftime('%Y-%m-%d') if room.created_at else None,
            "members": serialized_members
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        room = self.get_object()
        room.status = 'archived'
        room.save()
        return Response({"message": f"Successfully archived chat room {room.name}.", "status": room.status}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def unarchive(self, request, pk=None):
        room = self.get_object()
        room.status = 'active'
        room.save()
        return Response({"message": f"Successfully activated chat room {room.name}.", "status": room.status}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='remove-member')
    def remove_member(self, request, pk=None):
        room = self.get_object()
        profile_id = request.data.get('profile_id')
        if not profile_id:
            return Response({"error": "profile_id is required."}, status=status.HTTP_400_BAD_REQUEST)
            
        profile = get_object_or_404(UserProfile, id=profile_id)
        room.members.remove(profile)
        room.member_count = room.members.count()
        room.save()
        
        return Response({
            "message": f"Successfully removed {profile.username} from {room.name}.",
            "room_id": room.id,
            "member_count": room.member_count
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='block-member')
    def block_member(self, request, pk=None):
        room = self.get_object()
        profile_id = request.data.get('profile_id')
        if not profile_id:
            return Response({"error": "profile_id is required."}, status=status.HTTP_400_BAD_REQUEST)
            
        profile = get_object_or_404(UserProfile, id=profile_id)
        
        # Deactivate user account
        user = profile.user
        user.is_active = False
        user.save()
        profile.is_deactivated = True
        profile.save()
        
        # Remove from room
        room.members.remove(profile)
        room.member_count = room.members.count()
        room.save()
        
        return Response({
            "message": f"Successfully blocked user {profile.username} and removed them from {room.name}.",
            "room_id": room.id,
            "member_count": room.member_count
        }, status=status.HTTP_200_OK)


class AdminAccountsViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Super Admin to manage other staff/admin accounts.
    """
    permission_classes = [IsAdminUser]
    serializer_class = UserSerializer

    def get_queryset(self):
        return User.objects.exclude(role='member').order_by('id')

    def list(self, request, *args, **kwargs):
        users = self.get_queryset()
        data = []
        for u in users:
            # Format last_login human-readably
            last_login_str = "Never logged in"
            if u.last_login:
                diff = timezone.now() - u.last_login
                if diff.days > 0:
                    last_login_str = f"{diff.days} day{'s' if diff.days > 1 else ''} ago"
                else:
                    hours = diff.seconds // 3600
                    if hours > 0:
                        last_login_str = f"{hours} hour{'s' if hours > 1 else ''} ago"
                    else:
                        minutes = diff.seconds // 60
                        last_login_str = f"{minutes} minute{'s' if minutes > 1 else ''} ago"
                        if minutes == 0:
                            last_login_str = "Just now"

            role_display_map = {
                'support': 'Customer Support',
                'moderator': 'Moderator',
                'admin': 'Admin',
                'superadmin': 'Super Admin'
            }

            data.append({
                "id": u.id,
                "full_name": f"{u.first_name} {u.last_name}".strip() or u.username,
                "admin_id": f"ADM-{str(u.id)[:8]}",
                "email": u.email,
                "role": u.role,
                "role_display": role_display_map.get(u.role, u.role.capitalize()),
                "status": "Active" if u.is_active else "Inactive",
                "last_login": last_login_str
            })
        return Response(data, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        full_name = request.data.get('full_name', '').strip()
        email = request.data.get('email', '').strip()
        role = request.data.get('role', '').strip()
        password = request.data.get('password', '').strip()

        if not email or not role or not password:
            return Response({"error": "Email, role, and password are required."}, status=status.HTTP_400_BAD_REQUEST)

        # Restrict normal admins from creating admins or superadmins
        if request.user.role != 'superadmin' and not request.user.is_superuser:
            if role in ['admin', 'superadmin']:
                return Response({"error": "You only have permission to add Support or Moderator roles."}, status=status.HTTP_403_FORBIDDEN)

        if User.objects.filter(email=email).exists():
            return Response({"error": "A user with this email already exists."}, status=status.HTTP_400_BAD_REQUEST)

        parts = full_name.split(' ', 1)
        first_name = parts[0]
        last_name = parts[1] if len(parts) > 1 else ''

        username = email.split('@')[0]
        base_username = username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_username}{counter}"
            counter += 1

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            role=role,
            is_staff=True
        )

        UserProfile.objects.get_or_create(
            user=user,
            defaults={
                'username': username,
                'is_verified': True,
                'face_verification_status': 'approved'
            }
        )

        role_display_map = {
            'support': 'Customer Support',
            'moderator': 'Moderator',
            'admin': 'Admin',
            'superadmin': 'Super Admin'
        }

        return Response({
            "id": user.id,
            "full_name": f"{user.first_name} {user.last_name}".strip() or user.username,
            "admin_id": f"ADM-{str(user.id)[:8]}",
            "email": user.email,
            "role": user.role,
            "role_display": role_display_map.get(user.role, user.role.capitalize()),
            "status": "Active" if user.is_active else "Inactive",
            "last_login": "Never logged in"
        }, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        u = self.get_object()
        full_name = request.data.get('full_name', '').strip()
        email = request.data.get('email', '').strip()
        role = request.data.get('role', '').strip()

        # Restrict normal admins from modifying admins or superadmins
        if request.user.role != 'superadmin' and not request.user.is_superuser:
            if u.role in ['admin', 'superadmin'] or u.is_superuser:
                return Response({"error": "You do not have permission to modify an Admin or Super Admin."}, status=status.HTTP_403_FORBIDDEN)
            if role in ['admin', 'superadmin']:
                return Response({"error": "You cannot grant Admin or Super Admin roles."}, status=status.HTTP_403_FORBIDDEN)

        if email and email != u.email:
            if User.objects.filter(email=email).exclude(id=u.id).exists():
                return Response({"error": "A user with this email already exists."}, status=status.HTTP_400_BAD_REQUEST)
            u.email = email

        if role:
            u.role = role

        if full_name:
            parts = full_name.split(' ', 1)
            u.first_name = parts[0]
            u.last_name = parts[1] if len(parts) > 1 else ''

        u.save()

        if email:
            p, created = UserProfile.objects.get_or_create(user=u)
            p.username = email.split('@')[0]
            p.save()

        role_display_map = {
            'support': 'Customer Support',
            'moderator': 'Moderator',
            'admin': 'Admin',
            'superadmin': 'Super Admin'
        }

        return Response({
            "id": u.id,
            "full_name": f"{u.first_name} {u.last_name}".strip() or u.username,
            "admin_id": f"ADM-{str(u.id)[:8]}",
            "email": u.email,
            "role": u.role,
            "role_display": role_display_map.get(u.role, u.role.capitalize()),
            "status": "Active" if u.is_active else "Inactive"
        }, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        u = self.get_object()
        if u == request.user:
            return Response({"error": "You cannot remove your own account."}, status=status.HTTP_400_BAD_REQUEST)
        
        # Restrict normal admins from deleting admins or superadmins
        if request.user.role != 'superadmin' and not request.user.is_superuser:
            if u.role in ['admin', 'superadmin'] or u.is_superuser:
                return Response({"error": "You do not have permission to delete an Admin or Super Admin."}, status=status.HTTP_403_FORBIDDEN)
        
        u.delete()
        return Response({"message": "Admin account successfully removed."}, status=status.HTTP_200_OK)


class AdminVerificationViewSet(APIView):
    permission_classes = [IsModerator]

    def get(self, request):
        # Return pending and verified users with selfie and profile photo
        qs = UserProfile.objects.exclude(Q(face_selfie='') | Q(face_selfie__isnull=True))
        pending = qs.filter(face_verification_status='pending')
        verified = qs.filter(face_verification_status='approved')
        rejected = qs.filter(face_verification_status='rejected')

        def format_user(p):
            profile_photo = p.photos.filter(is_main=True).first()
            return {
                "id": str(p.id),
                "name": p.username,
                "email": p.user.email,
                "joined_date": p.user.date_joined.strftime('%d %b %Y'),
                "status": "verified" if p.face_verification_status == 'approved' else ("pending" if p.face_verification_status == 'pending' else "rejected"),
                "profile_photo_url": get_cloudinary_url(profile_photo.image) if profile_photo else "",
                "selfie_urls": [
                    get_cloudinary_url(p.face_selfie) if p.face_selfie else "",
                    get_cloudinary_url(p.face_selfie_left) if p.face_selfie_left else "",
                    get_cloudinary_url(p.face_selfie_right) if p.face_selfie_right else "",
                ],
                "location": f"{p.city}, {p.country}" if p.city and p.country else "Unknown",
                "submitted_date": p.face_verified_at.strftime('%d %b %Y, %H:%M') if p.face_verified_at else "Recently",
            }

        return Response({
            "pending": [format_user(p) for p in pending],
            "verified": [format_user(p) for p in verified],
            "rejected": [format_user(p) for p in rejected]
        })

    def post(self, request, profile_id):
        profile = get_object_or_404(UserProfile, id=profile_id)
        action_type = request.data.get('action') # 'approve', 'reject'
        
        if action_type == 'approve':
            profile.is_verified = True
            profile.face_verification_status = 'approved'
            profile.must_verify_face = False
            profile.save()
            
            # Also mark underlying photos as verified
            profile.photos.all().update(is_verified=True)
            return Response({"message": "Photo verification approved."})
            
        elif action_type == 'reject':
            profile.is_verified = False
            profile.face_verification_status = 'rejected'
            profile.save()
            # Reject verification
            profile.photos.all().update(is_verified=False)
            return Response({"message": "Photo verification rejected."})
            
        return Response({"error": "Invalid action. Use 'approve' or 'reject'."}, status=status.HTTP_400_BAD_REQUEST)

class AdminUserListView(APIView):
    permission_classes = [IsSupportAgent]

    def get(self, request):
        query = request.query_params.get('search', '')
        users = UserProfile.objects.filter(
            Q(username__icontains=query) | Q(user__email__icontains=query)
        ).select_related('user').prefetch_related('photos')
        serializer = UserProfileSerializer(users, many=True, context={'request': request})
        return Response(serializer.data)


class AdminUserDeleteView(APIView):
    """
    DELETE /api/admin/users/<profile_id>/
    Restricted to Super Admin.
    Completely deletes the User, UserProfile, and all associated data via CASCADE.
    """
    permission_classes = [IsSuperAdmin]

    def delete(self, request, profile_id):
        profile = get_object_or_404(UserProfile, id=profile_id)
        core_user = profile.user
        
        if core_user == request.user:
            return Response({"error": "You cannot delete your own account."}, status=status.HTTP_400_BAD_REQUEST)
        
        # Log the action before deletion
        AdminActionLog.objects.create(
            admin_user=request.user,
            action="Deleted User Account",
            details=f"Completely deleted user {profile.username} ({core_user.email}) and all their data."
        )
        
        from api.utils_delete import delete_user_files
        delete_user_files(core_user)
        core_user.delete()
        return Response({"message": "User successfully deleted."}, status=status.HTTP_204_NO_CONTENT)


class AdminUserBlockView(APIView):
    """
    POST /api/admin/users/<profile_id>/block/
    Restricted to Super Admin.
    Toggles the is_active status of the user to block/unblock them.
    """
    permission_classes = [IsSuperAdmin]

    def post(self, request, profile_id):
        profile = get_object_or_404(UserProfile, id=profile_id)
        core_user = profile.user
        
        if core_user == request.user:
            return Response({"error": "You cannot block your own account."}, status=status.HTTP_400_BAD_REQUEST)

        core_user.is_active = not core_user.is_active
        core_user.save()
        
        action_verb = "Blocked" if not core_user.is_active else "Unblocked"
        AdminActionLog.objects.create(
            admin_user=request.user,
            action=f"{action_verb} User Account",
            target_user=profile,
            details=f"{action_verb} user {profile.username} ({core_user.email})."
        )
        
        return Response({"message": f"User successfully {action_verb.lower()}."}, status=status.HTTP_200_OK)


class AdminDashboardStatsView(APIView):
    """
    GET /api/admin/dashboard/stats/
    Restricted to Admin and Super Admin.
    """
    permission_classes = [IsAdminUser]

    def get(self, request):
        total_users = UserProfile.objects.filter(is_deactivated=False).count()
        premium_users = UserProfile.objects.filter(is_deactivated=False, subscription_tier__in=['light', 'plus']).count()
        pending_verifications = UserProfile.objects.filter(is_verified=False, face_selfie__isnull=False).exclude(face_selfie='').distinct().count()
        unresolved_reports = Report.objects.exclude(status='resolved').count()
        pending_tickets = SupportTicket.objects.exclude(status='resolved').count()
        total_revenue = Transaction.objects.filter(status='successful').aggregate(Sum('amount'))['amount__sum'] or 0.00

        data = {
            "total_users": total_users,
            "premium_users": premium_users,
            "pending_verifications": pending_verifications,
            "unresolved_reports": unresolved_reports,
            "pending_tickets": pending_tickets,
            "total_revenue": float(total_revenue)
        }
        return Response(data, status=status.HTTP_200_OK)


class AdminDashboardActivityView(APIView):
    """
    GET /api/admin/dashboard/activity/
    Restricted to Admin and Super Admin.
    Returns the latest global platform activities for the dashboard feed.
    """
    permission_classes = [IsAdminUser]

    def get(self, request):
        activities = []
        
        # 1. New users registered
        for up in UserProfile.objects.select_related('user').order_by('-user__date_joined')[:10]:
            activities.append({
                "id": f"usr_{up.id}",
                "type": "user_registered",
                "title": "New user registered",
                "timestamp": up.user.date_joined.isoformat(),
                "details": f"User: {up.username}"
            })

        # 2. New matches
        for m in Match.objects.filter(status='matched').select_related('user1', 'user2').order_by('-created_at')[:10]:
            activities.append({
                "id": f"mat_{m.id}",
                "type": "match_created",
                "title": "New match created",
                "timestamp": m.created_at.isoformat(),
                "details": f"{m.user1.username} & {m.user2.username}"
            })

        # 3. New messages
        for msg in DirectMessage.objects.select_related('sender', 'receiver').order_by('-timestamp')[:10]:
            activities.append({
                "id": f"msg_{msg.id}",
                "type": "message_sent",
                "title": "New message sent",
                "timestamp": msg.timestamp.isoformat(),
                "details": f"Between {msg.sender.username} and {msg.receiver.username}"
            })

        # 4. Premium subscriptions
        for tx in Transaction.objects.filter(status__in=['successful', 'paid'], amount__gt=0).select_related('user').order_by('-created_at')[:10]:
            activities.append({
                "id": f"tx_{tx.id}",
                "type": "subscription_purchased",
                "title": "Premium subscription purchased",
                "timestamp": tx.created_at.isoformat(),
                "details": f"{tx.user.username} purchased {tx.plan_name}"
            })

        # 5. Reports submitted
        for rpt in Report.objects.select_related('reporter').order_by('-created_at')[:10]:
            activities.append({
                "id": f"rpt_{rpt.id}",
                "type": "report_submitted",
                "title": "Report submitted",
                "timestamp": rpt.created_at.isoformat(),
                "details": f"By {rpt.reporter.username}"
            })

        # Sort all by timestamp descending and return top 15
        activities.sort(key=lambda x: x["timestamp"], reverse=True)
        return Response(activities[:15], status=status.HTTP_200_OK)


class AdminTransactionListView(APIView):
    """
    GET /api/admin/transactions/
    Restricted to Admin and Super Admin.
    """
    permission_classes = [IsAdminUser]

    def get(self, request):
        transactions = Transaction.objects.all().order_by('-created_at')
        serializer = TransactionSerializer(transactions, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AdminUserRoleUpdateView(APIView):
    """
    POST /api/admin/users/<profile_id>/role/
    Restricted STRICTLY to Super Admin.
    """
    permission_classes = [IsSuperAdmin]

    def post(self, request, profile_id):
        profile = get_object_or_404(UserProfile, id=profile_id)
        new_role = request.data.get('role')

        role_choices = [c[0] for c in User.ROLE_CHOICES]
        if new_role not in role_choices:
            return Response({"error": f"Invalid role. Must be one of: {', '.join(role_choices)}"}, status=status.HTTP_400_BAD_REQUEST)

        # Update the role of the underlying django User model object
        user = profile.user
        old_role = user.role
        user.role = new_role
        user.save()

        return Response({
            "message": f"Successfully updated user {profile.username}'s role.",
            "profile_id": profile.id,
            "username": profile.username,
            "old_role": old_role,
            "new_role": new_role
        }, status=status.HTTP_200_OK)


class AdminUserGiftSubscriptionView(APIView):
    """
    POST /api/admin/users/<profile_id>/gift/
    Restricted to Admin and Super Admin.
    Allows gifting a premium subscription for a specific duration.
    """
    permission_classes = [IsAdminUser]

    def post(self, request, profile_id):
        profile = get_object_or_404(UserProfile, id=profile_id)
        tier = request.data.get('tier')
        duration_months = request.data.get('duration_months')

        if not tier:
            return Response({"error": "tier is required."}, status=status.HTTP_400_BAD_REQUEST)

        # Standardize tier string
        tier = tier.strip().lower()
        
        # Support annual mapping
        if tier == 'annual':
            tier = 'plus'
            if duration_months is None:
                duration_months = 12
        
        if tier not in ['light', 'plus', 'freemium']:
            return Response({"error": "Invalid tier. Choose 'light', 'plus', or 'freemium'."}, status=status.HTTP_400_BAD_REQUEST)

        # Parse duration_months
        if duration_months is not None:
            try:
                duration_months = int(duration_months)
                if duration_months <= 0:
                    raise ValueError()
            except ValueError:
                return Response({"error": "duration_months must be a positive integer."}, status=status.HTTP_400_BAD_REQUEST)
        else:
            duration_months = 1 # Default to 1 month if not specified

        # If gifting freemium, it's effectively a downgrade / cancellation of active subscription
        if tier == 'freemium':
            profile.subscription_tier = 'freemium'
            profile.subscription_expires = None
            profile.save()

            tx = Transaction.objects.create(
                user=profile,
                plan_name="Gift: Freemium Downgrade",
                amount=0.00,
                status='successful',
                stripe_charge_id=f"gift_admin_{int(timezone.now().timestamp())}"
            )
            return Response({
                "message": f"Successfully set user {profile.username}'s subscription to Freemium.",
                "subscription_tier": profile.subscription_tier,
                "subscription_expires": profile.subscription_expires,
                "transaction": TransactionSerializer(tx).data
            }, status=status.HTTP_200_OK)

        # Update profile tier and expiry
        profile.subscription_tier = tier
        profile.subscription_expires = timezone.now() + timezone.timedelta(days=30 * duration_months)
        profile.save()

        # Log transaction
        tx = Transaction.objects.create(
            user=profile,
            plan_name=f"Gift: Premium {tier.title()} ({duration_months} Months)",
            amount=0.00,
            status='successful',
            stripe_charge_id=f"gift_admin_{int(timezone.now().timestamp())}"
        )

        return Response({
            "message": f"Successfully gifted Premium {tier.title()} subscription for {duration_months} months to {profile.username}.",
            "subscription_tier": profile.subscription_tier,
            "subscription_expires": profile.subscription_expires,
            "transaction": TransactionSerializer(tx).data
        }, status=status.HTTP_200_OK)


class AdminMatchesDashboardView(APIView):
    """
    GET /api/admin/matches/
    Restricted to Admin and Super Admin.
    Returns matches stats and all unique mutual matches.
    """
    permission_classes = [IsAdminUser]

    def get(self, request):
        # 1. Base query for matched pairs (ensuring each pair user1 < user2 is retrieved exactly once)
        from django.db import models
        matches = Match.objects.filter(
            status='matched',
            user1_id__lt=models.F('user2_id')
        ).select_related('user1', 'user2', 'user1__user', 'user2__user').prefetch_related('user1__photos', 'user2__photos')

        # 2. Analytics calculations
        total_matches = matches.count()
        
        # Matches today
        matches_today = matches.filter(created_at__date=timezone.now().date()).count()

        # DMs count
        total_dms = DirectMessage.objects.count()
        avg_messages = round(total_dms / total_matches, 1) if total_matches > 0 else 0.0

        # Calculate Active Matches (mutual matches with at least one DM)
        dm_pair_counts = Counter()
        message_pairs = DirectMessage.objects.values('sender_id', 'receiver_id').annotate(total=Count('id'))
        for message_pair in message_pairs:
            sender_id = message_pair['sender_id']
            receiver_id = message_pair['receiver_id']
            pair = tuple(sorted((sender_id, receiver_id)))
            dm_pair_counts[pair] += message_pair['total']
            
        active_matches = 0
        for match in matches:
            if (match.user1_id, match.user2_id) in dm_pair_counts:
                active_matches += 1

        # 3. Apply search query filter if provided
        search_query = request.query_params.get('search', '').strip()
        if search_query:
            matches = matches.filter(
                Q(user1__username__icontains=search_query) | Q(user2__username__icontains=search_query)
            )

        # 4. Serialize matches list
        serialized_matches = []
        for match in matches:
            comp_pct = calculate_compatibility(match.user1, match.user2)
            
            # Count DMs for this match
            dm_count = dm_pair_counts.get((match.user1_id, match.user2_id), 0)

            # Profile photos helper
            u1_photo = get_main_photo(match.user1)
            u1_photo_url = get_cloudinary_url(u1_photo.image) if u1_photo else None
            
            u2_photo = get_main_photo(match.user2)
            u2_photo_url = get_cloudinary_url(u2_photo.image) if u2_photo else None

            serialized_matches.append({
                "id": match.id,
                "user1": {
                    "id": match.user1.id,
                    "username": match.user1.username,
                    "email": match.user1.user.email,
                    "photo": u1_photo_url
                },
                "user2": {
                    "id": match.user2.id,
                    "username": match.user2.username,
                    "email": match.user2.user.email,
                    "photo": u2_photo_url
                },
                "date": match.created_at.strftime('%Y-%m-%d'),
                "messages_count": dm_count,
                "compatibility_pct": comp_pct
            })

        # 5. Apply sorting based on ordering parameter
        ordering = request.query_params.get('ordering', '-date').strip()
        if ordering == 'date':
            serialized_matches.sort(key=lambda x: x['date'])
        elif ordering == '-date':
            serialized_matches.sort(key=lambda x: x['date'], reverse=True)
        elif ordering == 'percentage':
            serialized_matches.sort(key=lambda x: x['compatibility_pct'])
        elif ordering == '-percentage':
            serialized_matches.sort(key=lambda x: x['compatibility_pct'], reverse=True)
        elif ordering == 'messages':
            serialized_matches.sort(key=lambda x: x['messages_count'])
        elif ordering == '-messages':
            serialized_matches.sort(key=lambda x: x['messages_count'], reverse=True)

        return Response({
            "stats": {
                "total_matches": total_matches,
                "active_matches": active_matches,
                "matches_today": matches_today,
                "avg_messages_per_match": avg_messages
            },
            "matches": serialized_matches
        }, status=status.HTTP_200_OK)


class AdminSubscriptionsDashboardView(APIView):
    """
    GET /api/admin/subscriptions/
    Restricted to Admin and Super Admin.
    Returns subscription stats and historical list of purchases/gifts.
    """
    permission_classes = [IsAdminUser]

    def get(self, request):
        now_dt = timezone.now()
        
        # 1. Compute Analytics
        active_subs_qs = UserProfile.objects.filter(
            subscription_tier__in=['light', 'plus'],
            subscription_expires__gt=now_dt
        )
        active_subscriptions = active_subs_qs.count()
        premium_plan_count = active_subs_qs.filter(subscription_tier='plus').count()
        basic_plan_count = active_subs_qs.filter(subscription_tier='light').count()

        # Monthly Revenue (last 30 days)
        thirty_days_ago = now_dt - timezone.timedelta(days=30)
        monthly_rev = Transaction.objects.filter(
            status='successful',
            created_at__gte=thirty_days_ago
        ).aggregate(Sum('amount'))['amount__sum'] or 0.00

        # 2. Get and Filter Subscriptions list (from successful transactions)
        tx_qs = Transaction.objects.filter(
            status='successful'
        ).select_related('user', 'user__user').order_by('-created_at')

        # Apply search filter by subscriber username
        search_query = request.query_params.get('search', '').strip()
        if search_query:
            tx_qs = tx_qs.filter(user__username__icontains=search_query)

        # 3. Serialize list
        serialized_subs = []
        for tx in tx_qs:
            # Parse plan duration to calculate end date
            duration_days = 30
            plan_lower = tx.plan_name.lower()
            if "3 month" in plan_lower:
                duration_days = 90
            elif "6 month" in plan_lower:
                duration_days = 180
            elif "12 month" in plan_lower or "annual" in plan_lower or "year" in plan_lower:
                duration_days = 365

            end_date = tx.created_at + timezone.timedelta(days=duration_days)
            
            # Status: Active if current date is before end_date and the user is still premium
            # If user has downgraded to freemium, status is Expired/Downgraded
            is_currently_active = tx.user.subscription_tier != 'freemium' and tx.user.subscription_expires and tx.user.subscription_expires > now_dt
            is_tx_active = end_date > now_dt
            status_str = "Active" if (is_tx_active and is_currently_active) else "Expired"

            serialized_subs.append({
                "id": tx.id,
                "user": {
                    "id": tx.user.id,
                    "username": tx.user.username,
                    "email": tx.user.user.email
                },
                "plan_name": tx.plan_name,
                "start_date": tx.created_at.strftime('%Y-%m-%d'),
                "end_date": end_date.strftime('%Y-%m-%d'),
                "amount": str(tx.amount),
                "status": status_str
            })

        # 4. Apply ordering
        ordering = request.query_params.get('ordering', '-date').strip()
        if ordering == 'date':
            serialized_subs.sort(key=lambda x: x['start_date'])
        elif ordering == '-date':
            serialized_subs.sort(key=lambda x: x['start_date'], reverse=True)
        elif ordering == 'amount':
            serialized_subs.sort(key=lambda x: float(x['amount']))
        elif ordering == '-amount':
            serialized_subs.sort(key=lambda x: float(x['amount']), reverse=True)

        return Response({
            "stats": {
                "active_subscriptions": active_subscriptions,
                "premium_plan_count": premium_plan_count,
                "basic_plan_count": basic_plan_count,
                "monthly_revenue": float(monthly_rev)
            },
            "subscriptions": serialized_subs
        }, status=status.HTTP_200_OK)


class AdminPaymentsDashboardView(APIView):
    """
    GET /api/admin/payments/
    Restricted to Admin and Super Admin.
    Returns payment stats and list of transactions.
    """
    permission_classes = [IsAdminUser]

    def get(self, request):
        now_dt = timezone.now()
        thirty_days_ago = now_dt - timezone.timedelta(days=30)
        
        # 1. Compute Analytics
        # Total revenue this month (paid or successful transactions in last 30 days)
        total_revenue = Transaction.objects.filter(
            status__in=['paid', 'successful'],
            created_at__gte=thirty_days_ago
        ).aggregate(Sum('amount'))['amount__sum'] or 0.00
        
        # Pending disputes
        pending_disputes = Transaction.objects.filter(status='disputed').count()

        # Refunds issued
        refunds_issued = Transaction.objects.filter(status='refunded').count()

        # 2. Get and Filter payments list
        tx_qs = Transaction.objects.all().select_related('user', 'user__user').order_by('-created_at')

        # Filter by search
        search_query = request.query_params.get('search', '').strip()
        if search_query:
            tx_qs = tx_qs.filter(user__username__icontains=search_query)

        # 3. Serialize list
        serialized_payments = []
        for tx in tx_qs:
            serialized_payments.append({
                "id": tx.id,
                "user": {
                    "id": tx.user.id,
                    "username": tx.user.username,
                    "email": tx.user.user.email
                },
                "transaction_id": tx.stripe_charge_id or f"TXN-{10000 + tx.id}",
                "amount": str(tx.amount),
                "plan_name": tx.plan_name,
                "date": tx.created_at.strftime('%Y-%m-%d'),
                "status": tx.get_status_display(),
                "payment_method": tx.payment_method
            })

        # 4. Apply ordering
        ordering = request.query_params.get('ordering', '-date').strip()
        if ordering == 'date':
            serialized_payments.sort(key=lambda x: x['date'])
        elif ordering == '-date':
            serialized_payments.sort(key=lambda x: x['date'], reverse=True)
        elif ordering == 'amount':
            serialized_payments.sort(key=lambda x: float(x['amount']))
        elif ordering == '-amount':
            serialized_payments.sort(key=lambda x: float(x['amount']), reverse=True)

        return Response({
            "stats": {
                "total_revenue_this_month": float(total_revenue),
                "pending_disputes": pending_disputes,
                "refunds_issued": refunds_issued
            },
            "payments": serialized_payments
        }, status=status.HTTP_200_OK)



# USERNAME AVAILABILITY CHECK
class CheckUsernameView(APIView):
    """
    GET /api/auth/check-username/?username=SomeUsername
    Public endpoint — no auth required.
    Returns:
        { "available": true, "message": "Username is available." }
        { "available": false, "message": "Username is already taken." }
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        username = request.query_params.get('username', '').strip()

        if not username:
            return Response(
                {"error": "Please provide a 'username' query parameter."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if len(username) < 3:
            return Response(
                {"available": False, "message": "Username must be at least 3 characters."},
                status=status.HTTP_200_OK
            )

        if len(username) > 30:
            return Response(
                {"available": False, "message": "Username must be 30 characters or fewer."},
                status=status.HTTP_200_OK
            )

        # Check both User model username and UserProfile username fields
        user_taken = User.objects.filter(username__iexact=username).exists()
        profile_taken = UserProfile.objects.filter(username__iexact=username).exists()

        if user_taken or profile_taken:
            return Response(
                {"available": False, "message": "Username is already taken."},
                status=status.HTTP_200_OK
            )

        return Response(
            {"available": True, "message": "Username is available."},
            status=status.HTTP_200_OK
        )


# FACE VERIFICATION
class FaceDetectView(APIView):
    """
    POST /api/auth/face-detect/
    Checks if a clear human face exists in the uploaded photo using OpenCV.
    Returns:
        { "face_detected": true/false, "error": "Error message if not detected" }
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        selfie = request.FILES.get('selfie')
        if not selfie:
            return Response(
                {"face_detected": False, "error": "No image file provided under the key 'selfie'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate it's a real image
        try:
            from PIL import Image
            img = Image.open(selfie)
            img.verify()
            selfie.seek(0)
        except Exception:
            return Response(
                {"face_detected": False, "error": "Invalid image file. Please upload a valid photo."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Run face detection
        try:
            import cv2
            import numpy as np
            
            file_bytes = np.frombuffer(selfie.read(), np.uint8)
            selfie.seek(0)
            
            cv_img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
            if cv_img is not None:
                gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
                cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
                face_cascade = cv2.CascadeClassifier(cascade_path)
                
                faces = face_cascade.detectMultiScale(
                    gray,
                    scaleFactor=1.1,
                    minNeighbors=5,
                    minSize=(80, 80)
                )
                
                if len(faces) == 0:
                    return Response(
                        {"face_detected": False, "error": "No face detected in the photo. Please make sure your face is clearly visible, well-lit, and fits within the frame."},
                        status=status.HTTP_200_OK
                    )
                elif len(faces) > 1:
                    return Response(
                        {"face_detected": False, "error": "Multiple faces detected. Please ensure only one person is in the frame."},
                        status=status.HTTP_200_OK
                    )
                else:
                    return Response(
                        {"face_detected": True, "faces_count": 1},
                        status=status.HTTP_200_OK
                    )
        except Exception as e:
            print(f"[FACE DETECTION API ERROR] {e}")
            return Response(
                {"face_detected": False, "error": f"Error running face detection: {str(e)}"},
                status=status.HTTP_200_OK
            )
            
        return Response({"face_detected": False, "error": "Could not process the image."}, status=status.HTTP_200_OK)


class FaceVerifyView(APIView):
    """
    POST /api/auth/face-verify/
    Requires: Bearer token (authenticated user)
    Body: multipart/form-data  →  { "selfie": <image file> }

    The app does on-device face detection, then calls this once a clear
    face is captured. The backend stores the selfie and marks the profile
    as pending admin review.

    Returns:
        { "status": "pending", "message": "Selfie submitted. Pending review." }
    """
    permission_classes = [permissions.IsAuthenticated]
    parser_classes_override = None  # DRF handles multipart automatically

    def post(self, request):
        profile = request.user.profile

        front = request.FILES.get('front')
        left = request.FILES.get('left')
        right = request.FILES.get('right')

        if not (front and left and right):
            return Response(
                {"error": "Please provide front, left, and right verification photos."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 10 MB size limit for each
        for f in [front, left, right]:
            if f.size > 10 * 1024 * 1024:
                return Response(
                    {"error": "One or more images are too large. Maximum size is 10 MB each."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        try:
            from PIL import Image, ImageOps
            import io
            from django.core.files.base import ContentFile

            # Open and verify
            img_front = Image.open(front)
            img_left = Image.open(left)
            img_right = Image.open(right)

            img_front.verify()
            img_left.verify()
            img_right.verify()

            front.seek(0)
            left.seek(0)
            right.seek(0)

            # Re-open for processing
            img_front = Image.open(front)
            img_left = Image.open(left)
            img_right = Image.open(right)

            # Auto-rotate based on EXIF data (crucial for mobile photos)
            img_front = ImageOps.exif_transpose(img_front)
            img_left = ImageOps.exif_transpose(img_left)
            img_right = ImageOps.exif_transpose(img_right)

            # Standardize height to 800px
            target_height = 800
            def resize_and_convert(img, h):
                ratio = h / float(img.size[1])
                w = int((float(img.size[0]) * float(ratio)))
                resized = img.resize((w, h), Image.Resampling.LANCZOS)
                if resized.mode in ("RGBA", "P"):
                    resized = resized.convert("RGB")
                
                output = io.BytesIO()
                resized.save(output, format='JPEG', quality=85)
                output.seek(0)
                return output

            front_io = resize_and_convert(img_front, target_height)
            left_io = resize_and_convert(img_left, target_height)
            right_io = resize_and_convert(img_right, target_height)

            # Delete previous files if they exist
            if profile.face_selfie:
                profile.face_selfie.delete(save=False)
            if profile.face_selfie_left:
                profile.face_selfie_left.delete(save=False)
            if profile.face_selfie_right:
                profile.face_selfie_right.delete(save=False)

            # Save the individual images
            uid = request.user.id
            profile.face_selfie.save(f"verification_{uid}_front.jpg", ContentFile(front_io.read()), save=False)
            profile.face_selfie_left.save(f"verification_{uid}_left.jpg", ContentFile(left_io.read()), save=False)
            profile.face_selfie_right.save(f"verification_{uid}_right.jpg", ContentFile(right_io.read()), save=False)
            
            profile.face_verification_status = 'pending'
            profile.face_verified_at = None  # Reset until admin approves
            profile.save(update_fields=[
                'face_selfie', 'face_selfie_left', 'face_selfie_right', 
                'face_verification_status', 'face_verified_at'
            ])

            return Response(
                {
                    "status": "pending",
                    "message": "Verification photos submitted successfully. Pending review."
                },
                status=status.HTTP_200_OK
            )

        except Exception as e:
            print(f"[FACE STITCHING ERROR] {e}")
            return Response(
                {"error": "Failed to process verification photos. Please try again."},
                status=status.HTTP_400_BAD_REQUEST
            )


class ChatImageUploadView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request, *args, **kwargs):
        from django.core.files.storage import default_storage
        file = request.FILES.get('image')
        if not file:
            return Response({"error": "No image provided"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            file_name = default_storage.save(f"chat_images/{file.name}", file)
            file_url = default_storage.url(file_name)
            return Response({"image_url": file_url}, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class AdminActionLogViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/admin/logs/
    Admin endpoint to view system logs.
    """
    permission_classes = [IsAdminUser]
    serializer_class = AdminActionLogSerializer
    queryset = AdminActionLog.objects.all().order_by('-timestamp')
    
    def get_queryset(self):
        qs = super().get_queryset()
        # Optional filtering by user or action
        search = self.request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                models.Q(admin_user__username__icontains=search) |
                models.Q(admin_user__email__icontains=search) |
                models.Q(target_user__username__icontains=search) |
                models.Q(action__icontains=search)
            )
        return qs

class AdminModerationStatsViewSet(APIView):
    permission_classes = [IsModerator]

    def get(self, request):
        today = timezone.now().date()
        
        # Global stats
        reports_received = Report.objects.count()
        reports_in_review = Report.objects.filter(status='under_review').count()
        actions_taken = Report.objects.filter(status='resolved').count()
        suspended_users = User.objects.filter(is_active=False, role='member').count()
        
        waiting_in_queue = Report.objects.filter(status='pending').count()
        assigned_to_moderators = Report.objects.filter(assign_to__isnull=False).count()
        closed_today = Report.objects.filter(status='resolved', created_at__date=today).count()
        
        # Moderator Activity
        moderators = User.objects.filter(role__in=['admin', 'superadmin', 'moderator', 'support'])
        moderator_activity = []
        for mod in moderators:
            resolved_count = Report.objects.filter(resolved_by=mod).count()
            pending_count = Report.objects.filter(assign_to=mod).exclude(status='resolved').count()
            if resolved_count > 0 or pending_count > 0:
                moderator_activity.append({
                    "id": mod.id,
                    "moderator": f"{mod.first_name} {mod.last_name}".strip() or mod.username,
                    "assignment": mod.role.capitalize(),
                    "resolvedReports": resolved_count,
                    "pendingReports": pending_count
                })

        return Response({
            "global_stats": {
                "reports_received": reports_received,
                "reports_in_review": reports_in_review,
                "actions_taken": actions_taken,
                "suspended_users": suspended_users,
                "waiting_in_queue": waiting_in_queue,
                "assigned_to_moderators": assigned_to_moderators,
                "closed_today": closed_today
            },
            "moderator_activity": moderator_activity
        })

class DeleteAccountView(APIView):
    def post(self, request):
        from api.utils_delete import delete_user_files
        user = request.user
        delete_user_files(user)
        user.delete()
        return Response({"message": "Account and all associated data deleted successfully."})

class NotificationListView(APIView):
    """
    GET /api/notifications/
    Returns the current user's chronological notification history.
    """
    def get(self, request):
        from api.models import Notification
        from api.serializers import NotificationSerializer
        
        try:
            limit = int(request.query_params.get('limit', 20))
            offset = int(request.query_params.get('offset', 0))
        except ValueError:
            limit = 20
            offset = 0
            
        qs = Notification.objects.filter(recipient=request.user).order_by('-created_at')
        total = qs.count()
        
        notifications = qs[offset:offset+limit]
        serializer = NotificationSerializer(notifications, many=True)
        
        return Response({
            'results': serializer.data,
            'total': total,
            'next': (offset + limit) < total
        }, status=status.HTTP_200_OK)

class MarkNotificationsReadView(APIView):
    """
    POST /api/notifications/read-all/
    Marks all notifications for the current user as read.
    """
    def post(self, request):
        from api.models import Notification
        Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
        return Response({"success": True}, status=status.HTTP_200_OK)

class UnreadNotificationCountView(APIView):
    """
    GET /api/notifications/unread-count/
    Returns the number of unread notifications for the current user.
    """
    def get(self, request):
        from api.models import Notification
        count = Notification.objects.filter(recipient=request.user, is_read=False).count()
        return Response({"count": count}, status=status.HTTP_200_OK)
