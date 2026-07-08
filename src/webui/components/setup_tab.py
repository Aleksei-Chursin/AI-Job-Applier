"""
First-Run Setup Tab — API key configuration written directly to .env.

Covers the four mandatory keys required before the Job Applicator can run:
  · Google Gemini API key (AI model)
  · Airtable API key + Base ID + Table name (job queue)
  · Outlook email address (verification code inbox)

Values are persisted to .env so they survive restarts. Environment variables
are also updated in-process so the app can use them without restarting for
basic connectivity (LLM init still requires a full restart).
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
    """Copy .env.example → .env if .env doesn't exist yet."""
    if not _ENV_PATH.exists() and _ENV_EXAMPLE.exists():
        shutil.copy(_ENV_EXAMPLE, _ENV_PATH)


def _read_env(key: str) -> str:
    """Read a value from .env (returns empty string if absent)."""
    if not _ENV_PATH.exists():
        return ""
    for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{key}="):
            return stripped[len(f"{key}="):].strip().strip('"').strip("'")
    return ""


def _write_env(key: str, value: str) -> None:
    """Write or update key=value in .env. Creates the file if missing."""
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
    # Also update the live process environment
    os.environ[key] = value


def _status(key: str, value: str) -> str:
    """Return a short status markdown string for a given key/value pair."""
    v = (value or "").strip()
    if not v:
        return "⚠️ Not set"
    if key == "AIRTABLE_BASE_ID" and not v.startswith("app"):
        return "⚠️ Should start with 'app'"
    if key == "EMAIL_ADDRESS" and "@" not in v:
        return "⚠️ Not a valid email"
    return "✅ Saved"


# ---------------------------------------------------------------------------
# Tab builder
# ---------------------------------------------------------------------------

