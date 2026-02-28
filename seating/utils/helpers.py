from django.db.models import QuerySet
from django.core.exceptions import ObjectDoesNotExist
from ..models import Room
from collections import defaultdict


def bench_to_row_col(bench, cols):
    """
    Convert bench number to row and column (1-based indexing).
    Assumes benches are numbered row-major order.
    """
    row = (bench - 1) // cols + 1
    col = (bench - 1) % cols + 1
    return row, col


def ensure_room_qs(rooms, RoomModel=Room):
    """
    Accepts:
      - rooms: QuerySet[Room] | list[Room] | list[int] | int | Room
    Returns:
      - QuerySet[Room] (possibly empty)
    Raises:
      - ValueError if input is invalid
    """
    if isinstance(rooms, QuerySet):
        return rooms
    if isinstance(rooms, RoomModel):
        return RoomModel.objects.filter(pk=rooms.pk)
    if isinstance(rooms, int):
        return RoomModel.objects.filter(pk=rooms)
    # list/tuple of ints or Room objects
    if isinstance(rooms, (list, tuple, set)):
        # if list of ints
        if all(isinstance(x, int) for x in rooms):
            return RoomModel.objects.filter(pk__in=list(rooms))
        # if list of Room instances
        if all(hasattr(x, 'pk') for x in rooms):
            pks = [x.pk for x in rooms]
            return RoomModel.objects.filter(pk__in=pks)
    raise ValueError("Invalid rooms parameter; expected queryset, model instance, id or list")


def group_students_by_year(students):
    """
    Group students by year globally.

    Args:
        students: List of Student objects

    Returns:
        Dict {"1": [...], "2": [...], "3": [...]}
    """
    students_by_year = defaultdict(list)
    for student in students:
        if student.year is not None:
            year = str(student.year)
            students_by_year[year].append(student)
    return dict(students_by_year)


def cycle_bench_patterns():
    """
    Generator that cycles through bench patterns: (Y1,Y2), (Y2,Y3), (Y3,Y1), repeat.

    Yields:
        Tuple (left_year, right_year) as strings "1", "2", "3"
    """
    pattern = [('1', '2'), ('2', '3'), ('3', '1')]
    index = 0
    while True:
        yield pattern[index % len(pattern)]
        index += 1


def safe_pop(year_list):
    """
    Safely pop the first student from a year list.

    Args:
        year_list: List of Student objects for a year

    Returns:
        Student object or None if list is empty
    """
    if year_list:
        return year_list.pop(0)
    return None
