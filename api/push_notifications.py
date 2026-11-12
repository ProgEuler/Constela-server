import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import List, Union, Dict, Any
from django.conf import settings
from django.db import close_old_connections

import firebase_admin
from firebase_admin import credentials, messaging

logger = logging.getLogger(__name__)
ANDROID_CHANNEL_ID = 'constela_default'
_push_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="fcm")

# FCM errors that mean the token will never work again (app uninstalled, token rotated, wrong project).
_DEAD_TOKEN_ERRORS = (messaging.UnregisteredError, messaging.SenderIdMismatchError)

# Initialize Firebase Admin SDK
# Check if already initialized to prevent errors on hot-reloads
if not firebase_admin._apps:
    env_creds = os.environ.get("FIREBASE_CREDENTIALS_JSON")
    cred_path = os.path.join(settings.BASE_DIR, 'firebase-service-account.json')

    if env_creds:
        import json
        try:
            cred_dict = json.loads(env_creds)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
            logger.info("✅ Firebase Admin SDK initialized from Environment Variable.")
        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse FIREBASE_CREDENTIALS_JSON: {e}. env_creds was: {repr(env_creds)}")
    elif os.path.exists(cred_path):
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
        logger.info("✅ Firebase Admin SDK initialized from local file.")
    else:
        logger.warning(f"⚠️ Firebase credential not found in ENV or at {cred_path}")


def send_fcm_push(
    push_tokens: Union[str, List[str]],
    title: str,
    body: str,
    data: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """
    Sends Firebase Cloud Messaging (FCM) push notifications and forgets tokens FCM reports as dead.
    """
    if isinstance(push_tokens, str):
        push_tokens = [push_tokens]

    valid_tokens = [t for t in push_tokens if t]

    if not valid_tokens:
        logger.warning("⚠️ No valid push tokens provided.")
        return {"status": "error", "message": "No valid push tokens provided."}

    if not firebase_admin._apps:
        logger.error("❌ Firebase Admin SDK not initialized.")
        return {"status": "error", "message": "Firebase Admin SDK not initialized."}

    # FCM data payloads only accept string values.
    payload = {str(k): str(v) for k, v in (data or {}).items() if v is not None}
    messages = [
        messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data=payload or None,
            # Channel created by the app (plugins/withAndroidNotifications.js): high importance → banners.
            android=messaging.AndroidConfig(
                priority='high',
                notification=messaging.AndroidNotification(
                    channel_id=ANDROID_CHANNEL_ID, color='#DE4177', sound='default',
                ),
            ),
            apns=messaging.APNSConfig(payload=messaging.APNSPayload(aps=messaging.Aps(sound='default'))),
            token=token,
        )
        for token in valid_tokens
    ]

    try:
        batch = messaging.send_each(messages)
    except Exception as e:
        logger.error(f"❌ Failed to send FCM notifications: {e}")
        return {"status": "error", "message": str(e)}

    dead_tokens = []
    for token, response in zip(valid_tokens, batch.responses):
        if response.success:
            continue
        logger.error(f"❌ Failed to send FCM notification: {response.exception}")
        if isinstance(response.exception, _DEAD_TOKEN_ERRORS):
            dead_tokens.append(token)

    if dead_tokens:
        from api.models import PushDevice
        PushDevice.objects.filter(token__in=dead_tokens).delete()
        logger.info(f"Removed {len(dead_tokens)} dead push token(s).")

    logger.info(f"✅ FCM push notification sent. Success: {batch.success_count}, Failures: {batch.failure_count}")
    return {"status": "completed", "success": batch.success_count, "failures": batch.failure_count}


def _send_in_background(**kwargs):
    # Worker threads keep their own DB connection; drop it if it has gone stale between jobs.
    close_old_connections()
    try:
        return send_fcm_push(**kwargs)
    finally:
        close_old_connections()


def queue_push_to_profile(profile, title: str, body: str, data: Dict[str, Any] = None) -> bool:
    """
    Pushes to every device the profile is signed in on, without saving an in-app Notification.
    Returns False when the profile has no registered device.
    """
    tokens = list(profile.push_devices.values_list('token', flat=True))
    if not tokens:
        return False

    # Push delivery is best-effort; never hold an API response open on FCM network latency.
    _push_executor.submit(
        _send_in_background,
        push_tokens=tokens,
        title=title,
        body=body,
        data=data,
    )
    return True


