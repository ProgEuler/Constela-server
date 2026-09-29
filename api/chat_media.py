from urllib.parse import unquote, urlsplit
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.core.files.storage import default_storage
from django.utils import timezone


AUDIO_REF_SALT = "constela.chat-audio"
IMAGE_REF_SALT = "constela.chat-image"
UPLOAD_REF_MAX_AGE = 60 * 60


def _storage_key(reference, prefix):
    if not reference:
        return None
    if reference.startswith(prefix):
        return reference

    parsed = urlsplit(reference)
    path = unquote(parsed.path).lstrip("/")

    if parsed.netloc:
        endpoint_host = urlsplit(getattr(settings, "AWS_S3_ENDPOINT_URL", "") or "").netloc
        custom_host = getattr(settings, "AWS_S3_CUSTOM_DOMAIN", "") or ""
        allowed_hosts = {host for host in (endpoint_host, custom_host) if host}
        if not any(parsed.netloc == host or parsed.netloc.endswith(f".{host}") for host in allowed_hosts):
            return None

        bucket = getattr(settings, "AWS_STORAGE_BUCKET_NAME", "") or ""
        if bucket and path.startswith(f"{bucket}/"):
            path = path[len(bucket) + 1:]
    else:
        media_path = urlsplit(getattr(settings, "MEDIA_URL", "/media/")).path.lstrip("/")
        if media_path and path.startswith(media_path):
            path = path[len(media_path):]

    return path if path.startswith(prefix) else None


def audio_storage_key(reference):
    """Return the R2 key from either a stable key or one of our legacy URLs."""
    return _storage_key(reference, "chat_audio/")


def image_storage_key(reference):
    return _storage_key(reference, "chat_images/")


def fresh_audio_url(reference):
    key = audio_storage_key(reference)
    if not key:
        return reference
    try:
        return default_storage.url(key)
    except Exception:
        return reference


def audio_url_expires_at(reference):
    if not audio_storage_key(reference):
        return None
    lifetime = getattr(settings, "AWS_QUERYSTRING_EXPIRE", 3600)
    return (timezone.now() + timedelta(seconds=lifetime)).isoformat()


def fresh_image_url(reference):
    key = image_storage_key(reference)
    if not key:
        return reference
    try:
        return default_storage.url(key)
    except Exception:
        return reference


def image_url_expires_at(reference):
    if not image_storage_key(reference):
        return None
    lifetime = getattr(settings, "AWS_QUERYSTRING_EXPIRE", 3600)
    return (timezone.now() + timedelta(seconds=lifetime)).isoformat()


def sign_audio_upload(key, uploader_id):
    return signing.dumps(
        {"key": key, "uploader": str(uploader_id)},
        salt=AUDIO_REF_SALT,
        compress=True,
    )


def verify_audio_upload(reference, uploader_id):
    data = signing.loads(reference, salt=AUDIO_REF_SALT, max_age=UPLOAD_REF_MAX_AGE)
    if not isinstance(data, dict):
        raise signing.BadSignature("Invalid voice-message upload reference")
    key = data.get("key")
    if str(data.get("uploader")) != str(uploader_id) or not isinstance(key, str) or not key.startswith("chat_audio/"):
        raise signing.BadSignature("Invalid voice-message upload reference")
    return key


def sign_image_upload(key, uploader_id):
    return signing.dumps(
        {"key": key, "uploader": str(uploader_id)},
        salt=IMAGE_REF_SALT,
        compress=True,
    )


def verify_image_upload(reference, uploader_id):
    data = signing.loads(reference, salt=IMAGE_REF_SALT, max_age=UPLOAD_REF_MAX_AGE)
    if not isinstance(data, dict):
        raise signing.BadSignature("Invalid chat-image upload reference")
    key = data.get("key")
    if str(data.get("uploader")) != str(uploader_id) or not isinstance(key, str) or not key.startswith("chat_images/"):
        raise signing.BadSignature("Invalid chat-image upload reference")
    return key
