from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("dashboard", "0007_tokenpurchase_sepaywebhookevent"),
    ]

    operations = [
        migrations.AddField(
            model_name="tokenpurchase",
            name="promotion_bonus_usd",
            field=models.DecimalField(
                decimal_places=4,
                default=Decimal("0"),
                max_digits=12,
            ),
        ),
        migrations.AddField(
            model_name="tokenpurchase",
            name="promotion_code",
            field=models.CharField(blank=True, db_index=True, max_length=40),
        ),
    ]
