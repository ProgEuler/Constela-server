"""Server-verified entitlement snapshots. Never accept entitlement claims from clients."""
from datetime import datetime, time, timedelta
import uuid
from urllib.parse import quote

import requests
from django.conf import settings
from django.db import transaction
from django.db.models import OuterRef, Q, Subquery
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from api.models import ChatRoom, ChatRoomMessage, DirectMessage, Match, SubscriptionUsage, Transaction, UserProfile

ENTITLEMENTS = {
    'premium_light', 'premium_plus', 'add_on_match_analysis',
}
DEFAULT_TIER_CONFIGS = {
    'freemium': {
        'name': 'Freemium',
        'daily_likes_limit': 20,
        'daily_personal_messages_limit': 5,
        'daily_community_messages_limit': 10,
        'community_room_limit': None,
        'can_see_likes': False,
        'can_undo_swipes': False,
    },
    'light': {
        'name': 'Premium Light',
        'daily_likes_limit': 50,
        'daily_personal_messages_limit': None,
        'daily_community_messages_limit': None,
        'community_room_limit': None,
        'can_see_likes': True,
        'can_undo_swipes': True,
    },
    'plus': {
        'name': 'Premium Plus',
        'daily_likes_limit': None,
        'daily_personal_messages_limit': None,
        'daily_community_messages_limit': None,
        'community_room_limit': None,
        'can_see_likes': True,
        'can_undo_swipes': True,
    },
}


def get_all_tier_configs():
    from django.core.cache import cache
    cached = cache.get('tier_config_all')
    if cached is not None:
        return cached

    configs = {}
    try:
        from api.models import SubscriptionTierConfig
        for row in SubscriptionTierConfig.objects.all():
            configs[row.tier] = {
                'name': row.name,
                'daily_likes_limit': row.daily_likes_limit,
                'daily_personal_messages_limit': row.daily_personal_messages_limit,
                'daily_community_messages_limit': row.daily_community_messages_limit,
                'community_room_limit': row.community_room_limit,
                'can_see_likes': row.can_see_likes,
                'can_undo_swipes': row.can_undo_swipes,
            }
    except Exception:
        pass

    merged = {}
    for tier, defaults in DEFAULT_TIER_CONFIGS.items():
        merged[tier] = {**defaults, **configs.get(tier, {})}

    try:
        cache.set('tier_config_all', merged, timeout=300)
    except Exception:
        pass

    return merged


def get_tier_config(tier):
    configs = get_all_tier_configs()
    return configs.get(tier, DEFAULT_TIER_CONFIGS.get(tier, DEFAULT_TIER_CONFIGS['freemium']))


def get_usage_limit(kind, tier):
    config = get_tier_config(tier)
    if kind == 'likes':
        return config.get('daily_likes_limit')
    if kind == 'personal_messages':
        return config.get('daily_personal_messages_limit')
    if kind == 'community_messages':
        return config.get('daily_community_messages_limit')
    return None


def payment_history():
    """Hide legacy duplicate receipts without deleting financial records."""
    first = Transaction.objects.filter(user_id=OuterRef('user_id'), stripe_charge_id=OuterRef('stripe_charge_id')).order_by('created_at', 'id').values('id')[:1]
    return Transaction.objects.filter(Q(stripe_charge_id__isnull=True) | Q(stripe_charge_id='') | Q(id=Subquery(first)))


def usage_count(profile, kind):
    today = timezone.localdate()
    period = today
    usage = SubscriptionUsage.objects.filter(profile=profile, kind=kind, period=period).first()
    if usage:
        return usage.count
    if kind == 'likes':
        return Match.objects.filter(user1=profile, status__in=['liked', 'superliked', 'matched'], created_at__date=today).count()
    if kind == 'personal_messages':
        return DirectMessage.objects.filter(sender=profile, timestamp__date=today).count()
    if kind == 'community_messages':
        return ChatRoomMessage.objects.filter(sender=profile, timestamp__date=today).count()
    return 0


def consume_usage(profile, kind):
    """Caller holds the profile row lock inside the transaction creating the like/message."""
    tier = effective_access(profile)['subscription_tier']
    limit = get_usage_limit(kind, tier)
    count = usage_count(profile, kind)
    if limit is not None and count >= limit:
        return False
    today = timezone.localdate()
    usage, _ = SubscriptionUsage.objects.get_or_create(
        profile=profile, kind=kind, period=today, defaults={'count': count}
    )
    usage.count += 1
    usage.save(update_fields=['count'])
    return True


