from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from seating.models import Student, BatchMapping
from seating.utils.allocation import parse_excel_or_csv_file
import os


class Command(BaseCommand):
    help = 'Import students from Excel file'

    def add_arguments(self, parser):
        parser.add_argument(
            'excel_file',
            type=str,
            help='Path to Excel file containing student data'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be imported without actually importing'
        )

    def handle(self, *args, **options):
        excel_file_path = options['excel_file']
        dry_run = options['dry_run']

        if not os.path.exists(excel_file_path):
            raise CommandError(f'File "{excel_file_path}" does not exist')

        try:
            with open(excel_file_path, 'rb') as f:
                students_data, invalid_rows = parse_excel_or_csv_file(f)

            if invalid_rows:
                self.stdout.write(
                    self.style.WARNING(f'Found {len(invalid_rows)} invalid rows:')
                )
                for invalid in invalid_rows[:5]:  # Show first 5
                    self.stdout.write(f'  Row {invalid["row_number"]}: {invalid["error"]}')

            if dry_run:
                self.stdout.write(
                    self.style.SUCCESS(f'Dry run: Would import {len(students_data)} students')
                )
                return

            # Perform actual import
            created_count = 0
            updated_count = 0

            with transaction.atomic():
                for row in students_data:
                    student, created = Student.objects.update_or_create(
                        roll=row['roll'],
                        defaults={
                            'name': row['name'],
                            'batch_code': row['batch_code'],
                            'dept_code': row['dept_code'],
                            'serial': row['serial'],
                            'year': row['year'],
                            'department': row.get('department'),
                            'extra': row.get('extra'),
                        }
                    )
                    if created:
                        created_count += 1
                    else:
                        updated_count += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully imported {len(students_data)} students. '
                    f'Created: {created_count}, Updated: {updated_count}'
                )
            )

        except Exception as e:
            raise CommandError(f'Error importing students: {str(e)}')
