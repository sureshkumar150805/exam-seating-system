import logging
import os
from datetime import datetime
from pathlib import Path

from django.conf import settings

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import cm, mm

logger = logging.getLogger(__name__)


def generate_pdf(allocation, seating_by_room, rooms_list):
    """
    Generate professional, formal PDF for exam seating allocation.

    Format:
    - Professional header with institution details
    - Exam details section (properly formatted)
    - Benches in organized grid with clear boxes
    - Year-wise student summary (individual boxes per year)
    - Signature section on last page
    """
    logger.info(f"generate_pdf called with {len(rooms_list)} rooms, seating_by_room keys: {list(seating_by_room.keys())}")

    # Fetch department name from allocation
    department = allocation.department
    if not department or not department.strip():
        raise ValueError("Department is not configured. Please set the department in Exam Configuration before downloading the PDF.")

    # Save PDF
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'allocation_{allocation.id}_{timestamp}.pdf'
    rel_path = f'pdfs/{filename}'
    full_path = Path(settings.MEDIA_ROOT) / rel_path
    full_path.parent.mkdir(parents=True, exist_ok=True)

    c = canvas.Canvas(str(full_path), pagesize=A4)
    width, height = A4

    left_margin = 25
    right_margin = 25
    top_margin = 35
    content_width = width - left_margin - right_margin

    is_last_room = False
    
    for room_idx, room in enumerate(rooms_list):
        is_last_room = (room_idx == len(rooms_list) - 1)
        
        # Reset y position for new page
        y = height - top_margin

        # ===== FORMAL HEADER =====
        # Institution Name - centered, bold, larger
        c.setFont('Helvetica-Bold', 14)
        c.drawCentredString(width / 2, y, allocation.institution_name)
        y -= 18

        # Academic Year - centered
        c.setFont('Helvetica', 9)
        semester_display = allocation.semester_type.capitalize() if allocation.semester_type else ""
        c.drawCentredString(width / 2, y, f"{semester_display} Semester - Academic Year: {allocation.academic_year}")
        y -= 14

        # Subject/Department - centered, bold
        c.setFont('Helvetica-Bold', 10)
        c.drawCentredString(width / 2, y, department)
        y -= 16

        # Horizontal line for separation
        c.setLineWidth(2)
        c.line(left_margin, y, width - right_margin, y)
        y -= 12

        # ===== EXAM DETAILS SECTION (IMPROVED) =====
        c.setFont('Helvetica-Bold', 9)
        c.drawString(left_margin, y, "EXAM DETAILS")
        y -= 10

        # Draw exam details box with better formatting
        exam_details = []
        exam_details.append(f"Exam Name: {allocation.exam.name}")
        exam_details.append(f"Date: {allocation.exam.date.strftime('%d-%m-%Y')}")

        # Build subject lines: one subject per line, wrapped to fit box width.
        subjects = list(allocation.subjects.all())
        if subjects:
            exam_details.append("Subjects:")

            max_text_width = content_width - 18  # inner box padding
            indent = "  - "
            wrap_indent = "    "

            for s in subjects:
                subject_label = f"{s.name}" + (f" ({s.subject_code})" if s.subject_code else "")
                words = subject_label.split(" ")

                current_line = indent
                for word in words:
                    candidate = f"{current_line}{word} "
                    if c.stringWidth(candidate, 'Helvetica', 8) <= max_text_width:
                        current_line = candidate
                    else:
                        exam_details.append(current_line.rstrip())
                        current_line = f"{wrap_indent}{word} "
                exam_details.append(current_line.rstrip())
        else:
            exam_details.append("Subjects: -")

        # Calculate box height based on all rendered lines
        line_height = 10
        box_height = 15 + (len(exam_details) * line_height)
        
        c.setLineWidth(1)
        c.rect(left_margin, y - box_height, content_width, box_height, fill=0)
        
        # Details inside box
        c.setFont('Helvetica', 8)
        detail_y = y - 10
        
        for detail in exam_details:
            c.drawString(left_margin + 5, detail_y, detail)
            detail_y -= line_height
        
        y -= box_height + 12

        # ===== ROOM & SEATING SECTION =====
        assignments = seating_by_room.get(room.id, [])

        # Derive year and section from students
        year = None
        section = None
        for assignment in assignments:
            if assignment.student and year is None:
                year = assignment.student.year
                section = assignment.student.roll[3].upper() if len(assignment.student.roll) >= 4 else 'A'
                section = section if section in ['A', 'B'] else 'A'
                break

        # Room Header - Bold
        c.setFont('Helvetica-Bold', 9)
        room_title = room.name
        c.drawCentredString(width / 2, y, room_title)
        y -= 12

        # ===== BENCHES IN PROFESSIONAL GRID FORMAT =====
        if not assignments:
            c.setFont('Helvetica', 8)
            c.drawString(left_margin, y, "No seat assignments found for this room.")
            y -= 20
            _add_page_footer(c, width, left_margin)
            c.showPage()
            continue
        # Collect benches
        bench_dict = {}
        for a in assignments:
            bench_key = f"{a.row}-{a.column}"
            if bench_key not in bench_dict:
                bench_dict[bench_key] = {
                    'bench_no': a.bench_no,
                    'row': a.row,
                    'column': a.column,
                    'left': None,
                    'right': None,
                }
            if a.position == 'left':
                bench_dict[bench_key]['left'] = a.student.roll if a.student else 'Empty'
            else:
                bench_dict[bench_key]['right'] = a.student.roll if a.student else 'Empty'

        benches = sorted(bench_dict.values(), key=lambda b: (b['row'], b['column']))

        # Draw benches in grid format (use room cols, fallback to 5)
        bench_width = 75
        bench_height = 40
        spacing = 5
        cols = room.cols if getattr(room, "cols", None) else 5
        # Calculate centered x_start
        grid_width = cols * bench_width + (cols - 1) * spacing
        x_start = left_margin + (content_width - grid_width) / 2
        y_start = y - 40

        row_count = 0
        for bench in benches:
            # Keep exact placement same as preview: use stored seat row/column.
            row = max(int(bench.get('row', 1)) - 1, 0)
            col = max(int(bench.get('column', 1)) - 1, 0)
            x = x_start + col * (bench_width + spacing)
            yy = y_start - row * (bench_height + spacing)

            # Check if we need a new page
            if yy < 120:
                _add_page_footer(c, width, left_margin)
                c.showPage()
                y = height - top_margin
                _draw_page_header(c, width, allocation, department, left_margin, y)
                y -= 80
                y_start = y
                yy = y_start - row * (bench_height + spacing)

            # Draw bench box with border
            c.setLineWidth(0.8)
            c.setFillColor(colors.HexColor('#F5F5F5'))  # Light gray background
            c.rect(x, yy, bench_width, bench_height, fill=1)  # Filled
            
            # Border
            c.setLineWidth(0.8)
            c.setStrokeColor(colors.black)
            c.rect(x, yy, bench_width, bench_height, fill=0)

            # Bench number header - bold
            c.setFont('Helvetica-Bold', 7)
            c.setFillColor(colors.black)
            c.drawString(x + 3, yy + bench_height - 7, f"Bench {bench['bench_no']}")

            # Divider line
            c.setLineWidth(0.5)
            c.line(x + 2, yy + bench_height - 11, x + bench_width - 2, yy + bench_height - 11)

            # Student IDs
            c.setFont('Helvetica', 6.5)
            c.drawString(x + 3, yy + 20, f"L: {bench['left']}")
            c.drawString(x + 3, yy + 9, f"R: {bench['right']}")

        # Move y below seating
        rows = (len(benches) + cols - 1) // cols
        y = y_start - rows * (bench_height + spacing) - 15

        # ===== LEGEND =====
        if y < 130:
            _add_page_footer(c, width, left_margin)
            c.showPage()
            y = height - top_margin
            _draw_page_header(c, width, allocation, department, left_margin, y)
            y -= 80
        
        c.setFont('Helvetica', 7)
        c.drawString(left_margin, y, "Legend: L = Left Seat | R = Right Seat")
        y -= 15

        # ===== YEAR-WISE STUDENT SUMMARY (BOXED) =====
        c.setFont('Helvetica-Bold', 8)
        c.drawString(left_margin, y, "STUDENT SUMMARY")
        y -= 12

        year_rolls = {1: [], 2: [], 3: []}
        for a in assignments:
            if a.student:
                year_rolls[a.student.year].append(a.student.roll)

        for yr in year_rolls:
            year_rolls[yr].sort()

        year_names = {1: 'YEAR I', 2: 'YEAR II', 3: 'YEAR III'}

        for yr in [1, 2, 3]:
            if year_rolls[yr]:
                rolls = year_rolls[yr]
                count = len(rolls)

                # Check page overflow (reserve space for signature if last room)
                reserve_space = 80 if is_last_room else 20
                if y < reserve_space + 70:
                    _add_page_footer(c, width, left_margin)
                    c.showPage()
                    y = height - top_margin
                    _draw_page_header(c, width, allocation, department, left_margin, y)
                    y -= 80

                # Calculate text height for word wrapping
                c.setFont('Helvetica', 7)
                roll_text = ", ".join(rolls)
                words = roll_text.split(", ")
                lines = []
                line = ""
                for word in words:
                    test_line = line + word + ", " if line else word + ", "
                    test_width = c.stringWidth(test_line, 'Helvetica', 7)
                    if test_width > content_width - 40:
                        if line:
                            lines.append(line.rstrip(", "))
                        line = word + ", "
                    else:
                        line = test_line
                if line:
                    lines.append(line.rstrip(", "))

                # Year box height calculation
                header_height = 18
                lines_height = len(lines) * 8
                box_height = header_height + lines_height + 10

                # Draw box
                c.setLineWidth(0.8)
                c.setFillColor(colors.HexColor('#FFFFFF'))
                c.rect(left_margin, y - box_height, content_width, box_height, fill=1)
                
                # Border
                c.setLineWidth(0.8)
                c.setStrokeColor(colors.black)
                c.rect(left_margin, y - box_height, content_width, box_height, fill=0)

                # Year header inside box
                c.setFont('Helvetica-Bold', 8)
                c.setFillColor(colors.black)
                c.drawString(left_margin + 5, y - 10, f"{year_names[yr]} - Total Students: {count}")
                
                # Line separator
                c.setLineWidth(0.5)
                c.line(left_margin + 5, y - 14, content_width - 5, y - 14)

                # Students list inside box
                c.setFont('Helvetica', 7)
                line_y = y - 22
                for line_text in lines:
                    c.drawString(left_margin + 5, line_y, line_text)
                    line_y -= 8

                y -= box_height + 8

        # ===== SIGNATURE SECTION (ONLY ON LAST ROOM) =====
        if is_last_room:
            if y < 100:
                _add_page_footer(c, width, left_margin)
                c.showPage()
                y = height - top_margin
                _draw_page_header(c, width, allocation, department, left_margin, y)
                y -= 80

            y -= 30

            # Signature section
            c.setFont('Helvetica-Bold', 9)
            c.drawString(left_margin, y, "AUTHORIZED SIGNATURES")
            y -= 15

            # Exam Incharge Signature (LEFT)
            sig_line_x1 = left_margin
            sig_line_width = (content_width - 20) / 2
            
            c.setLineWidth(0.5)
            c.line(sig_line_x1, y - 30, sig_line_x1 + sig_line_width - 10, y - 30)
            c.setFont('Helvetica-Bold', 8)
            sig_center_x1 = sig_line_x1 + (sig_line_width - 10) / 2
            c.drawCentredString(sig_center_x1, y - 45, "Exam Incharge")
            c.setFont('Helvetica', 7)
            c.drawCentredString(sig_center_x1, y - 52, "(Signature & Date)")

            # HOD Signature (RIGHT)
            sig_line_x2 = left_margin + sig_line_width + 20
            c.setLineWidth(0.5)
            c.line(sig_line_x2, y - 30, sig_line_x2 + sig_line_width - 10, y - 30)
            c.setFont('Helvetica-Bold', 8)
            sig_center_x2 = sig_line_x2 + (sig_line_width - 10) / 2
            c.drawCentredString(sig_center_x2, y - 45, "HOD")
            c.setFont('Helvetica', 7)
            c.drawCentredString(sig_center_x2, y - 52, "(Head of Department)")

        _add_page_footer(c, width, left_margin)
        c.showPage()

    c.save()
    return rel_path


def _draw_page_header(c, width, allocation, department, left_margin, y):
    """Draw standard page header."""
    # Institution Name
    c.setFont('Helvetica-Bold', 14)
    c.drawCentredString(width / 2, y, allocation.institution_name)
    y -= 14

    # Academic Year
    c.setFont('Helvetica', 9)
    semester_display = allocation.semester_type.capitalize() if allocation.semester_type else ""
    c.drawCentredString(width / 2, y, f"{semester_display} Semester - Academic Year: {allocation.academic_year}")
    y -= 10

    # Subject/Department
    c.setFont('Helvetica-Bold', 10)
    c.drawCentredString(width / 2, y, department)
    y -= 12

    # Horizontal line
    c.setLineWidth(2)
    c.line(left_margin, y, width - left_margin - 25, y)


def _add_page_footer(c, width, left_margin):
    """Add footer with generation timestamp."""
    c.setFont('Helvetica', 7)
    c.setFillColor(colors.grey)
    c.drawString(left_margin, 15, f"Generated on: {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}")
