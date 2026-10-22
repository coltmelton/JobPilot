"""Profile fields and reusable history tables for the applicant editor."""

TEXT_SECTIONS = {
    'Contact details': {
        'first_name': 'Legal first name', 'middle_name': 'Middle name',
        'last_name': 'Legal last name', 'preferred_name': 'Preferred name',
        'email': 'Email', 'phone': 'Phone (include country code)',
        'address_line1': 'Street address', 'address_line2': 'Apartment / unit',
        'city': 'City', 'state': 'State / province', 'postal_code': 'ZIP / postal code',
        'country': 'Country', 'linkedin': 'LinkedIn URL', 'github': 'GitHub URL',
        'website': 'Portfolio URL',
    },
    'Career and availability': {
        'target_roles': 'Target roles', 'preferred_locations': 'Preferred locations',
        'available_start': 'Available start date / notice period',
        'compensation': 'Desired compensation (include currency and annual / hourly)',
        'travel': 'Travel availability', 'shift_preferences': 'Shift preferences',
        'skills': 'Technical skills / tools', 'languages': 'Languages and proficiency',
    },
}

CHOICES = {
    'work_authorization': ('Authorized to work in the United States', ['Yes', 'No']),
    'sponsorship_now': ('Require employment sponsorship now', ['Yes', 'No']),
    'sponsorship_future': ('Require employment sponsorship in the future', ['Yes', 'No']),
    'us_citizen': ('U.S. citizen (self-reported)', ['Yes', 'No']),
    'clearance_level': ('Clearance level (self-reported)', ['None', 'Confidential', 'Secret', 'Top Secret', 'Other']),
    'clearance_status': ('Clearance status (self-reported)', ['Active', 'Current eligibility / no current access', 'Previously held', 'In process', 'Never held', 'Unknown']),
    'clearance_process': ('Willing to undergo a required clearance process', ['Yes', 'No', 'Discuss with recruiter']),
    'relocation': ('Willing to relocate', ['Yes', 'No', 'Depends on location']),
    'work_arrangement': ('Preferred work arrangement', ['On-site', 'Hybrid', 'Remote', 'Flexible']),
    'employment_type': ('Employment type', ['Full-time', 'Part-time', 'Internship', 'Co-op', 'Contract', 'Flexible']),
}

HISTORY = {
    'education': ('Education', ['School', 'Degree', 'Major', 'Start date', 'Graduation / expected date', 'GPA (optional)']),
    'employment': ('Employment history', ['Employer', 'Title', 'Location', 'Start date', 'End date / Present', 'Responsibilities / accomplishments', 'Reason for leaving']),
    'certifications': ('Certifications', ['Certification', 'Issuer', 'Issued date', 'Expiration date']),
    'projects': ('Projects', ['Name', 'Technologies', 'Your contribution / results', 'URL']),
    'military': ('Military experience (optional)', ['Branch', 'Role / specialty', 'Start date', 'End date', 'Transferable skills']),
}

CHECKLIST = [
    'Read minimum qualifications and saved the requisition ID',
    'Reviewed citizenship / export-control wording in this posting',
    'Reviewed work authorization and sponsorship questions',
    'Reviewed required clearance level and whether it is needed at start',
    'Confirmed location, on-site work, shifts and travel requirements',
    'Selected a tailored resume and required supporting documents',
    'Reviewed education, employment dates and screening answers',
    'Reviewed every field and attachment in the employer portal',
]


def history_rows(rows, columns):
    """Return string-only nonempty rows suitable for JSON and the data editor."""
    return [
        {column: str(row.get(column) or '').strip() for column in columns}
        for row in rows
        if any(str(row.get(column) or '').strip() for column in columns)
    ]
