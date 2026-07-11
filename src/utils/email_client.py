"""
IMAP email client supporting both Outlook.com (OAuth2) and Gmail (App Password).

Provider is detected automatically from the email address domain.

── Outlook setup (one-time) ─────────────────────────────────────────────────
    python src/utils/email_auth.py
Opens a Microsoft device-code login, saves the token to
tmp/outlook_token_<email>.json and silently reuses it on future runs.

── Gmail setup (one-time) ───────────────────────────────────────────────────
1. Enable 2-Factor Authentication on your Google account.
2. Go to myaccount.google.com/apppasswords
3. Create an App Password for "Mail" (or any name).
4. In the Job Applicator tab → Candidate Profile → Connect Email Account,
   enter the 16-character code and click Save.
   The password is stored in tmp/gmail_apppassword_<email>.json.
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
# Provider detection
# ---------------------------------------------------------------------------

_GMAIL_DOMAINS   = frozenset({"gmail.com", "googlemail.com"})
_OUTLOOK_DOMAINS = frozenset({
    "outlook.com", "outlook.com.au", "outlook.at", "outlook.be", "outlook.ca",
    "outlook.cl", "outlook.co.id", "outlook.co.nz", "outlook.co.th",
    "outlook.com.ar", "outlook.com.br", "outlook.com.gr", "outlook.com.pe",
    "outlook.com.tr", "outlook.com.vn", "outlook.cz", "outlook.de",
    "outlook.dk", "outlook.es", "outlook.fr", "outlook.hu", "outlook.ie",
    "outlook.in", "outlook.it", "outlook.jp", "outlook.kr", "outlook.lv",
    "outlook.my", "outlook.ph", "outlook.pt", "outlook.sa", "outlook.sg",
    "outlook.sk",
    "hotmail.com", "hotmail.co.uk", "hotmail.fr", "hotmail.de",
    "live.com", "live.co.uk", "live.com.au", "live.ca",
    "msn.com", "windowslive.com",
})


def detect_email_provider(email_address: str) -> str:
    """Return 'gmail', 'outlook', or 'unknown' based on the email domain."""
    if not email_address or "@" not in email_address:
        return "unknown"
    domain = email_address.split("@")[-1].lower()
    if domain in _GMAIL_DOMAINS:
        return "gmail"
    if domain in _OUTLOOK_DOMAINS:
        return "outlook"
    return "unknown"


# ---------------------------------------------------------------------------
# Gmail — App Password IMAP
# ---------------------------------------------------------------------------

GMAIL_IMAP_HOST = "imap.gmail.com"
GMAIL_IMAP_PORT = 993


def get_gmail_apppassword_path(email_address: str) -> Path:
    safe = email_address.replace("@", "_").replace(".", "_")
    return Path(f"tmp/gmail_apppassword_{safe}.json").resolve()


def save_gmail_app_password(email_address: str, app_password: str) -> None:
    path = get_gmail_apppassword_path(email_address)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"email": email_address, "app_password": app_password.strip()}),
        encoding="utf-8",
    )
    logger.info("Gmail App Password saved for %s", email_address)


def load_gmail_app_password(email_address: str) -> Optional[str]:
    path = get_gmail_apppassword_path(email_address)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("app_password")
    except Exception:
        return None


def is_gmail_configured(email_address: str) -> bool:
    return bool(load_gmail_app_password(email_address))


def _latest_subject(imap: imaplib.IMAP4_SSL, search_data) -> str:
    """Fetch the subject of the most recent message from an IMAP search result."""
    try:
        if not (search_data and search_data[0]):
            return ""
        latest_id = search_data[0].split()[-1]
        _, msg_data = imap.fetch(latest_id, "(BODY[HEADER.FIELDS (SUBJECT)])")
        if msg_data and msg_data[0]:
            raw_header = msg_data[0][1] if isinstance(msg_data[0], tuple) else b""
            msg = email.message_from_bytes(raw_header)
            parts = decode_header(msg.get("Subject", ""))
            return " ".join(_decode_str(p, enc) for p, enc in parts).strip()
    except Exception:
        pass
    return ""


def _test_gmail_connection(email_address: str, app_password: str) -> tuple[bool, str]:
    """Test App Password + read the latest inbox subject. Returns (ok, message)."""
    try:
        with imaplib.IMAP4_SSL(GMAIL_IMAP_HOST, GMAIL_IMAP_PORT) as imap:
            imap.login(email_address, app_password.strip())
            imap.select("INBOX")
            _, data = imap.search(None, "ALL")
            subject = _latest_subject(imap, data)
        if subject:
            return True, f"✅ Connected to Gmail — latest email: \"{subject}\""
        return True, "✅ Connected to Gmail — inbox is empty"
    except imaplib.IMAP4.error as exc:
        msg = str(exc)
        if "AUTHENTICATIONFAILED" in msg or "Invalid credentials" in msg:
            return False, (
                "❌ Authentication failed.  \n"
                "Check the App Password is correct and that IMAP is enabled in Gmail settings "
                "(Gmail Settings → See all settings → Forwarding and POP/IMAP → Enable IMAP)."
            )
        return False, f"❌ IMAP error: {msg}"
    except Exception as exc:
        return False, f"❌ Connection error: {exc}"


def test_inbox_connection(email_address: str) -> tuple[bool, str]:
    """
    Test the inbox connection for the given address and return the subject of
    the latest email as proof that reading works end-to-end.

    Returns (ok, human-readable message).
    Provider (Gmail or Outlook) is detected from the email domain.
    """
    provider = detect_email_provider(email_address)

    if provider == "gmail":
        pw = load_gmail_app_password(email_address)
        if not pw:
            return False, (
                "⚠️ Gmail App Password not set. "
                "Go to Job Applicator → Candidate Profile → Connect Email → Gmail tab."
            )
        return _test_gmail_connection(email_address, pw)

    # Outlook
    try:
        token = get_access_token(email_address)
    except RuntimeError as exc:
        return False, f"⚠️ {exc}"

    try:
        with _open_imap_outlook(email_address, token) as imap:
            imap.select("INBOX")
            _, data = imap.search(None, "ALL")
            subject = _latest_subject(imap, data)
        if subject:
            return True, f"✅ Connected to Outlook — latest email: \"{subject}\""
        return True, "✅ Connected to Outlook — inbox is empty"
    except imaplib.IMAP4.error as exc:
        raw = str(exc).lower()
        if "not connected" in raw or "authenticated but not connected" in raw:
            return False, (
                "✅ Token saved — but IMAP is disabled on this Outlook mailbox.\n\n"
                "**To fix:** Go to [outlook.com](https://outlook.com) → Settings ⚙️ → "
                "View all Outlook settings → Mail → Forwarding and IMAP → "
                "Under POP and IMAP, set IMAP to **Enabled** → Save.\n\n"
                "Then restart the app and reconnect."
            )
        return False, f"❌ Outlook IMAP error: {exc}"
    except Exception as exc:
        return False, f"❌ Outlook error: {exc}"


def _open_imap_gmail(email_address: str, app_password: str) -> imaplib.IMAP4_SSL:
    imap = imaplib.IMAP4_SSL(GMAIL_IMAP_HOST, GMAIL_IMAP_PORT)
    imap.login(email_address, app_password.strip())
    return imap


# ---------------------------------------------------------------------------
# Outlook — OAuth2 / XOAUTH2
# ---------------------------------------------------------------------------

CLIENT_ID = "9e5f94bc-e8a4-4e73-b8be-63364c29d753"   # Thunderbird public MSAL client
TENANT_ID = "consumers"                                 # personal Outlook accounts
SCOPES    = ["https://outlook.office.com/IMAP.AccessAsUser.All"]

IMAP_HOST = "outlook.office365.com"
IMAP_PORT = 993

# Backward compatibility
TOKEN_PATH = Path(os.getenv("OUTLOOK_TOKEN_PATH", "tmp/outlook_token.json")).resolve()


def get_configured_email() -> str:
    env_mail = os.getenv("EMAIL_ADDRESS")
    if env_mail:
        return env_mail
    try:
        from src.utils import candidate_manager
        prof = candidate_manager.get_active_profile()
        return prof.get("personal", {}).get("email", "")
    except Exception:
        return ""


def get_token_path(email_address: Optional[str] = None) -> Path:
    if not email_address:
        email_address = get_configured_email()
    safe_name = email_address.replace("@", "_").replace(".", "_")
    path = Path(f"tmp/outlook_token_{safe_name}.json").resolve()
    # Backward compatibility with legacy single-token file
    return path


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


def _xoauth2_string(user: str, token: str) -> bytes:
    return f"user={user}\x01auth=Bearer {token}\x01\x01".encode()


def _open_imap_outlook(email_address: str, token: str) -> imaplib.IMAP4_SSL:
    imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    auth_str = _xoauth2_string(email_address, token)
    imap.authenticate("XOAUTH2", lambda x: auth_str)
    return imap


# ---------------------------------------------------------------------------
# Email parsing helpers (shared)
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


def _poll_imap(
    open_fn,
    max_wait_seconds: int,
    poll_interval: int,
    sender_filter: Optional[str],
    subject_filter: Optional[str],
    provider_label: str,
) -> dict:
    """Generic IMAP polling loop. open_fn() must return an open imaplib connection."""
    _EMPTY = dict(found=False, subject="", sender="", body_text="",
                  codes=[], links=[], error=None)
    deadline = time.time() + max_wait_seconds
    attempt  = 0

    while time.time() < deadline:
        attempt += 1
        logger.info("%s IMAP poll #%d for verification email…", provider_label, attempt)
        try:
            with open_fn() as imap:
                imap.select("INBOX")
                criteria = ["UNSEEN"]
                if sender_filter:
                    criteria += ["FROM", f'"{sender_filter}"']
                if subject_filter:
                    criteria += ["SUBJECT", f'"{subject_filter}"']
                status, data = imap.search(None, *criteria)

                # Fallback: search all with filters (email may already be read)
                if not (status == "OK" and data and data[0]) and (sender_filter or subject_filter):
                    criteria_all: list = []
                    if sender_filter:
                        criteria_all += ["FROM", f'"{sender_filter}"']
                    if subject_filter:
                        criteria_all += ["SUBJECT", f'"{subject_filter}"']
                    status, data = imap.search(None, *criteria_all)

                # Fallback: scan last 15 messages — return the most recent one
                # that contains codes or links, WITHOUT applying subject/sender
                # filters (the agent may guess filters incorrectly, e.g.
                # "Passcode" when the real subject is "One-Time Password").
                if not (status == "OK" and data and data[0]):
                    _, all_msgs = imap.search(None, "ALL")
                    if all_msgs and all_msgs[0]:
                        for r_id in reversed(all_msgs[0].split()[-15:]):
                            st, md = imap.fetch(r_id, "(RFC822)")
                            if st == "OK":
                                res = _parse_message(md[0][1])
                                if res["codes"] or res["links"]:
                                    logger.info("%s email via recent scan (no filter): %s | codes=%s",
                                                provider_label, res["subject"], res["codes"])
                                    return res

                if status == "OK" and data and data[0]:
                    msg_id = data[0].split()[-1]
                    st2, msg_data = imap.fetch(msg_id, "(RFC822)")
                    if st2 == "OK":
                        result = _parse_message(msg_data[0][1])
                        logger.info("%s email found: %s | codes=%s",
                                    provider_label, result["subject"], result["codes"])
                        return result

        except imaplib.IMAP4.error as imap_err:
            logger.warning("%s IMAP error: %s", provider_label, imap_err)
            # For Outlook: caller may retry with a refreshed token. For Gmail: surface the error.
            return {**_EMPTY, "error": f"IMAP error: {imap_err}"}
        except Exception as exc:
            logger.error("Unexpected %s error: %s", provider_label, exc)
            return {**_EMPTY, "error": str(exc)}

        remaining = deadline - time.time()
        if remaining <= 0:
            break
        time.sleep(min(poll_interval, remaining))

    return {**_EMPTY, "error": f"No email received within {max_wait_seconds}s."}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_latest_verification_email(
    max_wait_seconds: int = 60,
    poll_interval: int = 5,
    sender_filter: Optional[str] = None,
    subject_filter: Optional[str] = None,
    email_address: Optional[str] = None,
) -> dict:
    """
    Wait up to max_wait_seconds for a verification email.

    Provider (Outlook or Gmail) is detected automatically from the email address.
    Falls back to get_configured_email() when email_address is not provided.
    """
    _EMPTY = dict(found=False, subject="", sender="", body_text="",
                  codes=[], links=[], error=None)

    if not email_address:
        email_address = get_configured_email()

    provider = detect_email_provider(email_address)
    logger.info("Email provider for %s: %s", email_address, provider)

    # ── Gmail path ────────────────────────────────────────────────────────────
    if provider == "gmail":
        app_password = load_gmail_app_password(email_address)
        if not app_password:
            return {**_EMPTY, "error": (
                f"Gmail App Password not configured for {email_address}. "
                "Go to Job Applicator → Candidate Profile → Connect Email Account "
                "and enter your App Password."
            )}
        return _poll_imap(
            open_fn=lambda: _open_imap_gmail(email_address, app_password),
            max_wait_seconds=max_wait_seconds,
            poll_interval=poll_interval,
            sender_filter=sender_filter,
            subject_filter=subject_filter,
            provider_label="Gmail",
        )

    # ── Outlook path (default) ────────────────────────────────────────────────
    try:
        token = get_access_token(email_address)
    except RuntimeError as e:
        return {**_EMPTY, "error": str(e)}

    result = _poll_imap(
        open_fn=lambda: _open_imap_outlook(email_address, token),
        max_wait_seconds=max_wait_seconds,
        poll_interval=poll_interval,
        sender_filter=sender_filter,
        subject_filter=subject_filter,
        provider_label="Outlook",
    )

    # Refresh token once on IMAP auth error and retry
    if result.get("error") and "IMAP error" in result["error"]:
        logger.info("Retrying Outlook after token refresh…")
        try:
            token = get_access_token(email_address)
        except RuntimeError:
            return result
        result = _poll_imap(
            open_fn=lambda: _open_imap_outlook(email_address, token),
            max_wait_seconds=30,
            poll_interval=poll_interval,
            sender_filter=sender_filter,
            subject_filter=subject_filter,
            provider_label="Outlook-retry",
        )

    return result
