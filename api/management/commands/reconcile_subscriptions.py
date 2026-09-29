from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from api.models import UserProfile
from api.subscriptions import sync_subscription


class Command(BaseCommand):
    help = 'Refresh verified RevenueCat entitlements; run periodically to recover missed webhooks.'

    def add_arguments(self, parser):
        parser.add_argument('--profile-id')

    def handle(self, *args, **options):
        profiles = UserProfile.objects.order_by('id')
        if options['profile_id']:
            profiles = profiles.filter(id=options['profile_id'])
        else:
            profiles = profiles.filter(Q(revenuecat_entitlements__isnull=False) | Q(subscription_store__isnull=False))
        failed = 0
        count = 0
        for profile_id in profiles.values_list('id', flat=True).iterator(chunk_size=100):
            try:
                sync_subscription(profile_id)
                count += 1
            except Exception:
                failed += 1
                self.stderr.write(f'Sync failed for profile {profile_id}; retry after checking provider configuration.')
        self.stdout.write(f'Reconciled {count} customers; {failed} failures.')
        if failed:
            raise CommandError('Reconciliation incomplete')
