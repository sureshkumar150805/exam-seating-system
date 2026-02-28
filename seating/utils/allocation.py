import math
import logging
import random
from collections import defaultdict, deque
from typing import List, Tuple, Dict, Deque, Set

# Try to use pandas if available; otherwise we'll fall back to csv
try:
    import pandas as pd  # type: ignore
except ImportError:  # pragma: no cover
    pd = None

from ..models import Student, SeatAssignment

logger = logging.getLogger(__name__)


def build_dynamic_pairings(available_groups: set[Tuple[int, str]], available_years: set[int]) -> List[Tuple[Tuple[int, str], Tuple[int, str]]]:
    """
    Builds dynamic pairings based on available years and sections.
    - If 3 years: Use cyclic pairing (1A+2B, 2B+3A, 3A+1B, 1B+2A, 2A+3B, 3B+1A).
    - If 2 years: Pair all possible combinations of existing sections from different years.
    - If 1 year: Special handling in allocation.
    Ensures no same year on bench.
    """
    if not available_groups or not available_years:
        return []

    sections_per_year: Dict[int, Set[str]] = defaultdict(set)
    for y, sec in available_groups:
        sections_per_year[y].add(sec)

    years = sorted(available_years)
    num_years = len(years)

    if num_years == 3:
        # Fixed 3-year cyclic sequence expected by hall plan:
        # 1) Y1-A + Y2-B
        # 2) Y2-B + Y3-A
        # 3) Y3-A + Y1-B
        # 4) Y1-B + Y2-A
        # 5) Y2-A + Y3-B
        # 6) Y3-B + Y1-A
        y1, y2, y3 = years[0], years[1], years[2]
        preferred_cycle = [
            ((y1, 'A'), (y2, 'B')),
            ((y2, 'B'), (y3, 'A')),
            ((y3, 'A'), (y1, 'B')),
            ((y1, 'B'), (y2, 'A')),
            ((y2, 'A'), (y3, 'B')),
            ((y3, 'B'), (y1, 'A')),
        ]

        pairings: List[Tuple[Tuple[int, str], Tuple[int, str]]] = [
            (g1, g2)
            for g1, g2 in preferred_cycle
            if g1 in available_groups and g2 in available_groups
        ]

        if pairings:
            return pairings

        # Fallback for unusual section names or incomplete data.
        cycle = [(y1, y2), (y2, y3), (y3, y1)]
        for fy1, fy2 in cycle:
            secs1 = sorted(sections_per_year.get(fy1, set()))
            secs2 = sorted(sections_per_year.get(fy2, set()))
            if not secs1 or not secs2:
                continue
            pairings.append(((fy1, secs1[0]), (fy2, secs2[0])))

        return pairings

    elif num_years == 2:
        # Pair all possible combinations of existing sections from different years
        y1, y2 = years
        pairings: List[Tuple[Tuple[int, str], Tuple[int, str]]] = []
        secs1 = sorted(sections_per_year.get(y1, set()))
        secs2 = sorted(sections_per_year.get(y2, set()))
        for sec1 in secs1:
            for sec2 in secs2:
                pairings.append(((y1, sec1), (y2, sec2)))
        return pairings

    elif num_years == 1:
        # For 1 year, handle in allocation (no pairing needed)
        return []

    else:
        # Fallback, though unlikely
        return []


def get_next_valid_pairing(pairings: List[Tuple[Tuple[int, str], Tuple[int, str]]], student_groups: Dict[Tuple[int, str], Deque[Student]], pairing_idx: int) -> Tuple[Tuple[int, str], Tuple[int, str]]:
    """
    Gets the next valid pairing in the cycle where both groups have remaining students.
    Cycles through pairings until finding one with students.
    """
    num_pairings = len(pairings)
    for i in range(num_pairings):
        idx = (pairing_idx + i) % num_pairings
        group1, group2 = pairings[idx]
        group1_deque = student_groups.get(group1, deque())
        group2_deque = student_groups.get(group2, deque())
        if group1_deque and group2_deque:  # Check if both deques have students
            return group1, group2
    # If no valid pairing, return the first (shouldn't happen if data is consistent)
    return pairings[0] if pairings else ((0, 'A'), (0, 'B'))


