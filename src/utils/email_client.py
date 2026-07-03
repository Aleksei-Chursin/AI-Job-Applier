"""
IMAP + OAuth2 (Modern Auth) email client for Outlook.com.

Uses Microsoft's public Thunderbird client ID which supports personal Outlook
accounts without requiring Azure app registration.

FIRST-TIME SETUP (one-time only):
    python src/utils/email_auth.py

This opens a browser for Microsoft login, saves the token to
tmp/outlook_token.json, and all future runs reuse it silently.
"""
from __future__ import annotations

import imaplib
import json
import logging
import os
import re
import time
import email
from email.header import decode_header
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OAuth2 config — uses Thunderbird's public client ID (works for personal
# Outlook.com / Hotmail accounts without Azure app registration)
# ---------------------------------------------------------------------------
CLIENT_ID = "9e5f94bc-e8a4-4e73-b8be-63364c29d753"   # Thunderbird public MSAL client
TENANT_ID = "consumers"                                 # personal Outlook accounts
SCOPES = ["https://outlook.office.com/IMAP.AccessAsUser.All"]

IMAP_HOST = "outlook.office365.com"
IMAP_PORT = 993
def get_configured_email() -> str:
    env_mail = os.getenv("EMAIL_ADDRESS")
    if env_mail:
        return env_mail
    try:
        from src.utils import candidate_manager
        prof = candidate_manager.get_active_profile()
        return prof.get("personal", {}).get("email", "tom.petricek@outlook.com")
    except Exception:
        return "tom.petricek@outlook.com"


def get_token_path(email_address: Optional[str] = None) -> Path:
    if not email_address:
        email_address = get_configured_email()
    safe_name = email_address.replace("@", "_").replace(".", "_")
    path = Path(f"tmp/outlook_token_{safe_name}.json").resolve()
    # Backward compatibility with existing token file for Tomas
    if not path.exists() and email_address.lower() == "tom.petricek@outlook.com":
        old_path = Path(os.getenv("OUTLOOK_TOKEN_PATH", "tmp/outlook_token.json")).resolve()
        if old_path.exists():
            return old_path
    return path


# Backward compatibility alias
TOKEN_PATH = Path(os.getenv("OUTLOOK_TOKEN_PATH", "tmp/outlook_token.json")).resolve()


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------

def _get_msal_app(email_address: Optional[str] = None):
    import msal
    cache, _ = _load_cache(email_address)
    return msal.PublicClientApplication(
        CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
        token_cache=cache,
    )


def _load_cache(email_address: Optional[str] = None):
    import msal
    cache = msal.SerializableTokenCache()
    tpath = get_token_path(email_address)
    if tpath.exists():
        cache.deserialize(tpath.read_text(encoding="utf-8"))
    return cache, tpath


def _save_cache(cache, tpath: Optional[Path] = None) -> None:
    if not tpath:
        tpath = get_token_path()
    tpath.parent.mkdir(parents=True, exist_ok=True)
    if cache.has_state_changed:
        tpath.write_text(cache.serialize(), encoding="utf-8")


def get_access_token(email_address: Optional[str] = None) -> str:
    """
    Return a valid OAuth2 access token for the given account, refreshing silently if possible.
    Raises RuntimeError if authentication is required (run email_auth.py first).
    """
    if not email_address:
        email_address = get_configured_email()
    app = _get_msal_app(email_address)
    accounts = app.get_accounts()

    result = None
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])

    if not result or "access_token" not in result:
        raise RuntimeError(
            f"No valid Outlook OAuth2 token found for {email_address}. "
            f"Run  python src/utils/email_auth.py {email_address}  once to authenticate."
        )

    _, tpath = _load_cache(email_address)
    _save_cache(app.token_cache, tpath)
    return result["access_token"]


# ---------------------------------------------------------------------------
# IMAP with XOAUTH2
# ---------------------------------------------------------------------------

def _xoauth2_string(user: str, token: str) -> bytes:
    return f"user={user}\x01auth=Bearer {token}\x01\x01".encode()


def _open_imap(token: str) -> imaplib.IMAP4_SSL:
    imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    auth_str = _xoauth2_string(get_configured_email(), token)
    imap.authenticate("XOAUTH2", lambda x: auth_str)
    return imap


# ---------------------------------------------------------------------------
# Email parsing helpers
# ---------------------------------------------------------------------------

