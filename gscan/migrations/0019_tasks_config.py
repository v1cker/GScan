# -*- coding: utf-8 -*-
# Generated by Django 1.9.6 on 2016-05-17 16:56
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('gscan', '0018_auto_20160517_2329'),
    ]

    operations = [
        migrations.AddField(
            model_name='tasks',
            name='config',
            field=models.IntegerField(default=1),
            preserve_default=False,
        ),
    ]