from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import get_user_model

class SafeTokenRefreshView(TokenRefreshView):
    """Override to return 401 instead of 500 when user no longer exists."""
    def post(self, request, *args, **kwargs):
        try:
            return super().post(request, *args, **kwargs)
        except get_user_model().DoesNotExist:
            raise InvalidToken({'detail': 'User not found. Please log in again.'})

from api.serializers import ChahiraTokenObtainPairView
from api.views import (
    UserRegisterView, OTPVerifyView, ResendOTPView, ForgotPasswordView, ResetPasswordView, CheckUsernameView, FaceVerifyView, FaceDetectView,
    UserProfileViewSet, UserPhotoViewSet,
    PerfectMatchView, MatchAnalysisView, MatchActionView, LikesReceivedView, LikesSentView, MutualMatchesView,
    SaveMatchView, UnsaveMatchView, SavedMatchesListView, UnmatchUserView, UnfriendUserView,
    FriendshipViewSet, ChatRoomViewSet, ChatRoomMessageCreateView,
    DirectMessageViewSet, BlockViewSet, DeactivateAccountView,
    ChangePasswordView, RequestEmailChangeView, VerifyEmailChangeView, TransactionHistoryView, UpgradeSubscriptionView, CreateReportView, CreateSupportTicketView, MySupportTicketsView,
    AdminTicketViewSet, AdminReportViewSet, AdminVerificationViewSet,
    AdminUserListView, AdminDashboardStatsView, AdminDashboardActivityView, AdminTransactionListView,
    AdminUserDeleteView, AdminUserBlockView,
    AdminUserRoleUpdateView, AdminUserGiftSubscriptionView, AdminMatchesDashboardView,
    AdminSubscriptionsDashboardView, AdminPaymentsDashboardView, AdminChatRoomViewSet,
    AdminAccountsViewSet, ChatImageUploadView, AdminActionLogViewSet, AdminModerationStatsViewSet
)
from api.webhooks import RevenueCatWebhookView

router = DefaultRouter()
router.register(r'profiles', UserProfileViewSet, basename='profile')
router.register(r'photos', UserPhotoViewSet, basename='photo')
router.register(r'friends', FriendshipViewSet, basename='friendship')
router.register(r'chat/rooms', ChatRoomViewSet, basename='chatroom')
router.register(r'chat/direct', DirectMessageViewSet, basename='directmessage')
router.register(r'blocks', BlockViewSet, basename='block')

admin_router = DefaultRouter()
admin_router.register(r'tickets', AdminTicketViewSet, basename='admin-ticket')
admin_router.register(r'reports', AdminReportViewSet, basename='admin-report')
admin_router.register(r'chat/rooms', AdminChatRoomViewSet, basename='admin-chatroom')
admin_router.register(r'accounts', AdminAccountsViewSet, basename='admin-accounts')
admin_router.register(r'logs', AdminActionLogViewSet, basename='admin-logs')