def send_push_notification_to_user(user, title: str, body: str, data: Dict[str, Any] = None) -> bool:
    """
    Saves an in-app Notification for the user and pushes it to their devices.
    Callers are responsible for checking the user's push preferences.
    """
    try:
        from api.models import Notification

        # Save to database (even if they don't have a push token, so they see it in the app)
        stored_data = dict(data or {})
        # Signed R2 URLs expire; profile_id is the stable reference used by
        # NotificationListView to generate a fresh avatar URL on every fetch.
        stored_data.pop("sender_photo", None)
        notif_type = stored_data.get("type", "system")
        Notification.objects.create(
            recipient=user,
            title=title,
            body=body,
            type=notif_type,
            data=stored_data
        )

        profile = getattr(user, 'profile', None)
        if not profile or not queue_push_to_profile(profile, title, body, data):
            logger.info(f"User {user.email} has no registered push token. (Notification saved to DB only)")
            return False
        return True
    except Exception as e:
        logger.error(f"Error sending push notification to user {user}: {e}")
        return False


def notify_direct_message(message) -> None:
    """
    Pushes a new direct message to the receiver. Chat messages stay out of the in-app
    Notification list; the inbox already shows them.
    """
    receiver = message.receiver
    if not getattr(receiver, 'messages_push', True):
        return

    if message.content:
        body = message.content if len(message.content) <= 120 else message.content[:117] + '...'
    elif message.image_url:
        body = push_text(receiver, 'msg_photo')
    elif message.audio_url:
        body = push_text(receiver, 'msg_voice')
    else:
        body = push_text(receiver, 'msg_new')

    try:
        queue_push_to_profile(
            receiver,
            title=message.sender.display_name,
            body=body,
            data={
                "type": "message",
                "profile_id": str(message.sender_id),
                "message_id": str(message.id),
            },
        )
    except Exception as e:
        logger.error(f"Error sending message push for {message.id}: {e}")


# ── Localised push texts (recipient's preferred_language; English fallback) ──
PUSH_TEXTS = {
    "match_title": {"en": "It's a Match! 🎉", "fr": "C'est un match ! 🎉"},
    "match_body": {"en": "You and {name} have liked each other.", "fr": "{name} et vous vous êtes plu mutuellement."},
    "like_title": {"en": "Someone liked you 💜", "fr": "Quelqu'un vous a liké 💜"},
    "like_body": {"en": "Open Constela to see who it is.", "fr": "Ouvrez Constela pour découvrir qui c'est."},
    "superlike_title": {"en": "You got a Super Like ⭐", "fr": "Vous avez reçu un Super Like ⭐"},
    "superlike_body": {"en": "Someone really wants to meet you.", "fr": "Quelqu'un a très envie de vous rencontrer."},
    "friend_request_title": {"en": "New Friend Request", "fr": "Nouvelle demande d'ami"},
    "friend_request_body": {"en": "{name} sent you a friend request!", "fr": "{name} vous a envoyé une demande d'ami !"},
    "friend_accepted_title": {"en": "Friend Request Accepted", "fr": "Demande d'ami acceptée"},
    "friend_accepted_body": {"en": "{name} accepted your friend request!", "fr": "{name} a accepté votre demande d'ami !"},
    "verify_ok_title": {"en": "Photo verified ✅", "fr": "Photo vérifiée ✅"},
    "verify_ok_body": {"en": "Your photo verification was approved.", "fr": "Votre vérification photo a été approuvée."},
    "verify_no_title": {"en": "Photo verification declined", "fr": "Vérification photo refusée"},
    "verify_no_body": {"en": "Your verification photo could not be approved. Please take a new one.",
                       "fr": "Votre photo de vérification n'a pas pu être approuvée. Veuillez en prendre une nouvelle."},
    "msg_photo": {"en": "📷 Photo", "fr": "📷 Photo"},
    "msg_voice": {"en": "🎤 Voice message", "fr": "🎤 Message vocal"},
    "msg_new": {"en": "New message", "fr": "Nouveau message"},
}


def push_text(profile, key: str, **kwargs) -> str:
    lang = (getattr(profile, "preferred_language", "") or "en")[:2].lower()
    texts = PUSH_TEXTS[key]
    return texts.get(lang, texts["en"]).format(**kwargs)
