import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import List, Union, Dict, Any
from django.conf import settings

import firebase_admin
from firebase_admin import credentials, messaging

logger = logging.getLogger(__name__)
_push_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="fcm")

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


def send_expo_push_notification(
    push_tokens: Union[str, List[str]],
    title: str,
    body: str,
    data: Dict[str, Any] = None,
    sound: str = "default",
    badge: int = None
) -> Dict[str, Any]:
    """
    Sends Native Firebase Cloud Messaging (FCM) Push Notifications.
    (Kept function name for backward compatibility with views.py)
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

    messages = []
    for token in valid_tokens:
        msg = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            data={str(k): str(v) for k, v in data.items()} if data else None,
            token=token,
        )
        messages.append(msg)

    # Send all messages
    responses = []
    success_count = 0
    failure_count = 0
    
    for msg in messages:
        try:
            response = messaging.send(msg)
            responses.append({"status": "success", "response": response})
            success_count += 1
        except Exception as e:
            logger.error(f"❌ Failed to send FCM notification: {e}")
            responses.append({"status": "error", "message": str(e)})
            failure_count += 1

    logger.info(f"✅ FCM push notification sent. Success: {success_count}, Failures: {failure_count}")
    return {"status": "completed", "success": success_count, "failures": failure_count, "details": responses}


def send_push_notification_to_user(user, title: str, body: str, data: Dict[str, Any] = None) -> bool:
    """
    Convenience helper to send a push notification to a specific User instance.
    Checks profile push_token and user notification preferences.
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
        if not profile or not profile.push_token:
            logger.info(f"User {user.email} has no registered push token. (Notification saved to DB only)")
            return False

        # Push delivery is best-effort; never hold an API response open on FCM network latency.
        _push_executor.submit(
            send_expo_push_notification,
            push_tokens=profile.push_token,
            title=title,
            body=body,
            data=data,
        )
        return True
    except Exception as e:
        logger.error(f"Error sending push notification to user {user}: {e}")
        return False
