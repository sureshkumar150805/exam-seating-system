from django.urls import path
from . import views

app_name = 'seating'

urlpatterns = [
    # API Endpoints
    path('upload/', views.ExcelUploadView.as_view(), name='excel_upload'),
    path('generate_allocation/', views.GenerateAllocationView.as_view(), name='generate_allocation'),

    path('allocation/<int:allocation_id>/report/', views.AllocationReportView.as_view(), name='allocation_report'),
    path('allocation/<int:allocation_id>/preview/', views.AllocationPreviewView.as_view(), name='allocation_preview'),

    # CRUD API Endpoints
    path('students/', views.student_list, name='student_list'),
    path('students/<int:pk>/', views.student_detail, name='student_detail'),
    path('exams/', views.exam_list, name='exam_list'),
    path('rooms/', views.room_list, name='room_list'),
    path('allocations/', views.allocation_list, name='allocation_list'),
    path('allocations/<int:pk>/', views.allocation_detail, name='allocation_detail'),

    # Frontend Views
    path('', views.home_view, name='home'),
    path('upload-form/', views.upload_view, name='upload_form'),
    path('allocation-form/', views.allocation_form_view, name='allocation_form'),
    path('allocation-history/', views.allocation_history_view, name='allocation_history'),
    path('batch-mapping/', views.batch_mapping_view, name='batch_mapping'),
    path('uploaded-files/', views.uploaded_files_view, name='uploaded_files'),
    path('subject-management/', views.subject_management_view, name='subject_management'),
    path('preview/<int:allocation_id>/', views.preview_view, name='preview'),
    path('allocation/<int:allocation_id>/pdf/', views.allocation_pdf_view, name='allocation_pdf'),

    # Subject API Endpoints
    path('subjects/delete/<int:subject_id>/', views.delete_subject, name='delete_subject'),
    path('subjects/by-semester/', views.get_subjects_by_semester, name='get_subjects_by_semester'),
    path('api/subjects/by-semester/', views.subjects_by_semester, name='subjects_by_semester'),
    path('api/subjects/by-semester/', views.subjects_by_semester, name='api_subjects_by_semester'),
]
