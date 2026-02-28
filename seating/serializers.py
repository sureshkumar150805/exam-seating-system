from rest_framework import serializers
from .models import Student, Exam, Room, Allocation, SeatAssignment, Subject


class StudentSerializer(serializers.ModelSerializer):
    year_display = serializers.CharField(source='get_year_display', read_only=True)

    class Meta:
        model = Student
        fields = ['id', 'roll', 'name', 'year', 'year_display', 'department', 'extra']


class ExamSerializer(serializers.ModelSerializer):
    year_display = serializers.CharField(source='get_year_display', read_only=True)

    class Meta:
        model = Exam
        fields = ['id', 'name', 'date', 'year', 'year_display']


class RoomSerializer(serializers.ModelSerializer):
    total_benches = serializers.ReadOnlyField()
    total_seats = serializers.ReadOnlyField()

    class Meta:
        model = Room
        fields = ['id', 'name', 'rows', 'cols', 'benches_per_room', 'seats_per_room', 'total_benches', 'total_seats']


class SeatAssignmentSerializer(serializers.ModelSerializer):
    student = StudentSerializer(read_only=True)
    room = RoomSerializer(read_only=True)
    bench_type_display = serializers.CharField(source='get_bench_type_display', read_only=True)
    seat_pos_display = serializers.CharField(source='get_seat_pos_display', read_only=True)

    class Meta:
        model = SeatAssignment
        fields = [
            'id', 'allocation', 'room', 'bench_no', 'seat_pos', 'seat_pos_display',
            'bench_type', 'bench_type_display', 'student'
        ]


class AllocationSerializer(serializers.ModelSerializer):
    exam = ExamSerializer(read_only=True)
    rooms = RoomSerializer(many=True, read_only=True)
    seat_assignments = SeatAssignmentSerializer(source='seat_assignments', many=True, read_only=True)
    distribution_strategy_display = serializers.CharField(source='get_distribution_strategy_display', read_only=True)

    class Meta:
        model = Allocation
        fields = [
            'id', 'exam', 'name', 'rooms', 'num_rooms', 'seats_per_room', 'base_pattern',
            'flip_lr', 'random_seed', 'distribution_strategy', 'distribution_strategy_display',
            'uploaded_file', 'pdf_file', 'created_at', 'updated_at', 'seat_assignments'
        ]


class AllocationCreateSerializer(serializers.Serializer):
    exam_id = serializers.IntegerField()
    name = serializers.CharField(max_length=200, required=False)
    num_rooms = serializers.IntegerField(min_value=1, default=1)
    seats_per_room = serializers.IntegerField(min_value=1, default=60, required=False)
    base_pattern = serializers.ListField(child=serializers.CharField(), required=False)
    flip_lr = serializers.BooleanField(default=False)
    random_seed = serializers.IntegerField(required=False, allow_null=True)
    distribution_strategy = serializers.ChoiceField(
        choices=['block', 'round_robin', 'seeded_shuffle'],
        default='block'
    )

    def validate_exam_id(self, value):
        try:
            Exam.objects.get(id=value)
        except Exam.DoesNotExist:
            raise serializers.ValidationError("Exam does not exist.")
        return value

    def validate(self, data):
        # Set default name if not provided
        if 'name' not in data:
            exam = Exam.objects.get(id=data['exam_id'])
            data['name'] = f"Allocation for {exam.name}"
        return data


class AllocationPreviewSerializer(serializers.ModelSerializer):
    exam = ExamSerializer(read_only=True)
    rooms = RoomSerializer(many=True, read_only=True)

    class Meta:
        model = Allocation
        fields = [
            'id', 'exam', 'name', 'rooms', 'num_rooms', 'benches_per_room',
            'rows_per_room', 'cols_per_room', 'seats_per_room', 'created_at'
        ]


class SubjectSerializer(serializers.ModelSerializer):
    semester_display = serializers.CharField(source='get_semester_display', read_only=True)

    class Meta:
        model = Subject
        fields = ['id', 'name', 'subject_code', 'semester', 'semester_display', 'created_at', 'updated_at']


class ExcelUploadSerializer(serializers.Serializer):
    excel_file = serializers.FileField()

    def validate_excel_file(self, value):
        if not value.name.lower().endswith(('.xlsx', '.xls', '.csv')):
            raise serializers.ValidationError("File must be an Excel file (.xlsx, .xls) or CSV file (.csv)")
        return value
