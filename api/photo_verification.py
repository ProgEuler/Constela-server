"""Manual photo verification.

The user takes one live photo in the app; an admin compares it with the
profile pictures and approves or rejects it. Every decision path (Django admin
list/detail, the dashboard API) goes through `decide()` so side effects match.
"""
import logging

from django.utils import timezone

logger = logging.getLogger(__name__)


def decide(profile, approved, note=''):
    """Apply an admin decision to a profile's photo verification."""
    note = (note or '').strip()[:255]
    if approved:
        profile.face_verification_status = 'approved'
        profile.is_verified = True
        profile.must_verify_face = False
        profile.face_verified_at = timezone.now()
        profile.face_verification_note = ''
    else:
        profile.face_verification_status = 'rejected'
        profile.is_verified = False
        profile.face_verified_at = None
        profile.face_verification_note = note
    profile.save(update_fields=[
        'face_verification_status', 'is_verified', 'must_verify_face',
        'face_verified_at', 'face_verification_note',
    ])
    profile.photos.all().update(is_verified=approved)
    _notify(profile, approved, note)
    return profile


def _notify(profile, approved, note):
    try:
        from api.push_notifications import send_push_notification_to_user
        if approved:
            title, body = 'Photo verified ✅', 'Your photo verification was approved.'
        else:
            title = 'Photo verification declined'
            body = note or 'Your verification photo could not be approved. Please take a new one.'
        send_push_notification_to_user(profile.user, title, body, {'type': 'photo_verification',
                                                                   'status': profile.face_verification_status})
    except Exception:
        logger.exception('Could not send photo verification notification')


def pending_badge(request):
    """Sidebar badge in the admin: number of photos waiting for review."""
    from api.models import UserProfile
    count = UserProfile.objects.filter(face_verification_status='pending').exclude(face_selfie='').count()
    return count or None
