import os
import json
from django.conf import settings
from django.core.files.base import ContentFile

def save_allocation_report(allocation, seating_by_room, room_students_map, extra_meta=None):
	"""
	Write JSON allocation report under MEDIA_ROOT/reports/allocation_{id}.json.
	Also update MEDIA_ROOT/reports/index.json mapping allocation.id -> filename.
	Returns the full filesystem path to the saved report.
	"""
	reports_dir = os.path.join(getattr(settings, 'MEDIA_ROOT', '.'), 'reports')
	os.makedirs(reports_dir, exist_ok=True)
	report_path = os.path.join(reports_dir, f'allocation_report_{allocation.id}.json')

	# build simple serializable report
	report = {
		'allocation': {
			'id': allocation.id,
			'name': getattr(allocation, 'name', None),
			'exam': {
				'id': allocation.exam.id,
				'name': allocation.exam.name,
				'date': str(allocation.exam.date),
				'year': getattr(allocation.exam, 'year', None)
			},
			'num_rooms': getattr(allocation, 'num_rooms', None),
			'benches_per_room': getattr(allocation, 'benches_per_room', None),
			'created_at': str(getattr(allocation, 'created_at', None)),
		},
		'rooms': {},
		'extra_meta': extra_meta or {}
	}
	# per-room summary from room_students_map and seating_by_room
	for room_id, students_by_year in room_students_map.items():
		year_counts = {'1': len(students_by_year['1']), '2': len(students_by_year['2']), '3': len(students_by_year['3']), 'empty': 0}
		# Count empty from seating_by_room
		assigns = seating_by_room.get(room_id, [])
		empty_count = sum(1 for a in assigns if a.get('student') is None)
		year_counts['empty'] = empty_count
		report['rooms'][str(room_id)] = {
			'counts': year_counts,
			'total_assigned': sum(v for k,v in year_counts.items() if k != 'empty'),
			'total_empty': year_counts['empty']
		}
	# write report
	with open(report_path, 'w', encoding='utf-8') as f:
		json.dump(report, f, indent=2, default=str)

	# update index
	index_path = os.path.join(reports_dir, 'index.json')
	index_data = {}
	if os.path.exists(index_path):
		try:
			with open(index_path, 'r', encoding='utf-8') as f:
				index_data = json.load(f)
		except Exception:
			index_data = {}
	index_data[str(allocation.id)] = os.path.basename(report_path)
	with open(index_path, 'w', encoding='utf-8') as f:
		json.dump(index_data, f, indent=2)

	# attempt to save onto allocation.report_file if the model has that field
	try:
		if hasattr(allocation, 'report_file'):
			with open(report_path, 'rb') as f:
				allocation.report_file.save(os.path.basename(report_path), ContentFile(f.read()), save=True)
	except Exception:
		# ignore if saving to model field fails
		pass

	return report_path
