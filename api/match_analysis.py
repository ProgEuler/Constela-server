"""Perfect Match Analysis as a one-time purchase.

Each store purchase of the analysis product becomes one MatchAnalysisPurchase.
The top 5 is computed once, when the purchase is recorded, and frozen. Buying
again later produces a new snapshot. Only profile IDs and scores are stored;
names and photos are loaded fresh on read so signed media URLs never go stale.
"""
from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from api.matching_engine import calculate_compatibility
from api.models import Block, Friendship, Match, MatchAnalysisPurchase, UserProfile

TOP_N = 5


def compute_top_matches(me):
    """Rank every eligible candidate for `me` and return the top 5 as [{id, compatibility_score}]."""
    blocked_by_me = Block.objects.filter(blocker=me).values_list('blocked_user', flat=True)
    blocked_me = Block.objects.filter(blocked_user=me).values_list('blocker', flat=True)
    friends_sent = Friendship.objects.filter(sender=me).values_list('receiver', flat=True)
    friends_received = Friendship.objects.filter(receiver=me).values_list('sender', flat=True)
    swiped = Match.objects.filter(user1=me).values_list('user2', flat=True)

    exclude = set(blocked_by_me) | set(blocked_me) | set(friends_sent) | set(friends_received) | set(swiped)
    exclude.add(me.id)

    candidates = UserProfile.objects.filter(
        is_deactivated=False,
        is_verified=True,
        user__role='member',
        user__is_staff=False,
        user__is_superuser=False,
    ).exclude(id__in=exclude)

    gender = (me.gender or '').lower()
    if gender == 'man':
        candidates = candidates.filter(gender__iexact='woman')
    elif gender == 'woman':
        candidates = candidates.filter(gender__iexact='man')

    scored = [
        {'id': str(candidate.id), 'compatibility_score': calculate_compatibility(me, candidate)}
        for candidate in candidates
    ]
    scored.sort(key=lambda item: item['compatibility_score'], reverse=True)
    return scored[:TOP_N]


def generate_snapshot(analysis):
    analysis.results = compute_top_matches(analysis.profile)
    analysis.generated_at = timezone.now()
    analysis.save(update_fields=['results', 'generated_at'])
    return analysis


def import_store_purchases(profile, subscriber):
    """Record every analysis purchase found in the RevenueCat subscriber payload.

    Idempotent: keyed by the store transaction, so webhook retries and repeated
    syncs never grant twice. New purchases get their top 5 computed right away.
    Returns the number of newly recorded purchases.
    """
    non_subscriptions = subscriber.get('non_subscriptions') or {}
    if not isinstance(non_subscriptions, dict):
        return 0

    created_count = 0
    for product_id in settings.MATCH_ANALYSIS_PRODUCT_IDS:
        purchases = non_subscriptions.get(product_id) or []
        if not isinstance(purchases, list):
            continue
        for purchase in purchases:
            if not isinstance(purchase, dict):
                continue
            if purchase.get('is_sandbox') is not False and not settings.REVENUECAT_ALLOW_SANDBOX:
                continue
            if purchase.get('refunded_at'):
                continue
            txid = purchase.get('store_transaction_id') or purchase.get('id')
            if not txid:
                continue
            purchased_at = parse_datetime(str(purchase.get('purchase_date') or '')) or timezone.now()
            analysis, created = MatchAnalysisPurchase.objects.get_or_create(
                transaction_key=f"{purchase.get('store') or 'store'}:{txid}"[:255],
                defaults={
                    'profile': profile,
                    'product_id': product_id[:100],
                    'store': str(purchase.get('store') or '')[:50],
                    'purchased_at': purchased_at,
                },
            )
            if created:
                generate_snapshot(analysis)
                created_count += 1
    return created_count


def latest_analysis(profile):
    """Most recent analysis with results, granting one final snapshot to legacy add-on holders."""
    analysis = (
        MatchAnalysisPurchase.objects.filter(profile=profile, generated_at__isnull=False)
        .order_by('-generated_at')
        .first()
    )
    if analysis is not None:
        return analysis

    # Accounts flagged under the old "add-on" model (or by an admin) but with no
    # recorded purchase get one snapshot, then must buy again like everyone else.
    if profile.has_match_analysis:
        analysis, created = MatchAnalysisPurchase.objects.get_or_create(
            transaction_key=f'legacy:{profile.id}',
            defaults={'profile': profile, 'product_id': 'legacy', 'store': 'LEGACY', 'purchased_at': timezone.now()},
        )
        if created or analysis.generated_at is None:
            generate_snapshot(analysis)
        return analysis
    return None


def serialize_analysis(analysis, request, photo_for):
    """Build the API payload, loading each saved profile fresh. Removed/blocked profiles are skipped."""
    entries = analysis.results or []
    ids = [entry.get('id') for entry in entries if entry.get('id')]
    profiles = {
        str(p.id): p
        for p in UserProfile.objects.filter(id__in=ids, is_deactivated=False).prefetch_related('photos')
    }
    me = analysis.profile
    hidden = set(map(str, Block.objects.filter(blocker=me).values_list('blocked_user', flat=True)))
    hidden |= set(map(str, Block.objects.filter(blocked_user=me).values_list('blocker', flat=True)))

    results = []
    for entry in entries:
        candidate = profiles.get(str(entry.get('id')))
        if candidate is None or str(candidate.id) in hidden:
            continue
        results.append({
            'id': candidate.id,
            'name': candidate.display_name,
            'age': candidate.age,
            'gender': candidate.gender,
            'city': candidate.city,
            'country': candidate.country,
            'tags': (candidate.qualities or []) + (candidate.interests or []),
            'photo': photo_for(candidate, request),
            'is_verified': candidate.is_verified,
            'compatibility_score': entry.get('compatibility_score'),
        })
    return {
        'results': results,
        'generated_at': analysis.generated_at.isoformat() if analysis.generated_at else None,
        'purchased_at': analysis.purchased_at.isoformat() if analysis.purchased_at else None,
    }
