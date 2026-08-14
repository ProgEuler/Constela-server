import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from api.models import UserProfile, Match, Block, Friendship, User
from django.db.models import Q

target_email = 'jamilhossain3741@gmail.com'
user = User.objects.get(email=target_email)
me = UserProfile.objects.get(user=user)

blocked_by_me = Block.objects.filter(blocker=me).values_list('blocked_user', flat=True)
blocked_me = Block.objects.filter(blocked_user=me).values_list('blocker', flat=True)

friends_sent = Friendship.objects.filter(sender=me).values_list('receiver', flat=True)
friends_received = Friendship.objects.filter(receiver=me).values_list('sender', flat=True)

base_exclude = set(blocked_by_me).union(set(blocked_me)).union(set(friends_sent)).union(set(friends_received))
base_exclude.add(me.id)

swiped_users = Match.objects.filter(user1=me).values_list('user2', flat=True)
exclude_users = base_exclude.union(set(swiped_users))

print(f"Me: {me.id}, Exclude total: {len(exclude_users)}")

q1 = UserProfile.objects.filter(is_deactivated=False)
print(f"After is_deactivated=False: {q1.count()}")

q2 = q1.filter(is_verified=True)
print(f"After is_verified=True: {q2.count()}")

q3 = q2.filter(user__role='member')
print(f"After role=member: {q3.count()}")

q4 = q3.exclude(id__in=exclude_users)
print(f"After exclude: {q4.count()}")
