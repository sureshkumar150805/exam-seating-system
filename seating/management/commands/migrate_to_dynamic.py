"""
Management command to migrate existing static data to dynamic configurations.
"""

from django.core.management.base import BaseCommand
from ...models import Room, Allocation
from ...models_dynamic import (
    DynamicRoom, DynamicAllocation, RoomConfiguration, AllocationConfiguration
)


class Command(BaseCommand):
    help = 'Migrate existing static data to dynamic configurations'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be migrated without making changes',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        if dry_run:
            self.stdout.write('DRY RUN - No changes will be made')
            self.stdout.write('=' * 50)

        self.stdout.write('Migrating existing data to dynamic configurations...')

        # Get or create default configurations
        room_config, created = RoomConfiguration.objects.get_or_create(
            name="Migrated Standard Classroom",
            defaults={
                'description': "Migrated from existing static configuration",
                'rows': 6,
                'cols': 5,
                'benches_per_row': 5,
                'seats_per_bench': 2,
                'bench_pattern': ["A", "B", "C", "A", "B"],
                'pattern_rotation': True,
                'is_default': False,
                'is_active': True,
            }
        )

        alloc_config, created = AllocationConfiguration.objects.get_or_create(
            name="Migrated Standard Allocation",
            defaults={
                'description': "Migrated from existing static configuration",
                'distribution_strategy': 'balanced',
                'base_pattern': ["A", "B", "C", "A", "B"],
                'flip_lr': False,
                'prevent_same_year_adjacent': True,
                'prevent_same_year_vertical': True,
                'allow_empty_seats': False,
                'validate_capacity': True,
                'is_default': False,
                'is_active': True,
            }
        )

        # Migrate rooms
        self.stdout.write('\nMigrating rooms...')
        migrated_rooms = 0

        for room in Room.objects.all():
            if dry_run:
                self.stdout.write(f'  Would migrate: {room.name} ({room.rows}x{room.cols})')
                migrated_rooms += 1
                continue

            dynamic_room, created = DynamicRoom.objects.get_or_create(
                name=room.name,
                defaults={
                    'configuration': room_config,
                    'custom_rows': room.rows if room.rows != 6 else None,
                    'custom_cols': room.cols if room.cols != 5 else None,
                    'max_capacity': room.seats_per_room if hasattr(room, 'seats_per_room') else None,
                    'is_active': True,
                }
            )

            if created:
                self.stdout.write(f'  Created: {dynamic_room.name}')
                migrated_rooms += 1
            else:
                self.stdout.write(f'  Already exists: {dynamic_room.name}')

        # Migrate allocations
        self.stdout.write('\nMigrating allocations...')
        migrated_allocations = 0

        for allocation in Allocation.objects.all():
            if dry_run:
                self.stdout.write(f'  Would migrate: {allocation.name}')
                migrated_allocations += 1
                continue

            # Get rooms for this allocation
            room_names = list(allocation.rooms.values_list('name', flat=True))
            dynamic_rooms = DynamicRoom.objects.filter(name__in=room_names)

            if dynamic_rooms.exists():
                dynamic_allocation, created = DynamicAllocation.objects.get_or_create(
                    exam=allocation.exam,
                    name=f"{allocation.name} (Dynamic)",
                    defaults={
                        'room_config': room_config,
                        'allocation_config': alloc_config,
                        'base_pattern': allocation.base_pattern,
                        'flip_lr': allocation.flip_lr,
                        'random_seed': allocation.random_seed,
                        'distribution_strategy': allocation.distribution_strategy,
                        'uploaded_file': allocation.uploaded_file,
                        'pdf_file': allocation.pdf_file,
                        'status': 'completed',  # Assume existing allocations are complete
                    }
                )

                if created:
                    # Add rooms to the dynamic allocation
                    dynamic_allocation.rooms.set(dynamic_rooms)
                    dynamic_allocation.save()
                    self.stdout.write(f'  Created: {dynamic_allocation.name}')
                    migrated_allocations += 1
                else:
                    self.stdout.write(f'  Already exists: {dynamic_allocation.name}')

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\nDRY RUN COMPLETE\n'
                    f'Would migrate {migrated_rooms} rooms and {migrated_allocations} allocations'
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f'\nMigration complete!\n'
                    f'Migrated {migrated_rooms} rooms and {migrated_allocations} allocations'
                )
            )

        self.stdout.write('\nNext steps:')
        self.stdout.write('1. Update your views to use DynamicRoom and DynamicAllocation models')
        self.stdout.write('2. Update your templates to reference the new models')
        self.stdout.write('3. Test the dynamic allocation functionality')
        self.stdout.write('4. Gradually phase out the old static models')
