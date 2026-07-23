"""
Candidate Manager for centralized profile handling.
Stores candidate details (personal info, CV path, work history, education, credentials)
in tmp/candidates.json and dynamically formats them for the application agent prompt.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

STORE_PATH = Path(os.getenv("CANDIDATES_STORE_PATH", "tmp/candidates.json")).resolve()

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_DATA = {
    "active_profile": "My Profile",
    "profiles": {
        "My Profile": {
            "personal": {
                "first_name": "",
                "last_name": "",
                "full_name": "",
                "email": "",
                "phone": "",
                "country": "",
                "street_address": "",
                "zip_code": "",
                "city": "",
                "current_location": "",
                "work_authorization": "",
                "electronic_signature": "",
                "gender": "",
                "veteran": "No",
                "disability": "No",
                "years_of_experience": "",
                "linkedin_url": "",
                "date_of_birth": ""
            },
            "resume": {
                "file_path": "",
                "filename": ""
            },
            "credentials": {
                "default_password": "",
                "strong_password": ""
            },
            "work_experience": [],
            "education": [],
            "preferences": {
                "desired_salary": "",
                "frequency": "Monthly",
                "notice_period": "",
                "availability": ""
            }
        }
    }
}


def _load_store() -> Dict[str, Any]:
    if not STORE_PATH.exists():
        STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with STORE_PATH.open("w", encoding="utf-8") as f:
            json.dump(DEFAULT_DATA, f, indent=2, ensure_ascii=False)
        return DEFAULT_DATA

    try:
        with STORE_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
            if "active_profile" not in data or "profiles" not in data:
                return DEFAULT_DATA
            return data
    except Exception as exc:
        logger.warning("Failed to load candidates store %s: %s", STORE_PATH, exc)
        return DEFAULT_DATA


def _save_store(data: Dict[str, Any]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with STORE_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_all_profile_names() -> List[str]:
    data = _load_store()
    return list(data.get("profiles", {}).keys())


def get_active_profile_name() -> str:
    data = _load_store()
    active = data.get("active_profile")
    if active and active in data.get("profiles", {}):
        return active
    names = get_all_profile_names()
    return names[0] if names else "My Profile"


def set_active_profile(name: str) -> bool:
    data = _load_store()
    if name in data.get("profiles", {}):
        data["active_profile"] = name
        _save_store(data)
        logger.info("Active candidate profile set to '%s'", name)
        return True
    return False


def get_active_profile() -> Dict[str, Any]:
    data = _load_store()
    active = get_active_profile_name()
    return data.get("profiles", {}).get(active, DEFAULT_DATA["profiles"]["My Profile"])


def get_profile_by_name(name: str) -> Dict[str, Any]:
    data = _load_store()
    return data.get("profiles", {}).get(name, {})


def save_profile(name: str, profile_data: Dict[str, Any], set_active: bool = False) -> None:
    data = _load_store()
    if "profiles" not in data:
        data["profiles"] = {}
    data["profiles"][name] = profile_data
    if set_active or not data.get("active_profile"):
        data["active_profile"] = name
    _save_store(data)


def resolve_resume_path(profile: Dict[str, Any]) -> str:
    """Return the resume file path for *profile*, resolving it robustly.

    Priority order:
    1. The stored ``file_path`` value, if it points to an existing file.
    2. A file named ``filename`` located directly in PROJECT_ROOT.
    3. Empty string when neither resolves to an existing file.

    This handles the common case where ``tmp/candidates.json`` was saved on a
    different machine (different OS user or project location) and the absolute
    path no longer matches the current environment.
    """
    resume = profile.get("resume", {})
    stored_path = resume.get("file_path", "")
    filename = resume.get("filename", "")

    if stored_path and os.path.exists(stored_path):
        return stored_path

    if filename:
        fallback = PROJECT_ROOT / filename
        if fallback.exists():
            return str(fallback)

    return ""


def format_candidate_profile_prompt(profile: Dict[str, Any]) -> str:
    """Format the structured candidate profile into clean markdown sections for the agent prompt."""
    p = profile.get("personal", {})
    r = profile.get("resume", {})
    work = profile.get("work_experience", [])
    edu = profile.get("education", [])
    pref = profile.get("preferences", {})

    lines = ["=== CANDIDATE PROFILE ==="]
    if p.get("first_name"): lines.append(f"- First Name: {p['first_name']}")
    if p.get("last_name"): lines.append(f"- Last Name: {p['last_name']}")
    if p.get("full_name"): lines.append(f"- Full Name: {p['full_name']}")
    if p.get("email"): lines.append(f"- Email: {p['email']}")
    if p.get("phone"): lines.append(f"- Phone: {p['phone']}")
    if p.get("country"): lines.append(f"- Country: {p['country']}")
    if p.get("street_address"): lines.append(f"- Street Address: {p['street_address']}")
    if p.get("zip_code"): lines.append(f"- Zip/Postal Code: {p['zip_code']}")
    if p.get("city"): lines.append(f"- City: {p['city']}")
    if p.get("current_location"): lines.append(f"- Current Location: {p['current_location']}")
    if p.get("work_authorization"): lines.append(f"- Work Authorization: {p['work_authorization']}")
    if p.get("years_of_experience"): lines.append(f"- Years of Experience: {p['years_of_experience']}")
    dob = p.get("date_of_birth", "1995-05-05 (05/05/1995)")
    lines.append(f"- Date of Birth: {dob}")
    linkedin = p.get("linkedin_url", "")
    lines.append(f"- LinkedIn Profile URL: {linkedin} (If requested by the form, enter this exact URL)")

    lines.append("")
    lines.append("=== RESUME & FILE UPLOADS ===")
    filename = r.get("filename", "Resume.pdf")
    lines.append(f'- MANDATORY RESUME UPLOAD: If the application form contains ANY field, button, or drag-and-drop zone for a resume, CV, or alternative documents, you MUST upload the file named "{filename}". Do not skip or bypass this step under any circumstances.')

    lines.append("")
    lines.append("=== WORK EXPERIENCE ===")
    for idx, w in enumerate(work):
        if idx > 0: lines.append("")
        if w.get("company"): lines.append(f"- Current Company: {w['company']}" if idx == 0 else f"- Previous Company: {w['company']}")
        if w.get("title"): lines.append(f"- Title: {w['title']}")
        if w.get("start_date"): lines.append(f"- Start Date: {w['start_date']}")
        if w.get("end_date"): lines.append(f"- End Date: {w['end_date']}")
        if w.get("description"): lines.append(f"- Description: {w['description']}")

    lines.append("")
    lines.append("=== EDUCATION ===")
    for e in edu:
        if e.get("university"): lines.append(f"- University: {e['university']}")
        if e.get("degree_level"): lines.append(f"- Degree Level: {e['degree_level']}")
        if e.get("major"): lines.append(f"- Major: {e['major']}")
        if e.get("graduation_date"): lines.append(f"- Graduation/End Date: {e['graduation_date']}")
        if e.get("status"): lines.append(f"- Status: {e['status']}")

    lines.append("")
    lines.append("=== APPLICATION PREFERENCES ===")
    if pref.get("desired_salary"): lines.append(f"- Desired Salary: {pref['desired_salary']}")
    if pref.get("frequency"): lines.append(f"- Frequency: {pref['frequency']}")
    if pref.get("notice_period"): lines.append(f"- Work Notice: {pref['notice_period']}")
    if pref.get("availability"): lines.append(f"- Availability: {pref['availability']}")
    sig = p.get("electronic_signature", p.get("full_name", ""))
    lines.append(f'- Electronic Signature: Type "{sig}" and check the acknowledgment boxes.')

    return "\n".join(lines)
