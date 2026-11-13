from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0008_sale_approval_amount_received_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="sale",
            name="client_request_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="sale",
            constraint=models.UniqueConstraint(
                fields=("branch", "client_request_id"),
                name="unique_sale_client_request_per_branch",
            ),
        ),
    ]
