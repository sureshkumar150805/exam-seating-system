# seating/utils/parsers.py
import re
import logging
from typing import Any, Dict, List, Iterable, Tuple, Optional

logger = logging.getLogger(__name__)

# Import BatchMapping only here (models)
from ..models import BatchMapping

# Try pandas
try:
    import pandas as pd  # type: ignore
except Exception:
    pd = None


# -------------------- helpers --------------------

def roman_to_int(roman: Optional[Any]) -> Optional[int]:
    if roman is None:
        return None
    r = str(roman).strip().upper()
    mapping = {'I': 1, 'II': 2, 'III': 3}
    return mapping.get(r)


def parse_roll_number(roll: Any) -> Optional[Dict[str, Any]]:
    roll = str(roll).strip()
    # Pattern 1: 3 digits (batch) + 2–4 letters (dept) + 3–4 digits (serial)
    pattern1 = r'^(\d{3})([A-Za-z]{2,4})(\d{3,4})$'
    m1 = re.match(pattern1, roll)
    if m1:
        batch_code, dept_code, serial_str = m1.groups()
        try:
            serial = int(serial_str)
            return {'batch_code': batch_code, 'dept_code': dept_code.lower(), 'serial': serial}
        except ValueError:
            return None

    # Pattern 2: 3 letters (dept) + 2–4 alnum (batch) + 3–4 digits (serial)
    pattern2 = r'^([A-Za-z]{3})([A-Za-z0-9]{2,4})(\d{3,4})$'
    m2 = re.match(pattern2, roll)
    if m2:
        dept_code, batch_code, serial_str = m2.groups()
        try:
            serial = int(serial_str)
            return {'batch_code': batch_code, 'dept_code': dept_code.lower(), 'serial': serial}
        except ValueError:
            return None

    # Pattern 3: YYUG<DEPT><SERIAL> e.g., 24UGBCA00003
    pattern3 = r'^(\d{2})UG([A-Z]{2,4})(\d{3,5})$'
    m3 = re.match(pattern3, roll)
    if m3:
        batch_code, dept_code, serial_str = m3.groups()
        try:
            serial = int(serial_str)
            return {'batch_code': batch_code, 'dept_code': dept_code.lower(), 'serial': serial}
        except ValueError:
            return None

    return None


def batch_to_year(batch_code: Optional[str]) -> int:
    """Try DB mapping, else fall back to sensible default (1)."""
    if not batch_code:
        return 1
    try:
        mapping = BatchMapping.objects.get(batch_code=batch_code)
        return mapping.year
    except Exception:
        # fallback: if numeric, you might implement logic; default to 1
        try:
            if str(batch_code).isdigit():
                # Example quick heuristic (customise to your college rules):
                # You could map 231->1, 221->2, etc. But we return 1 as safe default.
                return 1
        except Exception:
            pass
    return 1


# -------------------- row parsing --------------------

def parse_student_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse a single row (dict / pandas Series) and return either parsed dict
    or {'error': '...', 'row': row}
    """
    def get_val(row_obj, keys):
        for k in keys:
            # handle both dict and pandas.Series
            if hasattr(row_obj, "get"):
                val = row_obj.get(k)
            else:
                # pandas Series supports __getitem__ but also .get; keep safe
                try:
                    val = row_obj[k]
                except Exception:
                    val = None
            if val is not None and str(val).strip() != "":
                return val
        return None

    roll_raw = get_val(row, ['roll', 'Roll', 'Roll Number', 'Roll No', 'ROLL', 'ROLL NO'])
    name_raw = get_val(row, ['name', 'Name', 'Student Name'])
    dept_raw = get_val(row, ['department', 'Department', 'Dept', 'Dept Code'])
    section_raw = get_val(row, ['section', 'Section', 'SECTION', 'Sec'])
    year_raw = get_val(row, ['year', 'Year', 'YEAR'])
    extra_raw = get_val(row, ['extra', 'Extra', 'Remarks'])

    roll = str(roll_raw).strip() if roll_raw is not None else ""
    name = str(name_raw).strip() if name_raw is not None else ""
    department = str(dept_raw).strip() if dept_raw is not None else None
    section = str(section_raw).strip().upper() if section_raw is not None else None

    if not roll or not name:
        return {'error': 'Missing roll or name', 'row': row}

    parsed_roll = parse_roll_number(roll)
    if not parsed_roll:
        return {'error': f'Invalid roll format: {roll}', 'row': row}

    # Year resolution: prefer explicit column, else batch mapping
    if year_raw is not None and str(year_raw).strip() != "":
        year = roman_to_int(year_raw)
        if year is None:
            # try numeric year (1/2/3) if user provided numbers
            try:
                year = int(year_raw)
                if year not in (1, 2, 3):
                    raise ValueError()
            except Exception:
                return {'error': f'Invalid year value: {year_raw} (expected I/II/III or 1/2/3)', 'row': row}
    else:
        year = batch_to_year(parsed_roll['batch_code'])

    return {
        'roll': roll,
        'name': name,
        'batch_code': parsed_roll['batch_code'],
        'dept_code': parsed_roll['dept_code'],
        'serial': parsed_roll['serial'],
        'year': year,
        'department': department,
        'section': section,
        'extra': str(extra_raw).strip() if extra_raw is not None else None,
    }


# -------------------- file parsing --------------------

def parse_excel_or_csv_file(file_obj) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Read uploaded file_obj (Django InMemoryUploadedFile or file-like),
    return (students_data, invalid_rows).
    """
    rows_iterable: List[Dict[str, Any]] = []

    # If pandas available, prefer it for robustness
    if pd is not None:
        from io import BytesIO, StringIO

        if hasattr(file_obj, "read"):
            content = file_obj.read()
            # reset pointer if file-like was read elsewhere (some frameworks)
            try:
                file_obj.seek(0)
            except Exception:
                pass

            if isinstance(content, bytes):
                file_name = getattr(file_obj, "name", "").lower()
                if file_name.endswith(".csv"):
                    df = pd.read_csv(BytesIO(content))
                else:
                    try:
                        df = pd.read_excel(BytesIO(content))
                    except Exception:
                        df = pd.read_csv(BytesIO(content))
            else:
                # text - treat as CSV
                df = pd.read_csv(StringIO(str(content)))
        else:
            # file_obj may be a path string
            fstr = str(file_obj)
            if fstr.lower().endswith(".csv"):
                df = pd.read_csv(fstr)
            else:
                df = pd.read_excel(fstr)

        rows_iterable = df.to_dict(orient="records")
    else:
        import csv
        from io import StringIO, TextIOWrapper

        if hasattr(file_obj, "read"):
            content = file_obj.read()
            if isinstance(content, bytes):
                try:
                    content = content.decode("utf-8")
                except Exception:
                    content = content.decode("latin-1", errors="ignore")
        else:
            with open(str(file_obj), "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

        reader = csv.DictReader(StringIO(content))
        rows_iterable = list(reader)

    # parse rows
    students_data: List[Dict[str, Any]] = []
    invalid_rows: List[Dict[str, Any]] = []

    for idx, row in enumerate(rows_iterable):
        try:
            parsed = parse_student_row(row)
            if "error" in parsed:
                invalid_rows.append({'row_number': idx + 2, 'error': parsed['error'], 'row_data': row})
            else:
                students_data.append(parsed)
        except Exception as e:
            logger.exception("Error parsing row %s: %s", idx + 2, e)
            invalid_rows.append({'row_number': idx + 2, 'error': str(e), 'row_data': row})

    logger.info("Parsed student file: %d valid rows, %d invalid rows", len(students_data), len(invalid_rows))
    return students_data, invalid_rows
