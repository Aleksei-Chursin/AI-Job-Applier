"""
One-time Outlook OAuth2 authentication setup.

Run this script ONCE to authorize the job application agent to read your inbox:

    python src/utils/email_auth.py

A browser window will open asking you to sign in to Microsoft.
After signing in, the token is saved to tmp/outlook_token.json and the
agent will silently reuse it (auto-refreshing) for all future runs.
"""
from dotenv import load_dotenv
load_dotenv()

import sys
from pathlib import Path

# Make sure project root is on the path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import msal
from src.utils.email_client import (
    CLIENT_ID, TENANT_ID, SCOPES, get_configured_email, get_token_path,
    _save_cache,
)


def main():
    email_address = None
    if len(sys.argv) > 1:
        arg = sys.argv[1].strip()
        if "@" in arg:
            email_address = arg
        else:
            try:
                from src.utils import candidate_manager
                prof = candidate_manager.get_profile_by_name(arg)
                email_address = prof.get("personal", {}).get("email", arg)
            except Exception:
                email_address = arg

    if not email_address:
        email_address = get_configured_email()

    token_path = get_token_path(email_address)

    print("=" * 60)
    print("  Outlook OAuth2 Setup for Job Application Agent")
    print("=" * 60)
    print(f"\nAccount  : {email_address}")
    print(f"Token saved to: {token_path}\n")

    cache = msal.SerializableTokenCache()
    app = msal.PublicClientApplication(
        CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
        token_cache=cache,
    )

    # Device code flow — works in any environment, no redirect URI needed
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        print("ERROR: Could not initiate device flow:", flow)
        sys.exit(1)

    print("─" * 60)
    print("ACTION REQUIRED:\n")
    print(f"  1. Open this URL in your browser:\n     {flow['verification_uri']}")
    print(f"\n  2. Enter this code: {flow['user_code']}")
    print(f"\n  3. Sign in as: {email_address}")
    print("─" * 60)
    print("\nWaiting for you to complete sign-in", end="", flush=True)

    result = app.acquire_token_by_device_flow(flow)

    if "access_token" in result:
        _save_cache(cache, token_path)
        print(f"\n\n✅  Authentication successful for {email_address}!")
        print(f"    Token saved to: {token_path}")
        print(f"\n    The agent will now use this token automatically.")
        print(f"    Tokens auto-refresh — you should not need to run this again.")
    else:
        print(f"\n\n❌  Authentication failed: {result.get('error_description', result)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
