def delete_user_files(user):
    """Kept for existing callers.

    Stored files (profile pictures, verification photos, chat images and voice
    messages) are now removed by the post_delete handlers in api/signals.py,
    which run for every deletion path, including cascades and bulk deletes.
    Deleting the user is enough.
    """
    return None