urlpatterns = [
    # Auth Endpoints
    path('auth/signup/', UserRegisterView.as_view(), name='auth-signup'),
    path('auth/verify-otp/', OTPVerifyView.as_view(), name='auth-verify-otp'),
    path('auth/resend-otp/', ResendOTPView.as_view(), name='auth-resend-otp'),
    path('auth/login/', ChahiraTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/token/refresh/', SafeTokenRefreshView.as_view(), name='token_refresh'),
    path('auth/check-username/', CheckUsernameView.as_view(), name='check-username'),
    path('auth/face-verify/', FaceVerifyView.as_view(), name='face-verify'),
    path('auth/face-detect/', FaceDetectView.as_view(), name='face-detect'),
    path('auth/forgot-password/', ForgotPasswordView.as_view(), name='auth-forgot-password'),
    path('auth/reset-password/', ResetPasswordView.as_view(), name='auth-reset-password'),
    
    # Profile Endpoints
    path('profile/me/', UserProfileViewSet.as_view({'get': 'me', 'put': 'me', 'patch': 'me'}), name='profile-me'),
    path('', include(router.urls)),
    
    # Matching Endpoints
    path('matching/perfect-match/', PerfectMatchView.as_view(), name='perfect-match'),
    path('matching/analysis/', MatchAnalysisView.as_view(), name='match-analysis'),
    path('matching/matches/', MutualMatchesView.as_view(), name='mutual-matches'),
    path('matching/saved/', SavedMatchesListView.as_view(), name='saved-matches-list'),
    path('matching/<uuid:target_profile_id>/action/', MatchActionView.as_view(), name='match-action'),
    path('matching/<uuid:target_profile_id>/save/', SaveMatchView.as_view(), name='save-match'),
    path('matching/<uuid:target_profile_id>/unsave/', UnsaveMatchView.as_view(), name='unsave-match'),
    path('matching/<uuid:target_profile_id>/unmatch/', UnmatchUserView.as_view(), name='unmatch'),
    path('matching/likes-received/', LikesReceivedView.as_view(), name='likes-received'),
    path('matching/likes-sent/', LikesSentView.as_view(), name='likes-sent'),
    
    path('friends/<uuid:target_profile_id>/unfriend/', UnfriendUserView.as_view(), name='unfriend'),
    
    # Community Chat Room Sending
    path('chat/rooms/<uuid:room_id>/send/', ChatRoomMessageCreateView.as_view(), name='chatroom-send'),
    path('chat/upload-image/', ChatImageUploadView.as_view(), name='chat-image-upload'),
    
    # Safety & Settings
    path('reports/create/', CreateReportView.as_view(), name='report-create'),
    path('support/create/', CreateSupportTicketView.as_view(), name='support-create'),
    path('support/my-tickets/', MySupportTicketsView.as_view(), name='support-list'),
    path('settings/deactivate/', DeactivateAccountView.as_view(), name='settings-deactivate'),
    path('settings/change-password/', ChangePasswordView.as_view(), name='settings-change-password'),
    path('settings/request-email-change/', RequestEmailChangeView.as_view(), name='settings-request-email-change'),
    path('settings/verify-email-change/', VerifyEmailChangeView.as_view(), name='settings-verify-email-change'),
    path('subscription/history/', TransactionHistoryView.as_view(), name='subscription-history'),
    path('subscription/upgrade/', UpgradeSubscriptionView.as_view(), name='subscription-upgrade'),
    path('subscription/webhook/', RevenueCatWebhookView.as_view(), name='subscription-webhook'),
    
    # Admin Endpoints
    path('admin/', include(admin_router.urls)),
    path('admin/dashboard/stats/', AdminDashboardStatsView.as_view(), name='admin-dashboard-stats'),
    path('admin/dashboard/activity/', AdminDashboardActivityView.as_view(), name='admin-dashboard-activity'),
    path('admin/transactions/', AdminTransactionListView.as_view(), name='admin-transactions-list'),
    path('admin/matches/', AdminMatchesDashboardView.as_view(), name='admin-matches-dashboard'),
    path('admin/subscriptions/', AdminSubscriptionsDashboardView.as_view(), name='admin-subscriptions-dashboard'),
    path('admin/payments/', AdminPaymentsDashboardView.as_view(), name='admin-payments-dashboard'),
    path('admin/moderation/stats/', AdminModerationStatsViewSet.as_view(), name='admin-moderation-stats'),
    path('admin/users/<uuid:profile_id>/role/', AdminUserRoleUpdateView.as_view(), name='admin-user-role-update'),
    path('admin/users/<uuid:profile_id>/gift/', AdminUserGiftSubscriptionView.as_view(), name='admin-user-gift-subscription'),
    path('admin/users/<uuid:profile_id>/block/', AdminUserBlockView.as_view(), name='admin-user-block'),
    path('admin/users/<uuid:profile_id>/', AdminUserDeleteView.as_view(), name='admin-user-delete'),
    path('admin/users/', AdminUserListView.as_view(), name='admin-user-list'),
    path('admin/verifications/', AdminVerificationViewSet.as_view(), name='admin-verification-list'),
    path('admin/verifications/<uuid:profile_id>/action/', AdminVerificationViewSet.as_view(), name='admin-verification-action'),
]