def quota_snapshot(profile, kind):
    tier = effective_access(profile)['subscription_tier']
    limit = get_usage_limit(kind, tier)
    used = usage_count(profile, kind)
    today = timezone.localdate()
    reset_date = today + timedelta(days=1)
    resets_at = timezone.make_aware(
        datetime.combine(reset_date, time.min), timezone.get_current_timezone()
    )
    return {
        'limit': limit,
        'used': used,
        'remaining': None if limit is None else max(limit - used, 0),
        'resets_at': resets_at.isoformat(),
    }


def access_snapshot(profile):
    access = effective_access(profile)
    tier = access['subscription_tier']
    config = get_tier_config(tier)
    room_limit = config.get('community_room_limit')
    return {
        'tier': tier,
        'can_access_community': room_limit is None or room_limit > 0,
        'community_room_limit': room_limit,
        'can_see_likes': config.get('can_see_likes', tier != 'freemium'),
        'can_undo_swipes': config.get('can_undo_swipes', tier != 'freemium'),
        'has_match_analysis': access['has_match_analysis'],
        'quotas': {
            'likes': quota_snapshot(profile, 'likes'),
            'personal_messages': quota_snapshot(profile, 'personal_messages'),
            'community_messages': quota_snapshot(profile, 'community_messages'),
        },
        'tier_rules': {
            key: {
                'name': value.get('name'),
                'daily_likes_limit': value.get('daily_likes_limit'),
                'daily_personal_messages_limit': value.get('daily_personal_messages_limit'),
                'daily_community_messages_limit': value.get('daily_community_messages_limit'),
                'community_room_limit': value.get('community_room_limit'),
                'can_see_likes': value.get('can_see_likes'),
                'can_undo_swipes': value.get('can_undo_swipes'),
            }
            for key, value in get_all_tier_configs().items()
        },
    }


def active(grant):
    if not isinstance(grant, dict):
        return False
    expiry = grant.get('expires_date')
    if expiry is None:
        return grant.get('lifetime') is True
    try:
        date = parse_datetime(expiry)
        return date is not None and timezone.is_aware(date) and date > timezone.now()
    except (TypeError, ValueError):
        return False


def effective_access(profile):
    grants = profile.revenuecat_entitlements
    # Existing grants remain compatible, but expired subscriptions never authorize access.
    if grants is None:
        tier = profile.subscription_tier
        if profile.subscription_store == 'ADMIN':
            tier = 'freemium'
        if profile.subscription_store == 'TEST_STORE' and not settings.REVENUECAT_ALLOW_SANDBOX:
            tier = 'freemium'
        if profile.subscription_expires and profile.subscription_expires <= timezone.now():
            tier = 'freemium'
        result = dict(subscription_tier=tier, subscription_expires=profile.subscription_expires,
                      subscription_product_id=profile.subscription_product_id,
                      subscription_store=profile.subscription_store,
                      has_match_analysis=profile.has_match_analysis)
    else:
        live = {key: value for key, value in grants.items() if active(value)}
        tier = 'plus' if 'premium_plus' in live else 'light' if 'premium_light' in live else 'freemium'
        grant = live.get('premium_' + tier, {})
        result = dict(subscription_tier=tier,
                      subscription_expires=parse_datetime(grant['expires_date']) if grant.get('expires_date') else None,
                      subscription_product_id=grant.get('product_identifier'), subscription_store=grant.get('store'),
                      has_match_analysis='add_on_match_analysis' in live)
    gift = profile.subscription_gift
    if active(gift) and {'freemium': 0, 'light': 1, 'plus': 2}[gift['tier']] > {'freemium': 0, 'light': 1, 'plus': 2}[result['subscription_tier']]:
        result.update(subscription_tier=gift['tier'], subscription_expires=parse_datetime(gift['expires_date']),
                      subscription_product_id=None, subscription_store='ADMIN')
    if result['subscription_tier'] == 'freemium':
        result.update(subscription_expires=None, subscription_product_id=None, subscription_store=None)
    return result


