from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('api', '0024_daily_message_limits'),
    ]

    operations = [
        migrations.AlterField(
            model_name='subscriptionusage',
            name='kind',
            field=models.CharField(max_length=32),
        ),
    ]