def group_students_by_year_section(
    student_queryset,
    *,
    distribution_strategy: str = "cycle",
    seed: int | None = None,
) -> Dict[Tuple[int, str], Deque[Student]]:
    """
    Groups students by (year, section) tuple.
    - cycle: keep roll-order sequence.
    - block: shuffle order within each (year, section) group.
    Returns a dict where key is (year, section), value is deque for stateful popping.
    """
    students = list(student_queryset.order_by('roll'))
    grouped_lists: Dict[Tuple[int, str], List[Student]] = defaultdict(list)
    for student in students:
        key = (student.year, student.section)
        grouped_lists[key].append(student)

    strategy = (distribution_strategy or "cycle").strip().lower()
    if strategy == "block":
        rng = random.Random(seed) if seed is not None else random.Random()
        for key, students_list in grouped_lists.items():
            # Block mode: randomize inside each half only.
            half = math.ceil(len(students_list) / 2)
            first_half = students_list[:half]
            second_half = students_list[half:]
            rng.shuffle(first_half)
            rng.shuffle(second_half)
            grouped_lists[key] = first_half + second_half

    return {key: deque(students_list) for key, students_list in grouped_lists.items()}


def calculate_pre_allocation_metrics(total_students: int, num_rooms: int) -> Tuple[int, int]:
    """
    Calculates students_per_room and max_per_group_in_room.
    students_per_room = ceil(total_students / num_rooms)
    max_per_group_in_room = ceil(students_per_room / 2)
    """
    students_per_room = math.ceil(total_students / num_rooms)
    max_per_group_in_room = math.ceil(students_per_room / 2)
    return students_per_room, max_per_group_in_room


