from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group
from django.utils.html import format_html
from unfold.admin import ModelAdmin, StackedInline, TabularInline
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm
from api.models import (
    User, UserProfile, UserPhoto, Match, Friendship,
    DirectMessage, ChatRoom, ChatRoomMessage, SupportTicket,
    SupportTicketReply, Report, Block, Transaction, OTPLog, SavedMatch,
    SubscriptionTierConfig, MatchAnalysisPurchase, PhotoVerification, PushDevice
)
from django import forms
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html_join
from unfold.decorators import action, display


# ──────────────────────────────────────────────────────────────
# IMAGE HELPERS (same URL logic the app API uses)
# ──────────────────────────────────────────────────────────────
def media_url(image_field):
    """Resolve a stored image exactly like the API does: full URLs as-is,
    R2 presigned URLs, or the Cloudinary CDN fallback for legacy files."""
    if not image_field:
        return ''
    try:
        from api.views import get_cloudinary_url
        return get_cloudinary_url(image_field) or ''
    except Exception:
        return ''


def image_tag(image_field, height=80, round_=False):
    url = media_url(image_field)
    if not url:
        return '—'
    if round_:
        return format_html(
            '<img src="{}" style="width:{}px;height:{}px;border-radius:50%;object-fit:cover;" />',
            url, height, height,
        )
    return format_html('<img src="{}" style="height:{}px;border-radius:8px;object-fit:cover;" />', url, height)


def main_photo_of(profile):
    if profile is None:
        return None
    photos = list(profile.photos.all())
    photo = next((p for p in photos if p.is_main), photos[0] if photos else None)
    return photo.image if photo else None


# ──────────────────────────────────────────────────────────────
# USER
# ──────────────────────────────────────────────────────────────
class CustomUserAdmin(UserAdmin, ModelAdmin):
    model = User
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm
    list_display = ('avatar', 'email', 'username', 'role', 'is_verified', 'is_active', 'date_joined')
    list_display_links = ('avatar', 'email')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('profile').prefetch_related('profile__photos')

    def avatar(self, obj):
        profile = getattr(obj, 'profile', None)
        return image_tag(main_photo_of(profile), height=36, round_=True)
    avatar.short_description = 'Photo'
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
class UserPhotoInline(TabularInline):
    model = UserPhoto
    extra = 0
    fields = ('image_preview', 'image', 'is_main', 'is_verified', 'uploaded_at')
    readonly_fields = ('image_preview', 'uploaded_at')

    def image_preview(self, obj):
        return image_tag(obj.image, height=60)
    image_preview.short_description = 'Preview'


# ──────────────────────────────────────────────────────────────
# USER PROFILE
# ──────────────────────────────────────────────────────────────
class PushDeviceInline(TabularInline):
    model = PushDevice
    extra = 0
    can_delete = True
    fields = ('platform', 'token', 'updated_at')
    readonly_fields = ('platform', 'token', 'updated_at')
    verbose_name = 'Push device'
    verbose_name_plural = 'Push devices (phones registered for notifications)'

    def has_add_permission(self, request, obj=None):
        return False


class UserProfileAdmin(ModelAdmin):
    inlines = [UserPhotoInline, PushDeviceInline]
    list_display = ('avatar', 'username', 'user_email', 'gender', 'age', 'city', 'country',
                    'subscription_tier', 'subscription_product_id', 'is_verified', 'profile_completion_pct')
    readonly_fields = ('face_selfie_preview', 'face_selfie_left_preview', 'face_selfie_right_preview',
                       'subscription_product_id', 'subscription_store')

    list_display_links = ('avatar', 'username')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user').prefetch_related('photos')

    def avatar(self, obj):
        return image_tag(main_photo_of(obj), height=36, round_=True)
    avatar.short_description = 'Photo'

    def get_cloudinary_preview(self, img_field):
        return image_tag(img_field, height=150)

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
class UserPhotoAdmin(ModelAdmin):
    list_display = ('id', 'profile', 'image_preview', 'is_main', 'is_verified', 'uploaded_at')
    list_filter = ('is_main', 'is_verified')
    search_fields = ('profile__username',)
    readonly_fields = ('image_preview', 'uploaded_at')
    fields = ('profile', 'image', 'image_preview', 'is_main', 'is_verified', 'uploaded_at')

    def image_preview(self, obj):
        return image_tag(obj.image, height=80)
    image_preview.short_description = 'Preview'


