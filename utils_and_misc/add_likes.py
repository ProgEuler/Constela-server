import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from api.models import UserProfile, Match

def add_likes():
    try:
        jamil = UserProfile.objects.get(user__email="jamilhossain3251@gmail.com")
    except UserProfile.DoesNotExist:
        print("User not found.")
        return

    # Clear existing matches for jamil
    Match.objects.filter(user2=jamil).delete()

    # Find some seed users (those starting with randomuser_)
    others = UserProfile.objects.filter(username__startswith='randomuser_')[:8]

    if not others:
        print("No seed users found.")
        return

    for other in others:
        Match.objects.create(
            user1=other,
            user2=jamil,
            status='liked'
        )
        print(f"User {other.username} liked Jamil.")
        
    print("Done adding likes!")

if __name__ == '__main__':
    add_likes()