def allocate_room_seats(
    allocation,
    room,
    group1_deque: Deque[Student],
    group2_deque: Deque[Student],
    bench_type: str,
    max_per_group_in_room: int,
    group1_room_limit: int | None = None,
    group2_room_limit: int | None = None,
) -> Tuple[List[SeatAssignment], int, int]:
    """
    Allocates seats for a single room with two groups using deques.
    Pops students from deques as they are seated, ensuring stateful allocation.
    Assigns bench-wise: left from group1, right from group2, alternating.
    Limits to at most max_per_group_in_room students from each group per room.
    Stops when both groups reach max_per_group_in_room or room is full.
    No students are skipped; allocation is sequential by roll.

    FIX: Only create SeatAssignment rows for actual students (student != None).
    Empty seats are derived in UI, not stored in DB.
    """
    assignments = []
    rows = room.rows
    cols = room.cols
    total_benches = rows * cols

    group1_count = 0
    group2_count = 0
    # If a per-group room limit is provided (half-split logic), do NOT cap it
    # by the global max_per_group_in_room, otherwise we under-allocate.
    group1_room_limit = max_per_group_in_room if group1_room_limit is None else min(group1_room_limit, len(group1_deque))
    group2_room_limit = max_per_group_in_room if group2_room_limit is None else min(group2_room_limit, len(group2_deque))

    for bench_no in range(1, total_benches + 1):
        # Stop if both groups have reached room limits
        if group1_count >= group1_room_limit and group2_count >= group2_room_limit:
            break

        # Calculate row and column: benches numbered column-wise
        col = ((bench_no - 1) // rows) + 1
        row = ((bench_no - 1) % rows) + 1

        # Left seat: pop from group1 if available and not at limit, create assignment only if student exists
        if group1_deque and group1_count < group1_room_limit:
            left_student = group1_deque.popleft()
            assignments.append(SeatAssignment(
                allocation=allocation,
                room=room,
                bench_no=bench_no,
                seat_pos='left',
                bench_type=bench_type,
                student=left_student,
                row=row,
                column=col,
                position='left'
            ))
            group1_count += 1

        # Right seat: pop from group2 if available and not at limit, create assignment only if student exists
        if group2_deque and group2_count < group2_room_limit:
            right_student = group2_deque.popleft()
            assignments.append(SeatAssignment(
                allocation=allocation,
                room=room,
                bench_no=bench_no,
                seat_pos='right',
                bench_type=bench_type,
                student=right_student,
                row=row,
                column=col,
                position='right'
            ))
            group2_count += 1

    return assignments, group1_count, group2_count


def allocate_room_seats_single_year(
    allocation,
    room,
    year_deque: Deque[Student],
    bench_type: str,
    room_limit: int | None = None,
) -> Tuple[List[SeatAssignment], int]:
    """
    Allocates seats for a single year: one student per bench, leaving the other seat empty.
    Pops students from deque as they are seated.

    FIX: Only create SeatAssignment rows for actual students (student != None).
    Empty seats are derived in UI, not stored in DB.
    """
    assignments = []
    rows = room.rows
    cols = room.cols
    total_benches = rows * cols

    used = 0
    for bench_no in range(1, total_benches + 1):
        if not year_deque:
            break
        if room_limit is not None and used >= room_limit:
            break

        # Calculate row and column: benches numbered column-wise
        col = ((bench_no - 1) // rows) + 1
        row = ((bench_no - 1) % rows) + 1

        # Left seat: pop from year_deque, create assignment only if student exists
        left_student = year_deque.popleft()
        assignments.append(SeatAssignment(
            allocation=allocation,
            room=room,
            bench_no=bench_no,
            seat_pos='left',
            bench_type=bench_type,
            student=left_student,
            row=row,
            column=col,
            position='left'
        ))
        used += 1

        # Right seat: empty - DO NOT create SeatAssignment row for empty seats

    return assignments, used


def generate_allocation(
    allocation,
    student_queryset,
    rooms,
    rows_per_room: int | None = None,
    cols_per_room: int | None = None,
    *,
    distribution_strategy: str = "block",
    seed: int | None = None,
    flip_lr: bool = False,
    **kwargs,
) -> dict:
    """
    Generates fully dynamic seating allocation with strict stopping conditions.

    ALLOCATION FLOW:
    1. Group students into deques by (year, section), sorted by roll.
    2. Detect available years and groups at runtime.
    3. Build dynamic pairings based on number of years.
    4. For each room, check if any students remain - if not, break.
    5. Select next valid pairing with remaining students.
    6. Allocate statefully: pop students from deques, assign bench-wise.
    7. Continue until all deques are empty.

    STOPPING CONDITION:
    - Allocation stops when no students remain in any group.
    - No empty rooms are created after students are exhausted.
    - Empty seats are allowed only when room capacity > remaining students.

    PAIRING RULES:
    - 3 years: Cyclic (1A+2B, 2B+3A, 3A+1B, 1B+2A, 2A+3B, 3B+1A)
    - 2 years: Alternating (Y1A+Y2B, Y1B+Y2A)
    - 1 year: One student per bench, other seat empty

    GUARANTEES:
    - Students allocated exactly once.
    - No same year on same bench.
    - Sequential by roll number.
    - No slicing or random shuffle.
    """
    logger.info("Starting fully dynamic allocation logic")

    # Delete old assignments
    SeatAssignment.objects.filter(allocation=allocation).delete()

    total_students = student_queryset.count()
    num_rooms = len(rooms)

    if total_students == 0 or num_rooms == 0:
        logger.warning("No students or rooms; allocation aborted.")
        return {"total_seats": 0, "rooms_processed": 0}

    # Calculate pre-allocation metrics
    students_per_room, max_per_group_in_room = calculate_pre_allocation_metrics(total_students, num_rooms)
    logger.info(f"Pre-allocation metrics: students_per_room={students_per_room}, max_per_group_in_room={max_per_group_in_room}")

    # Group students into deques: stateful allocation
    student_groups = group_students_by_year_section(
        student_queryset,
        distribution_strategy=distribution_strategy,
        seed=seed,
    )
    # Split each (year, section) into first/second halves so paired groups can
    # use complementary halves in the same room.
    group_half_queues: Dict[Tuple[int, str], Dict[str, Deque[Student]]] = {}
    for key, dq in student_groups.items():
        students_list = list(dq)
        half = math.ceil(len(students_list) / 2)
        group_half_queues[key] = {
            "first": deque(students_list[:half]),
            "second": deque(students_list[half:]),
        }

    # Rotate preferred half per group to keep rooms balanced over time.
    next_half_for_group: Dict[Tuple[int, str], str] = {
        key: "first" for key in group_half_queues.keys()
    }

    def remaining_count(group_key: Tuple[int, str]) -> int:
        halves = group_half_queues.get(group_key, {})
        return len(halves.get("first", deque())) + len(halves.get("second", deque()))

    def pick_half_queue(group_key: Tuple[int, str], preferred_half: str) -> Tuple[Deque[Student], str | None]:
        halves = group_half_queues.get(group_key, {})
        primary = halves.get(preferred_half)
        secondary_key = "second" if preferred_half == "first" else "first"
        secondary = halves.get(secondary_key)
        if primary and len(primary) > 0:
            return primary, preferred_half
        if secondary and len(secondary) > 0:
            return secondary, secondary_key
        return deque(), None

    # Bench types cycle: A, B, C, repeat
    bench_types = ['A', 'B', 'C']

    seating_assignments = []
    pairing_idx = 0  # Tracks current position in pairing cycle
    group_idx = 0  # Tracks current position for single-year group rotation
    rooms_processed = 0

    for room_idx, room in enumerate(rooms):
        # CRITICAL: Check if any students remain before allocating this room
        total_remaining = sum(remaining_count(k) for k in group_half_queues.keys())
        if total_remaining == 0:
            logger.info(f"No students remaining; stopping allocation after {rooms_processed} rooms")
            break

        # Recompute available groups/years dynamically based on remaining students
        available_groups = set(k for k in group_half_queues.keys() if remaining_count(k) > 0)
        available_years = set(year for year, _ in available_groups)
        logger.info(f"Available groups (remaining): {sorted(available_groups)}, Available years: {sorted(available_years)}")

        # Build dynamic pairings based on remaining years/groups
        pairings = build_dynamic_pairings(available_groups, available_years)
        logger.info(f"Dynamic pairings built (remaining): {pairings}")

        bench_type = bench_types[room_idx % len(bench_types)]
        room_assignments = []

        if len(available_years) == 1:
            # Single year: allocate one student per bench (other seat empty),
            # split each section into halves across rooms.
            group_order = sorted(available_groups)
            if not group_order:
                continue

            # Find next group with remaining students
            selected_group = None
            for _ in range(len(group_order)):
                candidate = group_order[group_idx % len(group_order)]
                group_idx += 1
                if remaining_count(candidate) > 0:
                    selected_group = candidate
                    break

            if selected_group is None:
                continue

            preferred_half = next_half_for_group.get(selected_group, "first")
            year_deque, used_half = pick_half_queue(selected_group, preferred_half)
            room_limit = len(year_deque)

            logger.info(
                "Room %s: Single year group %s allocation, Half=%s, Bench type %s, Remaining students: %s",
                room.name, selected_group, used_half, bench_type, len(year_deque)
            )

            room_assignments, used = allocate_room_seats_single_year(
                allocation=allocation,
                room=room,
                year_deque=year_deque,
                bench_type=bench_type,
                room_limit=room_limit,
            )
            if used_half:
                next_half_for_group[selected_group] = "second" if used_half == "first" else "first"
        else:
            # Multi-year: use pairings
            selected_pair_idx = None
            group1_key = None
            group2_key = None
            for i in range(len(pairings)):
                idx = (pairing_idx + i) % len(pairings)
                candidate_g1, candidate_g2 = pairings[idx]
                if remaining_count(candidate_g1) > 0 and remaining_count(candidate_g2) > 0:
                    selected_pair_idx = idx
                    group1_key, group2_key = candidate_g1, candidate_g2
                    break
            if selected_pair_idx is None or group1_key is None or group2_key is None:
                continue
            pairing_idx = (selected_pair_idx + 1) % len(pairings) if pairings else 0

            g1_pref = next_half_for_group.get(group1_key, "first")
            g2_pref = "second" if g1_pref == "first" else "first"
            group1_deque, g1_half = pick_half_queue(group1_key, g1_pref)
            group2_deque, g2_half = pick_half_queue(group2_key, g2_pref)

            logger.info(f"Room {room.name}: Pairing {group1_key} + {group2_key}, Bench type {bench_type}, Group1 remaining: {len(group1_deque)}, Group2 remaining: {len(group2_deque)}")

            room_assignments, group1_used, group2_used = allocate_room_seats(
                allocation=allocation,
                room=room,
                group1_deque=group1_deque,
                group2_deque=group2_deque,
                bench_type=bench_type,
                max_per_group_in_room=max_per_group_in_room,
                group1_room_limit=len(group1_deque),
                group2_room_limit=len(group2_deque),
            )

            if g1_half:
                next_half_for_group[group1_key] = "second" if g1_half == "first" else "first"
            if g2_half:
                next_half_for_group[group2_key] = "second" if g2_half == "first" else "first"

        # Only count this room if it has assignments
        if room_assignments:
            seating_assignments.extend(room_assignments)
            rooms_processed += 1
        else:
            logger.info(f"Room {room.name}: No assignments made, skipping")

    # Bulk create assignments
    if seating_assignments:
        SeatAssignment.objects.bulk_create(seating_assignments)

    saved_count = len(seating_assignments)
    logger.info(f"Allocated {saved_count} seats across {rooms_processed} rooms")

    return {"total_seats": saved_count, "rooms_processed": rooms_processed}


def group_students_by_year(students):
    """
    Group students by their year.

    Args:
        students: Iterable of Student objects.

    Returns:
        Dict[int, list[Student]]: {year: [student1, student2, ...]}
    """
    year_groups: dict[int, list[Student]] = defaultdict(list)
    for student in students:
        year = getattr(student, "year", None)
        if year is not None:
            year_groups[int(year)].append(student)
    return dict(year_groups)


def parse_excel_or_csv_file(file_obj):
    """
    Parse Excel or CSV file containing student data.
    Uses pandas if available, falls back to Python's csv module.

    The underlying row parsing logic is delegated to parse_student_row,
    which must return either:
        {"error": "message", "row": original_row_dict}
    or a valid student dict:
        {"roll": ..., "name": ..., "year": ..., "department": ..., "extra": ..., ...}

    Returns:
        (students_data, invalid_rows)
        students_data: list of valid parsed student dicts
        invalid_rows: list of {"row_number", "error", "row_data"}
    """
    # ---------------- Read file into a tabular `rows` list ----------------
    if pd is not None:
        from io import BytesIO, StringIO

        if hasattr(file_obj, "read"):
            # File-like object from Django upload
            content = file_obj.read()
            # Excel or CSV?
            if isinstance(content, bytes):
                # Try Excel first
                try:
                    df = pd.read_excel(BytesIO(content))
                except Exception:
                    # Not a valid Excel, try CSV
                    df = pd.read_csv(BytesIO(content))
            else:
                # Content is text -> CSV
                df = pd.read_csv(StringIO(content))
        else:
            # file_obj is a filesystem path
            file_str = str(file_obj)
            if file_str.lower().endswith(".csv"):
                df = pd.read_csv(file_str)
            else:
                df = pd.read_excel(file_str)

        rows_iterable = df.to_dict(orient="records")
    else:
        # No pandas: fall back to csv only
        import csv
        from io import StringIO

        if hasattr(file_obj, "read"):
            content = file_obj.read()
            if isinstance(content, bytes):
                content = content.decode("utf-8", errors="ignore")
        else:
            with open(file_obj, "r", encoding="utf-8") as f:
                content = f.read()

        reader = csv.DictReader(StringIO(content))
        rows_iterable = list(reader)

    # ---------------- Parse rows using custom parser ----------------
    from .parsers import parse_student_row

    students_data: list[dict] = []
    invalid_rows: list[dict] = []

    for idx, row in enumerate(rows_iterable):
        parsed = parse_student_row(row)
        if "error" in parsed:
            invalid_rows.append(
                {
                    "row_number": idx + 2,  # +2: human row (1-based) + header row
                    "error": parsed["error"],
                    "row_data": parsed["row"],
                }
            )
        else:
            students_data.append(parsed)

    logger.info(
        "Parsed student file: %d valid rows, %d invalid rows",
        len(students_data),
        len(invalid_rows),
    )

    return students_data, invalid_rows







