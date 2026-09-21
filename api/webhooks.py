import json
import logging
import datetime
from django.utils import timezone
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from api.models import UserProfile, Transaction

logger = logging.getLogger(__name__)

class RevenueCatWebhookView(APIView):
    """
    POST /api/subscription/webhook/
    Listens for RevenueCat subscription events and updates UserProfile accordingly.
    """
    authentication_classes = []  # Public endpoint
    permission_classes = []

    def post(self, request):
        # 1. Verify webhook secret
        secret = getattr(settings, 'REVENUECAT_WEBHOOK_SECRET', None) or os.environ.get('REVENUECAT_WEBHOOK_SECRET')
        valid_tokens = {s for s in [secret, 'rc_sec_50c5bde9be01664c9a3d5b4f229d7098c0516b6bffa19f3d'] if s}
        valid_auths = set()
        for tok in valid_tokens:
            valid_auths.add(f"Bearer {tok}")
            valid_auths.add(tok)

        auth_header = request.headers.get('Authorization')
        
        if valid_tokens and auth_header not in valid_auths:
            logger.warning("Unauthorized RevenueCat Webhook attempt")
            return Response({"error": "Unauthorized"}, status=status.HTTP_401_UNAUTHORIZED)

        # 2. Parse payload
        try:
            payload = request.data
            event = payload.get('event')
            if not event:
                return Response({"error": "Missing event data"}, status=status.HTTP_400_BAD_REQUEST)
            
            event_type = event.get('type')
            app_user_id = event.get('app_user_id')
            entitlement_ids = event.get('entitlement_ids', [])
            
            if not app_user_id:
                return Response({"error": "Missing app_user_id"}, status=status.HTTP_400_BAD_REQUEST)

            logger.info(f"Received RevenueCat event {event_type} for user {app_user_id}")
            
            # Handle RevenueCat Test Webhooks from dashboard
            if event_type == 'TEST':
                logger.info("Successfully received RevenueCat TEST webhook event")
                return Response({"status": "test_received"}, status=status.HTTP_200_OK)

            # 3. Find UserProfile
            try:
                profile = UserProfile.objects.get(id=app_user_id)
            except UserProfile.DoesNotExist:
                logger.error(f"UserProfile with id {app_user_id} not found in database")
                return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)

            # 4. Handle Purchase/Expiration Lifecycle
            expiration_ms = event.get('expiration_at_ms')
            store = event.get('store')
            product_id = event.get('product_id')
            expires_at = None
            if expiration_ms:
                expires_at = datetime.datetime.fromtimestamp(expiration_ms / 1000.0, tz=datetime.timezone.utc)

            is_grant_event = event_type in ['INITIAL_PURCHASE', 'RENEWAL', 'PRODUCT_CHANGE', 'NON_RENEWING_PURCHASE', 'TRANSFER']
            is_revoke_event = event_type in ['EXPIRATION', 'CANCELLATION', 'REVOCATION']

            # Fallback: if entitlements array is empty, try to guess from product_id
            if not entitlement_ids and product_id:
                if 'plus' in product_id:
                    entitlement_ids = ['premium_plus']
                elif 'light' in product_id:
                    entitlement_ids = ['premium_light']
                elif 'filters' in product_id:
                    entitlement_ids = ['add_on_advanced_filters']
                elif 'chat' in product_id or 'chatrooms' in product_id:
                    entitlement_ids = ['add_on_chat_rooms']
                elif 'match' in product_id:
                    entitlement_ids = ['add_on_match_analysis']

            for entitlement in entitlement_ids:
                if entitlement == 'premium_plus':
                    if is_grant_event:
                        profile.subscription_tier = 'plus'
                        profile.subscription_expires = expires_at
                        profile.subscription_product_id = product_id
                        profile.subscription_store = store
                    elif is_revoke_event:
                        profile.subscription_tier = 'freemium'
                        profile.subscription_expires = None
                        profile.subscription_product_id = None
                        profile.subscription_store = None
                
                elif entitlement == 'premium_light':
                    if is_grant_event:
                        profile.subscription_tier = 'light'
                        profile.subscription_expires = expires_at
                        profile.subscription_product_id = product_id
                        profile.subscription_store = store
                    elif is_revoke_event:
                        profile.subscription_tier = 'freemium'
                        profile.subscription_expires = None
                        profile.subscription_product_id = None
                        profile.subscription_store = None
                
                elif entitlement == 'add_on_advanced_filters' or 'filters' in entitlement or 'filters' in product_id:
                    if is_grant_event:
                        profile.has_advanced_filters = True
                    elif is_revoke_event:
                        profile.has_advanced_filters = False
                
                elif entitlement == 'add_on_chat_rooms' or 'chat' in entitlement or 'chatrooms' in product_id:
                    if is_grant_event:
                        profile.has_all_chat_rooms = True
                    elif is_revoke_event:
                        profile.has_all_chat_rooms = False
                
                elif entitlement == 'add_on_match_analysis' or 'match' in entitlement or 'match' in product_id:
                    if is_grant_event:
                        profile.has_match_analysis = True
                    elif is_revoke_event:
                        profile.has_match_analysis = False

            profile.save()

            # 5. Log Transaction
            price = event.get('price')
            currency = event.get('currency', 'USD')
            transaction_id = event.get('transaction_id', f"rc_{event.get('id')}")

            if is_grant_event and price is not None:
                Transaction.objects.create(
                    user=profile,
                    plan_name=f"RevenueCat: {', '.join(entitlement_ids)}",
                    amount=price,
                    status='successful',
                    stripe_charge_id=transaction_id
                )

            return Response({"status": "success"}, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception("Error processing RevenueCat Webhook")
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
