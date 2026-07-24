from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dashboard", "0005_alter_userapiaccess_external_api_key_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="customeraccount",
            name="low_credit_alert_credit_limit",
            field=models.DecimalField(
                blank=True, decimal_places=4, max_digits=12, null=True
            ),
        ),
        migrations.AddField(
            model_name="customeraccount",
            name="low_credit_alert_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
