import hashlib
import hmac
import json
import time
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import ChatRoom, ChatRoomMessage, DirectMessage, Friendship, Match, MatchAnalysisPurchase, RevenueCatEvent, SubscriptionTierConfig, SubscriptionUsage, Transaction, User, UserProfile
from api.subscriptions import access_snapshot, accessible_rooms, consume_usage, effective_access, gift_subscription, payment_history, subscriber_snapshot, sync_subscription, usage_count
from api.consumers import ChatConsumer


@override_settings(
    REVENUECAT_WEBHOOK_SECRET='test-secret', REVENUECAT_API_KEY='test-server-key',
    REVENUECAT_SIGNING_SECRET='', REVENUECAT_APP_IDS=['app_test'], REVENUECAT_ALLOW_SANDBOX=False,
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    STORAGES={'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
              'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}},
)
class SubscriptionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='subscriber', email='subscriber@example.com')
        self.profile = UserProfile.objects.create(user=self.user, username='subscriber')
        self.client = APIClient()
        self.future = (timezone.now() + timezone.timedelta(days=30)).isoformat()
        self.past = (timezone.now() - timezone.timedelta(seconds=1)).isoformat()
        self.grants = {'premium_plus': {'expires_date': self.future, 'product_identifier': 'premium_plus:monthly', 'store': 'play_store'}}
        # sync_subscription fetches the raw RevenueCat payload once; tests that mock
        # subscriber_snapshot don't need a network call for it.
        self.fetch_patcher = patch('api.subscriptions.fetch_subscriber',
                                   return_value={'entitlements': {}, 'non_subscriptions': {}})
        self.fetch_subscriber = self.fetch_patcher.start()
        self.addCleanup(self.fetch_patcher.stop)

    def event(self, **overrides):
        return dict(id='event-1', type='INITIAL_PURCHASE', app_user_id=str(self.profile.id),
                    app_id='app_test', environment='PRODUCTION', price=10, transaction_id='charge-1',
                    store='PLAY_STORE', product_id='premium_plus:monthly', **overrides)

    def deliver(self, event, **headers):
        return self.client.post('/api/subscription/webhook/', {'event': event}, format='json',
                                HTTP_AUTHORIZATION='Bearer test-secret', **headers)

    def tearDown(self):
        SubscriptionTierConfig.objects.all().delete()
        from django.core.cache import cache
        cache.clear()

    def test_auth_fails_closed_and_test_does_not_require_customer(self):
        self.assertEqual(self.client.post('/api/subscription/webhook/', {'event': {}}, format='json').status_code, 401)
        with override_settings(REVENUECAT_WEBHOOK_SECRET=''):
            self.assertEqual(self.deliver(self.event()).status_code, 503)
        self.assertEqual(self.deliver({'type': 'TEST'}).status_code, 200)

    def test_signature_is_checked_against_raw_body_and_fresh_timestamp(self):
        body = json.dumps({'event': {'type': 'TEST'}})
        timestamp = str(int(time.time()))
        signature = hmac.new(b'signing-key', (timestamp + '.' + body).encode(), hashlib.sha256).hexdigest()
        with override_settings(REVENUECAT_SIGNING_SECRET='signing-key'):
            self.assertEqual(self.client.post('/api/subscription/webhook/', body, content_type='application/json',
                HTTP_AUTHORIZATION='test-secret', HTTP_X_REVENUECAT_WEBHOOK_SIGNATURE=f't={timestamp},v1={signature}').status_code, 200)
            self.assertEqual(self.deliver({'type': 'TEST'}).status_code, 401)

    @patch('api.subscriptions.subscriber_snapshot')
    def test_duplicate_events_and_duplicate_charges_are_idempotent(self, snapshot):
        snapshot.return_value = self.grants
        event = self.event()
        self.assertEqual(self.deliver(event).status_code, 200)
        self.assertEqual(self.deliver(event).data['status'], 'duplicate')
        event['id'] = 'event-2'
        self.assertEqual(self.deliver(event).status_code, 200)
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(RevenueCatEvent.objects.count(), 2)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.subscription_access['subscription_tier'], 'plus')

    @patch('api.subscriptions.subscriber_snapshot')
    def test_cancellation_and_old_expiration_use_current_verified_state(self, snapshot):
        snapshot.return_value = self.grants
        for number, event_type in enumerate(['CANCELLATION', 'EXPIRATION', 'PRODUCT_CHANGE', 'BILLING_ISSUE', 'UNCANCELLATION', 'SUBSCRIPTION_EXTENDED']):
            event = self.event()
            event.update(id=str(number), type=event_type, expiration_at_ms=1, entitlement_ids=None)
            self.assertEqual(self.deliver(event).status_code, 200)
            self.profile.refresh_from_db()
            self.assertEqual(self.profile.subscription_access['subscription_tier'], 'plus')
        self.assertEqual(Transaction.objects.count(), 0)

    @patch('api.subscriptions.subscriber_snapshot')
    def test_failure_rolls_back_and_retry_recovers(self, snapshot):
        snapshot.side_effect = RuntimeError('provider unavailable')
        self.assertEqual(self.deliver(self.event()).status_code, 503)
        self.assertFalse(RevenueCatEvent.objects.exists())
        self.assertFalse(Transaction.objects.exists())
        snapshot.side_effect = None
        snapshot.return_value = self.grants
        self.assertEqual(self.deliver(self.event()).status_code, 200)

    @patch('api.subscriptions.subscriber_snapshot')
    def test_transfer_refreshes_both_accounts_without_app_user_id(self, snapshot):
        other_user = User.objects.create_user(username='other', email='other@example.com')
        other = UserProfile.objects.create(user=other_user, username='other')
        snapshot.side_effect = lambda pk, subscriber=None: {} if pk == self.profile.id else self.grants
        self.profile.revenuecat_entitlements = self.grants
        self.profile.save()
        event = {'id': 'transfer', 'type': 'TRANSFER', 'app_id': 'app_test',
                 'transferred_from': [str(self.profile.id)], 'transferred_to': [str(other.id)]}
        self.assertEqual(self.deliver(event).status_code, 200)
        self.profile.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(self.profile.subscription_access['subscription_tier'], 'freemium')
        self.assertEqual(other.subscription_access['subscription_tier'], 'plus')

    def test_expiry_and_lifetime_entitlements_are_checked_at_access_time(self):
        self.profile.revenuecat_entitlements = {
            'premium_plus': {'expires_date': self.past},
            'premium_light': {'expires_date': self.future},
            'add_on_match_analysis': {'expires_date': None, 'lifetime': True},
        }
        access = effective_access(self.profile)
        self.assertEqual(access['subscription_tier'], 'light')
        # Perfect Match Analysis is a one-time purchase now; an old entitlement grants nothing.
        self.assertFalse(access['has_match_analysis'])

    @patch('api.subscriptions.subscriber_snapshot')
    def test_gifts_survive_sync_and_removing_gift_does_not_remove_purchase(self, snapshot):
        snapshot.return_value = {'premium_light': {'expires_date': self.future}}
        gift_subscription(self.profile.id, 'plus', 1)
        profile = sync_subscription(self.profile.id)
        self.assertEqual(profile.subscription_access['subscription_tier'], 'plus')
        profile = gift_subscription(self.profile.id, 'freemium', 1)
        self.assertEqual(profile.subscription_access['subscription_tier'], 'light')

    @patch('api.subscriptions.subscriber_snapshot')
    def test_sync_only_targets_authenticated_account_and_ignores_client_grants(self, snapshot):
        snapshot.return_value = {}
        self.assertEqual(self.client.post('/api/subscription/sync/').status_code, 401)
        self.client.force_authenticate(self.user)
        result = self.client.post('/api/subscription/sync/', {'tier': 'plus', 'profile_id': 'untrusted'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data['subscription_tier'], 'freemium')
        snapshot.assert_called_once_with(self.profile.id, self.fetch_subscriber.return_value)

    @patch('api.subscriptions.subscriber_snapshot')
    def test_sandbox_and_wrong_app_cannot_grant(self, snapshot):
        event = self.event()
        event['environment'] = 'SANDBOX'
        self.assertEqual(self.deliver(event).data['status'], 'sandbox_ignored')
        event['app_id'] = 'wrong'
        self.assertEqual(self.deliver(event).status_code, 403)
        snapshot.assert_not_called()

    def test_community_rest_and_socket_enforce_the_same_room_set(self):
        rooms = [ChatRoom.objects.create(name=f'Room {i}') for i in range(4)]
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get(f'/api/chat/rooms/{rooms[0].id}/messages/').status_code, 200)
        self.assertTrue(ChatConsumer._profile_can_access_room(self.profile.id, str(rooms[0].id)))
        self.profile.revenuecat_entitlements = {'premium_light': {'expires_date': self.future}}
        self.profile.save()
        allowed = set(accessible_rooms(self.profile).values_list('id', flat=True))
        self.assertEqual(len(allowed), 4)
        for room in rooms:
            self.assertEqual(ChatConsumer._profile_can_access_room(self.profile.id, str(room.id)), room.id in allowed)
        self.profile.revenuecat_entitlements = {'premium_light': {'expires_date': self.past}}
        self.profile.save()
        self.assertTrue(ChatConsumer._profile_can_access_room(self.profile.id, str(rooms[0].id)))

    def test_community_room_count_comes_from_membership(self):
        self.profile.revenuecat_entitlements = {'premium_plus': {'expires_date': self.future}}
        self.profile.save()
        room = ChatRoom.objects.create(name='Accurate count', member_count=99)
        room.members.add(self.profile)
        self.client.force_authenticate(self.user)

        response = self.client.get('/api/chat/rooms/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]['member_count'], 1)
        self.assertTrue(response.data[0]['is_joined'])

    def test_advanced_match_filters_are_available_to_freemium_users(self):
        self.client.force_authenticate(self.user)
        response = self.client.get('/api/matching/perfect-match/?education_level=masters&interests=books')
        self.assertEqual(response.status_code, 200)

    def _analysis_candidate(self, name):
        user = User.objects.create_user(username=name, email=f'{name}@example.com')
        return UserProfile.objects.create(user=user, username=name, is_verified=True)

    def _store_purchase(self, txid, sandbox=False):
        return {'id': txid, 'store_transaction_id': f'GPA.{txid}', 'store': 'play_store',
                'purchase_date': timezone.now().isoformat(), 'is_sandbox': sandbox}

    @patch('api.subscriptions.subscriber_snapshot', return_value={})
    def test_match_analysis_is_a_one_time_frozen_snapshot(self, _snapshot):
        first = self._analysis_candidate('first')
        second = self._analysis_candidate('second')
        self.client.force_authenticate(self.user)

        # Nothing bought yet.
        self.assertEqual(self.client.get('/api/matching/analysis/').status_code, 403)

        # One purchase -> one analysis, computed at purchase time.
        self.fetch_subscriber.return_value = {'entitlements': {}, 'non_subscriptions': {
            'perfect_match': [self._store_purchase('one')]}}
        profile = sync_subscription(self.profile.id)
        self.assertTrue(profile.has_match_analysis)
        sync_subscription(self.profile.id)  # re-sync / webhook retry must not double-grant
        self.assertEqual(MatchAnalysisPurchase.objects.filter(profile=self.profile).count(), 1)

        response = self.client.get('/api/matching/analysis/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual({str(m['id']) for m in response.data['results']}, {str(first.id), str(second.id)})
        self.assertIsNotNone(response.data['generated_at'])

        # A profile that appears later is NOT added: the results stay as they were at purchase time.
        newcomer = self._analysis_candidate('newcomer')
        response = self.client.get('/api/matching/analysis/')
        self.assertNotIn(str(newcomer.id), {str(m['id']) for m in response.data['results']})

        # Buying again produces a fresh top 5.
        self.fetch_subscriber.return_value['non_subscriptions']['perfect_match'].append(self._store_purchase('two'))
        sync_subscription(self.profile.id)
        self.assertEqual(MatchAnalysisPurchase.objects.filter(profile=self.profile).count(), 2)
        response = self.client.get('/api/matching/analysis/')
        self.assertIn(str(newcomer.id), {str(m['id']) for m in response.data['results']})

    @patch('api.subscriptions.subscriber_snapshot', return_value={})
    def test_match_analysis_ignores_sandbox_purchases(self, _snapshot):
        self.fetch_subscriber.return_value = {'entitlements': {}, 'non_subscriptions': {
            'perfect_match': [self._store_purchase('sbx', sandbox=True)]}}
        profile = sync_subscription(self.profile.id)
        self.assertFalse(profile.has_match_analysis)
        self.assertFalse(MatchAnalysisPurchase.objects.filter(profile=self.profile).exists())

    def test_legacy_match_analysis_flag_gets_one_snapshot(self):
        self._analysis_candidate('legacy-candidate')
        self.profile.has_match_analysis = True
        self.profile.save(update_fields=['has_match_analysis'])
        self.client.force_authenticate(self.user)

        self.assertEqual(self.client.get('/api/matching/analysis/').status_code, 200)
        self.client.get('/api/matching/analysis/')
        self.assertEqual(MatchAnalysisPurchase.objects.filter(profile=self.profile).count(), 1)

    def test_education_filter_accepts_multiple_levels(self):
        def candidate(name, education):
            user = User.objects.create_user(username=name, email=f'{name}@example.com')
            return UserProfile.objects.create(user=user, username=name, is_verified=True, education_level=education)

        high_school = candidate('hs', 'High School')
        masters = candidate('ms', "Master's")
        phd = candidate('doc', 'PhD')
        self.client.force_authenticate(self.user)

        response = self.client.get('/api/matching/perfect-match/?education_level=Masters,Before Bachelor')

        self.assertEqual(response.status_code, 200)
        results = response.data.get('results', response.data) if isinstance(response.data, dict) else response.data
        ids = {str(p['id']) for p in results}
        self.assertIn(str(high_school.id), ids)
        self.assertIn(str(masters.id), ids)
        self.assertNotIn(str(phd.id), ids)

    @patch('api.subscriptions.requests.get')
    def test_provider_snapshot_checks_environment_grace_and_unknown_entitlements(self, get):
        self.fetch_patcher.stop()
        get.return_value = Mock(**{'json.return_value': {'subscriber': {
            'entitlements': {'premium_light': {'product_identifier': 'light', 'expires_date': self.past},
                             'unknown': {'product_identifier': 'unknown', 'expires_date': None}},
            'subscriptions': {'light': {'is_sandbox': False, 'grace_period_expires_date': self.future, 'store': 'play_store'}},
        }}})
        grants = subscriber_snapshot(self.profile.id)
        self.assertEqual(set(grants), {'premium_light'})
        self.assertEqual(grants['premium_light']['expires_date'], self.future)
        data = get.return_value.json.return_value
        data['subscriber']['subscriptions']['light']['is_sandbox'] = True
        self.assertEqual(subscriber_snapshot(self.profile.id), {})

    def test_legacy_expiry_and_gift_revocation(self):
        self.profile.subscription_tier = 'plus'
        self.profile.subscription_expires = timezone.now() - timezone.timedelta(days=1)
        self.profile.save()
        self.assertEqual(effective_access(self.profile)['subscription_tier'], 'freemium')
        gift_subscription(self.profile.id, 'plus', 1)
        profile = gift_subscription(self.profile.id, 'freemium', 1)
        self.assertEqual(effective_access(profile)['subscription_tier'], 'freemium')

    def test_usage_bootstrap_counts_each_sent_message_today(self):
        user = User.objects.create_user(username='recipient', email='recipient@example.com')
        other = UserProfile.objects.create(user=user, username='recipient')
        incoming = DirectMessage.objects.create(sender=other, receiver=self.profile, content='hello')
        DirectMessage.objects.create(sender=self.profile, receiver=other, content='reply')
        self.assertEqual(usage_count(self.profile, 'personal_messages'), 1)
        incoming.delete()
        self.assertEqual(usage_count(self.profile, 'personal_messages'), 1)
        DirectMessage.objects.filter(sender=self.profile).update(timestamp=timezone.now() - timezone.timedelta(days=366))
        self.assertEqual(usage_count(self.profile, 'personal_messages'), 0)

    def test_usage_is_not_refunded_by_deleting_messages_or_undoing_likes(self):
        for _ in range(5):
            self.assertTrue(consume_usage(self.profile, 'personal_messages'))
        self.assertFalse(consume_usage(self.profile, 'personal_messages'))
        for _ in range(10):
            self.assertTrue(consume_usage(self.profile, 'community_messages'))
        self.assertFalse(consume_usage(self.profile, 'community_messages'))
        for _ in range(20):
            self.assertTrue(consume_usage(self.profile, 'likes'))
        self.assertFalse(consume_usage(self.profile, 'likes'))
        Match.objects.all().delete()
        DirectMessage.objects.all().delete()
        self.assertEqual(usage_count(self.profile, 'likes'), 20)
        ChatRoomMessage.objects.all().delete()
        self.assertEqual(usage_count(self.profile, 'personal_messages'), 5)
        self.assertEqual(usage_count(self.profile, 'community_messages'), 10)

    def test_free_message_limits_are_enforced_by_rest_endpoints(self):
        other_user = User.objects.create_user(username='message-recipient', email='message-recipient@example.com')
        other = UserProfile.objects.create(user=other_user, username='message-recipient')
        Friendship.objects.create(sender=self.profile, receiver=other, status='accepted')
        room = ChatRoom.objects.create(name='Open room')
        room.members.add(self.profile)
        self.client.force_authenticate(self.user)

        for remaining in range(4, -1, -1):
            response = self.client.post('/api/chat/direct/', {'receiver': str(other.id), 'content': 'hello'}, format='json')
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.data['quota']['remaining'], remaining)
        response = self.client.post('/api/chat/direct/', {'receiver': str(other.id), 'content': 'blocked'}, format='json')
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.data['code'], 'DAILY_PERSONAL_MESSAGE_LIMIT_REACHED')

        for remaining in range(9, -1, -1):
            response = self.client.post(f'/api/chat/rooms/{room.id}/send/', {'content': 'hello'}, format='json')
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.data['quota']['remaining'], remaining)
        response = self.client.post(f'/api/chat/rooms/{room.id}/send/', {'content': 'blocked'}, format='json')
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.data['code'], 'DAILY_COMMUNITY_MESSAGE_LIMIT_REACHED')

    def test_profile_access_snapshot_contains_server_owned_limits(self):
        SubscriptionUsage.objects.create(
            profile=self.profile,
            kind='likes',
            period=timezone.localdate(),
            count=7,
        )
        access = access_snapshot(self.profile)
        self.assertTrue(access['can_access_community'])
        self.assertEqual(access['quotas']['likes']['remaining'], 13)
        self.assertEqual(access['quotas']['personal_messages']['remaining'], 5)
        self.assertEqual(access['quotas']['community_messages']['remaining'], 10)
        self.assertEqual(access['tier_rules']['freemium']['daily_personal_messages_limit'], 5)
        self.assertEqual(access['tier_rules']['freemium']['daily_community_messages_limit'], 10)
        self.assertIsNone(access['tier_rules']['light']['daily_personal_messages_limit'])

        self.client.force_authenticate(self.user)
        response = self.client.get('/api/profile/me/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['access'], access)

    @patch('api.subscriptions.subscriber_snapshot')
    def test_ambiguous_aliases_never_grant_multiple_accounts(self, snapshot):
        user = User.objects.create_user(username='alias', email='alias@example.com')
        other = UserProfile.objects.create(user=user, username='alias')
        event = self.event()
        event['aliases'] = [str(other.id)]
        self.assertEqual(self.deliver(event).status_code, 503)
        snapshot.assert_not_called()

    @patch('api.subscriptions.subscriber_snapshot')
    def test_legacy_duplicate_receipts_are_preserved_but_not_double_counted(self, snapshot):
        snapshot.return_value = self.grants
        for _ in range(2):
            Transaction.objects.create(user=self.profile, plan_name='RevenueCat: premium_plus', amount=10,
                                       status='successful', stripe_charge_id='charge-1')
        self.assertEqual(payment_history().count(), 1)
        self.assertEqual(self.deliver(self.event()).status_code, 200)
        self.assertEqual(Transaction.objects.count(), 2)
        self.assertEqual(payment_history().count(), 1)

    @patch('api.subscriptions.requests.get')
    def test_sync_rejects_provider_customer_owned_by_another_account(self, get):
        self.fetch_patcher.stop()
        other_user = User.objects.create_user(username='owner', email='owner@example.com')
        other = UserProfile.objects.create(user=other_user, username='owner')
        get.return_value = Mock(**{'json.return_value': {'subscriber': {
            'original_app_user_id': str(other.id), 'entitlements': {},
        }}})
        with self.assertRaises(ValueError):
            subscriber_snapshot(self.profile.id)

    def test_dynamic_undo_and_likes_visibility(self):
        other_user = User.objects.create_user(username='candidate', email='candidate@example.com')
        other = UserProfile.objects.create(user=other_user, username='candidate')
        self.client.force_authenticate(self.user)

        # 1. By default freemium cannot see likes received or undo
        Match.objects.create(user1=other, user2=self.profile, status='liked')
        self.assertEqual(self.client.get('/api/matching/likes-received/').status_code, 403)
        self.assertEqual(self.client.post(f'/api/matching/{other.id}/action/', {'action': 'undo'}).status_code, 403)

        # 2. Dynamically enable can_see_likes and can_undo_swipes for freemium
        cfg, _ = SubscriptionTierConfig.objects.get_or_create(
            tier='freemium',
            defaults={'name': 'Freemium', 'daily_likes_limit': 20, 'daily_personal_messages_limit': 5,
                      'daily_community_messages_limit': 10, 'community_room_limit': None}
        )
        cfg.can_see_likes = True
        cfg.can_undo_swipes = True
        cfg.save()
        from django.core.cache import cache
        cache.clear()

        # Likes received should now return 200 with other's profile
        res = self.client.get('/api/matching/likes-received/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data), 1)

        # Undo should now succeed (returns 200)
        Match.objects.create(user1=self.profile, user2=other, status='liked')
        undo_res = self.client.post(f'/api/matching/{other.id}/action/', {'action': 'undo'})
        self.assertEqual(undo_res.status_code, 200)
        self.assertEqual(undo_res.data['status'], 'undone')

        # 3. Dynamically disable undo for a Premium Light user
        self.profile.revenuecat_entitlements = {'premium_light': {'expires_date': self.future}}
        self.profile.save()
        light_cfg, _ = SubscriptionTierConfig.objects.get_or_create(tier='light')
        light_cfg.can_undo_swipes = False
        light_cfg.save()
        cache.clear()

        self.assertEqual(self.client.post(f'/api/matching/{other.id}/action/', {'action': 'undo'}).status_code, 403)

    def test_dynamic_community_rooms(self):
        r1 = ChatRoom.objects.create(name='Room 1')
        r2 = ChatRoom.objects.create(name='Room 2')
        self.client.force_authenticate(self.user)

        cfg, _ = SubscriptionTierConfig.objects.get_or_create(tier='freemium')
        cfg.community_room_limit = 0
        cfg.save()
        from django.core.cache import cache
        cache.clear()

        # A configured room limit of 0 locks community access.
        self.assertEqual(self.client.get('/api/chat/rooms/').status_code, 403)
        self.assertEqual(self.client.post(f'/api/chat/rooms/{r1.id}/join/').status_code, 403)
        self.assertEqual(self.client.post(f'/api/chat/rooms/{r1.id}/send/', {'content': 'hi'}).status_code, 403)

        # Dynamically grant 1 room to freemium
        cfg.community_room_limit = 1
        cfg.save()
        cache.clear()

        # List should now return 200 with 1 room
        res = self.client.get('/api/chat/rooms/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data), 1)
        self.assertEqual(res.data[0]['id'], str(r1.id))

        # Can join r1, but cannot join r2 (not in accessible_rooms)
        self.assertEqual(self.client.post(f'/api/chat/rooms/{r1.id}/join/').status_code, 200)
        self.assertEqual(self.client.post(f'/api/chat/rooms/{r2.id}/join/').status_code, 404)

        # Can send to r1, but cannot send to r2
        self.assertEqual(self.client.post(f'/api/chat/rooms/{r1.id}/send/', {'content': 'hello r1'}).status_code, 201)
        self.assertEqual(self.client.post(f'/api/chat/rooms/{r2.id}/send/', {'content': 'hello r2'}).status_code, 404)

    def test_admin_tier_config_validation(self):
        admin_user = User.objects.create_user(username='admin', email='admin@example.com', role='admin')
        self.client.force_authenticate(admin_user)

        # Invalid tier name rejected with 400
        res = self.client.put('/api/admin/subscriptions/tiers/', {'tiers': [{'tier': 'invalid_tier'}]}, format='json')
        self.assertEqual(res.status_code, 400)

        # Negative limit rejected with 400
        res = self.client.put('/api/admin/subscriptions/tiers/', {'tiers': [{'tier': 'light', 'daily_likes_limit': -5}]}, format='json')
        self.assertEqual(res.status_code, 400)

        # Non-integer value rejected with 400
        res = self.client.put('/api/admin/subscriptions/tiers/', {'tiers': [{'tier': 'light', 'daily_likes_limit': 'abc'}]}, format='json')
        self.assertEqual(res.status_code, 400)

        # Valid update with booleans and limits succeeds
        res = self.client.put('/api/admin/subscriptions/tiers/', {
            'tiers': [
                {'tier': 'light', 'daily_likes_limit': 75, 'daily_personal_messages_limit': 25,
                 'daily_community_messages_limit': 40, 'can_see_likes': True, 'can_undo_swipes': 'false'}
            ]
        }, format='json')
        self.assertEqual(res.status_code, 200)

        cfg = SubscriptionTierConfig.objects.get(tier='light')
        self.assertEqual(cfg.daily_likes_limit, 75)
        self.assertEqual(cfg.daily_personal_messages_limit, 25)
        self.assertEqual(cfg.daily_community_messages_limit, 40)
        self.assertTrue(cfg.can_see_likes)
        self.assertFalse(cfg.can_undo_swipes)
