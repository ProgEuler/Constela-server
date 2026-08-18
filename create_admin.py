import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()

from django.contrib.auth import get_user_model
User = get_user_model()

try:
    if not User.objects.filter(email="admin@gmail.com").exists():
        user = User.objects.create_superuser(
            email="admin@gmail.com",
            password="Pass@123",
            username="admin",
            first_name="Admin",
            last_name="User"
        )
        print("Superuser created successfully.")
    else:
        print("Superuser already exists.")
except Exception as e:
    print(f"Error: {e}")
