"""
Dynamic configuration models for the exam seating system.
These models provide flexible configuration options for room layouts,
allocation algorithms, and system settings.
"""

from django.db import models
from django.core.validators import MinValueValidator
import json


class SystemConfiguration(models.Model):
    """
    System-wide configuration settings for the seating allocation system.
    """
    key = models.CharField(max_length=100, unique=True, help_text="Configuration key")
    value = models.TextField(help_text="Configuration value (JSON)")
    description = models.TextField(blank=True, help_text="Description of this configuration")
    is_active = models.BooleanField(default=True, help_text="Whether this configuration is active")

    def __str__(self):
        return f"{self.key}: {self.description}"

    @classmethod
    def get_value(cls, key, default=None):
        """Get configuration value by key"""
        try:
            config = cls.objects.get(key=key, is_active=True)
            return json.loads(config.value)
        except (cls.DoesNotExist, json.JSONDecodeError):
            return default

    class Meta:
        ordering = ['key']


class RoomConfiguration(models.Model):
    """
    Flexible room configuration templates.
    """
    name = models.CharField(max_length=100, unique=True, help_text="Configuration name")
    description = models.TextField(blank=True, help_text="Description of this configuration")

    # Layout settings
    rows = models.IntegerField(default=6, validators=[MinValueValidator(1)], help_text="Number of rows")
    cols = models.IntegerField(default=5, validators=[MinValueValidator(1)], help_text="Number of columns")
    benches_per_row = models.IntegerField(default=5, validators=[MinValueValidator(1)], help_text="Benches per row")
    seats_per_bench = models.IntegerField(default=2, validators=[MinValueValidator(1)], help_text="Seats per bench")

    # Bench type patterns
    bench_pattern = models.JSONField(default=list, help_text="Pattern of bench types (A, B, C)")
    pattern_rotation = models.BooleanField(default=True, help_text="Whether to rotate pattern across rooms")

    # Constraints
    max_students_per_room = models.IntegerField(null=True, blank=True, help_text="Maximum students per room")
    min_students_per_room = models.IntegerField(null=True, blank=True, help_text="Minimum students per room")

    is_default = models.BooleanField(default=False, help_text="Whether this is the default configuration")
    is_active = models.BooleanField(default=True, help_text="Whether this configuration is active")

    def __str__(self):
        return f"{self.name} ({self.rows}x{self.cols})"

    @property
    def total_benches(self):
        return self.rows * self.cols

    @property
    def total_seats(self):
        return self.total_benches * self.seats_per_bench

    def save(self, *args, **kwargs):
        if self.is_default:
            # Ensure only one default configuration
            RoomConfiguration.objects.filter(is_default=True).update(is_default=False)
        if not self.bench_pattern:
            self.bench_pattern = ["A", "B", "C", "A", "B"]
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['name']


class AllocationConfiguration(models.Model):
    """
    Dynamic allocation algorithm configuration.
    """
    name = models.CharField(max_length=100, unique=True, help_text="Configuration name")
    description = models.TextField(blank=True, help_text="Description of this configuration")

    # Distribution strategies
    DISTRIBUTION_CHOICES = [
        ('block', 'Block Distribution'),
        ('round_robin', 'Round Robin Distribution'),
        ('seeded_shuffle', 'Seeded Shuffle Distribution'),
        ('balanced', 'Balanced Distribution'),
    ]

    distribution_strategy = models.CharField(
        max_length=20,
        choices=DISTRIBUTION_CHOICES,
        default='balanced',
        help_text="Student distribution strategy"
    )

    # Algorithm parameters
    base_pattern = models.JSONField(default=list, help_text="Base pattern for bench types")
    flip_lr = models.BooleanField(default=False, help_text="Flip left-right seating")
    random_seed = models.IntegerField(null=True, blank=True, help_text="Random seed for reproducibility")

    # Anti-cheating rules
    prevent_same_year_adjacent = models.BooleanField(default=True, help_text="Prevent same year students from sitting adjacent")
    prevent_same_year_vertical = models.BooleanField(default=True, help_text="Prevent same year students from sitting vertically")
    max_same_department_per_room = models.IntegerField(null=True, blank=True, help_text="Max students from same department per room")

    # Validation settings
    allow_empty_seats = models.BooleanField(default=False, help_text="Allow empty seats in allocation")
    validate_capacity = models.BooleanField(default=True, help_text="Validate room capacity constraints")

    is_default = models.BooleanField(default=False, help_text="Whether this is the default configuration")
    is_active = models.BooleanField(default=True, help_text="Whether this configuration is active")

    def __str__(self):
        return f"{self.name} ({self.distribution_strategy})"

    def save(self, *args, **kwargs):
        if self.is_default:
            # Ensure only one default configuration
            AllocationConfiguration.objects.filter(is_default=True).update(is_default=False)
        if not self.base_pattern:
            self.base_pattern = ["A", "B", "C", "A", "B"]
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['name']


