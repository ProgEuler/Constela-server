def delete_user_files(user):
    try:
        profile = user.profile
        if profile.face_selfie:
            profile.face_selfie.delete(save=False)
        if profile.face_selfie_left:
            profile.face_selfie_left.delete(save=False)
        if profile.face_selfie_right:
            profile.face_selfie_right.delete(save=False)
            
        for photo in profile.photos.all():
            if photo.image:
                photo.image.delete(save=False)
    except Exception as e:
        pass
