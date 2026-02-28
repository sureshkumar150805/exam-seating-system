from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction, DatabaseError, OperationalError
from django.db.models import Count, Max
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.views import APIView

import os
import logging

logger = logging.getLogger(__name__)

from .models import Student, Exam, Room, Allocation, SeatAssignment, Subject
from .serializers import (
    StudentSerializer, ExamSerializer, RoomSerializer,
    AllocationSerializer, AllocationCreateSerializer,
    ExcelUploadSerializer, SeatAssignmentSerializer, SubjectSerializer,
)
from .utils.allocation import generate_allocation
from .utils.parsers import parse_excel_or_csv_file




# =====================================================================
#                       FILE UPLOAD / IMPORT
# =====================================================================

class ExcelUploadView(APIView):
    """
    API endpoint for uploading Excel/CSV files containing student data.
    Expects year and section in request data, as per new architecture.
    """
    def post(self, request):
        serializer = ExcelUploadSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        excel_file = serializer.validated_data['excel_file']
        year = request.data.get('year')
        section = request.data.get('section')

        if not year or not section:
            return Response({'error': 'Year and section must be provided'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            year = int(year)
            if year not in [1, 2, 3]:
                return Response({'error': 'Year must be 1, 2, or 3'}, status=status.HTTP_400_BAD_REQUEST)
            if section not in ['A', 'B']:
                return Response({'error': 'Section must be A or B'}, status=status.HTTP_400_BAD_REQUEST)
        except ValueError:
            return Response({'error': 'Invalid year or section'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            students_data, invalid_rows = parse_excel_or_csv_file(excel_file)

            created_count = 0
            updated_count = 0
            student_objs = []

            from django.db import transaction as dj_transaction, DatabaseError
            import uuid

            # Clear all old student data before processing new upload
            Student.objects.all().delete()
            logger.info('Cleared all old student data before new upload (API)')

            upload_batch_id = str(uuid.uuid4())[:8]  # Short unique ID

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    with dj_transaction.atomic():
                        # Do NOT clear all students; append to existing
                        for row in students_data:
                            student, created = Student.objects.update_or_create(
                                roll=row['roll'],
                                defaults={
                                    'name': row['name'],
                                    'batch_code': row['batch_code'],
                                    'dept_code': row['dept_code'],
                                    'serial': row['serial'],
                                    'year': year,  # Use selected year
                                    'section': section,  # Use selected section
                                    'department': row.get('department'),
                                    'upload_batch_id': upload_batch_id,
                                    'extra': row.get('extra'),
                                }
                            )
                            if created:
                                created_count += 1
                            else:
                                updated_count += 1
                            student_objs.append(student)
                    break
                except DatabaseError as db_error:
                    if 'database is locked' in str(db_error).lower() and attempt < max_retries - 1:
                        import time
                        time.sleep(0.5 * (attempt + 1))
                        continue
                    else:
                        raise db_error

            # Count students by year and section
            year_sec_counts = {}
            for student in student_objs:
                key = f"{student.year}-{student.section}"
                year_sec_counts[key] = year_sec_counts.get(key, 0) + 1

            response_data = {
                'message': (
                    f'Successfully processed {len(student_objs)} students for Year {year} Section {section}. '
                    f'Created: {created_count}, Updated: {updated_count}'
                ),
                'students_count': len(student_objs),
                'year_sec_counts': year_sec_counts,
                'upload_batch_id': upload_batch_id,
                'invalid_rows_count': len(invalid_rows),
                'invalid_rows': invalid_rows[:10],
            }

            # CSV preview for invalid rows (if any)
            if invalid_rows:
                import csv
                import io as py_io
                csv_buffer = py_io.StringIO()
                writer = csv.DictWriter(
                    csv_buffer,
                    fieldnames=['row_number', 'error', 'roll', 'name', 'department', 'extra']
                )
                writer.writeheader()
                for invalid in invalid_rows:
                    row_data = invalid['row_data']
                    writer.writerow({
                        'row_number': invalid['row_number'],
                        'error': invalid['error'],
                        'roll': row_data.get('roll', ''),
                        'name': row_data.get('name', ''),
                        'department': row_data.get('department', ''),
                        'extra': row_data.get('extra', ''),
                    })
                response_data['invalid_rows_csv'] = csv_buffer.getvalue()

            return Response(response_data, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response(
                {'error': f'Error processing file: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )


# =====================================================================
#                       API â€“ GENERATE ALLOCATION
# =====================================================================

class GenerateAllocationView(APIView):
    """
    API endpoint for generating seating allocations programmatically.
    Uses the same algorithm as the HTML form (allocation_form_view),
    but takes JSON input (exam_name, exam_date, num_rooms, etc.).
    """
    def post(self, request):
        serializer = AllocationCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        validated = serializer.validated_data
        exam_name = validated.get('exam_name')
        exam_date = validated.get('exam_date')
        num_rooms = validated.get('num_rooms', 1)
        distribution_strategy = validated.get('distribution_strategy', 'block')
        flip_lr = validated.get('flip_lr', False)
        seed = validated.get('random_seed', request.data.get('seed'))

        try:
            from datetime import datetime
            exam_date_parsed = datetime.strptime(exam_date, '%Y-%m-%d').date()
            exam, created = Exam.objects.get_or_create(
                name=exam_name,
                date=exam_date_parsed,
                defaults={'year': 1}  # or any default year you want
            )

            # Convert numeric options
            num_rooms = int(num_rooms) if num_rooms is not None else 1

            with transaction.atomic():
                # Remove previous allocations for this exam (project choice)
                SeatAssignment.objects.filter(allocation__exam=exam).delete()
                Allocation.objects.filter(exam=exam).delete()
                Room.objects.filter(allocations__exam=exam).delete()

                # Create rooms dynamically with default dimensions
                rooms = []
                default_rows = 6
                default_cols = 5
                default_benches = default_rows * default_cols
                default_seats = default_benches * 2
                for i in range(1, num_rooms + 1):
                    room = Room.objects.create(
                        name=f"Room {exam.name}-{i}",
                        rows=default_rows,
                        cols=default_cols,
                        benches_per_room=default_benches,
                        seats_per_room=default_seats,
                    )
                    rooms.append(room)

                allocation = Allocation.objects.create(
                    exam=exam,
                    name=f"Allocation for {exam.name}",
                    num_rooms=num_rooms,
                    seats_per_room=default_seats,
                    distribution_strategy=distribution_strategy,
                    random_seed=int(seed) if seed else None,
                    flip_lr=flip_lr,
                )
                allocation.rooms.set(rooms)

                # IMPORTANT: match allocation.py signature: student_queryset
                generate_allocation(
                    allocation=allocation,
                    student_queryset=Student.objects.all(),
                    rooms=rooms,
                    rows_per_room=None,
                    cols_per_room=None,
                    distribution_strategy=distribution_strategy,
                    seed=int(seed) if seed else None,
                    flip_lr=flip_lr,
                )

                logger.info("Allocation completed successfully.")

            serializer_out = AllocationSerializer(allocation)
            return Response({'allocation': serializer_out.data}, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f'Error generating allocation (API): {str(e)}', exc_info=True)
            return Response(
                {'error': f'Error generating allocation: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AllocationReportView(APIView):
    """
    API endpoint for downloading allocation report JSON files.
    (If you generate them.)
    """
    def get(self, request, allocation_id):
        allocation = get_object_or_404(Allocation, id=allocation_id)

        # Prefer model field
        if hasattr(allocation, 'report_file') and allocation.report_file:
            try:
                report_file = allocation.report_file
                response = HttpResponse(report_file.read(), content_type='application/json')
                response['Content-Disposition'] = (
                    f'attachment; filename="{os.path.basename(report_file.name)}"'
                )
                return response
            except Exception as e:
                return Response(
                    {'error': f'Error retrieving report from model field: {str(e)}'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        # Fallback: MEDIA_ROOT
        media_root = getattr(settings, 'MEDIA_ROOT', None)
        if media_root:
            filename = os.path.join(media_root, f"allocation_report_{allocation.id}.json")
            if os.path.exists(filename):
                try:
                    with open(filename, 'rb') as f:
                        resp = HttpResponse(f.read(), content_type='application/json')
                        resp['Content-Disposition'] = (
                            f'attachment; filename="{os.path.basename(filename)}"'
                        )
                        return resp
                except Exception as e:
                    return Response(
                        {'error': f'Error retrieving report from MEDIA_ROOT: {str(e)}'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )

        return Response({'error': 'Report not available'}, status=status.HTTP_404_NOT_FOUND)


class AllocationPreviewView(APIView):
    """
    Simple API endpoint for previewing allocation data as JSON.
    """
    def get(self, request, allocation_id):
        allocation = get_object_or_404(Allocation, id=allocation_id)
        serializer = AllocationSerializer(allocation)
        return Response(serializer.data)


class AllocationRoomsView(APIView):
    """
    API endpoint for getting room-specific allocation data.
    """
    def get(self, request, allocation_id, room_id):
        allocation = get_object_or_404(Allocation, id=allocation_id)
        room = get_object_or_404(Room, id=room_id)

        seat_assignments = SeatAssignment.objects.filter(
            allocation=allocation, room=room
        ).select_related('student')

        serializer = SeatAssignmentSerializer(seat_assignments, many=True)
        return Response({
            'allocation': AllocationSerializer(allocation).data,
            'room': RoomSerializer(room).data,
            'seat_assignments': serializer.data
        })


# =====================================================================
#                       FRONTEND VIEWS
# =====================================================================

def home_view(request):
    """Home page redirect to upload form."""
    Student.objects.all().delete()
    return redirect('seating:upload_form')


def uploaded_files_view(request):
    """Display all uploaded file batches with their details."""
    from django.db.models import Count

    # Get all unique upload_batch_ids with their statistics
    batches = Student.objects.values('upload_batch_id', 'year', 'section').annotate(
        total_students=Count('id'),
        created_at=Max('id')  # Use max id as proxy for latest creation time
    ).filter(upload_batch_id__isnull=False).order_by('-created_at')

    # Get detailed file information for each batch
    batch_details = []
    for batch in batches:
        batch_id = batch['upload_batch_id']
        students = Student.objects.filter(upload_batch_id=batch_id).select_related()

        # Group by year-section for this batch
        year_sec_groups = {}
        for student in students:
            key = f"{student.year}-{student.section}"
            if key not in year_sec_groups:
                year_sec_groups[key] = []
            year_sec_groups[key].append(student)

        batch_details.append({
            'batch_id': batch_id,
            'year': batch['year'],
            'section': batch['section'],
            'total_students': batch['total_students'],
            'year_sec_groups': year_sec_groups,
            'created_at': batch['created_at']
        })

    return render(request, 'seating/uploaded_files.html', {
        'batch_details': batch_details
    })


def upload_view(request):
    """Upload form view for multiple Excel/CSV files."""
    logger.info("upload_view called")
    if request.method == 'POST':
        logger.info("Processing POST request for upload")

        year = request.POST.get('year')
        section = request.POST.get('section')

        if not year or not section:
            return render(request, 'seating/upload.html', {'error_message': 'Year and section are required'})

        try:
            year = int(year)
            if year not in [1, 2, 3]:
                return render(request, 'seating/upload.html', {'error_message': 'Year must be 1, 2, or 3'})
            if section not in ['A', 'B']:
                return render(request, 'seating/upload.html', {'error_message': 'Section must be A or B'})
        except ValueError:
            return render(request, 'seating/upload.html', {'error_message': 'Invalid year or section'})

        if 'excel_files' not in request.FILES:
            return render(request, 'seating/upload.html', {'error_message': 'No files uploaded'})

        excel_files = request.FILES.getlist('excel_files')
        if not excel_files:
            return render(request, 'seating/upload.html', {'error_message': 'No files selected'})

        logger.info(f"Processing {len(excel_files)} files for Year {year} Section {section}")

        # Process each file
        total_files = len(excel_files)
        total_students_created = 0
        total_students_updated = 0
        all_invalid_rows = []
        file_results = []
        successful_files = 0

        import uuid



        upload_batch_id = str(uuid.uuid4())[:8]

        for file_idx, excel_file in enumerate(excel_files):
            file_name = excel_file.name
            logger.info(f"Processing file {file_idx + 1}/{total_files}: {file_name}")

            try:
                # Validate file type
                if not file_name.lower().endswith(('.xlsx', '.xls', '.csv')):
                    file_results.append({
                        'file_name': file_name,
                        'status': 'error',
                        'error': 'Invalid file type. Only .xlsx, .xls, .csv files are allowed.'
                    })
                    continue

                # Parse the file
                students_data, invalid_rows = parse_excel_or_csv_file(excel_file)
                all_invalid_rows.extend(invalid_rows)

                if not students_data and invalid_rows:
                    file_results.append({
                        'file_name': file_name,
                        'status': 'error',
                        'error': f'Failed to parse any valid students. {len(invalid_rows)} invalid rows.'
                    })
                    continue

                # Process students for this file
                created_count = 0
                updated_count = 0

                from django.db import DatabaseError
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        with transaction.atomic():
                            # Do NOT clear existing students; append to database
                            for student_data in students_data:
                                student, created = Student.objects.update_or_create(
                                    roll=student_data['roll'],
                                    defaults={
                                        'name': student_data['name'],
                                        'batch_code': student_data['batch_code'],
                                        'dept_code': student_data['dept_code'],
                                        'serial': student_data['serial'],
                                        'year': year,  # Use selected year
                                        'section': section,  # Use selected section
                                        'department': student_data.get('department'),
                                        'upload_batch_id': upload_batch_id,
                                        'extra': student_data.get('extra'),
                                    }
                                )
                                if created:
                                    created_count += 1
                                else:
                                    updated_count += 1
                        break
                    except DatabaseError as db_error:
                        if 'database is locked' in str(db_error).lower() and attempt < max_retries - 1:
                            import time
                            time.sleep(0.5 * (attempt + 1))
                            continue
                        else:
                            raise db_error

                total_students_created += created_count
                total_students_updated += updated_count
                successful_files += 1

                file_results.append({
                    'file_name': file_name,
                    'status': 'success',
                    'students_processed': len(students_data),
                    'created': created_count,
                    'updated': updated_count,
                    'invalid_rows': len(invalid_rows)
                })

                logger.info(f"File {file_name}: {len(students_data)} students, {created_count} created, {updated_count} updated")

            except Exception as e:
                logger.error(f'Error processing file {file_name}: {str(e)}', exc_info=True)
                file_results.append({
                    'file_name': file_name,
                    'status': 'error',
                    'error': str(e)
                })

        # Prepare response
        success_message = (
            f"Processed {total_files} files successfully for Year {year} Section {section}. "
            f"Created: {total_students_created} students, Updated: {total_students_updated} students."
        )

        # Count students by year and section
        year_sec_counts = {}
        students = Student.objects.filter(upload_batch_id=upload_batch_id)
        for student in students:
            key = f"{student.year}-{student.section}"
            year_sec_counts[key] = year_sec_counts.get(key, 0) + 1

        context = {
            'success_message': success_message,
            'total_files': total_files,
            'successful_files': successful_files,
            'total_students_created': total_students_created,
            'total_students_updated': total_students_updated,
            'year_sec_counts': year_sec_counts,
            'file_results': file_results,
            'invalid_rows_count': len(all_invalid_rows),
            'invalid_rows': all_invalid_rows[:10],
        }

        if all_invalid_rows:
            import csv
            import io as py_io
            csv_buffer = py_io.StringIO()
            writer = csv.DictWriter(
                csv_buffer,
                fieldnames=['row_number', 'error', 'roll', 'name', 'department', 'extra']
            )
            writer.writeheader()
            for invalid in all_invalid_rows:
                row_data = invalid['row_data']
                writer.writerow({
                    'row_number': invalid['row_number'],
                    'error': invalid['error'],
                    'roll': row_data.get('roll', ''),
                    'name': row_data.get('name', ''),
                    'department': row_data.get('department', ''),
                    'extra': row_data.get('extra', ''),
                })
            context['invalid_rows_csv'] = csv_buffer.getvalue()

        return render(request, 'seating/upload.html', context)

    return render(request, 'seating/upload.html')


def allocation_form_view(request):
    """
    HTML form for creating allocations with per-year subject dropdowns depending
    on semester type (odd/even) and only for years present in the Student table.
    """
    # Hard-coded exam choices for dropdown (not from DB)
    exam_choices = [
        {'name': 'CIA 1', 'date_required': True},
        {'name': 'Model', 'date_required': True},
    ]

    # Determine which student years are present in the system (dynamic detection)
    available_years_qs = Student.objects.values_list('year', flat=True).distinct()
    available_years = sorted([int(y) for y in available_years_qs if y is not None])

    # Mapping templates: year -> semester for odd/even
    year_to_semester_odd = {1: 1, 2: 3, 3: 5}
    year_to_semester_even = {1: 2, 2: 4, 3: 6}

    # Load all subjects grouped by semester for building dropdowns
    subjects_by_semester = {}
    try:
        subjects_qs = Subject.objects.values('id', 'name', 'semester', 'subject_code').order_by('semester', 'name')
        for subj in subjects_qs:
            sem = subj['semester']
            subjects_by_semester.setdefault(sem, []).append({
                'id': subj['id'],
                'name': subj['name'],
                'subject_code': subj.get('subject_code')
            })
    except OperationalError:
        # DB not migrated yet (department column missing). Fall back to empty dict.
        subjects_by_semester = {}

    if request.method == 'POST':
        try:
            exam_name = request.POST.get('exam_name')
            exam_date = request.POST.get('exam_date')
            name = request.POST.get('name', '')
            institution_name = request.POST.get('institution_name', 'Institution Name')
            academic_year = request.POST.get('academic_year', '').strip()
            department = request.POST.get('department', '').strip()
            semester_type = request.POST.get('semester_type')
            num_rooms = request.POST.get('num_rooms')
            allocation_mode = request.POST.get('allocation_mode', 'cycle')
            distribution_strategy = request.POST.get('distribution_strategy', 'block')
            # Use dropdown mode as source of truth: cycle | block
            selected_mode = (allocation_mode or '').strip().lower()
            if selected_mode in ['cycle', 'block']:
                distribution_strategy = selected_mode
            random_seed = request.POST.get('random_seed')
            flip_lr = request.POST.get('flip_lr') == 'on'

            if not exam_name:
                raise ValueError("Exam name is required")
            if not exam_date:
                raise ValueError("Exam date is required")
            if not department:
                raise ValueError("Department is required")
            if not semester_type or semester_type not in ['odd', 'even']:
                raise ValueError("Semester type is required and must be 'odd' or 'even'")
            if not num_rooms:
                raise ValueError("Number of rooms is required")

            num_rooms = int(num_rooms)
            if num_rooms < 1:
                raise ValueError("Number of rooms must be at least 1")

            # determine semester mapping based on selected semester type
            year_sem_map = year_to_semester_odd if semester_type == 'odd' else year_to_semester_even

            # Only consider years that actually exist in data AND are in the semester map
            visible_years = [y for y in available_years if y in year_sem_map]

            if not visible_years:
                raise ValueError(
                    f"No valid academic years found for {semester_type} semester. "
                    f"Student data contains years: {available_years}, "
                    f"but only years 1-3 are supported for semester type '{semester_type}'."
                )

            # Validate subject selection per unique semester (expect single subject id per semester)
            selected_subject_ids = []
            unique_semesters = set(year_sem_map[y] for y in visible_years)
            for sem in unique_semesters:
                field_name = f"subject_semester_{sem}"
                subj_val = request.POST.get(field_name)
                if not subj_val:
                    # Check if subjects exist for this semester
                    subject_count = Subject.objects.filter(semester=sem).count()
                    if subject_count == 0:
                        raise ValueError(
                            f"No subjects found in the database for Semester {sem} ({semester_type.capitalize()} Semester). "
                            f"Please add subjects via the Subject Management page first."
                        )
                    raise ValueError(f"Subject for Semester {sem} is required.")
                try:
                    sid = int(subj_val)
                except ValueError:
                    raise ValueError(f"Invalid subject selection for Semester {sem}.")
                selected_subject_ids.append(sid)

            # Parse dynamic room inputs (unchanged)
            rooms_data = []
            total_seats = 0
            for i in range(1, num_rooms + 1):
                room_name = request.POST.get(f'room_name_{i}')
                room_rows = request.POST.get(f'room_rows_{i}')
                room_cols = request.POST.get(f'room_cols_{i}')
                room_benches = request.POST.get(f'room_benches_{i}')

                if not room_name:
                    raise ValueError(f"Room name for Room {i} is required")
                if not room_rows:
                    raise ValueError(f"Rows for Room {i} is required")
                if not room_cols:
                    raise ValueError(f"Columns for Room {i} is required")

                room_rows = int(room_rows)
                room_cols = int(room_cols)
                room_benches = int(room_benches) if room_benches else 0

                if room_rows < 1:
                    raise ValueError(f"Rows for Room {i} must be at least 1")
                if room_cols < 1:
                    raise ValueError(f"Columns for Room {i} must be at least 1")

                computed_benches = room_rows * room_cols
                if room_benches != computed_benches:
                    raise ValueError(
                        f"Benches for Room {i} ({room_benches}) must equal rows Ã— columns ({computed_benches})"
                    )

                seats_per_room = room_benches * 2
                total_seats += seats_per_room

                rooms_data.append({
                    'name': room_name,
                    'rows': room_rows,
                    'cols': room_cols,
                    'benches_per_room': room_benches,
                    'seats_per_room': seats_per_room,
                })

            from datetime import datetime
            exam_date_parsed = datetime.strptime(exam_date, '%Y-%m-%d').date()
            exam, created = Exam.objects.get_or_create(
                name=exam_name,
                date=exam_date_parsed,
                defaults={'year': 1}
            )

            if not name:
                name = f"Allocation for {exam.name}"

            with transaction.atomic():
                SeatAssignment.objects.filter(allocation__exam=exam).delete()
                Allocation.objects.filter(exam=exam).delete()
                Room.objects.filter(allocations__exam=exam).delete()

                rooms_created = []
                for room_data in rooms_data:
                    room, created = Room.objects.update_or_create(
                        name=room_data['name'],
                        defaults={
                            'rows': room_data['rows'],
                            'cols': room_data['cols'],
                            'benches_per_room': room_data['benches_per_room'],
                            'seats_per_room': room_data['seats_per_room'],
                        }
                    )
                    rooms_created.append(room)

                allocation = Allocation.objects.create(
                    exam=exam,
                    name=name,
                    num_rooms=num_rooms,
                    semester_type=semester_type,
                    distribution_strategy=distribution_strategy,
                    allocation_mode=allocation_mode,
                    random_seed=int(random_seed) if random_seed else None,
                    flip_lr=flip_lr,
                    institution_name=institution_name,
                    department=department,
                    academic_year=academic_year,
                )

                # Set selected subjects (one per visible year) using PK list to avoid loading full Subject rows
                allocation.subjects.set(selected_subject_ids)

                allocation.rooms.set(rooms_created)

                # Generate allocation using the standard algorithm
                students_qs = Student.objects.all()
                generate_allocation(
                    allocation=allocation,
                    student_queryset=students_qs,
                    rooms=rooms_created,
                    rows_per_room=None,
                    cols_per_room=None,
                    distribution_strategy=distribution_strategy,
                    seed=int(random_seed) if random_seed else None,
                    flip_lr=flip_lr,
                )

                logger.info("Allocation completed successfully. Student data retained for preview.")

                # Mark upload batch completed so next upload starts with fresh data.
                request.session['upload_batch_active'] = False
                request.session['upload_batch_id'] = None

            success_message = f"Dynamic allocation created successfully. {total_seats} seats across {num_rooms} rooms. Next upload will start with fresh student data."
            return render(request, 'seating/allocation_form.html', {
                'exam_choices': exam_choices,
                'success_message': success_message,
                'error_message': None,
                'allocation_id': allocation.id,
                # pass data for frontend dynamic rendering
                'available_years': available_years,
                'subjects_by_semester': subjects_by_semester,
                'selected_semester_type': semester_type,
            })

        except Exception as e:
            logger.error(f'Error generating allocation (HTML): {str(e)}', exc_info=True)
            return render(request, 'seating/allocation_form.html', {
                'exam_choices': exam_choices,
                'success_message': None,
                'error_message': f"Error generating allocation: {str(e)}",
                'allocation_id': None,
                'available_years': available_years,
                'subjects_by_semester': subjects_by_semester,
                'selected_semester_type': semester_type,
            })

    # GET: provide available_years and subjects_by_semester for dynamic UI
    return render(request, 'seating/allocation_form.html', {
        'exam_choices': exam_choices,
        'success_message': None,
        'error_message': None,
        'allocation_id': None,
        'available_years': available_years,
        'subjects_by_semester': subjects_by_semester,
        'selected_semester_type': None,
    })


def preview_view(request, allocation_id):
    """Preview allocation details with room-wise and year-wise counts."""
    allocation = get_object_or_404(Allocation, id=allocation_id)
    seat_assignments = SeatAssignment.objects.filter(
        allocation=allocation
    ).select_related('room', 'student').order_by('room', 'row', 'column', 'position')

    rooms_data = {}
    # Calculate counts from actual assignments
    total_students = 0
    global_year_counts = {1: 0, 2: 0, 3: 0}

    for assignment in seat_assignments:
        room = assignment.room
        room_name = room.name

        if room_name not in rooms_data:
            rows = room.rows
            cols = room.cols
            total_benches = rows * cols

            rooms_data[room_name] = {
                'room': room,
                'rows': rows,
                'cols': cols,
                'total_benches': total_benches,
                'year': None,  # Will be derived from first student
                'grid': {},                     # bench_key -> bench dict
                'year_counts': {1: 0, 2: 0, 3: 0},
                'total_students': 0,
            }

        # NEW: Derive year and section from actual students in the room
        if assignment.student and rooms_data[room_name]['year'] is None:
            rooms_data[room_name]['year'] = assignment.student.year

        bench_key = f"{assignment.row}-{assignment.column}"
        if bench_key not in rooms_data[room_name]['grid']:
            rooms_data[room_name]['grid'][bench_key] = {
                'bench_no': assignment.bench_no,
                'row': assignment.row,
                'column': assignment.column,
                'bench_type': assignment.bench_type,
                'left_student': None,
                'right_student': None,
            }

        # Fill left/right student
        bench = rooms_data[room_name]['grid'][bench_key]
        if assignment.position == 'left':
            bench['left_student'] = assignment.student
        else:
            bench['right_student'] = assignment.student

        # Count students
        if assignment.student and assignment.student.year:
            y = assignment.student.year
            if y in rooms_data[room_name]['year_counts']:
                rooms_data[room_name]['year_counts'][y] += 1
            else:
                rooms_data[room_name]['year_counts'][y] = 1

            if y in global_year_counts:
                global_year_counts[y] += 1
            else:
                global_year_counts[y] = 1

            rooms_data[room_name]['total_students'] += 1
            total_students += 1

    # Build ordered grid list per room (by bench_no) for stable rendering
    for room_name, room_data in rooms_data.items():
        room_data['grid_list'] = sorted(
            room_data['grid'].values(), key=lambda b: b['bench_no']
        )

    response = render(request, 'seating/preview.html', {
        'allocation': allocation,
        'rooms_data': rooms_data,
        'total_students': total_students,
        'global_year_counts': global_year_counts,
    })

    # Do NOT delete students here; needed for PDF generation.
    # Reset batch flag so the next upload starts a new clean batch.
    if total_students > 0:
        request.session['upload_batch_active'] = False
        request.session['upload_batch_id'] = None
        logger.info("Upload batch reset after allocation preview; next upload will clear old students.")

    return response



def allocation_history_view(request):
    """View allocation history and handle delete requests."""
    logger.info(f"allocation_history_view called with method: {request.method}")

    if request.method == 'POST' and 'delete' in request.POST:
        logger.info("Processing delete request")
        allocation_id = request.POST.get('allocation_id')
        try:
            allocation = Allocation.objects.get(id=allocation_id)
            allocation_name = allocation.name
            allocation.delete()
            messages.success(request, f'Allocation "{allocation_name}" deleted successfully.')
            logger.info(f"Successfully deleted allocation: {allocation_name}")
        except Allocation.DoesNotExist:
            messages.error(request, 'Allocation not found.')
            logger.error(f"Allocation not found: {allocation_id}")

        return redirect('seating:allocation_history')

    allocations = Allocation.objects.all().order_by('-created_at')
    logger.info(f"Rendering allocation history with {allocations.count()} allocations")
    return render(request, 'seating/allocation_history.html', {
        'allocations': allocations
    })


def batch_mapping_view(request):
    """Manage batch-year mappings."""
    from .models import BatchMapping

    if request.method == 'POST':
        if 'delete' in request.POST:
            mapping_id = request.POST.get('mapping_id')
            try:
                BatchMapping.objects.get(id=mapping_id).delete()
                messages.success(request, 'Batch mapping deleted successfully.')
            except BatchMapping.DoesNotExist:
                messages.error(request, 'Batch mapping not found.')
        else:
            batch_code = request.POST.get('batch_code', '').strip()
            year = request.POST.get('year', '').strip()

            if not batch_code or not year:
                messages.error(request, 'Both batch code and year are required.')
            elif year not in ['1', '2', '3']:
                messages.error(request, 'Year must be 1, 2, or 3.')
            else:
                mapping, created = BatchMapping.objects.update_or_create(
                    batch_code=batch_code,
                    defaults={'year': year}
                )
                if created:
                    messages.success(request, f'Batch mapping for "{batch_code}" created successfully.')
                else:
                    messages.success(request, f'Batch mapping for "{batch_code}" updated successfully.')

        return redirect('seating:batch_mapping')

    mappings = BatchMapping.objects.all().order_by('batch_code')
    return render(request, 'seating/batch_mapping.html', {
        'mappings': mappings
    })


def allocation_pdf_view(request, allocation_id):
    """Generate and download PDF for allocation."""
    allocation = get_object_or_404(Allocation, id=allocation_id)

    # Always regenerate to reflect latest allocations
    media_root = getattr(settings, 'MEDIA_ROOT', None)

    try:
        from .utils.pdf_generator import generate_pdf

        seat_assignments = SeatAssignment.objects.filter(
            allocation=allocation
        ).select_related('room', 'student').order_by('room', 'bench_no', 'seat_pos')

        seating_by_room = {}
        for assignment in seat_assignments:
            room_id = assignment.room_id
            if room_id not in seating_by_room:
                seating_by_room[room_id] = []
            seating_by_room[room_id].append(assignment)

        # Use allocation.rooms.all() to ensure rooms are included even if assignments are empty
        rooms_list = list(allocation.rooms.all())

        # Log for debugging
        logger.info(f"PDF generation: {len(seat_assignments)} assignments, {len(rooms_list)} rooms")

        pdf_rel_path = generate_pdf(allocation, seating_by_room, rooms_list)

        if media_root:
            pdf_full_path = os.path.join(media_root, pdf_rel_path)
            if os.path.exists(pdf_full_path):
                with open(pdf_full_path, 'rb') as f:
                    response = HttpResponse(f.read(), content_type='application/pdf')
                    response['Content-Disposition'] = f'attachment; filename="{os.path.basename(pdf_rel_path)}"'
                    return response

        return HttpResponse("PDF generated but could not be read.", status=500)

    except ValueError as ve:
        # Handle validation errors like missing department
        return HttpResponse(f"Validation Error: {str(ve)}", status=400)
    except Exception as e:
        return HttpResponse(f"Error generating PDF: {str(e)}", status=500)


# =====================================================================
#                       SIMPLE CRUD API VIEWS
# =====================================================================

@api_view(['GET', 'POST'])
def student_list(request):
    if request.method == 'GET':
        students = Student.objects.all()
        serializer = StudentSerializer(students, many=True)
        return Response(serializer.data)
    elif request.method == 'POST':
        serializer   = StudentSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PUT', 'DELETE'])
def student_detail(request, pk):
    try:
        student = Student.objects.get(pk=pk)
    except Student.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = StudentSerializer(student)
        return Response(serializer.data)
    elif request.method == 'PUT':
        serializer = StudentSerializer(student, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    elif request.method == 'DELETE':
        student.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['GET', 'POST'])
def exam_list(request):
    if request.method == 'GET':
        exams = Exam.objects.all()
        serializer = ExamSerializer(exams, many=True)
        return Response(serializer.data)
    elif request.method == ['POST']:
        serializer = ExamSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'POST'])
def room_list(request):
    if request.method == 'GET':
        rooms = Room.objects.all()
        serializer = RoomSerializer(rooms, many=True)
        return Response(serializer.data)
    elif request.method == ['POST']:
        serializer = RoomSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
def allocation_list(request):
    allocations = Allocation.objects.all().prefetch_related('rooms', 'seat_assignments')
    serializer = AllocationSerializer(allocations, many=True)
    return Response(serializer.data)


@api_view(['DELETE'])
@csrf_exempt
def allocation_detail(request, pk):
    try:
        allocation = Allocation.objects.get(pk=pk)
    except Allocation.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    if request.method == 'DELETE':
        allocation.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# =====================================================================
#                       SUBJECT MANAGEMENT VIEWS
# =====================================================================

def subject_management_view(request):
    """Manage subjects: create, update, delete."""
    from .models import Subject

    if request.method == 'POST':
        if 'delete' in request.POST:
            subject_id = request.POST.get('subject_id')
            # perform delete without fetching full model (avoids selecting missing columns)
            deleted_count, _ = Subject.objects.filter(id=subject_id).delete()
            if deleted_count:
                messages.success(request, 'Subject deleted successfully.')
            else:
                messages.error(request, 'Subject not found.')
        else:
            subject_id = request.POST.get('subject_id')
            name = request.POST.get('name', '').strip()
            subject_code = request.POST.get('subject_code', '').strip()
            semester = request.POST.get('semester')

            if not name or not semester:
                messages.error(request, 'Name and semester are required.')
            elif semester not in ['1', '2', '3', '4', '5', '6']:
                messages.error(request, 'Semester must be between 1 and 6.')
            else:
                if subject_id:
                    # Update existing subject
                    try:
                        update_kwargs = {
                            'name': name,
                            'subject_code': subject_code or None,
                            'semester': int(semester),
                        }
                        updated = Subject.objects.filter(id=subject_id).update(**update_kwargs)

                        if updated:
                            messages.success(request, f'Subject "{name}" updated successfully.')
                        else:
                            messages.error(request, 'Subject not found.')
                    except Exception as e:
                        logger.error(f'Error updating subject "{name}": {str(e)}', exc_info=True)
                        messages.error(request, f'Error updating subject "{name}": {str(e)}')
                else:
                    # Create new subject
                    try:
                        # Check for existing subject with same name and semester
                        existing_count = Subject.objects.filter(
                            name__iexact=name,
                            semester=int(semester)
                        ).count()

                        if existing_count > 0:
                            messages.error(request, f'Subject "{name}" already exists for Semester {semester}.')
                            return redirect('seating:subject_management')

                        # Create subject
                        subject = Subject.objects.create(
                            name=name,
                            semester=int(semester),
                            subject_code=subject_code or None
                        )
                        messages.success(request, f'Subject "{name}" created successfully.')
                    except Exception as e:
                        logger.error(f'Error creating subject "{name}": {str(e)}', exc_info=True)
                        messages.error(request, f'Error creating subject "{name}": {str(e)}')

        return redirect('seating:subject_management')

    # GET: load subjects
    try:
        subjects_qs = Subject.objects.values('id', 'name', 'semester', 'subject_code').order_by('semester', 'name')
        subjects_by_semester = {}
        for subj in subjects_qs:
            sem_label = f"Semester {subj['semester']}"
            subjects_by_semester.setdefault(sem_label, []).append(subj)
    except Exception as e:
        logger.error(f'Error loading subjects: {str(e)}', exc_info=True)
        subjects_by_semester = {}

    return render(request, 'seating/subject_management.html', {
        'subjects': [],  # template should handle empty/new-style dicts
        'subjects_by_semester': subjects_by_semester
    })

@api_view(['DELETE'])
@csrf_exempt
def delete_subject(request, subject_id):
    """API endpoint to delete a subject."""
    # delete without loading full model to avoid missing-column errors
    deleted_count, _ = Subject.objects.filter(id=subject_id).delete()
    if deleted_count:
        return Response({'message': 'Subject deleted successfully.'}, status=status.HTTP_204_NO_CONTENT)
    return Response({'error': 'Subject not found.'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['GET'])
def get_subjects_by_semester(request):
    """API endpoint to get subjects filtered by semester."""
    semester = request.GET.get('semester')
    try:
        if semester:
            semester = int(semester)
            subjects = list(Subject.objects.filter(semester=semester).values('id', 'name', 'semester', 'subject_code').order_by('name'))
        else:
            subjects = list(Subject.objects.values('id', 'name', 'semester', 'subject_code').order_by('semester', 'name'))
    except OperationalError:
        return Response([], status=status.HTTP_200_OK)

    return Response(subjects)

@require_GET
def subjects_by_semester(request):
    """
    API: /seating/api/subjects/by-semester/?semester_type=odd|even
    Returns JSON: { "1": [{id,name,subject_code,semester_number}, ...], "2": [...], ... }
    Robust to Subject model field names (semester_number vs semester, is_active vs active).
    Uses .values() to avoid loading unmigrated columns.
    """
    sem_type = request.GET.get('semester_type', '').lower()
    if sem_type == 'odd':
        sems = [1,3,5,7]
    elif sem_type == 'even':
        sems = [2,4,6,8]
    else:
        sems = None

    # detect actual field names
    model_field_names = {f.name for f in Subject._meta.get_fields()}
    semester_field = 'semester_number' if 'semester_number' in model_field_names else ('semester' if 'semester' in model_field_names else None)
    active_field = 'is_active' if 'is_active' in model_field_names else ('active' if 'active' in model_field_names else None)

    # Build filter kwargs for safe fields
    filter_kwargs = {}
    if active_field:
        filter_kwargs[active_field] = True
    if semester_field and sems is not None:
        filter_kwargs[f"{semester_field}__in"] = sems

    # Build values() list: only fetch fields that exist in the current schema
    values_fields = ['id', 'name', 'subject_code']
    if semester_field:
        values_fields.append(semester_field)

    try:
        qs = Subject.objects.filter(**filter_kwargs).values(*values_fields)
        
        # safe ordering
        order_fields = []
        if semester_field:
            order_fields.append(semester_field)
        order_fields.append('name')
        qs = qs.order_by(*order_fields)

        result = {}
        for row in qs:
            sem_val = row.get(semester_field) if semester_field else None
            if sem_val is None:
                continue
            key = str(sem_val)
            result.setdefault(key, []).append({
                'id': row['id'],
                'name': row['name'],
                'subject_code': row.get('subject_code'),
                'semester_number': sem_val,
            })
        return JsonResponse(result)
    except Exception as e:
        logger.error(f'Error in subjects_by_semester: {str(e)}', exc_info=True)
        return JsonResponse({}, status=500)