def _decode_str(value, charset=None) -> str:
    if isinstance(value, bytes):
        return value.decode(charset or "utf-8", errors="replace")
    return value or ""


def _extract_codes(text: str) -> list[str]:
    return re.findall(r"\b\d{4,8}\b", text)


def _extract_links(text: str) -> list[str]:
    return re.findall(r"https?://[^\s\"'>]+", text)


def _parse_message(raw: bytes) -> dict:
    msg = email.message_from_bytes(raw)
    parts = decode_header(msg.get("Subject", ""))
    subject = " ".join(_decode_str(p, enc) for p, enc in parts)
    sender = msg.get("From", "")
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                body += _decode_str(part.get_payload(decode=True),
                                    part.get_content_charset())
    else:
        body = _decode_str(msg.get_payload(decode=True),
                           msg.get_content_charset())
    body = body[:3000]
    return {
        "found": True,
        "subject": subject,
        "sender": sender,
        "body_text": body,
        "codes": _extract_codes(body),
        "links": _extract_links(body),
        "error": None,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_latest_verification_email(
    max_wait_seconds: int = 60,
    poll_interval: int = 5,
    sender_filter: Optional[str] = None,
    subject_filter: Optional[str] = None,
) -> dict:
    """
    Wait up to max_wait_seconds for a new unread email matching the filters,
    then return its subject, body, extracted codes, and links.
    """
    _EMPTY = dict(found=False, subject="", sender="", body_text="",
                  codes=[], links=[], error=None)

    try:
        token = get_access_token()
    except RuntimeError as e:
        return {**_EMPTY, "error": str(e)}

    deadline = time.time() + max_wait_seconds
    attempt = 0

    while time.time() < deadline:
        attempt += 1
        logger.info("IMAP OAuth2 poll #%d for verification email…", attempt)
        try:
            with _open_imap(token) as imap:
                imap.select("INBOX")
                criteria = ["UNSEEN"]
                if sender_filter:
                    criteria += ["FROM", f'"{sender_filter}"']
                if subject_filter:
                    criteria += ["SUBJECT", f'"{subject_filter}"']
                status, data = imap.search(None, *criteria)
                
                # If no unread email matched, search ALL messages matching filters (in case marked seen)
                if not (status == "OK" and data and data[0]) and (sender_filter or subject_filter):
                    criteria_all = []
                    if sender_filter:
                        criteria_all += ["FROM", f'"{sender_filter}"']
                    if subject_filter:
                        criteria_all += ["SUBJECT", f'"{subject_filter}"']
                    status, data = imap.search(None, *criteria_all)
                
                # If still no match and we have a subject/sender filter, check the last 15 messages in INBOX directly
                if not (status == "OK" and data and data[0]):
                    status_all, all_msgs = imap.search(None, "ALL")
                    if status_all == "OK" and all_msgs and all_msgs[0]:
                        recent_ids = all_msgs[0].split()[-15:]
                        for r_id in reversed(recent_ids):
                            st, md = imap.fetch(r_id, "(RFC822)")
                            if st == "OK":
                                res = _parse_message(md[0][1])
                                s_ok = not sender_filter or sender_filter.lower() in res["sender"].lower()
                                sub_ok = not subject_filter or subject_filter.lower() in res["subject"].lower()
                                if s_ok and sub_ok and (_extract_codes(res["body_text"]) or _extract_links(res["body_text"])):
                                    logger.info("Email found via recent scan: %s | codes=%s", res["subject"], res["codes"])
                                    return res

                if status == "OK" and data and data[0]:
                    msg_id = data[0].split()[-1]
                    status2, msg_data = imap.fetch(msg_id, "(RFC822)")
                    if status2 == "OK":
                        result = _parse_message(msg_data[0][1])
                        logger.info("Email found: %s | codes=%s",
                                    result["subject"], result["codes"])
                        return result
        except imaplib.IMAP4.error as imap_err:
            # Token may have expired mid-session — refresh once
            logger.warning("IMAP error: %s — refreshing token", imap_err)
            try:
                token = get_access_token()
            except RuntimeError as e:
                return {**_EMPTY, "error": str(e)}
        except Exception as exc:
            logger.error("Unexpected IMAP error: %s", exc)
            return {**_EMPTY, "error": str(exc)}

        remaining = deadline - time.time()
        if remaining <= 0:
            break
        time.sleep(min(poll_interval, remaining))

    return {**_EMPTY,
            "error": f"No email received within {max_wait_seconds}s."}
