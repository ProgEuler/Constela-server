from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from api.models import (
    User, UserProfile, UserPhoto, Match, Friendship,
    DirectMessage, ChatRoom, ChatRoomMessage, SupportTicket,
    SupportTicketReply, Report, Block, Transaction, OTPLog, SavedMatch,
    SubscriptionTierConfig
)


# ──────────────────────────────────────────────────────────────
# USER
# ──────────────────────────────────────────────────────────────
class CustomUserAdmin(UserAdmin):
    model = User
    list_display = ('email', 'username', 'role', 'is_verified', 'is_active', 'date_joined')
    list_filter = ('role', 'is_verified', 'is_staff', 'is_active')
    search_fields = ('email', 'username')
    ordering = ('-date_joined',)
    fieldsets = (
        ('Account', {'fields': ('email', 'username', 'password')}),
        ('Role & Verification', {'fields': ('role', 'is_verified', 'otp', 'otp_created_at')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Timestamps', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        ('Create User', {
            'classes': ('wide',),
            'fields': ('email', 'username', 'password1', 'password2', 'role', 'is_verified'),
        }),
    )


# ──────────────────────────────────────────────────────────────
# USER PHOTO (inline inside UserProfile)
# ──────────────────────────────────────────────────────────────
class UserPhotoInline(admin.TabularInline):
    model = UserPhoto
    extra = 0
    fields = ('image_preview', 'image', 'is_main', 'is_verified', 'uploaded_at')
    readonly_fields = ('image_preview', 'uploaded_at')

    def image_preview(self, obj):
        if obj.image:
            try:
                url = obj.image.url
                if not (url.startswith('http://') or url.startswith('https://')):
                    import cloudinary.utils
                    url, _ = cloudinary.utils.cloudinary_url(obj.image.name, secure=True)
            except Exception:
                url = ''
            if url:
                return format_html('<img src="{}" style="height:60px;border-radius:6px;" />', url)
        return '—'
    image_preview.short_description = 'Preview'


# ──────────────────────────────────────────────────────────────
# USER PROFILE
# ──────────────────────────────────────────────────────────────
class UserProfileAdmin(admin.ModelAdmin):
    inlines = [UserPhotoInline]
    list_display = ('username', 'user_email', 'gender', 'age', 'city', 'country',
                    'subscription_tier', 'subscription_product_id', 'is_verified', 'profile_completion_pct')
    readonly_fields = ('face_selfie_preview', 'face_selfie_left_preview', 'face_selfie_right_preview',
                       'subscription_product_id', 'subscription_store')

    def get_cloudinary_preview(self, img_field):
        if img_field:
            try:
                url = img_field.url
                if not (url.startswith('http://') or url.startswith('https://')):
                    import cloudinary.utils
                    url, _ = cloudinary.utils.cloudinary_url(img_field.name, secure=True)
            except Exception:
                url = ''
            if url:
                return format_html('<img src="{}" style="height:150px;border-radius:8px;object-fit:cover;" />', url)
        return '—'

    def face_selfie_preview(self, obj):
        return self.get_cloudinary_preview(obj.face_selfie)
    face_selfie_preview.short_description = 'Front Selfie'
    
    def face_selfie_left_preview(self, obj):
        return self.get_cloudinary_preview(obj.face_selfie_left)
    face_selfie_left_preview.short_description = 'Left Selfie'
    
    def face_selfie_right_preview(self, obj):
        return self.get_cloudinary_preview(obj.face_selfie_right)
    face_selfie_right_preview.short_description = 'Right Selfie'
    list_filter = ('gender', 'subscription_tier', 'subscription_store', 'is_verified', 'is_neurodivergent',
                   'marital_status', 'looking_for')
    search_fields = ('username', 'city', 'country', 'user__email')
    ordering = ('username',)
    fieldsets = (
        ('Linked Account', {
            'fields': ('user',)
        }),
        ('Basic Info', {
            'fields': ('username', 'age', 'height_cm', 'weight_kg', 'gender',
                       'looking_for', 'marital_status', 'education_level', 'spoken_languages')
        }),
        ('Location', {
            'fields': ('city', 'country', 'latitude', 'longitude')
        }),
        ('Neurodivergent Profile', {
            'fields': ('is_neurodivergent', 'open_to_meet_neurodivergent', 'neurotype_labels',
                       'qualities', 'interests', 'recharge_methods', 'exhaust_triggers',
                       'emotional_needs', 'second_degree_humor', 'soothe_methods')
        }),
        ('Lifestyle', {
            'fields': ('smoking', 'alcohol', 'pets', 'sport', 'eating_habits',
                       'has_children', 'wants_children')
        }),
        ('Subscription', {
            'fields': ('subscription_tier', 'subscription_expires', 'subscription_product_id', 'subscription_store')
        }),
        ('App Settings', {
            'fields': ('likes_push', 'messages_push', 'is_dark_mode', 'preferred_language', 'is_deactivated')
        }),
        ('Verification & Completion', {
            'fields': ('is_verified', 'profile_completion_pct',
                       'face_selfie_preview', 'face_selfie', 
                       'face_selfie_left_preview', 'face_selfie_left', 
                       'face_selfie_right_preview', 'face_selfie_right', 
                       'face_verification_status', 'face_verified_at')
        }),
    )

    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'Email'
    user_email.admin_order_field = 'user__email'