def accessible_rooms(profile):
    access = effective_access(profile)
    tier = access['subscription_tier']
    config = get_tier_config(tier)
    room_limit = config.get('community_room_limit')
    rooms = ChatRoom.objects.order_by('created_at', 'id')
    if room_limit is None:
        return rooms
    if room_limit > 0:
        return rooms.filter(id__in=rooms.values('id')[:room_limit])
    return rooms.none()


def profile_ids(candidates):
    # Only immutable IDs assigned by our app; never resolve untrusted aliases as emails/usernames.
    ids = set()
    for candidate in candidates:
        try:
            ids.add(uuid.UUID(str(candidate)))
        except (ValueError, TypeError, AttributeError):
            continue
    return list(UserProfile.objects.filter(id__in=ids).order_by('id').values_list('id', flat=True))


def subscriber_snapshot(profile_id):
    key = settings.REVENUECAT_API_KEY
    if not key:
        raise RuntimeError('RevenueCat server API key is not configured')
    response = requests.get(
        'https://api.revenuecat.com/v1/subscribers/' + quote(str(profile_id), safe=''),
        headers={'Authorization': 'Bearer ' + key, 'Accept': 'application/json'}, timeout=(3, 8),
    )
    response.raise_for_status()
    subscriber = response.json()['subscriber']
    original_profiles = profile_ids([subscriber.get('original_app_user_id')])
    if original_profiles and str(original_profiles[0]) != str(profile_id):
        raise ValueError('RevenueCat customer is owned by another known account; resolve aliases before granting access')
    entitlements = subscriber['entitlements']
    if not isinstance(entitlements, dict):
        raise ValueError('Invalid RevenueCat entitlement response')
    grants = {}
    for name, entitlement in entitlements.items():
        if name not in ENTITLEMENTS:
            continue
        product = entitlement['product_identifier']
        purchase = subscriber.get('subscriptions', {}).get(product)
        if purchase is None:
            purchases = subscriber.get('non_subscriptions', {}).get(product, [])
            purchase = purchases[-1] if purchases else {}
        if purchase.get('is_sandbox') is not False and not settings.REVENUECAT_ALLOW_SANDBOX:
            continue
        if purchase.get('refunded_at'):
            continue
        expiry = entitlement['expires_date']
        grace = purchase.get('grace_period_expires_date')
        if grace and (not expiry or parse_datetime(grace) > parse_datetime(expiry)):
            expiry = grace
        grants[name] = dict(product_identifier=product, expires_date=expiry,
                            lifetime=expiry is None, store=purchase.get('store'))
    return grants


@transaction.atomic
def sync_subscription(profile_id):
    # Serialize refreshes per customer so an older in-flight response cannot win.
    profile = UserProfile.objects.select_for_update().get(id=profile_id)
    grants = subscriber_snapshot(profile.id)
    if profile.revenuecat_entitlements is None and not profile.subscription_store and profile.subscription_tier != 'freemium' and profile.subscription_expires:
        profile.subscription_gift = {'tier': profile.subscription_tier, 'expires_date': profile.subscription_expires.isoformat()}
    profile.revenuecat_entitlements = grants
    profile.subscription_synced_at = timezone.now()
    for key, value in effective_access(profile).items():
        setattr(profile, key, value)
    profile.save(update_fields=['revenuecat_entitlements', 'subscription_synced_at', 'subscription_gift',
                               'subscription_tier', 'subscription_expires', 'subscription_product_id',
                               'subscription_store', 'has_match_analysis'])
    return profile


@transaction.atomic
def gift_subscription(profile_id, tier, duration_months):
    profile = UserProfile.objects.select_for_update().get(id=profile_id)
    profile.subscription_gift = {} if tier == 'freemium' else {
        'tier': tier, 'expires_date': (timezone.now() + timezone.timedelta(days=30 * duration_months)).isoformat(),
    }
    # A revoked gift must not revoke a store purchase. Clear only legacy manual grants.
    if profile.revenuecat_entitlements is None and not profile.subscription_store:
        profile.subscription_tier = 'freemium'
        profile.subscription_expires = None
    for key, value in effective_access(profile).items():
        setattr(profile, key, value)
    profile.save(update_fields=['subscription_gift', 'subscription_tier', 'subscription_expires',
                               'subscription_product_id', 'subscription_store'])
    return profile
