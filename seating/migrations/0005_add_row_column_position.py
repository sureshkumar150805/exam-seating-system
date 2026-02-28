# Generated manually for adding row, column, position fields to SeatAssignment

from django.db import migrations, models
from django.core.validators import MinValueValidator


def populate_row_column_position(apps, schema_editor):
    """Populate row, column, position for existing SeatAssignment records."""
    SeatAssignment = apps.get_model('seating', 'SeatAssignment')

    for assignment in SeatAssignment.objects.all():
        # Calculate row and column from bench_no
        # Assuming benches are numbered row-major order
        cols = assignment.room.cols
        bench_no = assignment.bench_no
        row = (bench_no - 1) // cols + 1
        col = (bench_no - 1) % cols + 1

        # Set position to seat_pos (left/right)
        position = assignment.seat_pos

        # Update the record
        assignment.row = row
        assignment.column = col
        assignment.position = position
        assignment.save()


class Migration(migrations.Migration):

    dependencies = [
        ('seating', '0004_alter_seatassignment_options_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='seatassignment',
            name='row',
            field=models.IntegerField(default=1, validators=[MinValueValidator(1)], help_text='Row number in room'),
        ),
        migrations.AddField(
            model_name='seatassignment',
            name='column',
            field=models.IntegerField(default=1, validators=[MinValueValidator(1)], help_text='Column number in room'),
        ),
        migrations.AddField(
            model_name='seatassignment',
            name='position',
            field=models.CharField(choices=[('left', 'Left'), ('right', 'Right')], default='left', help_text='Position (left/right)', max_length=5),
        ),
        migrations.RunPython(populate_row_column_position, migrations.RunPython.noop),
        migrations.AlterUniqueTogether(
            name='seatassignment',
            unique_together={('allocation', 'room', 'row', 'column', 'position')},
        ),
        migrations.AlterModelOptions(
            name='seatassignment',
            options={'ordering': ['room', 'row', 'column', 'position']},
        ),
    ]
