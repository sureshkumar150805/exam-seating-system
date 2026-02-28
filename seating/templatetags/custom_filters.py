from django import template

register = template.Library()

@register.filter
def ordinal(value):
    """
    Converts an integer to its ordinal representation.
    For example: 1 -> 1st, 2 -> 2nd, 3 -> 3rd, etc.
    """
    try:
        value = int(value)
    except (ValueError, TypeError):
        return value

    if 11 <= (value % 100) <= 13:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(value % 10, 'th')

    return f"{value}{suffix}"
