import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()

from api.models import AdminActionLog, User

admin = User.objects.filter(is_superuser=True).first() or User.objects.first()

if admin:
    log = AdminActionLog.objects.create(
        admin_user=admin,
        action="Created a test system log",
        details="This is a test detail for the system log to ensure the frontend renders properly."
    )
    print(f"Created log: {log}")
else:
    print("No users found to set as admin.")
