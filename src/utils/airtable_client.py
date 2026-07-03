"""
Airtable REST API client for the job application orchestrator.

Responsibilities:
- get_unapplied_jobs()  → fetch all records where Applied=false into memory
- mark_as_applied(record_id) → PATCH Applied=true
- log_error(record_id, msg) → PATCH Job Description with an error note
"""
from __future__ import annotations

import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (overridable via env)
# ---------------------------------------------------------------------------
_BASE_URL = "https://api.airtable.com/v0"
_BASE_ID = os.getenv("AIRTABLE_BASE_ID", "appJgpsg8NxzRHWxK")
_TABLE = os.getenv("AIRTABLE_TABLE_NAME", "Table 1")
_TOKEN = os.getenv("AIRTABLE_API_KEY", "")

# Column names (match Airtable exactly)
COL_TITLE = "Title"
COL_JOB_DESC = "Job Description"
COL_JOB_LINK = "Job Link"
COL_JOB_DATE = "Job Date"
COL_APPLIED = "Applied"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _headers() -> dict[str, str]:
    if not _TOKEN:
        raise RuntimeError(
            "AIRTABLE_API_KEY is not set. "
            "Add it to your .env file and restart the WebUI."
        )
    return {
        "Authorization": f"Bearer {_TOKEN}",
        "Content-Type": "application/json",
    }


def _table_url() -> str:
    from urllib.parse import quote
    return f"{_BASE_URL}/{_BASE_ID}/{quote(_TABLE, safe='')}"


def _raise_for_status(resp: requests.Response) -> None:
    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        body = resp.text[:500]
        raise RuntimeError(
            f"Airtable API error {resp.status_code}: {body}"
        ) from exc


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_unapplied_jobs() -> list[dict[str, Any]]:
    """
    Fetch all records from Airtable where the 'Applied' checkbox is NOT checked
    and no automation error has been logged in 'Job Link'.
    Returns a list of dicts:
        [
            {
                "id": "<record_id>",
                "title": "...",
                "job_description": "...",
                "job_link": "...",
                "job_date": "...",
            },
            ...
        ]
    """
    url = _table_url()
    params: dict[str, Any] = {
        "filterByFormula": f"NOT({{{COL_APPLIED}}})",
        "fields[]": [COL_TITLE, COL_JOB_DESC, COL_JOB_LINK, COL_JOB_DATE],
    }

    jobs: list[dict[str, Any]] = []
    offset: str | None = None

    while True:
        if offset:
            params["offset"] = offset

        logger.info("Fetching Airtable records (offset=%s)…", offset)
        resp = requests.get(url, headers=_headers(), params=params, timeout=30)
        _raise_for_status(resp)
        data = resp.json()

        for record in data.get("records", []):
            fields = record.get("fields", {})
            job_link = str(fields.get(COL_JOB_LINK, "") or "")
            job_desc = str(fields.get(COL_JOB_DESC, "") or "")

            # Filter out jobs that have an error logged in Job Link
            if "[Automation Error:" in job_link or "[Error:" in job_link or "Automation Error" in job_link:
                logger.info("Skipping record %s (%s) because it has an error log in Job Link.", record["id"], fields.get(COL_TITLE, ""))
                continue

            jobs.append(
                {
                    "id": record["id"],
                    "title": fields.get(COL_TITLE, ""),
                    "job_description": fields.get(COL_JOB_DESC, ""),
                    "job_link": fields.get(COL_JOB_LINK, ""),
                    "job_date": fields.get(COL_JOB_DATE, ""),
                }
            )

        offset = data.get("offset")
        if not offset:
            break

    logger.info("Loaded %d unapplied job(s) from Airtable.", len(jobs))
    return jobs


def mark_as_applied(record_id: str) -> None:
    """
    Set the 'Applied' checkbox to true for the given record.
    """
    url = f"{_table_url()}/{record_id}"
    payload = {"fields": {COL_APPLIED: True}}
    logger.info("Marking record %s as applied.", record_id)
    resp = requests.patch(url, headers=_headers(), json=payload, timeout=30)
    _raise_for_status(resp)
    logger.info("Record %s marked as applied ✓", record_id)


def log_error(record_id: str, error_msg: str) -> None:
    """
    Append an automation error note to the 'Job Link' field.
    Reads the existing value first to avoid overwriting it.
    """
    # Read current value
    url = f"{_table_url()}/{record_id}"
    resp = requests.get(url, headers=_headers(), timeout=30)
    _raise_for_status(resp)
    current_fields = resp.json().get("fields", {})
    existing = current_fields.get(COL_JOB_LINK, "") or ""

    note = f"[Automation Error: {error_msg}]"
    new_value = f"{existing} | {note}".strip(" |") if existing else note

    payload = {"fields": {COL_JOB_LINK: new_value}}
    logger.warning("Logging error for record %s: %s", record_id, error_msg)
    resp = requests.patch(url, headers=_headers(), json=payload, timeout=30)
    _raise_for_status(resp)
    logger.info("Error logged for record %s ✓", record_id)


def reload_jobs() -> list[dict[str, Any]]:
    """Alias for get_unapplied_jobs(), used for manual refresh from the UI."""
    return get_unapplied_jobs()
