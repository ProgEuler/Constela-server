from django.apps import AppConfig

import sys

class ApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api'

    def ready(self):
        # Only run background tasks if we are running the web server
        if 'runserver' not in sys.argv:
            return

        import threading
        import time

        def cleanup_loop():
            # Wait for Django to complete model loading and db bindings
            time.sleep(5)
            while True:
                try:
                    from django.utils import timezone
                    from api.models import User
                    
                    cutoff = timezone.now() - timezone.timedelta(days=3)
                    deleted_count, _ = User.objects.filter(
                        profile__face_verification_status='not_submitted',
                        date_joined__lt=cutoff
                    ).delete()
                    
                    if deleted_count > 0:
                        print(f"\n[AUTO-CLEANUP] Deleted {deleted_count} unverified user account(s) older than 3 days.\n")
                except Exception as e:
                    print(f"\n[AUTO-CLEANUP ERROR] Failed to run automated cleanup: {e}\n")
                
                # Sleep for 1 hour (3600 seconds)
                time.sleep(3600)

        # Start cleanup daemon thread
        t = threading.Thread(target=cleanup_loop, daemon=True)
        t.start()
