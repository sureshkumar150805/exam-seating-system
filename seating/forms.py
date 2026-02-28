from django import forms
from .models import Subject

class AllocationValidationForm(forms.Form):
    semester_type = forms.ChoiceField(choices=(('odd','Odd'),('even','Even')))
    # dynamic fields subject_year_X will be in POST; we'll validate in clean()

    def __init__(self, *args, detected_years=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.detected_years = detected_years or []

    def clean(self):
        cleaned = super().clean()
        sem_type = cleaned.get('semester_type')
        if not sem_type:
            raise forms.ValidationError("Semester type is required.")

        year_to_sem = {
            'odd': {1:1,2:3,3:5,4:7},
            'even':{1:2,2:4,3:6,4:8}
        }[sem_type]

        # determine actual semester field name on Subject model
        model_field_names = {f.name for f in Subject._meta.get_fields()}
        semester_field = 'semester_number' if 'semester_number' in model_field_names else ('semester' if 'semester' in model_field_names else None)

        selected = {}
        for y in self.detected_years:
            field = f"subject_year_{y}"
            val = self.data.get(field)
            if not val:
                raise forms.ValidationError(f"Subject for Year {y} is required.")
            try:
                subj = Subject.objects.get(pk=int(val))
            except (Subject.DoesNotExist, ValueError):
                raise forms.ValidationError(f"Invalid subject selected for Year {y}.")

            subj_sem = getattr(subj, semester_field, None) if semester_field else None
            expected_sem = year_to_sem.get(int(y))
            if subj_sem != expected_sem:
                raise forms.ValidationError(f"Selected subject for Year {y} must be for Semester {expected_sem}.")
            selected[y] = subj.id

        # ensure one subject per year checked by loop above
        cleaned['selected_subjects'] = selected
        return cleaned