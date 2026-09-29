from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('api', '0017_notification_data'),
    ]

    operations = [
        migrations.AlterField(
            model_name='directmessage',
            name='image_url',
            field=models.CharField(blank=True, max_length=500, null=True),
        ),
        migrations.AlterField(
            model_name='directmessage',
            name='audio_url',
            field=models.CharField(blank=True, max_length=500, null=True),
        ),
    ]
