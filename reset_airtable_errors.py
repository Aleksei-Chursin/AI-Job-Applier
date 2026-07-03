"""
Utility script to clear [Automation Error: ...] notes from Airtable Job Links
so jobs can be re-attempted by the agent.
"""
import re
import requests
from dotenv import load_dotenv

load_dotenv()
from src.utils.airtable_client import _headers, _table_url, COL_JOB_LINK, COL_TITLE, _raise_for_status


def reset_errors():
    url = _table_url()
    params = {
        "filterByFormula": "NOT({Applied})",
    }
    resp = requests.get(url, headers=_headers(), params=params, timeout=30)
    _raise_for_status(resp)
    records = resp.json().get("records", [])

    cleaned = 0
    for rec in records:
        rec_id = rec["id"]
        fields = rec.get("fields", {})
        title = fields.get(COL_TITLE, "Untitled")
        link = fields.get(COL_JOB_LINK, "")
        
        if "[Automation Error:" in link or "[Error:" in link or "Automation Error" in link:
            # Strip out everything starting from | [Automation Error or [Automation Error
            new_link = re.sub(r'\s*\|\s*\[(?:Automation )?Error:.*', '', link).strip()
            new_link = re.sub(r'\[(?:Automation )?Error:.*', '', new_link).strip()
            
            patch_url = f"{url}/{rec_id}"
            payload = {"fields": {COL_JOB_LINK: new_link}}
            patch_resp = requests.patch(patch_url, headers=_headers(), json=payload, timeout=30)
            _raise_for_status(patch_resp)
            clean_title = title.encode('ascii', 'replace').decode('ascii')
            print(f"[OK] Cleared error log for: {clean_title}")
            cleaned += 1

    print(f"\nDone! Reset error logs for {cleaned} job record(s).")


if __name__ == "__main__":
    reset_errors()
