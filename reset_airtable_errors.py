"""
Utility script to clear [Automation Error: ...] notes from Airtable Job Links
so jobs can be re-attempted by the agent.
"""
import re
import requests
from dotenv import load_dotenv

load_dotenv()
from src.utils.airtable_client import _headers, _table_url, COL_STATE, COL_ERROR_MSG, COL_TITLE, _raise_for_status


def reset_errors():
    url = _table_url()
    params = {
        "filterByFormula": f"{{{COL_STATE}}} = 'error'",
    }
    resp = requests.get(url, headers=_headers(), params=params, timeout=30)
    _raise_for_status(resp)
    records = resp.json().get("records", [])

    cleaned = 0
    for rec in records:
        rec_id = rec["id"]
        fields = rec.get("fields", {})
        title = fields.get(COL_TITLE, "Untitled")
        
        patch_url = f"{url}/{rec_id}"
        # Reset State to 'new' and clear the Error Message column
        payload = {
            "fields": {
                COL_STATE: "new",
                COL_ERROR_MSG: ""
            }
        }
        patch_resp = requests.patch(patch_url, headers=_headers(), json=payload, timeout=30)
        _raise_for_status(patch_resp)
        clean_title = title.encode('ascii', 'replace').decode('ascii')
        print(f"[OK] Reset state to 'new' and cleared Error Message for: {clean_title}")
        cleaned += 1

    print(f"\nDone! Reset error logs for {cleaned} job record(s).")


if __name__ == "__main__":
    reset_errors()
