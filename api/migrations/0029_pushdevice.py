import django.db.models.deletion
from django.db import migrations, models


def copy_profile_tokens(apps, schema_editor):
    UserProfile = apps.get_model('api', 'UserProfile')
    PushDevice = apps.get_model('api', 'PushDevice')
    seen = set()
    for profile_id, token in (
        UserProfile.objects.exclude(push_token__isnull=True).exclude(push_token='')
        .order_by('id').values_list('id', 'push_token')
    ):
        # A token belongs to one device; if two profiles share it, the device can only be signed in to one.
        if token in seen:
            continue
        seen.add(token)
        PushDevice.objects.create(profile_id=profile_id, token=token)


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0028_chatroommessagereaction_directmessagereaction'),
    ]

    operations = [
        migrations.CreateModel(
            name='PushDevice',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token', models.CharField(max_length=255, unique=True)),
                ('platform', models.CharField(blank=True, default='', max_length=10)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('profile', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='push_devices', to='api.userprofile')),
            ],
        ),
        migrations.RunPython(copy_profile_tokens, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='userprofile',
            name='push_token',
        ),
    ]
