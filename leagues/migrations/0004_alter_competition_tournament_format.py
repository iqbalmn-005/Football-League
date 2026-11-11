# Generated for Page-McIntyre Playoff System

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('leagues', '0003_alter_competition_tournament_format'),
    ]

    operations = [
        migrations.AlterField(
            model_name='competition',
            name='tournament_format',
            field=models.CharField(
                choices=[
                    ('ROUND_ROBIN', 'Round Robin / League'),
                    ('LEAGUE_KNOCKOUT', 'League + Knockout'),
                    ('GROUP_KNOCKOUT', 'Group Stage + Knockout'),
                    ('SINGLE_ELIMINATION', 'Single Elimination / Knockout'),
                    ('PAGE_MCINTYRE', 'Page–McIntyre System (Final 4)'),
                ],
                default='ROUND_ROBIN',
                max_length=30
            ),
        ),
    ]