class DynamicRoom(models.Model):
    """
    Enhanced Room model with dynamic configuration support.
    """
    name = models.CharField(max_length=50, unique=True, help_text="Unique room identifier")
    configuration = models.ForeignKey(
        RoomConfiguration,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Room configuration template"
    )

    # Override configuration values if needed
    custom_rows = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(1)], help_text="Custom number of rows")
    custom_cols = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(1)], help_text="Custom number of columns")
    custom_benches_per_row = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(1)], help_text="Custom benches per row")
    custom_seats_per_bench = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(1)], help_text="Custom seats per bench")

    # Room-specific constraints
    max_capacity = models.IntegerField(null=True, blank=True, help_text="Maximum capacity override")
    is_active = models.BooleanField(default=True, help_text="Whether this room is available")

    def __str__(self):
        return f"{self.name} ({self.rows}x{self.cols})"

    @property
    def rows(self):
        return self.custom_rows or (self.configuration.rows if self.configuration else 6)

    @property
    def cols(self):
        return self.custom_cols or (self.configuration.cols if self.configuration else 5)

    @property
    def benches_per_row(self):
        return self.custom_benches_per_row or (self.configuration.benches_per_row if self.configuration else 5)

    @property
    def seats_per_bench(self):
        return self.custom_seats_per_bench or (self.configuration.seats_per_bench if self.configuration else 2)

    @property
    def total_benches(self):
        return self.rows * self.cols

    @property
    def total_seats(self):
        return self.total_benches * self.seats_per_bench

    @property
    def effective_capacity(self):
        return self.max_capacity or self.total_seats

    class Meta:
        ordering = ['name']


class DynamicAllocation(models.Model):
    """
    Enhanced Allocation model with dynamic configuration support.
    """
    exam = models.ForeignKey('Exam', on_delete=models.CASCADE, related_name='dynamic_allocations')
    name = models.CharField(max_length=200, help_text="Name for this allocation")
    rooms = models.ManyToManyField(DynamicRoom, related_name='dynamic_allocations')

    # Configuration references
    room_config = models.ForeignKey(
        RoomConfiguration,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Room configuration to use"
    )
    allocation_config = models.ForeignKey(
        AllocationConfiguration,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Allocation algorithm configuration"
    )

    # Legacy fields for backward compatibility (will be deprecated)
    num_rooms = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(1)], help_text="Number of rooms used")
    benches_per_room = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(1)], help_text="Benches per room")
    rows_per_room = models.IntegerField(null=True, blank=True, default=6, validators=[MinValueValidator(1)], help_text="Rows per room")
    cols_per_room = models.IntegerField(null=True, blank=True, default=5, validators=[MinValueValidator(1)], help_text="Columns per room")
    seats_per_room = models.IntegerField(null=True, blank=True, default=60, validators=[MinValueValidator(1)], help_text="Seats per room")

    # Algorithm parameters (override config if needed)
    base_pattern = models.JSONField(null=True, blank=True, help_text="Base pattern for bench types")
    flip_lr = models.BooleanField(null=True, blank=True, help_text="Flip left-right seating")
    random_seed = models.IntegerField(null=True, blank=True, help_text="Random seed for reproducibility")
    distribution_strategy = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        choices=[
            ('block', 'Block Distribution'),
            ('round_robin', 'Round Robin Distribution'),
            ('seeded_shuffle', 'Seeded Shuffle Distribution'),
            ('balanced', 'Balanced Distribution'),
        ],
        help_text="Student distribution strategy"
    )

    # File storage
    uploaded_file = models.FileField(upload_to='uploads/', null=True, blank=True, help_text="Uploaded Excel file")
    pdf_file = models.FileField(upload_to='pdfs/', null=True, blank=True, help_text="Generated PDF file")

    # Status and metadata
    status = models.CharField(
        max_length=20,
        choices=[
            ('draft', 'Draft'),
            ('processing', 'Processing'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
        ],
        default='draft',
        help_text="Allocation status"
    )
    error_message = models.TextField(blank=True, null=True, help_text="Error message if allocation failed")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} - {self.exam.name} ({self.created_at.date()})"

    def get_room_config(self):
        """Get effective room configuration"""
        return self.room_config or RoomConfiguration.objects.filter(is_default=True, is_active=True).first()

    def get_allocation_config(self):
        """Get effective allocation configuration"""
        return self.allocation_config or AllocationConfiguration.objects.filter(is_default=True, is_active=True).first()

    def get_base_pattern(self):
        """Get effective base pattern"""
        if self.base_pattern:
            return self.base_pattern
        config = self.get_allocation_config()
        return config.base_pattern if config else ["A", "B", "C", "A", "B"]

    def get_distribution_strategy(self):
        """Get effective distribution strategy"""
        if self.distribution_strategy:
            return self.distribution_strategy
        config = self.get_allocation_config()
        return config.distribution_strategy if config else 'balanced'

    def get_flip_lr(self):
        """Get effective flip_lr setting"""
        if self.flip_lr is not None:
            return self.flip_lr
        config = self.get_allocation_config()
        return config.flip_lr if config else False

    class Meta:
        ordering = ['-created_at']