def create_setup_tab() -> None:
    """Render the 🔑 Setup tab content inside an existing gr.Blocks context."""

    with gr.Column():
        gr.Markdown(
            """
            ## 🔑 First-Run Setup

            Fill in your API keys below and click **Save**. Values are written to your `.env`
            file and take effect immediately for most settings.  
            A **full restart** (`python webui.py`) is required after making changes here for
            the first time.
            """
        )

        # ── Google Gemini ──────────────────────────────────────────────────────
        with gr.Accordion("🤖 Google Gemini API Key — AI model (required)", open=True):
            gr.Markdown(
                "Get a **free** key (no credit card) at "
                "[aistudio.google.com](https://aistudio.google.com) → **Get API key**."
            )
            with gr.Row():
                gemini_input = gr.Textbox(
                    label="GOOGLE_API_KEY",
                    value=_read_env("GOOGLE_API_KEY"),
                    placeholder="AIza...",
                    type="password",
                    scale=4,
                )
                gemini_status = gr.Markdown(_status("GOOGLE_API_KEY", _read_env("GOOGLE_API_KEY")), scale=1)
            gemini_save_btn = gr.Button("💾 Save Gemini Key", size="sm")

        # ── Airtable ───────────────────────────────────────────────────────────
        with gr.Accordion("📊 Airtable — job queue (required)", open=True):
            gr.Markdown(
                "In Airtable: **Profile → Developer Hub → Personal access tokens**.  \n"
                "Create a token with scopes `data.records:read` and `data.records:write`.\n\n"
                "**Base ID** — open your base in the browser; the URL contains `airtable.com/appXXXXX…` — copy the `app…` part."
            )
            with gr.Row():
                at_key_input = gr.Textbox(
                    label="AIRTABLE_API_KEY",
                    value=_read_env("AIRTABLE_API_KEY"),
                    placeholder="pat...",
                    type="password",
                    scale=4,
                )
                at_key_status = gr.Markdown(_status("AIRTABLE_API_KEY", _read_env("AIRTABLE_API_KEY")), scale=1)
            with gr.Row():
                at_base_input = gr.Textbox(
                    label="AIRTABLE_BASE_ID",
                    value=_read_env("AIRTABLE_BASE_ID"),
                    placeholder="appXXXXXXXXXXXXXX",
                    scale=4,
                )
                at_base_status = gr.Markdown(_status("AIRTABLE_BASE_ID", _read_env("AIRTABLE_BASE_ID")), scale=1)
            with gr.Row():
                at_table_input = gr.Textbox(
                    label="AIRTABLE_TABLE_NAME",
                    value=_read_env("AIRTABLE_TABLE_NAME") or "Job Table",
                    placeholder="Job Table",
                    scale=4,
                )
                at_table_status = gr.Markdown(_status("AIRTABLE_TABLE_NAME", _read_env("AIRTABLE_TABLE_NAME") or "Job Table"), scale=1)
            at_save_btn = gr.Button("💾 Save Airtable Settings", size="sm")

        # ── Outlook email ──────────────────────────────────────────────────────
        with gr.Accordion("📧 Outlook Email — verification codes (recommended)", open=True):
            gr.Markdown(
                "The agent monitors this inbox for email verification codes sent by job sites during "
                "account creation. Any free [outlook.com](https://outlook.com) address works.  \n"
                "After saving, go to **🚀 Job Applicator → Candidate Profile → Connect Outlook Account** "
                "to complete the one-time sign-in."
            )
            with gr.Row():
                email_input = gr.Textbox(
                    label="EMAIL_ADDRESS",
                    value=_read_env("EMAIL_ADDRESS"),
                    placeholder="you@outlook.com",
                    scale=4,
                )
                email_status = gr.Markdown(_status("EMAIL_ADDRESS", _read_env("EMAIL_ADDRESS")), scale=1)
            email_save_btn = gr.Button("💾 Save Email", size="sm")

        # ── Optional extras ────────────────────────────────────────────────────
        with gr.Accordion("🔧 Optional — CAPTCHA solvers & observability", open=False):
            gr.Markdown(
                "These are optional. Leave blank if you don't need them.\n\n"
                "- **CapSolver / 2Captcha** — paid CAPTCHA solving APIs for sites the audio solver can't handle.\n"
                "- **Langfuse** — open-source LLM observability. Get keys at [cloud.langfuse.com](https://cloud.langfuse.com)."
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
            optional_save_btn = gr.Button("💾 Save Optional Keys", size="sm")

        gr.Markdown(
            "---\n"
            "After saving all required keys, go to the **🚀 Job Applicator** tab to set up your "
            "candidate profiles and run your first batch."
        )

    # ── Callbacks ──────────────────────────────────────────────────────────────

    def _save_gemini(val: str):
        _write_env("GOOGLE_API_KEY", val.strip())
        gr.Info("Gemini API key saved.")
        return _status("GOOGLE_API_KEY", val.strip())

    def _save_airtable(key: str, base: str, table: str):
        _write_env("AIRTABLE_API_KEY", key.strip())
        _write_env("AIRTABLE_BASE_ID", base.strip())
        _write_env("AIRTABLE_TABLE_NAME", table.strip())
        gr.Info("Airtable settings saved.")
        return (
            _status("AIRTABLE_API_KEY", key.strip()),
            _status("AIRTABLE_BASE_ID", base.strip()),
            _status("AIRTABLE_TABLE_NAME", table.strip()),
        )

    def _save_email(val: str):
        _write_env("EMAIL_ADDRESS", val.strip())
        gr.Info("Email address saved.")
        return _status("EMAIL_ADDRESS", val.strip())

    def _save_optional(capsolver: str, twocaptcha: str, lf_pub: str, lf_sec: str):
        if capsolver.strip():
            _write_env("CAPSOLVER_API_KEY", capsolver.strip())
        if twocaptcha.strip():
            _write_env("TWOCAPTCHA_API_KEY", twocaptcha.strip())
        if lf_pub.strip():
            _write_env("LANGFUSE_PUBLIC_KEY", lf_pub.strip())
        if lf_sec.strip():
            _write_env("LANGFUSE_SECRET_KEY", lf_sec.strip())
        gr.Info("Optional keys saved.")

    gemini_save_btn.click(fn=_save_gemini, inputs=[gemini_input], outputs=[gemini_status])

    at_save_btn.click(
        fn=_save_airtable,
        inputs=[at_key_input, at_base_input, at_table_input],
        outputs=[at_key_status, at_base_status, at_table_status],
    )

    email_save_btn.click(fn=_save_email, inputs=[email_input], outputs=[email_status])

    optional_save_btn.click(
        fn=_save_optional,
        inputs=[capsolver_input, twocaptcha_input, langfuse_pub_input, langfuse_sec_input],
        outputs=[],
    )
