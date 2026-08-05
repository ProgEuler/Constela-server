from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from api.models import User

class Command(BaseCommand):
    help = 'Deletes user accounts that have not completed face verification within 3 days.'

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=3)
        # Find users who have not completed face verification and joined more than 3 days ago
        unverified_users = User.objects.filter(
            profile__face_verification_status='not_submitted',
            date_joined__lt=cutoff
        )
        
        count = unverified_users.count()
        if count > 0:
            unverified_users.delete()
            self.stdout.write(self.style.SUCCESS(f"Successfully deleted {count} unverified user account(s) older than 3 days."))
        else:
            self.stdout.write(self.style.SUCCESS("No unverified user accounts older than 3 days found to delete."))
