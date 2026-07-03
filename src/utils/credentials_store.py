"""
Persistent credentials store for job application site accounts.

Saves and looks up login credentials per site domain in a JSON file
at tmp/site_credentials.json. The browser agent uses this to:
  1. Check for existing credentials before trying to register.
  2. Append new credentials after successfully creating an account.

File format:
{
  "greenhouse.io": {
    "email": "tom.petricek@outlook.com",
    "password": "Metro_l123!",
    "url": "https://app.greenhouse.io",
    "notes": "Created during Monks application",
    "created_at": "2026-07-01T10:05:00"
  },
  ...
}
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

STORE_PATH = Path(os.getenv("CREDENTIALS_STORE_PATH",
                             "tmp/site_credentials.json")).resolve()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load() -> dict:
    if STORE_PATH.exists():
        try:
            return json.loads(STORE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("Credentials store corrupted — starting fresh.")
    return {}


def _save(data: dict) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def _root_domain(raw: str) -> str:
    """
    Extract the registrable root domain from a URL or hostname.
    Examples:
      "https://app.greenhouse.io/jobs/123" -> "greenhouse.io"
      "jobs.eu.lever.co"                   -> "lever.co"
      "barclays.com"                        -> "barclays.com"
    """
    # If it looks like a URL, parse it first
    if raw.startswith("http"):
        host = urlparse(raw).netloc
    else:
        host = raw.strip().lstrip("www.")

    # Take the last two dot-separated parts as the root domain
    parts = host.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host.lower()


def _host_from(raw: str) -> str:
    """Extract the full hostname from a URL or plain domain string."""
    if raw.startswith("http"):
        return urlparse(raw).netloc.lower().lstrip("www.")
    return raw.strip().lower().lstrip("www.")


def _find_key(data: dict, domain_raw: str) -> Optional[str]:
    """
    Return the matching key in the store for a given domain/URL, or None.

    Matching priority:
    1. Exact hostname match              (e.g. "greenhouse.io" == "greenhouse.io")
    2. Suffix match — stored key is a   (e.g. host="barclays.wd3.myworkdayjobs.com"
       suffix of the incoming host           key ="wd3.myworkdayjobs.com" ✅)
    3. Root-domain fallback             (e.g. "app.greenhouse.io" -> "greenhouse.io")
    """
    host = _host_from(domain_raw)
    root = _root_domain(domain_raw)

    # 1. Exact match
    if host in data:
        return host

    # 2. Suffix match — key is a trailing component of host
    for key in data:
        if host == key or host.endswith("." + key):
            return key

    # 3. Root-domain fallback
    if root in data:
        return root

    # 4. Partial substring match (last resort)
    for key in data:
        if key in host or host in key:
            return key

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def lookup(domain_or_url: str) -> Optional[dict]:
    """
    Return stored credentials for the given site, or None if not found.

    Args:
        domain_or_url: e.g. "https://app.greenhouse.io/apply/123"
                        or "greenhouse.io" or "barclays.com"

    Returns:
        dict with keys: email, password, url, notes, created_at
        or None if no match exists.
    """
    data = _load()
    key = _find_key(data, domain_or_url)
    if key:
        logger.info("Credentials found for '%s' (matched key: %s)", domain_or_url, key)
        return data[key]
    logger.info("No credentials found for '%s'", domain_or_url)
    return None


def save(domain_or_url: str, email: str, password: str,
         notes: str = "") -> str:
    """
    Save credentials for a site. Overwrites if the domain already exists.

    Args:
        domain_or_url: the site URL or domain, e.g. "https://app.greenhouse.io"
        email:         the email/username used
        password:      the password used
        notes:         optional context (e.g. which job triggered the registration)

    Returns:
        The key under which credentials were stored (root domain string).
    """
    data = _load()
    key = _root_domain(domain_or_url)
    if not email:
        try:
            from src.utils import candidate_manager
            prof = candidate_manager.get_active_profile()
            email = prof.get("personal", {}).get("email", "tom.petricek@outlook.com")
        except Exception:
            email = "tom.petricek@outlook.com"
    data[key] = {
        "email": email,
        "password": password,
        "url": domain_or_url if domain_or_url.startswith("http") else f"https://{domain_or_url}",
        "notes": notes,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _save(data)
    logger.info("Credentials saved for '%s'", key)
    return key


def all_entries() -> dict:
    """Return the full credentials store (for display in the UI)."""
    return _load()
