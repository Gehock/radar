# Generated by Django 2.0 on 2018-06-13 10:26

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('data', '0009_auto_20180612_1127'),
    ]

    operations = [
        migrations.AlterField(
            model_name='comparison',
            name='similarity',
            field=models.FloatField(default=0.0),
        ),
    ]
