from django.db import models
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError
import json


class Subject(models.Model):
    """
    Subject model for managing course subjects.
    """
    SEMESTER_CHOICES = [
        (1, '1st Semester'),
        (2, '2nd Semester'),
        (3, '3rd Semester'),
        (4, '4th Semester'),
        (5, '5th Semester'),
        (6, '6th Semester'),
    ]

    name = models.CharField(max_length=255, help_text="Name of the subject")
    subject_code = models.CharField(max_length=64, blank=True, null=True, help_text="Optional subject code")
    semester = models.PositiveSmallIntegerField(choices=SEMESTER_CHOICES, help_text="Semester number (1-6)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} (Sem {self.semester})"

    def get_semester_display(self):
        return f"Semester {self.semester}"

    class Meta:
        ordering = ['semester', 'name']
        unique_together = ['name', 'semester']


class BatchMapping(models.Model):
    """
    BatchMapping model for mapping batch codes to academic years.
    """
    YEAR_CHOICES = [
        (1, '1st Year'),
        (2, '2nd Year'),
        (3, '3rd Year'),
    ]

    batch_code = models.CharField(max_length=3, unique=True, help_text="Batch code (e.g., '231')")
    year = models.IntegerField(choices=YEAR_CHOICES, help_text="Mapped academic year")

    def __str__(self):
        return f"{self.batch_code} -> Year {self.year}"

    class Meta:
        ordering = ['batch_code']


class Student(models.Model):
    """
    Student model representing exam candidates.
    """
    YEAR_CHOICES = [
        (1, '1st Year'),
        (2, '2nd Year'),
        (3, '3rd Year'),
    ]

    SECTION_CHOICES = [
        ('A', 'Section A'),
        ('B', 'Section B'),
    ]

    roll = models.CharField(max_length=20, unique=True, help_text="Unique roll number")
    name = models.CharField(max_length=100, help_text="Full name of the student")
    batch_code = models.CharField(max_length=3, blank=True, null=True, help_text="Batch code extracted from roll")
    dept_code = models.CharField(max_length=10, blank=True, null=True, help_text="Department code extracted from roll")
    serial = models.IntegerField(blank=True, null=True, help_text="Serial number extracted from roll")
    year = models.IntegerField(choices=YEAR_CHOICES, help_text="Academic year (selected during upload)")
    section = models.CharField(max_length=1, choices=SECTION_CHOICES, help_text="Section (selected during upload)")
    department = models.CharField(max_length=100, blank=True, null=True, help_text="Department (optional)")
    upload_batch_id = models.CharField(max_length=50, blank=True, null=True, help_text="Upload batch identifier")
    extra = models.TextField(blank=True, null=True, help_text="Additional information")

    def __str__(self):
        return f"{self.roll} - {self.name}"

    class Meta:
        # Removed ordering to preserve Excel upload order
        # ordering = ['roll']
        indexes = [
            models.Index(fields=['year']),
            models.Index(fields=['roll']),
            models.Index(fields=['batch_code']),
        ]


class Exam(models.Model):
    """
    Exam model representing different exam sessions.
    """
    YEAR_CHOICES = [
        (1, '1st Year'),
        (2, '2nd Year'),
        (3, '3rd Year'),
    ]

    name = models.CharField(max_length=200, help_text="Name of the exam")
    date = models.DateField(help_text="Date of the exam")
    year = models.IntegerField(choices=YEAR_CHOICES, default=1, help_text="Target year for this exam")

    def __str__(self):
        return f"{self.name} ({self.date}) - {self.get_year_display()}"

    class Meta:
        ordering = ['-date']
        indexes = [
            models.Index(fields=['date']),
            models.Index(fields=['year']),
        ]


class Room(models.Model):
    """
    Room model representing exam halls.
    """
    name = models.CharField(max_length=50, unique=True, help_text="Unique room identifier")
    rows = models.PositiveSmallIntegerField(default=6, help_text="Number of rows")
    cols = models.PositiveSmallIntegerField(default=5, help_text="Number of columns")
    benches = models.PositiveIntegerField(default=30, editable=False)
    benches_per_room = models.IntegerField(default=30, validators=[MinValueValidator(1)], help_text="Total benches in room")
    seats_per_room = models.IntegerField(default=60, validators=[MinValueValidator(1)], help_text="Total seats in room")

    def __str__(self):
        return f"{self.name} ({self.rows}x{self.cols})"

    def clean(self):
        """Validate that benches_per_room equals rows * cols."""
        if self.benches_per_room != self.rows * self.cols:
            raise ValidationError(f"benches_per_room ({self.benches_per_room}) must equal rows * cols ({self.rows * self.cols})")

    @property
    def total_benches(self):
        return self.rows * self.cols

    @property
    def total_seats(self):
        return self.total_benches * 2  # Left and right seats per bench

    class Meta:
        ordering = ['name']


class Allocation(models.Model):
    """
    Allocation model representing seating arrangements for exams.
    """
    DISTRIBUTION_CHOICES = [
        ('block', 'Block Distribution'),
        ('round_robin', 'Round Robin Distribution'),
        ('seeded_shuffle', 'Seeded Shuffle Distribution'),
    ]

    ALLOCATION_MODE_CHOICES = [
        ('cycle', 'Cycle Mode (Ordered, Non-Random)'),
        ('block', 'Block Mode (Random Selection)'),
        ('hybrid', 'Hybrid Mode (Cycle + Smart Fill + Block)'),
    ]

    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='allocations')
    name = models.CharField(max_length=200, default='Default Allocation', help_text="Name for this allocation")
    rooms = models.ManyToManyField(Room, related_name='allocations')
    num_rooms = models.IntegerField(validators=[MinValueValidator(1)], help_text="Number of rooms used")
    seats_per_room = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(1)], help_text="Seats per room (optional)")

    # Algorithm parameters
    base_pattern = models.JSONField(default=list, help_text="Base pattern for bench types")
    flip_lr = models.BooleanField(default=False, help_text="Flip left-right seating")
    random_seed = models.IntegerField(null=True, blank=True, help_text="Random seed for reproducibility")
    distribution_strategy = models.CharField(
        max_length=20,
        choices=DISTRIBUTION_CHOICES,
        default='block',
        help_text="Student distribution strategy"
    )
    allocation_mode = models.CharField(
        max_length=20,
        choices=ALLOCATION_MODE_CHOICES,
        default='cycle',
        help_text="Allocation mode: cycle or block"
    )

    # File storage
    uploaded_file = models.FileField(upload_to='uploads/', null=True, blank=True, help_text="Uploaded Excel file")
    pdf_file = models.FileField(upload_to='pdfs/', null=True, blank=True, help_text="Generated PDF file")
    report_file = models.FileField(upload_to='reports/', null=True, blank=True, help_text="Allocation report JSON file")

    # Allocation counters
    total_students = models.IntegerField(default=0, help_text="Total students allocated")
    year_1_students = models.IntegerField(default=0, help_text="Year 1 students")
    year_2_students = models.IntegerField(default=0, help_text="Year 2 students")
    year_3_students = models.IntegerField(default=0, help_text="Year 3 students")

    # Subject and Semester Info
    semester_type = models.CharField(max_length=4, choices=[('odd', 'Odd'), ('even', 'Even')], null=True, blank=True)
    subjects = models.ManyToManyField(Subject, related_name='allocations', blank=True)

    # PDF Header Info
    institution_name = models.CharField(max_length=255, default='Institution Name', help_text="Name of the institution for PDF header")
    department = models.CharField(max_length=128, blank=True, null=True, help_text="Department name for PDF header")
    academic_year = models.CharField(max_length=20, default='2024-2025', help_text="Academic year for PDF header")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} - {self.exam.name} ({self.created_at.date()})"

    def save(self, *args, **kwargs):
        if not self.base_pattern:
            self.base_pattern = ["A", "B", "C"]
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['-created_at']


