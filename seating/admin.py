from django.contrib import admin
from django.apps import apps

# Get Subject model if present
Subject = apps.get_model('seating', 'Subject')

if Subject is not None:
    # Determine which preferred fields actually exist on the model
    model_field_names = {f.name for f in Subject._meta.get_fields()}

    preferred_display = ('name', 'subject_code', 'semester_number', 'is_active')
    preferred_filters = ('semester_number', 'is_active')
    preferred_ordering = ('semester_number', 'name')

    list_display = [f for f in preferred_display if f in model_field_names]
    if not list_display:
        list_display = ('pk',)

    list_filter = [f for f in preferred_filters if f in model_field_names]
    ordering = tuple([f for f in preferred_ordering if f in model_field_names])

    @admin.register(Subject)
    class SubjectAdmin(admin.ModelAdmin):
        list_display = list_display
        list_filter = list_filter
        search_fields = tuple(f for f in ('name', 'subject_code') if f in model_field_names)
        ordering = ordering if ordering else None
else:
    # Fallback: do nothing if model isn't available (prevents import-time errors)
    pass