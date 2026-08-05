import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()

from api.models import User

# Keep the admin
admin_email = "admin@gmail.com"

users_to_delete = User.objects.exclude(email=admin_email)
count = users_to_delete.count()

print(f"Deleting {count} users...")
users_to_delete.delete()

print(f"Finished deleting users. Remaining users: {User.objects.count()}")