# ──────────────────────────────────────────────────────────────
# USER PHOTO (standalone)
# ──────────────────────────────────────────────────────────────
class UserPhotoAdmin(admin.ModelAdmin):
    list_display = ('id', 'profile', 'image_preview', 'is_main', 'is_verified', 'uploaded_at')
    list_filter = ('is_main', 'is_verified')
    search_fields = ('profile__username',)
    readonly_fields = ('image_preview', 'uploaded_at')
    fields = ('profile', 'image', 'image_preview', 'is_main', 'is_verified', 'uploaded_at')

    def image_preview(self, obj):
        if obj.image:
            try:
                url = obj.image.url
                if not (url.startswith('http://') or url.startswith('https://')):
                    import cloudinary.utils
                    url, _ = cloudinary.utils.cloudinary_url(obj.image.name, secure=True)
            except Exception:
                url = ''
            if url:
                return format_html('<img src="{}" style="height:80px;border-radius:8px;" />', url)
        return '—'
    image_preview.short_description = 'Preview'


# ──────────────────────────────────────────────────────────────
# MATCH
# ──────────────────────────────────────────────────────────────
class MatchAdmin(admin.ModelAdmin):
    list_display = ('user1', 'user2', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('user1__username', 'user2__username')
    fields = ('user1', 'user2', 'status', 'created_at')
    readonly_fields = ('created_at',)


# ──────────────────────────────────────────────────────────────
# FRIENDSHIP
# ──────────────────────────────────────────────────────────────
class FriendshipAdmin(admin.ModelAdmin):
    list_display = ('sender', 'receiver', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('sender__username', 'receiver__username')
    fields = ('sender', 'receiver', 'status', 'created_at')
    readonly_fields = ('created_at',)


# ──────────────────────────────────────────────────────────────
# DIRECT MESSAGE
# ──────────────────────────────────────────────────────────────
class DirectMessageAdmin(admin.ModelAdmin):
    list_display = ('sender', 'receiver', 'content_snippet', 'timestamp', 'read_at')
    search_fields = ('sender__username', 'receiver__username')
    fields = ('sender', 'receiver', 'content', 'timestamp', 'read_at')
    readonly_fields = ('timestamp',)

    def content_snippet(self, obj):
        return obj.content[:60] + '…' if len(obj.content) > 60 else obj.content
    content_snippet.short_description = 'Message'


# ──────────────────────────────────────────────────────────────
# CHAT ROOM
# ──────────────────────────────────────────────────────────────
class ChatRoomMessageInline(admin.TabularInline):
    model = ChatRoomMessage
    extra = 0
    fields = ('sender', 'content', 'timestamp')
    readonly_fields = ('timestamp',)


class ChatRoomAdmin(admin.ModelAdmin):
    inlines = [ChatRoomMessageInline]
    list_display = ('name', 'status', 'member_count', 'created_at')
    list_filter = ('status',)
    search_fields = ('name',)
    fields = ('name', 'description', 'status', 'member_count', 'members', 'created_at')
    readonly_fields = ('created_at',)
    filter_horizontal = ('members',)


class ChatRoomMessageAdmin(admin.ModelAdmin):
    list_display = ('room', 'sender', 'content_snippet', 'timestamp')
    search_fields = ('room__name', 'sender__username')
    fields = ('room', 'sender', 'content', 'timestamp')
    readonly_fields = ('timestamp',)

    def content_snippet(self, obj):
        return obj.content[:60] + '…' if len(obj.content) > 60 else obj.content
    content_snippet.short_description = 'Message'


# ──────────────────────────────────────────────────────────────
# SUPPORT TICKET
# ──────────────────────────────────────────────────────────────
class SupportTicketReplyInline(admin.StackedInline):
    model = SupportTicketReply
    extra = 0
    fields = ('sender', 'content', 'created_at')
    readonly_fields = ('created_at',)


class SupportTicketAdmin(admin.ModelAdmin):
    inlines = [SupportTicketReplyInline]
    list_display = ('id', 'user', 'subject', 'priority', 'status', 'created_at')
    list_filter = ('priority', 'status')
    search_fields = ('subject', 'description', 'user__username')
    fields = ('user', 'email', 'subject', 'description', 'priority', 'status', 'created_at', 'updated_at')
    readonly_fields = ('created_at', 'updated_at')


class SupportTicketReplyAdmin(admin.ModelAdmin):
    list_display = ('ticket', 'sender', 'created_at')
    search_fields = ('ticket__subject', 'sender__email')
    fields = ('ticket', 'sender', 'content', 'created_at')
    readonly_fields = ('created_at',)


# ──────────────────────────────────────────────────────────────
# REPORT
# ──────────────────────────────────────────────────────────────
class ReportAdmin(admin.ModelAdmin):
    list_display = ('id', 'reporter', 'reported_user', 'reason', 'status', 'action_taken', 'created_at')
    list_filter = ('reason', 'status', 'action_taken')
    search_fields = ('reporter__username', 'reported_user__username')
    fields = ('reporter', 'reported_user', 'reason', 'description', 'status', 'action_taken', 'created_at')
    readonly_fields = ('created_at',)


# ──────────────────────────────────────────────────────────────
# BLOCK
# ──────────────────────────────────────────────────────────────
class BlockAdmin(admin.ModelAdmin):
    list_display = ('blocker', 'blocked_user', 'created_at')
    search_fields = ('blocker__username', 'blocked_user__username')
    fields = ('blocker', 'blocked_user', 'created_at')
    readonly_fields = ('created_at',)


# ──────────────────────────────────────────────────────────────
# TRANSACTION
# ──────────────────────────────────────────────────────────────
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'plan_name', 'amount', 'status', 'payment_method', 'created_at')
    list_filter = ('status', 'plan_name')
    search_fields = ('user__username', 'plan_name', 'stripe_charge_id')
    fields = ('user', 'plan_name', 'amount', 'status', 'payment_method', 'stripe_charge_id', 'created_at')
    readonly_fields = ('created_at',)


# ──────────────────────────────────────────────────────────────
# OTP LOG
# ──────────────────────────────────────────────────────────────
class OTPLogAdmin(admin.ModelAdmin):
    list_display = ('email', 'otp', 'action', 'timestamp')
    list_filter = ('action',)
    search_fields = ('email', 'otp')
    fields = ('email', 'otp', 'action', 'timestamp')
    readonly_fields = ('timestamp',)


# ──────────────────────────────────────────────────────────────
# SAVED MATCH
# ──────────────────────────────────────────────────────────────
class SavedMatchAdmin(admin.ModelAdmin):
    list_display = ('user', 'target_profile', 'created_at')
    search_fields = ('user__username', 'target_profile__username')
    fields = ('user', 'target_profile', 'created_at')
    readonly_fields = ('created_at',)


# ──────────────────────────────────────────────────────────────
# SUBSCRIPTION TIER CONFIGURATION
# ──────────────────────────────────────────────────────────────
class SubscriptionTierConfigAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'tier', 'daily_likes_limit', 'daily_personal_messages_limit',
        'daily_community_messages_limit',
        'community_room_limit', 'can_see_likes', 'can_undo_swipes', 'updated_at'
    )
    list_editable = (
        'daily_likes_limit', 'daily_personal_messages_limit',
        'daily_community_messages_limit',
        'community_room_limit', 'can_see_likes', 'can_undo_swipes'
    )
    readonly_fields = ('updated_at',)
    fieldsets = (
        ('Tier Identity', {
            'fields': ('tier', 'name')
        }),
        ('Quotas & Limits', {
            'fields': ('daily_likes_limit', 'daily_personal_messages_limit', 'daily_community_messages_limit', 'community_room_limit'),
            'description': 'Leave limits empty (null) for unlimited access. Set community_room_limit to 0 for none, or leave empty for all rooms.'
        }),
        ('Feature Permissions', {
            'fields': ('can_see_likes', 'can_undo_swipes')
        }),
        ('Audit', {
            'fields': ('updated_at',)
        }),
    )


# ──────────────────────────────────────────────────────────────
# REGISTRATIONS
# ──────────────────────────────────────────────────────────────
admin.site.register(User, CustomUserAdmin)
admin.site.register(UserProfile, UserProfileAdmin)
admin.site.register(UserPhoto, UserPhotoAdmin)
admin.site.register(Match, MatchAdmin)
admin.site.register(Friendship, FriendshipAdmin)
admin.site.register(DirectMessage, DirectMessageAdmin)
admin.site.register(ChatRoom, ChatRoomAdmin)
admin.site.register(ChatRoomMessage, ChatRoomMessageAdmin)
admin.site.register(SupportTicket, SupportTicketAdmin)
admin.site.register(SupportTicketReply, SupportTicketReplyAdmin)
admin.site.register(Report, ReportAdmin)
admin.site.register(Block, BlockAdmin)
admin.site.register(Transaction, TransactionAdmin)
admin.site.register(OTPLog, OTPLogAdmin)
admin.site.register(SavedMatch, SavedMatchAdmin)
admin.site.register(SubscriptionTierConfig, SubscriptionTierConfigAdmin)

admin.site.site_header = 'Constela Admin'
admin.site.site_title = 'Constela'
admin.site.index_title = 'Backend Management'
