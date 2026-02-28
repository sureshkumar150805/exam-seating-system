# Generated manually to add extra field to Student model

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('seating', '0002_exam_year'),
    ]

    operations = [
        migrations.AddField(
            model_name='student',
            name='extra',
            field=models.TextField(blank=True, help_text='Additional information', null=True),
        ),
    ]
