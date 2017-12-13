# -*- coding: utf-8 -*-
# Generated by Django 1.11.5 on 2017-11-13 15:41
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ozpcenter', '0033_auto_20171027_1948'),
    ]

    operations = [
        migrations.AlterField(
            model_name='listingactivity',
            name='action',
            field=models.CharField(choices=[('CREATED', 'CREATED'), ('MODIFIED', 'MODIFIED'), ('SUBMITTED', 'SUBMITTED'), ('APPROVED_ORG', 'APPROVED_ORG'), ('APPROVED', 'APPROVED'), ('REJECTED', 'REJECTED'), ('ENABLED', 'ENABLED'), ('DISABLED', 'DISABLED'), ('DELETED', 'DELETED'), ('REVIEWED', 'REVIEWED'), ('REVIEW_EDITED', 'REVIEW_EDITED'), ('REVIEW_DELETED', 'REVIEW_DELETED'), ('PENDING_DELETION', 'PENDING_DELETION')], max_length=128),
        ),
    ]