# ──────────────────────────────────────────────────────────────
# MATCH
# ──────────────────────────────────────────────────────────────
class MatchAdmin(ModelAdmin):
    list_display = ('user1', 'user2', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('user1__username', 'user2__username')
    fields = ('user1', 'user2', 'status', 'created_at')
    readonly_fields = ('created_at',)


# ──────────────────────────────────────────────────────────────
# FRIENDSHIP
# ──────────────────────────────────────────────────────────────
class FriendshipAdmin(ModelAdmin):
    list_display = ('sender', 'receiver', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('sender__username', 'receiver__username')
    fields = ('sender', 'receiver', 'status', 'created_at')
    readonly_fields = ('created_at',)


# ──────────────────────────────────────────────────────────────
# DIRECT MESSAGE
# ──────────────────────────────────────────────────────────────
class DirectMessageAdmin(ModelAdmin):
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
class ChatRoomMessageInline(TabularInline):
    model = ChatRoomMessage
    extra = 0
    fields = ('sender', 'content', 'timestamp')
    readonly_fields = ('timestamp',)


class ChatRoomAdmin(ModelAdmin):
    inlines = [ChatRoomMessageInline]
    list_display = ('name', 'status', 'member_count', 'created_at')
    list_filter = ('status',)
    search_fields = ('name',)
    fields = ('name', 'description', 'status', 'member_count', 'members', 'created_at')
    readonly_fields = ('created_at',)
    filter_horizontal = ('members',)


class ChatRoomMessageAdmin(ModelAdmin):
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
class SupportTicketReplyInline(StackedInline):
    model = SupportTicketReply
    extra = 0
    fields = ('sender', 'content', 'created_at')
    readonly_fields = ('created_at',)


class SupportTicketAdmin(ModelAdmin):
    inlines = [SupportTicketReplyInline]
    list_display = ('id', 'user', 'subject', 'priority', 'status', 'created_at')
    list_filter = ('priority', 'status')
    search_fields = ('subject', 'description', 'user__username')
    fields = ('user', 'email', 'subject', 'description', 'priority', 'status', 'created_at', 'updated_at')
    readonly_fields = ('created_at', 'updated_at')


class SupportTicketReplyAdmin(ModelAdmin):
    list_display = ('ticket', 'sender', 'created_at')
    search_fields = ('ticket__subject', 'sender__email')
    fields = ('ticket', 'sender', 'content', 'created_at')
    readonly_fields = ('created_at',)


# ──────────────────────────────────────────────────────────────
# REPORT
# ──────────────────────────────────────────────────────────────
class ReportAdmin(ModelAdmin):
    list_display = ('id', 'reporter', 'reported_user', 'reason', 'status', 'action_taken', 'created_at')
    list_filter = ('reason', 'status', 'action_taken')
    search_fields = ('reporter__username', 'reported_user__username')
    fields = ('reporter', 'reported_user', 'reason', 'description', 'status', 'action_taken', 'created_at')
    readonly_fields = ('created_at',)


# ──────────────────────────────────────────────────────────────
# BLOCK
# ──────────────────────────────────────────────────────────────
class BlockAdmin(ModelAdmin):
    list_display = ('blocker', 'blocked_user', 'created_at')
    search_fields = ('blocker__username', 'blocked_user__username')
    fields = ('blocker', 'blocked_user', 'created_at')
    readonly_fields = ('created_at',)


# ──────────────────────────────────────────────────────────────
# TRANSACTION
# ──────────────────────────────────────────────────────────────
class TransactionAdmin(ModelAdmin):
    list_display = ('id', 'user', 'plan_name', 'amount', 'status', 'payment_method', 'created_at')
    list_filter = ('status', 'plan_name')
    search_fields = ('user__username', 'plan_name', 'stripe_charge_id')
    fields = ('user', 'plan_name', 'amount', 'status', 'payment_method', 'stripe_charge_id', 'created_at')
    readonly_fields = ('created_at',)


# ──────────────────────────────────────────────────────────────
# OTP LOG
# ──────────────────────────────────────────────────────────────
class OTPLogAdmin(ModelAdmin):
    list_display = ('email', 'otp', 'action', 'timestamp')
    list_filter = ('action',)
    search_fields = ('email', 'otp')
    fields = ('email', 'otp', 'action', 'timestamp')
    readonly_fields = ('timestamp',)


# ──────────────────────────────────────────────────────────────
# SAVED MATCH
# ──────────────────────────────────────────────────────────────
class SavedMatchAdmin(ModelAdmin):
    list_display = ('user', 'target_profile', 'created_at')
    search_fields = ('user__username', 'target_profile__username')
    fields = ('user', 'target_profile', 'created_at')
    readonly_fields = ('created_at',)


# ──────────────────────────────────────────────────────────────
# SUBSCRIPTION TIER CONFIGURATION
# ──────────────────────────────────────────────────────────────
class SubscriptionTierConfigAdmin(ModelAdmin):
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
# PERFECT MATCH ANALYSIS (one-time purchases)
# ──────────────────────────────────────────────────────────────
class MatchAnalysisPurchaseAdmin(ModelAdmin):
    list_display = ('profile', 'store', 'product_id', 'purchased_at', 'generated_at', 'result_count')
    list_filter = ('store', 'product_id')
    search_fields = ('profile__username', 'profile__user__email', 'transaction_key')
    readonly_fields = ('generated_at', 'results', 'created_at')
    autocomplete_fields = ('profile',)
    ordering = ('-purchased_at',)

    def result_count(self, obj):
        return len(obj.results or [])
    result_count.short_description = 'Matches'

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # A manually granted analysis gets its top 5 computed right away.
        if obj.generated_at is None:
            from api.match_analysis import generate_snapshot
            generate_snapshot(obj)


# ──────────────────────────────────────────────────────────────
# PHOTO VERIFICATION (manual review: profile pictures vs live photo)
# ──────────────────────────────────────────────────────────────
class PhotoVerificationForm(forms.ModelForm):
    face_verification_status = forms.ChoiceField(
        label='Decision',
        choices=[('pending', 'Pending review'), ('approved', 'Approve — photos match'),
                 ('rejected', 'Reject — photos do not match')],
    )
    face_verification_note = forms.CharField(
        label='Reason shown to the user (if rejected)', required=False, max_length=255,
        widget=forms.Textarea(attrs={'rows': 2}),
    )

    class Meta:
        model = PhotoVerification
        fields = ('face_verification_status', 'face_verification_note')


class PhotoVerificationAdmin(ModelAdmin):
    form = PhotoVerificationForm
    list_display = ('comparison', 'username', 'user_email', 'status', 'face_submitted_at')
    list_display_links = ('username',)
    list_filter = ('face_verification_status',)
    search_fields = ('username', 'user__email')
    ordering = ('-face_submitted_at',)
    list_per_page = 25
    actions = ['approve_selected', 'reject_selected']
    actions_row = ['approve_row', 'reject_row']
    actions_detail = ['approve_detail', 'reject_detail']
    fieldsets = (
        ('Compare', {'fields': ('comparison_large',)}),
        ('Account', {'fields': ('user_email', 'city', 'country', 'face_submitted_at', 'face_verified_at')}),
        ('Decision', {'fields': ('face_verification_status', 'face_verification_note')}),
    )
    readonly_fields = ('comparison_large', 'user_email', 'city', 'country', 'face_submitted_at', 'face_verified_at')

    def get_queryset(self, request):
        return (super().get_queryset(request)
                .exclude(face_selfie='').exclude(face_selfie__isnull=True)
                .select_related('user').prefetch_related('photos'))

    def changelist_view(self, request, extra_context=None):
        # Open on the review queue by default.
        if not request.GET and request.method == 'GET':
            return redirect(f"{request.path}?face_verification_status__exact=pending")
        return super().changelist_view(request, extra_context)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    # ── display ──
    @staticmethod
    def _profile_images(obj, height):
        photos = sorted(obj.photos.all(), key=lambda p: (not p.is_main, p.uploaded_at))
        return [image_tag(p.image, height=height) for p in photos] or ['—']

    def comparison(self, obj):
        profile_imgs = self._profile_images(obj, 72)[:3]
        return format_html(
            '<div style="display:flex;gap:16px;align-items:flex-start">'
            '<div><div style="font-size:11px;opacity:.7;margin-bottom:4px">Profile pictures</div>'
            '<div style="display:flex;gap:6px">{}</div></div>'
            '<div style="border-left:2px solid #DE4177;padding-left:16px">'
            '<div style="font-size:11px;opacity:.7;margin-bottom:4px">Verification photo</div>{}</div>'
            '</div>',
            format_html_join('', '{}', ((img,) for img in profile_imgs)),
            image_tag(obj.face_selfie, height=72),
        )
    comparison.short_description = 'Profile vs verification'

    def comparison_large(self, obj):
        return format_html(
            '<div style="display:flex;gap:32px;flex-wrap:wrap;align-items:flex-start">'
            '<div><div style="font-weight:600;margin-bottom:8px">Profile pictures</div>'
            '<div style="display:flex;gap:10px;flex-wrap:wrap;max-width:620px">{}</div></div>'
            '<div><div style="font-weight:600;margin-bottom:8px;color:#DE4177">Live verification photo</div>{}</div>'
            '</div>',
            format_html_join('', '{}', ((img,) for img in self._profile_images(obj, 280))),
            image_tag(obj.face_selfie, height=360),
        )
    comparison_large.short_description = ''

    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'Email'

    @display(description='Status', label={'pending': 'warning', 'approved': 'success', 'rejected': 'danger'})
    def status(self, obj):
        return obj.face_verification_status

    # ── decisions ──
    def save_model(self, request, obj, form, change):
        from api.photo_verification import decide
        decision = form.cleaned_data.get('face_verification_status')
        note = form.cleaned_data.get('face_verification_note', '')
        if change and 'face_verification_status' in form.changed_data and decision in ('approved', 'rejected'):
            decide(obj, approved=decision == 'approved', note=note)
        else:
            super().save_model(request, obj, form, change)

    def _decide(self, request, object_id, approved):
        from api.photo_verification import decide
        profile = PhotoVerification.objects.get(pk=object_id)
        decide(profile, approved=approved)
        messages.success(request, f"{profile.username}: {'approved' if approved else 'rejected'}.")
        return redirect(request.headers.get('referer') or reverse('admin:api_photoverification_changelist'))

    @action(description='Approve', icon='check_circle')
    def approve_row(self, request, object_id):
        return self._decide(request, object_id, True)

    @action(description='Reject', icon='cancel')
    def reject_row(self, request, object_id):
        return self._decide(request, object_id, False)

    @action(description='Approve', icon='check_circle')
    def approve_detail(self, request, object_id):
        return self._decide(request, object_id, True)

    @action(description='Reject', icon='cancel')
    def reject_detail(self, request, object_id):
        return self._decide(request, object_id, False)

    @admin.action(description='Approve selected')
    def approve_selected(self, request, queryset):
        from api.photo_verification import decide
        count = 0
        for profile in queryset:
            decide(profile, approved=True)
            count += 1
        messages.success(request, f'Approved {count} verification(s).')

    @admin.action(description='Reject selected')
    def reject_selected(self, request, queryset):
        from api.photo_verification import decide
        count = 0
        for profile in queryset:
            decide(profile, approved=False)
            count += 1
        messages.success(request, f'Rejected {count} verification(s).')


# ──────────────────────────────────────────────────────────────
# PUSH DEVICES (FCM tokens registered by the app)
# ──────────────────────────────────────────────────────────────
class PushDeviceAdmin(ModelAdmin):
    list_display = ('profile', 'user_email', 'platform_badge', 'short_token', 'updated_at')
    list_filter = ('platform',)
    search_fields = ('profile__username', 'profile__user__email', 'token')
    ordering = ('-updated_at',)
    readonly_fields = ('profile', 'token', 'platform', 'updated_at')
    fields = ('profile', 'platform', 'token', 'updated_at')
    actions = ['send_test_push']
    actions_row = ['send_test_push_row']
    list_per_page = 50

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('profile__user')

    def has_add_permission(self, request):
        # Tokens come from the app only; deleting one is allowed (e.g. a stale phone).
        return False

    def user_email(self, obj):
        return obj.profile.user.email
    user_email.short_description = 'Email'

    @display(description='Platform', label={'android': 'success', 'ios': 'info'})
    def platform_badge(self, obj):
        return obj.platform or 'unknown'

    def short_token(self, obj):
        return f"{obj.token[:18]}…{obj.token[-6:]}" if len(obj.token) > 30 else obj.token
    short_token.short_description = 'Token'

    def _send_test(self, request, tokens):
        from api.push_notifications import send_fcm_push
        result = send_fcm_push(
            tokens,
            title='Constela test notification 🔔',
            body='If you can see this, push notifications are working on this device.',
            data={'type': 'test'},
        )
        if result.get('status') != 'completed':
            messages.error(request, f"Test push not sent: {result.get('message')}")
        elif result.get('failures'):
            messages.warning(
                request,
                f"Delivered to {result['success']} device(s), failed for {result['failures']}. "
                "Failed tokens that FCM reports as dead are removed automatically; see the server log for details.",
            )
        else:
            messages.success(request, f"Test push delivered to {result['success']} device(s).")

    @admin.action(description='Send test push to selected devices')
    def send_test_push(self, request, queryset):
        self._send_test(request, list(queryset.values_list('token', flat=True)))

    @action(description='Send test push', icon='notifications_active')
    def send_test_push_row(self, request, object_id):
        device = PushDevice.objects.get(pk=object_id)
        self._send_test(request, [device.token])
        return redirect(request.headers.get('referer') or reverse('admin:api_pushdevice_changelist'))


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
admin.site.register(MatchAnalysisPurchase, MatchAnalysisPurchaseAdmin)
admin.site.register(PhotoVerification, PhotoVerificationAdmin)
admin.site.register(PushDevice, PushDeviceAdmin)


# Re-register Group with Unfold styling
admin.site.unregister(Group)


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):
    pass


admin.site.index_title = 'Backend Management'
