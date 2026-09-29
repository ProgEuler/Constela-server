import hashlib
import hmac
import logging
import time
from decimal import Decimal
from django.conf import settings
from django.db import transaction
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView
from api.models import RevenueCatEvent, Transaction, UserProfile
from api.subscriptions import profile_ids, sync_subscription

logger = logging.getLogger(__name__)


class RevenueCatWebhookView(APIView):
    authentication_classes = []
    permission_classes = []
    throttle_classes = []

    def post(self, request):
        secret = (settings.REVENUECAT_WEBHOOK_SECRET or '').strip()
        if not secret:
            return Response({'error': 'Webhook is not configured'}, status=503)
        header = (request.headers.get('Authorization') or '').strip()
        token = header[7:].strip() if header.lower().startswith('bearer ') else header
        expected = secret[7:].strip() if secret.lower().startswith('bearer ') else secret
        if not hmac.compare_digest(token.encode(), expected.encode()):
            return Response({'error': 'Unauthorized'}, status=401)
        if settings.REVENUECAT_SIGNING_SECRET:
            try:
                parts = dict(part.strip().split('=', 1) for part in request.headers.get('X-RevenueCat-Webhook-Signature', '').split(','))
                digest = hmac.new(settings.REVENUECAT_SIGNING_SECRET.encode(), parts['t'].encode() + b'.' + request.body, hashlib.sha256).hexdigest()
                if abs(time.time() - int(parts['t'])) > 300 or not hmac.compare_digest(digest, parts['v1']):
                    raise ValueError()
            except (ValueError, KeyError):
                return Response({'error': 'Invalid signature'}, status=401)
        event = request.data.get('event') if isinstance(request.data, dict) else None
        if not isinstance(event, dict) or not isinstance(event.get('type'), str):
            return Response({'error': 'Invalid event'}, status=400)
        event_type = event['type']
        if event_type == 'TEST':
            return Response({'status': 'test_received'})
        event_id = event.get('id')
        if not isinstance(event_id, str) or not 0 < len(event_id) <= 255 or len(event_type) > 100:
            return Response({'error': 'Invalid event ID or type'}, status=400)
        if settings.REVENUECAT_APP_IDS and event.get('app_id') not in settings.REVENUECAT_APP_IDS:
            return Response({'error': 'Unexpected app'}, status=403)
        if event.get('environment') == 'SANDBOX' and not settings.REVENUECAT_ALLOW_SANDBOX:
            return Response({'status': 'sandbox_ignored'})
        candidates = [] if event_type == 'TRANSFER' else [event.get('app_user_id'), event.get('original_app_user_id')]
        for key in (('transferred_from', 'transferred_to') if event_type == 'TRANSFER' else ('aliases',)):
            values = event.get(key) or []
            if not isinstance(values, list) or len(values) > 100:
                return Response({'error': 'Invalid customer IDs'}, status=400)
            candidates.extend(values)
        ids = profile_ids(candidates)
        if (event_type != 'TRANSFER' and len(ids) > 1) or len(ids) > 4:
            logger.error('RevenueCat event %s has ambiguous customer ownership', event_id)
            return Response({'error': 'Customer ownership requires review'}, status=503)
        if not ids:
            logger.warning('RevenueCat event %s has no matching immutable profile ID', event_id)
            return Response({'error': 'Customer not found; retry delivery'}, status=503)
        try:
            with transaction.atomic():
                _, created = RevenueCatEvent.objects.get_or_create(id=event_id, defaults={'event_type': event_type})
                if not created:
                    return Response({'status': 'duplicate'})
                profiles = [sync_subscription(profile_id) for profile_id in ids]
                if event_type in {'INITIAL_PURCHASE', 'RENEWAL', 'NON_RENEWING_PURCHASE'} and event.get('price') is not None:
                    amount = Decimal(str(event['price']))
                    if not amount.is_finite() or amount < 0 or amount >= Decimal('100000000'):
                        raise ValueError('Invalid transaction amount')
                    owner = next((p for p in profiles if str(p.id) == event.get('app_user_id')), None)
                    if owner is None and len(profiles) == 1:
                        owner = profiles[0]
                    if owner:
                        txid = str(event.get('transaction_id') or event_id)
                        key = hashlib.sha256(f"{event.get('app_id')}:{event.get('environment')}:{event.get('store')}:{txid}".encode()).hexdigest()
                        legacy = Transaction.objects.filter(user=owner, stripe_charge_id=txid, revenuecat_charge_key__isnull=True, plan_name__startswith='RevenueCat:').order_by('created_at', 'id').first()
                        if legacy and not Transaction.objects.filter(revenuecat_charge_key=key).exists():
                            legacy.revenuecat_charge_key = key
                            legacy.payment_method = str(event.get('store') or 'RevenueCat')[:100]
                            legacy.save(update_fields=['revenuecat_charge_key', 'payment_method'])
                        Transaction.objects.get_or_create(revenuecat_charge_key=key, defaults={
                            'user': owner, 'plan_name': str(event.get('product_id') or 'RevenueCat purchase')[:100],
                            'amount': amount, 'status': 'successful', 'stripe_charge_id': txid[:255],
                            'payment_method': str(event.get('store') or 'RevenueCat')[:100],
                        })
                if event_type == 'CANCELLATION' and event.get('cancel_reason') == 'CUSTOMER_SUPPORT' and event.get('transaction_id'):
                    Transaction.objects.filter(user_id__in=ids, stripe_charge_id=event['transaction_id']).update(status='refunded')
                if event_type == 'REFUND_REVERSED' and event.get('transaction_id'):
                    Transaction.objects.filter(user_id__in=ids, stripe_charge_id=event['transaction_id']).update(status='successful')
            return Response({'status': 'success'})
        except Exception:
            logger.exception('RevenueCat event %s failed; transaction rolled back', event_id)
            return Response({'error': 'Subscription sync unavailable; retry delivery'}, status=503)


class SubscriptionSyncThrottle(UserRateThrottle):
    rate = '100/min'


class SubscriptionSyncView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [SubscriptionSyncThrottle]

    def post(self, request):
        from api.serializers import UserProfileSerializer
        try:
            profile = UserProfile.objects.get(user=request.user)
            profile = sync_subscription(profile.id)
        except UserProfile.DoesNotExist:
            return Response({'error': 'Profile not found'}, status=404)
        except Exception:
            logger.exception('Authenticated subscription sync failed')
            return Response({'error': 'Purchase verification is temporarily unavailable. Your purchase is not lost.'}, status=503)
        return Response(UserProfileSerializer(profile, context={'request': request}).data)
