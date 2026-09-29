from django.db import migrations, models


def set_message_limit_defaults(apps, schema_editor):
    Tier = apps.get_model('api', 'SubscriptionTierConfig')
    defaults = {
        'freemium': ('Freemium', 20, 5, 10, False, False),
        'light': ('Premium Light', 50, None, None, True, True),
        'plus': ('Premium Plus', None, None, None, True, True),
    }
    for tier, (name, likes, personal, community, see_likes, undo) in defaults.items():
        row, created = Tier.objects.get_or_create(tier=tier, defaults={
            'name': name,
            'daily_likes_limit': likes,
            'daily_personal_messages_limit': personal,
            'daily_community_messages_limit': community,
            'community_room_limit': None,
            'can_see_likes': see_likes,
            'can_undo_swipes': undo,
        })
        if not created:
            row.daily_personal_messages_limit = personal
            row.daily_community_messages_limit = community
            row.community_room_limit = None
            row.save(update_fields=[
                'daily_personal_messages_limit',
                'daily_community_messages_limit',
                'community_room_limit',
            ])


def restore_thread_defaults(apps, schema_editor):
    Tier = apps.get_model('api', 'SubscriptionTierConfig')
    defaults = {
        'freemium': (1, 0),
        'light': (3, 3),
        'plus': (None, None),
    }
    for tier, (threads, rooms) in defaults.items():
        Tier.objects.filter(tier=tier).update(
            daily_personal_messages_limit=threads,
            community_room_limit=rooms,
        )


class Migration(migrations.Migration):
    dependencies = [('api', '0023_subscriptiontierconfig')]

    operations = [
        migrations.RenameField(
            model_name='subscriptiontierconfig',
            old_name='monthly_threads_limit',
            new_name='daily_personal_messages_limit',
        ),
        migrations.AlterField(
            model_name='subscriptiontierconfig',
            name='daily_personal_messages_limit',
            field=models.PositiveIntegerField(
                blank=True,
                help_text='Max personal messages sent per day. Leave blank for unlimited.',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='subscriptiontierconfig',
            name='daily_community_messages_limit',
            field=models.PositiveIntegerField(
                blank=True,
                help_text='Max community-room messages sent per day. Leave blank for unlimited.',
                null=True,
            ),
        ),
        migrations.RunPython(set_message_limit_defaults, restore_thread_defaults),
    ]
