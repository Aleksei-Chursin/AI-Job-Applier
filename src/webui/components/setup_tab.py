"""
First-Run Setup Tab — API key configuration written directly to .env.

Covers the four mandatory keys required before the Job Applicator can run:
  · Google Gemini API key (AI model)
  · Airtable API key + Base ID + Table name (job queue)
  · Outlook email address (verification code inbox)

Save buttons test the credentials live before persisting them.
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

import gradio as gr

_ENV_PATH = Path(".env").resolve()
_ENV_EXAMPLE = Path(".env.example").resolve()


# ---------------------------------------------------------------------------
# .env helpers
# ---------------------------------------------------------------------------

def _ensure_env_file() -> None:
    if not _ENV_PATH.exists() and _ENV_EXAMPLE.exists():
        shutil.copy(_ENV_EXAMPLE, _ENV_PATH)


def _read_env(key: str) -> str:
    if not _ENV_PATH.exists():
        return ""
    for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{key}="):
            return stripped[len(f"{key}="):].strip().strip('"').strip("'")
    return ""


def _write_env(key: str, value: str) -> None:
    _ensure_env_file()
    content = _ENV_PATH.read_text(encoding="utf-8")
    lines = content.splitlines()
    new_lines, found = [], False
    for line in lines:
        if re.match(rf"^{re.escape(key)}\s*=", line):
            new_lines.append(f"{key}={value}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={value}")
    _ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    os.environ[key] = value


# ---------------------------------------------------------------------------
# Live validation helpers
# ---------------------------------------------------------------------------

def _test_google_key(key: str) -> tuple[bool, str]:
    """Ping the Gemini models list endpoint to verify the key."""
    try:
        import requests
        r = requests.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": key},
            timeout=8,
        )
        if r.status_code == 200:
            return True, "✅ Key valid — saved"
        if r.status_code == 400:
            return False, "❌ Invalid key format"
        if r.status_code == 403:
            return False, (
                "❌ API access denied.  \n"
                "Try creating a new key at [aistudio.google.com](https://aistudio.google.com) → Get API key → Create API key."
            )
        return False, f"❌ Unexpected response ({r.status_code})"
    except Exception as exc:
        return False, f"❌ Connection error: {exc}"


def _test_airtable(key: str, base: str, table: str) -> tuple[bool, str, str, str]:
    """Test all three Airtable fields together and return per-field status strings."""
    key, base, table = key.strip(), base.strip(), table.strip()

    if not key:
        return False, " Required", "", ""
    if not base:
        return False, "", " Required", ""
    if not base.startswith("app"):
        return False, "", " Should start with 'app'", ""
    if not table:
        return False, "", "", " Required"

    try:
        import requests
        r = requests.get(
            f"https://api.airtable.com/v0/{base}/{table}",
            headers={"Authorization": f"Bearer {key}"},
            params={"maxRecords": 1},
            timeout=8,
        )
        if r.status_code == 200:
            return True, "✅ Saved", "✅ Saved", "✅ Saved"
        if r.status_code == 401:
            return False, "❌ Invalid API key", "", ""
        if r.status_code == 403:
            return False, (
                "❌ No access to this base.  \n"
                "Open [airtable.com/create/tokens](https://airtable.com/create/tokens), "
                "edit the token and **grant access to your base**."
            ), "", ""
        if r.status_code == 404:
            return False, "", "❌ Base not found — check the ID", "❌ Table not found — check the name"
        msg = r.json().get("error", {}).get("message", r.text[:120])
        return False, f"❌ {r.status_code}: {msg}", "", ""
    except Exception as exc:
        return False, f"❌ Connection error: {exc}", "", ""


# ---------------------------------------------------------------------------
# Tab builder
# ---------------------------------------------------------------------------

def create_setup_tab() -> None:
    """Render the  Setup tab content inside an existing gr.Blocks context."""

    with gr.Column():
        gr.Markdown(
            """
            ##  First-Run Setup

            Fill in your API keys and click **Save & Test** — credentials are verified live
            before being written to `.env`.  
            Changes to API keys and the selected model take effect immediately — no restart needed.
            """
        )

        # ── AI Model ──────────────────────────────────────────────────────────
        with gr.Accordion("AI Model (required)", open=True):
            gr.Markdown(
                "Search or scroll to pick a model. **Google Gemini** has a free tier — good to start with.  \n"
                "See benchmark success rates in the README."
            )

            from src.utils.config import model_names as _model_names

            # Provider metadata
            _key_map = {
                "google":      ("GOOGLE_API_KEY",    "Get free key at [aistudio.google.com](https://aistudio.google.com) → Get API key → Create API key"),
                "anthropic":   ("ANTHROPIC_API_KEY", "Get key at [console.anthropic.com](https://console.anthropic.com)"),
                "openai":      ("OPENAI_API_KEY",    "Get key at [platform.openai.com/api-keys](https://platform.openai.com/api-keys)"),
                "deepseek":    ("DEEPSEEK_API_KEY",  "Get key at [platform.deepseek.com](https://platform.deepseek.com)"),
                "mistral":     ("MISTRAL_API_KEY",   "Get key at [console.mistral.ai](https://console.mistral.ai)"),
                "ollama":      (None,                "No API key needed — install Ollama from [ollama.com](https://ollama.com) and set OLLAMA_ENDPOINT in .env"),
                "grok":        ("GROK_API_KEY",      "Get key at [console.x.ai](https://console.x.ai)"),
                "alibaba":     ("ALIBABA_API_KEY",   "Get key from Alibaba Cloud DashScope"),
                "moonshot":    ("MOONSHOT_API_KEY",  "Get key at [platform.moonshot.cn](https://platform.moonshot.cn)"),
                "siliconflow": ("SiliconFLOW_API_KEY","Get key at [cloud.siliconflow.cn](https://cloud.siliconflow.cn)"),
                "ibm":         ("IBM_API_KEY",       "Get key from IBM Cloud"),
                "modelscope":  ("MODELSCOPE_API_KEY","Get key at [modelscope.cn](https://modelscope.cn)"),
            }
            _provider_label = {
                "google": "Google Gemini", "anthropic": "Anthropic", "openai": "OpenAI",
                "deepseek": "DeepSeek", "mistral": "Mistral", "ollama": "Ollama (local)",
                "grok": "Grok", "alibaba": "Alibaba", "moonshot": "Moonshot",
                "siliconflow": "SiliconFlow", "ibm": "IBM", "modelscope": "ModelScope",
            }

            # Build flat model list: "Provider — model"
            _model_choices = []
            _model_to_provider = {}  # "Provider — model" → provider key
            for _prov, _models in _model_names.items():
                _plabel = _provider_label.get(_prov, _prov.title())
                for _m in _models:
                    _entry = f"{_plabel} — {_m}"
                    _model_choices.append(_entry)
                    _model_to_provider[_entry] = (_prov, _m)

            # Determine current selection from .env
            _cur_provider = _read_env("DEFAULT_LLM") or "google"
            _cur_models   = _model_names.get(_cur_provider, [])
            _cur_model    = _cur_models[0] if _cur_models else ""
            _cur_plabel   = _provider_label.get(_cur_provider, _cur_provider.title())
            _cur_entry    = f"{_cur_plabel} — {_cur_model}" if _cur_model else (_model_choices[0] if _model_choices else "")

            model_dd = gr.Dropdown(
                label="Model (type to search)",
                choices=_model_choices,
                value=_cur_entry if _cur_entry in _model_choices else (_model_choices[0] if _model_choices else None),
                filterable=True,
                allow_custom_value=True,
            )

            _init_prov, _init_model = _model_to_provider.get(_cur_entry, (_cur_provider, _cur_model))
            _init_key_env, _init_hint = _key_map.get(_init_prov, (None, ""))
            _init_key_val = _read_env(_init_key_env) if _init_key_env else ""

            llm_key_input = gr.Textbox(
                label="API Key",
                value=_init_key_val,
                placeholder="Paste your API key here",
                type="password",
                visible=(_init_key_env is not None),
            )
            llm_hint_md  = gr.Markdown(_init_hint)
            llm_status   = gr.Markdown(
                _initial_status(_init_key_env) if _init_key_env else "ℹ️ No API key needed for Ollama"
            )
            llm_save_btn = gr.Button("Save & Test", variant="primary", size="sm")

            # Hidden legacy components (kept for callback compatibility)
            gemini_input    = gr.Textbox(visible=False, value=_read_env("GOOGLE_API_KEY"))
            gemini_status   = gr.Markdown(visible=False)
            gemini_save_btn = gr.Button(visible=False)

        # ── Airtable ───────────────────────────────────────────────────────────
        with gr.Accordion(" Airtable — job queue (required)", open=True):
            gr.Markdown(
                """
                1. Open [airtable.com/create/tokens](https://airtable.com/create/tokens) → **Create new token**
                2. Add scopes: `data.records:read` and `data.records:write`
                3. Under **Access**, click **+ Add a base** and select your job board base
                4. Create and copy the token → paste below
                5. **Base ID**: open your base in the browser — the URL is `airtable.com/appXXXXX/...` — copy the `app...` part
                """
            )
            at_key_input = gr.Textbox(
                label="AIRTABLE_API_KEY",
                value=_read_env("AIRTABLE_API_KEY"),
                placeholder="pat...",
                type="password",
            )
            at_key_status = gr.Markdown(_initial_status("AIRTABLE_API_KEY"))
            at_base_input = gr.Textbox(
                label="AIRTABLE_BASE_ID",
                value=_read_env("AIRTABLE_BASE_ID"),
                placeholder="appXXXXXXXXXXXXXX",
            )
            at_base_status = gr.Markdown(_initial_status("AIRTABLE_BASE_ID"))
            at_table_input = gr.Textbox(
                label="AIRTABLE_TABLE_NAME",
                value=_read_env("AIRTABLE_TABLE_NAME") or "Job Table",
                placeholder="Job Table",
            )
            at_table_status = gr.Markdown(_initial_status("AIRTABLE_TABLE_NAME", default="Job Table"))
            at_save_btn = gr.Button(" Save & Test Airtable", variant="primary", size="sm")

        # ── Outlook email ──────────────────────────────────────────────────────
        with gr.Accordion(" Email & Inbox Connection — verification codes", open=True):
            gr.Markdown(
                "The agent monitors this inbox for verification codes during job site account creation.  \n"
                "**Outlook / Hotmail / Live** and **Gmail** are both supported."
            )
            email_input = gr.Textbox(
                label="EMAIL_ADDRESS",
                value=_read_env("EMAIL_ADDRESS"),
                placeholder="you@outlook.com or you@gmail.com",
            )
            email_status = gr.Markdown(_initial_status("EMAIL_ADDRESS"))
            email_save_btn = gr.Button(" Save Email", variant="primary", size="sm")

            gr.Markdown("---")

            with gr.Tabs():
                # ── Outlook ───────────────────────────────────────────────────
                with gr.Tab("Outlook / Hotmail / Live"):
                    gr.Markdown(
                        "Click the button to start a one-time Microsoft sign-in. "
                        "A URL and short code will appear — open the URL, sign in, enter the code. "
                        "The token refreshes automatically and never expires."
                    )
                    _outlook_email = _read_env("EMAIL_ADDRESS")
                    _outlook_status_init = _connection_status_label("outlook", _outlook_email)
                    outlook_connect_btn    = gr.Button(" Connect Outlook Account", variant="primary", size="sm")
                    outlook_connect_status = gr.Markdown(_outlook_status_init)

                # ── Gmail ─────────────────────────────────────────────────────
                with gr.Tab("Gmail / Google"):
                    gr.Markdown(
                        """**Step 1 — Enable 2-Factor Authentication** (required for App Passwords)  
Go to [myaccount.google.com/security](https://myaccount.google.com/security) → 2-Step Verification → Turn On.

**Step 2 — Create an App Password**  
Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)  
Click **Create** → give it any name (e.g. "Job Applier") → copy the 16-character code.

**Step 3 — Enable IMAP in Gmail**  
Gmail Settings () → See all settings → Forwarding and POP/IMAP → Enable IMAP → Save.

**Step 4** — Paste the App Password below and click Save."""
                    )
                    _gmail_email = _read_env("EMAIL_ADDRESS")
                    _gmail_status_init = _connection_status_label("gmail", _gmail_email)
                    gmail_pw_input  = gr.Textbox(
                        label="Gmail App Password (16 characters, spaces optional)",
                        placeholder="xxxx xxxx xxxx xxxx",
                        type="password",
                    )
                    gmail_save_btn  = gr.Button(" Save Gmail App Password", variant="primary", size="sm")
                    gmail_status    = gr.Markdown(_gmail_status_init)

        # ── Optional extras ────────────────────────────────────────────────────
        with gr.Accordion(" Optional — CAPTCHA solvers & observability", open=False):
            gr.Markdown(
                "These are optional. Leave blank if you don't need them.\n\n"
                "- **CapSolver / 2Captcha** — paid CAPTCHA solving APIs\n"
                "- **Langfuse** — LLM observability at [cloud.langfuse.com](https://cloud.langfuse.com)"
            )
            with gr.Row():
                capsolver_input = gr.Textbox(
                    label="CAPSOLVER_API_KEY",
                    value=_read_env("CAPSOLVER_API_KEY"),
                    placeholder="CAP-...",
                    type="password",
                    scale=2,
                )
                twocaptcha_input = gr.Textbox(
                    label="TWOCAPTCHA_API_KEY",
                    value=_read_env("TWOCAPTCHA_API_KEY"),
                    placeholder="...",
                    type="password",
                    scale=2,
                )
            with gr.Row():
                langfuse_pub_input = gr.Textbox(
                    label="LANGFUSE_PUBLIC_KEY",
                    value=_read_env("LANGFUSE_PUBLIC_KEY"),
                    placeholder="pk-lf-...",
                    type="password",
                    scale=2,
                )
                langfuse_sec_input = gr.Textbox(
                    label="LANGFUSE_SECRET_KEY",
                    value=_read_env("LANGFUSE_SECRET_KEY"),
                    placeholder="sk-lf-...",
                    type="password",
                    scale=2,
                )
            optional_save_btn = gr.Button(" Save Optional Keys", size="sm")

        gr.Markdown(
            "---\n"
            "Once all required keys show ✅, go to ** Job Applicator** to set up "
            "candidate profiles and run your first batch."
        )

    # ── Callbacks ──────────────────────────────────────────────────────────────

    # ── Model dropdown change ──────────────────────────────────────────────────
    def _on_model_change(entry: str):
        prov, _mdl = _model_to_provider.get(entry, ("google", ""))
        key_env, hint = _key_map.get(prov, (None, ""))
        needs_key = key_env is not None
        current_key = _read_env(key_env) if needs_key else ""
        status = _initial_status(key_env) if needs_key else "ℹ️ No API key needed for Ollama"
        return (
            gr.update(visible=needs_key, value=current_key),
            gr.update(value=hint),
            gr.update(value=status),
        )

    model_dd.change(
        fn=_on_model_change,
        inputs=[model_dd],
        outputs=[llm_key_input, llm_hint_md, llm_status],
    )

    # ── Save & Test model ─────────────────────────────────────────────────────
    def _save_llm_provider(entry: str, key: str):
        provider, model_name = _model_to_provider.get(entry, ("google", ""))
        if not provider:
            # Custom/typed value — try to parse
            provider = "google"
            model_name = entry
        key = (key or "").strip()
        key_env, _ = _key_map.get(provider, (None, ""))

        # Ollama — no key needed
        if provider == "ollama":
            _write_env("DEFAULT_LLM", "ollama")
            yield f"✅ Ollama selected ({model_name}). Make sure Ollama is running locally."
            return

        if not key_env:
            yield f"✅ {provider} saved."
            return

        if not key:
            yield "⚠️ Please enter an API key."
            return

        yield f"⏳ Testing key — sending a quick message to `{model_name}`…"

        _prev = os.environ.get(key_env, "")
        os.environ[key_env] = key

        try:
            from src.utils import llm_provider as _lp
            from langchain_core.messages import HumanMessage as _HM

            llm = _lp.get_llm_model(
                provider=provider,
                model_name=model_name,
                temperature=0,
                base_url=None,
                api_key=key,
            )
            llm.invoke([_HM(content="Reply with exactly one word: hello")])

            _write_env(key_env, key)
            _write_env("DEFAULT_LLM", provider)
            yield f"✅ **{model_name}** connected. Ready to use — start a batch to apply."

        except Exception as exc:
            os.environ[key_env] = _prev
            err = str(exc)
            if "401" in err or "Incorrect API key" in err or "invalid_api_key" in err.lower():
                yield f"❌ Invalid API key. Double-check the key in your provider dashboard."
            elif "403" in err or "permission" in err.lower():
                yield f"❌ Key valid but no access to `{model_name}`. Check your account tier."
            elif "429" in err or "rate" in err.lower() or "quota" in err.lower():
                yield f"❌ Rate limited. Your key works — try again in a moment."
            elif "ImportError" in err or "ModuleNotFoundError" in err:
                pkg = {"anthropic": "langchain-anthropic", "mistral": "langchain-mistralai"}.get(provider, f"langchain-{provider}")
                yield f"❌ Missing package. Run: `.venv\\Scripts\\pip install {pkg}` then restart."
            else:
                yield f"❌ {err[:250]}"

    llm_save_btn.click(
        fn=_save_llm_provider,
        inputs=[model_dd, llm_key_input],
        outputs=[llm_status],
    )

    def _save_gemini(val: str):
        val = val.strip()
        if not val:
            yield " Please enter an API key"
            return
        yield "⏳ Testing key…"
        ok, msg = _test_google_key(val)
        if ok:
            _write_env("GOOGLE_API_KEY", val)
            _write_env("DEFAULT_LLM", "google")
            openai_key = _read_env("OPENAI_API_KEY")
            if openai_key and openai_key.startswith("<"):
                _write_env("OPENAI_API_KEY", "")
        yield msg

    def _save_airtable(key: str, base: str, table: str):
        key, base, table = key.strip(), base.strip(), table.strip()
        yield "⏳ Testing…", "", ""
        ok, key_msg, base_msg, table_msg = _test_airtable(key, base, table)
        if ok:
            _write_env("AIRTABLE_API_KEY", key)
            _write_env("AIRTABLE_BASE_ID", base)
            _write_env("AIRTABLE_TABLE_NAME", table)
        yield key_msg, base_msg, table_msg

    def _save_email(val: str):
        val = val.strip()
        if not val:
            yield " Please enter an email address"
            return
        if "@" not in val or "." not in val.split("@")[-1]:
            yield "❌ Not a valid email address"
            return

        _write_env("EMAIL_ADDRESS", val)
        yield "⏳ Checking connection…"

        from src.utils.email_client import (
            detect_email_provider, test_inbox_connection,
            load_gmail_app_password, get_token_path,
        )

        provider = detect_email_provider(val)
        has_creds = (
            (provider == "gmail" and bool(load_gmail_app_password(val))) or
            (provider == "outlook" and get_token_path(val).exists())
        )

        if has_creds:
            ok, msg = test_inbox_connection(val)
            yield msg
        elif provider == "gmail":
            yield "✅ Saved — enter your App Password in the Gmail tab below"
        elif provider == "outlook":
            yield "✅ Saved — click Connect in the Outlook tab below"
        else:
            yield "✅ Saved — use the Outlook or Gmail tab below to connect"

    # ── Outlook OAuth ─────────────────────────────────────────────────────────
    async def _do_outlook_connect(email_address: str):
        email_address = (email_address or "").strip()
        if not email_address or "@" not in email_address:
            yield " Save a valid email address above first"
            return
        yield f"⏳ Starting sign-in for **{email_address}**…"
        try:
            import msal
            from src.utils.email_client import (
                CLIENT_ID, TENANT_ID, SCOPES, get_token_path, _save_cache, test_inbox_connection,
            )
            import asyncio
            token_path = get_token_path(email_address)
            cache = msal.SerializableTokenCache()
            app = msal.PublicClientApplication(
                CLIENT_ID,
                authority=f"https://login.microsoftonline.com/{TENANT_ID}",
                token_cache=cache,
            )
            flow = app.initiate_device_flow(scopes=SCOPES)
            if "user_code" not in flow:
                yield f"❌ Could not start sign-in flow: {flow}"
                return
            uri, code = flow["verification_uri"], flow["user_code"]
            yield (
                f"### Action Required\n\n"
                f"1. Open **[{uri}]({uri})** in your browser\n"
                f"2. Enter code: **`{code}`**\n"
                f"3. Sign in as: {email_address}\n\n"
                f"⏳ Waiting…"
            )
            result = await asyncio.to_thread(app.acquire_token_by_device_flow, flow)
            if "access_token" in result:
                _save_cache(cache, token_path)
                yield "⏳ Testing inbox access…"
                _, inbox_msg = test_inbox_connection(email_address)
                yield inbox_msg
            else:
                yield f"❌ Sign-in failed: {result.get('error_description', result)}"
        except Exception as exc:
            yield f"❌ Error: {exc}"

    # ── Gmail App Password ────────────────────────────────────────────────────
    def _save_gmail_pw(email_address: str, app_password: str):
        email_address = (email_address or "").strip()
        app_password  = (app_password  or "").replace(" ", "").strip()
        if not email_address or "@" not in email_address:
            yield " Save a valid email address above first"
            return
        if len(app_password) != 16:
            yield f"❌ App Passwords are exactly 16 characters (you entered {len(app_password)}). Copy it again from myaccount.google.com/apppasswords."
            return
        yield f"⏳ Testing Gmail connection for **{email_address}**…"
        from src.utils.email_client import _test_gmail_connection, save_gmail_app_password
        ok, msg = _test_gmail_connection(email_address, app_password)
        if ok:
            save_gmail_app_password(email_address, app_password)
        yield msg

    def _save_optional(capsolver: str, twocaptcha: str, lf_pub: str, lf_sec: str):
        for k, v in [
            ("CAPSOLVER_API_KEY", capsolver),
            ("TWOCAPTCHA_API_KEY", twocaptcha),
            ("LANGFUSE_PUBLIC_KEY", lf_pub),
            ("LANGFUSE_SECRET_KEY", lf_sec),
        ]:
            if v.strip():
                _write_env(k, v.strip())
        gr.Info("Optional keys saved.")

    gemini_save_btn.click(
        fn=_save_gemini,
        inputs=[gemini_input],
        outputs=[gemini_status],
    )

    at_save_btn.click(
        fn=_save_airtable,
        inputs=[at_key_input, at_base_input, at_table_input],
        outputs=[at_key_status, at_base_status, at_table_status],
    )

    email_save_btn.click(fn=_save_email, inputs=[email_input], outputs=[email_status])

    outlook_connect_btn.click(
        fn=_do_outlook_connect,
        inputs=[email_input],
        outputs=[outlook_connect_status],
    )

    gmail_save_btn.click(
        fn=_save_gmail_pw,
        inputs=[email_input, gmail_pw_input],
        outputs=[gmail_status],
    )

    optional_save_btn.click(
        fn=_save_optional,
        inputs=[capsolver_input, twocaptcha_input, langfuse_pub_input, langfuse_sec_input],
        outputs=[],
    )


def _connection_status_label(provider: str, email: str) -> str:
    """Return a startup status string for Outlook or Gmail without doing a live test."""
    if not email or "@" not in email:
        return " Save an email address above first"
    from src.utils.email_client import load_gmail_app_password, get_token_path
    if provider == "gmail":
        if load_gmail_app_password(email):
            return "✅ App Password saved — click Save to re-test"
        return " Not connected — enter your App Password below"
    if provider == "outlook":
        if get_token_path(email).exists():
            return "✅ Token saved — click Connect to re-test"
        return " Not connected — click Connect to sign in"
    return ""


def _initial_status(key: str, default: str = "") -> str:
    """Status string shown at page load (no live test — just presence check)."""
    v = _read_env(key) or default
    if not v:
        return " Not set"
    if key == "AIRTABLE_BASE_ID" and not v.startswith("app"):
        return " Should start with 'app'"
    if key == "EMAIL_ADDRESS" and "@" not in v:
        return " Not a valid email"
    return "✅ Saved"