class SeatAssignment(models.Model):
    """
    SeatAssignment model representing individual seat assignments.
    """
    POSITION_CHOICES = [
        ('left', 'Left'),
        ('right', 'Right'),
    ]

    BENCH_TYPE_CHOICES = [
        ('A', 'Bench Type A'),
        ('B', 'Bench Type B'),
        ('C', 'Bench Type C'),
    ]

    allocation = models.ForeignKey(Allocation, on_delete=models.CASCADE, related_name='seat_assignments')
    room = models.ForeignKey(Room, on_delete=models.CASCADE)
    bench_no = models.IntegerField(default=1, validators=[MinValueValidator(1)], help_text="Bench number in room")
    seat_pos = models.CharField(max_length=5, choices=POSITION_CHOICES, default='left', help_text="Left or right seat")
    bench_type = models.CharField(max_length=1, choices=BENCH_TYPE_CHOICES, default='A', help_text="Type of bench arrangement")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, null=True, blank=True, related_name='seat_assignments')

    # Option B: Add row, column, position fields
    row = models.IntegerField(default=1, validators=[MinValueValidator(1)], help_text="Row number in room")
    column = models.IntegerField(default=1, validators=[MinValueValidator(1)], help_text="Column number in room")
    position = models.CharField(max_length=5, choices=POSITION_CHOICES, default='left', help_text="Position (left/right)")

    def __str__(self):
        student_info = f"{self.student.roll} - {self.student.name}" if self.student else "Empty"
        return f"Room {self.room.name} - Bench {self.bench_no} ({self.seat_pos}): {student_info}"

    class Meta:
        ordering = ['room', 'row', 'column', 'position']
        unique_together = ['allocation', 'room', 'row', 'column', 'position']
        indexes = [
            models.Index(fields=['allocation', 'room']),
            models.Index(fields=['student']),
        ]
