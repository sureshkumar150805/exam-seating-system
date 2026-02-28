"""
Helper functions for bench type patterns and year mappings.
"""

def get_bench_type_for_bench(bench_no, cycles=['A', 'B', 'C']):
    """
    Get bench type for a given bench number, cycling through the provided cycles.

    Args:
        bench_no: Bench number (1-based)
        cycles: List of bench types to cycle through, default ['A', 'B', 'C']

    Returns:
        Bench type string ('A', 'B', 'C', etc.)
    """
    index = (bench_no - 1) % len(cycles)
    return cycles[index]

def get_year_pair_for_bench_type(bench_type):
    """
    Get the year pair for a given bench type.

    Args:
        bench_type: Bench type ('A', 'B', 'C')

    Returns:
        Tuple of (left_year, right_year) as strings
    """
    mapping = {
        'A': ('1', '2'),  # Year1, Year2
        'B': ('2', '3'),  # Year2, Year3
        'C': ('3', '1'),  # Year3, Year1
    }
    return mapping.get(bench_type, ('1', '2'))  # Default to A if unknown

def get_bench_pattern_for_room(room, cycles=['A', 'B', 'C']):
    """
    Generate bench pattern for a room.

    Args:
        room: Room object with benches attribute
        cycles: List of bench types to cycle through

    Returns:
        Dict mapping bench_no to bench_type
    """
    pattern = {}
    for bench_no in range(1, room.benches + 1):
        pattern[bench_no] = get_bench_type_for_bench(bench_no, cycles)
    return pattern
