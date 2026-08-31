"""Lock the column mapping for the current (August 2025) application form, whose
real headers differ from the older form: 'Full Name', 'Email Address',
'Which roles are you applying for? ' (trailing space), 'Attach Your Resume', and
a long multi-line 'Portfolio / Work Samples Link ...' header.
"""
from app.intake.google_forms import _resolve_columns

# Exact headers read from the live sheet.
NEW_FORM_HEADER = [
    "Timestamp",
    "Stage",
    "Comments",
    "Full Name",
    "Email Address",
    "Phone / WhatsApp Number ",
    "Location (City & Country) ",
    "This role requires full-time commitment. Please confirm:",
    "Which roles are you applying for? ",
    "Experience Level",
    "Briefly describe what you currently do (or last role)",
    "Attach Your Resume",
    "Portfolio / Work Samples Link \nShare ONE link only. (Google Drive, Notion, Behance)",
    "Why do you want to work at Catalist Media?",
]


def test_new_form_columns_resolve(monkeypatch):
    monkeypatch.delenv("FORM_ROLE_COLUMN", raising=False)
    col = _resolve_columns(NEW_FORM_HEADER)
    assert col["name"] == "Full Name"
    assert col["email"] == "Email Address"
    assert col["cv"] == "Attach Your Resume"
    assert col["role"] == "Which roles are you applying for? "
    assert col["portfolio"].startswith("Portfolio / Work Samples Link")
