"""
Job Applicator Tab for Browser Use WebUI.

This tab:
1. Shows all unapplied jobs fetched from Airtable at startup.
2. Lets the user refresh the list manually via API (no browser needed).
3. Runs the browser agent sequentially for each unchecked job, with a
   focused single-job prompt.
4. On completion, calls Airtable API to mark Applied=true or log an error.
   The browser never needs to touch Airtable.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, Optional

import gradio as gr
from browser_use.browser.browser import BrowserConfig
from browser_use.browser.context import BrowserContextConfig
from browser_use.browser.views import BrowserState
from browser_use.agent.views import AgentHistoryList, AgentOutput

from src.agent.browser_use.browser_use_agent import BrowserUseAgent
from src.browser.custom_browser import CustomBrowser
from src.controller.custom_controller import CustomController
from src.utils import airtable_client, candidate_manager, llm_provider as llm_provider_module
from src.utils import resume_parser
from src.utils.resume_parser import PdfExtractionError
from src.webui.webui_manager import WebuiManager

logger = logging.getLogger(__name__)

RESUMES_DIR = Path("tmp/resumes")
MAX_WE_SLOTS = 4


def _build_task_prompt(job: dict, profile: dict = None) -> str:
    """Build a tight, single-job task prompt for the browser agent."""
    if not profile:
        profile = candidate_manager.get_active_profile()

    title = job.get("title", "Unknown Role")
    job_link = job.get("job_link", "")
    p = profile.get("personal", {})
    r = profile.get("resume", {})
    cred = profile.get("credentials", {})

    email = p.get("email", "")
    full_name = p.get("full_name", "")
    sig = p.get("electronic_signature", full_name)
    gender = p.get("gender", "")
    veteran = p.get("veteran", "No")
    disability = p.get("disability", "No")
    default_pw = cred.get("default_password", "")
    strong_pw = cred.get("strong_password", "")
    resume_filename = r.get("filename", "Resume.pdf")
    # Resolve the full path so upload_file can match it without relying on CWD
    resume_full_path = candidate_manager.resolve_resume_path(profile) or resume_filename
    linkedin = p.get("linkedin_url", "")
    candidate_profile_text = candidate_manager.format_candidate_profile_prompt(profile)

    return f"""Apply to the job below using the provided candidate profile.

JOB TITLE: {title}
LINKEDIN JOB POST LINK: {job_link} (CRITICAL: ALWAYS ignore this link. Do NOT navigate to or click this URL. It is a LinkedIn page, which must be ignored. You must search Google for the official company website or direct ATS portal to apply.)

{candidate_profile_text}

=== CORE RULES & TOOLS ===
1. SEARCH: Search Google for the official careers page or direct ATS portal of the company using the Job Title or info from the LinkedIn link.
   CRITICAL: ALWAYS ignore any LinkedIn link. Do NOT navigate to it. NEVER click LinkedIn, Indeed, Glassdoor, or job board links. Only click official company career pages or direct ATS application links (Workday, Greenhouse, Lever, Teamio, SmartRecruiters).
2. CREDENTIALS & LOGIN:
   - On any login/signup screen, immediately call `lookup_site_credentials(url)`. If found, log in.
   - Otherwise, register using Email: {email}, Password: {default_pw} (or {strong_pw}), Full Name: {full_name}.
   - After registering, immediately call `save_site_credentials(url, email, password, note)`.
3. EMAIL VERIFICATION: If prompted for an email verification code sent to {email}, do NOT navigate away. Call `read_verification_email` to retrieve the code or link.
4. RESUME UPLOAD (CRITICAL): NEVER click file upload buttons (`click_element` opens an OS popup that freezes the browser). ALWAYS call `upload_file(index, "{resume_full_path}")` directly on the upload element. Wait 3s for auto-fill.
5. FORM FILLING:
   - Fill ONLY required/mandatory fields using the profile. Skip optional fields.
   - Date of Birth: Type "1995-05-05" or "05/05/1995" directly into text inputs before trying visual pickers.
   - LinkedIn: If requested, enter "{linkedin}".
   - Regulatory: Gender: {gender}, Veteran: {veteran}, Disability: {disability}, Work Auth: Yes (EU authorized). Answer "No" to conflict/auditor/relatives questions. Write 2-3 enthusiastic sentences for motivation essays.
   - Signature: Type "{sig}".
6. SUBMISSION & RETRY:
   - Verify required fields are filled, then click Submit.
   - If submission fails with missing field validation errors (red outline/*), fill ONLY the uncompleted required fields and submit again. Do NOT refill already valid fields.

7. SITE SKILLS (.md files):
   - Upon visiting any company job portal or ATS domain, immediately call `lookup_site_skill(url)` to retrieve efficiency instructions for applying on that site.
   - Before finishing or if you discover new navigation patterns/quirks on the site, call `save_site_skill(url, instructions)` to create/update an .md skill file so future AI models can proceed more efficiently.
8. CAPTCHAs & SECURITY PROMPTS:
   - If a Turnstile or simple checkbox ('Verify you are human' / 'I am not a robot') appears, immediately call `solve_turnstile_or_checkbox`.
   - If an image grid or audio challenge appears, call `solve_captcha_via_audio`.
   - If automated resolution fails after 1 retry, call `pause_for_human_captcha_help` to abort this job and move to the next one.

=== COMPLETION ===
- On success page: you MUST stop and output exactly `DONE: <confirmation_url>`
- If stuck after 2 retries or unresolvable error: stop and output exactly `ERROR: <brief reason>`
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _jobs_to_table(jobs: list[dict]) -> list[list]:
    """Convert job dicts to a list-of-lists for gr.Dataframe."""
    rows = []
    for j in jobs:
        rows.append([
            j.get("title", ""),
            j.get("job_date", ""),
            "⏳ Pending",
            j.get("id", ""),
        ])
    return rows


def _we_slot(work: list, idx: int) -> dict:
    return work[idx] if idx < len(work) else {}


def _profile_to_form(profile: dict) -> tuple:
    """Extract form field values from a profile dict (supports up to MAX_WE_SLOTS positions)."""
    p   = profile.get("personal", {})
    work = profile.get("work_experience", [])
    edu  = profile.get("education", [])
    pref = profile.get("preferences", {})
    r    = profile.get("resume", {})
    ed1  = edu[0] if edu else {}

    values = [
        p.get("full_name", ""),
        p.get("email", ""),
        p.get("phone", ""),
        p.get("city", ""),
        p.get("country", ""),
        p.get("zip_code", ""),
        p.get("street_address", ""),
        p.get("linkedin_url", ""),
        p.get("date_of_birth", ""),
        r.get("file_path", ""),
    ]
    for i in range(MAX_WE_SLOTS):
        we = _we_slot(work, i)
        values += [
            we.get("company", ""),
            we.get("title", ""),
            we.get("start_date", ""),
            we.get("end_date", ""),
            we.get("description", ""),
        ]
    values += [
        ed1.get("university", ""),
        ed1.get("degree_level", ""),
        ed1.get("major", ""),
        ed1.get("graduation_date", ""),
        ed1.get("status", ""),
        pref.get("desired_salary", ""),
        pref.get("notice_period", ""),
        # Extra personal fields appended at end to preserve existing indices
        p.get("work_authorization", ""),
        str(p.get("years_of_experience", "")),
        # Credentials (indices 39-40)
        profile.get("credentials", {}).get("default_password", ""),
        profile.get("credentials", {}).get("strong_password", ""),
    ]
    return tuple(values)


def _form_to_profile(existing: dict, *args) -> dict:
    """Merge flat form values back into a profile dict.

    Expected args order (matches _profile_to_form output, minus resume_path):
      full_name, email, phone, city, country, zip_code, street, linkedin, dob,
      resume_path,
      [company, title, start, end, desc] × MAX_WE_SLOTS,
      edu_university, edu_degree, edu_major, edu_grad, edu_status,
      salary, notice
    """
    profile = json.loads(json.dumps(existing))  # deep copy

    (
        full_name, email, phone,
        city, country, zip_code, street,
        linkedin, dob,
        resume_path,
    ) = args[:10]

    # Work experience slots
    we_entries = []
    for i in range(MAX_WE_SLOTS):
        base = 10 + i * 5
        company, title, start, end, desc = args[base: base + 5]
        if (company or "").strip():
            we_entries.append({
                "company": company,
                "title": title,
                "start_date": start,
                "end_date": end,
                "description": desc,
            })

    tail_start = 10 + MAX_WE_SLOTS * 5
    (
        edu_university, edu_degree, edu_major, edu_grad, edu_status,
        salary, notice,
        work_auth, years_exp,
        default_pw, strong_pw,
    ) = args[tail_start:]

    p = profile.setdefault("personal", {})
    parts = (full_name or "").split(" ", 1)
    p["full_name"]             = full_name
    p["first_name"]            = parts[0] if parts else ""
    p["last_name"]             = parts[1] if len(parts) > 1 else ""
    p["email"]                 = email
    p["phone"]                 = phone
    p["city"]                  = city
    p["country"]               = country
    p["zip_code"]              = zip_code
    p["street_address"]        = street
    p["linkedin_url"]          = linkedin
    p["date_of_birth"]         = dob
    p["electronic_signature"]  = full_name
    p["work_authorization"]    = work_auth
    if years_exp and str(years_exp).strip():
        p["years_of_experience"] = years_exp
    if city and country:
        p["current_location"]  = f"{country} (CEST)"

    cred = profile.setdefault("credentials", {})
    if default_pw:
        cred["default_password"] = default_pw
    if strong_pw:
        cred["strong_password"]  = strong_pw

    if we_entries:
        profile["work_experience"] = we_entries

    if (edu_university or "").strip():
        profile["education"] = [{
            "university":    edu_university,
            "degree_level":  edu_degree,
            "major":         edu_major,
            "graduation_date": edu_grad,
            "status":        edu_status,
        }]

    pref = profile.setdefault("preferences", {})
    pref["desired_salary"] = salary
    pref["notice_period"]  = notice

    return profile


# ---------------------------------------------------------------------------
# Core batch-run generator
# ---------------------------------------------------------------------------

async def _run_batch(
    webui_manager: WebuiManager,
    table_data,
    log_box,
    table_comp,
    start_btn,
    stop_btn,
    refresh_btn,
) -> AsyncGenerator:
    """
    Async generator that runs the browser agent for each pending job.
    Yields Gradio component updates after each step.
    """
    webui_manager.ja_stop_requested = False

    jobs = webui_manager.airtable_jobs
    if not jobs:
        yield {
            log_box: gr.update(value=" No unapplied jobs loaded. Click Refresh first."),
            start_btn: gr.update(interactive=True),
            stop_btn: gr.update(interactive=False),
            refresh_btn: gr.update(interactive=True),
        }
        return

    llm_provider_name = os.getenv("DEFAULT_LLM", "google")

    # ── Pre-flight: verify the API key for the configured provider ────────────
    _key_map = {
        "google":    ("GOOGLE_API_KEY",    "Google Gemini", " Setup tab → Gemini section"),
        "openai":    ("OPENAI_API_KEY",    "OpenAI",        "your OpenAI dashboard"),
        "anthropic": ("ANTHROPIC_API_KEY", "Anthropic",     "your Anthropic dashboard"),
    }
    if llm_provider_name in _key_map:
        _env_var, _provider_name, _where = _key_map[llm_provider_name]
        _key_val = os.getenv(_env_var, "").strip()
        _placeholder = not _key_val or _key_val.startswith("<")
        if _placeholder:
            yield {
                log_box: gr.update(
                    value=(
                        f"❌ {_provider_name} API key is missing or still set to the placeholder value.\n\n"
                        f"Go to {_where}, paste your real key, and click Save & Test.\n"
                        f"Then restart the app for the key to take effect.\n\n"
                        f"(env var: {_env_var}, DEFAULT_LLM={llm_provider_name})"
                    )
                ),
                start_btn: gr.update(interactive=True),
                stop_btn: gr.update(interactive=False),
                refresh_btn: gr.update(interactive=True),
            }
            return

    from src.utils.config import model_names
    provider_models = model_names.get(llm_provider_name, [])
    model_name = provider_models[0] if provider_models else "gemini-2.5-flash"

    try:
        main_llm = llm_provider_module.get_llm_model(
            provider=llm_provider_name,
            model_name=model_name,
            temperature=0.3,
            base_url=None,
            api_key=None,
        )
    except Exception as e:
        yield {
            log_box: gr.update(value=f"❌ Failed to initialize LLM: {e}"),
            start_btn: gr.update(interactive=True),
            stop_btn: gr.update(interactive=False),
            refresh_btn: gr.update(interactive=True),
        }
        return

    browser_path = os.getenv("BROWSER_PATH", None) or None
    use_own_browser = os.getenv("USE_OWN_BROWSER", "false").lower() in ("true", "1", "yes")

    extra_args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-infobars",
        "--no-first-run",
    ]
    if use_own_browser and browser_path:
        user_data = os.getenv("BROWSER_USER_DATA", "") or None
        if user_data:
            extra_args.append(f"--user-data-dir={user_data}")

    env_browser_path = os.getenv("BROWSER_PATH", "")
    browser_class = "firefox" if "firefox" in env_browser_path.lower() else "chromium"

    if not webui_manager.bu_browser:
        webui_manager.bu_browser = CustomBrowser(
            config=BrowserConfig(
                headless=False,
                disable_security=False,
                browser_binary_path=browser_path if use_own_browser else None,
                browser_class=browser_class,
                extra_browser_args=extra_args,
                cdp_url=os.getenv("BROWSER_CDP") or None,
                new_context_config=BrowserContextConfig(window_width=1920, window_height=1080),
            )
        )

    if not webui_manager.bu_browser_context:
        webui_manager.bu_browser_context = await webui_manager.bu_browser.new_context(
            config=BrowserContextConfig(window_width=1920, window_height=1080)
        )

    if not webui_manager.bu_controller:
        webui_manager.bu_controller = CustomController()

    import pandas as pd
    if table_data is None or (isinstance(table_data, pd.DataFrame) and table_data.empty):
        rows = _jobs_to_table(jobs)
    else:
        rows = [list(r) for r in table_data.values]
    log_lines = [" Batch started. Processing {} job(s)…".format(len(jobs))]

    yield {
        log_box: gr.update(value="\n".join(log_lines)),
        table_comp: gr.update(value=rows),
        start_btn: gr.update(interactive=False, value="⏳ Running…"),
        stop_btn: gr.update(interactive=True),
        refresh_btn: gr.update(interactive=False),
    }

    save_path = "./tmp/agent_history"
    os.makedirs(save_path, exist_ok=True)

    for idx, job in enumerate(jobs):
        if webui_manager.ja_stop_requested:
            log_lines.append(" Batch stopped by user.")
            yield {
                log_box: gr.update(value="\n".join(log_lines)),
                table_comp: gr.update(value=rows),
            }
            break

        title = job.get("title", f"Job #{idx + 1}")
        record_id = job["id"]
        log_lines.append(f"\n[{idx + 1}/{len(jobs)}] Applying to: {title}")
        rows[idx][2] = " In Progress"

        yield {
            log_box: gr.update(value="\n".join(log_lines)),
            table_comp: gr.update(value=rows),
        }

        active_prof = candidate_manager.get_active_profile()
        task_prompt = _build_task_prompt(job, active_prof)
        resume_file = candidate_manager.resolve_resume_path(active_prof)
        if not resume_file:
            stored = active_prof.get("resume", {}).get("file_path", "")
            filename = active_prof.get("resume", {}).get("filename", "")
            logger.warning(
                "Resume file not found on disk! stored_path=%r filename=%r — "
                "place '%s' in the project root folder or update file_path in the profile.",
                stored, filename, filename,
            )
        file_paths = [resume_file] if resume_file else []

        task_id = str(uuid.uuid4())
        history_dir = os.path.join(save_path, task_id)
        os.makedirs(history_dir, exist_ok=True)

        success = False
        error_msg = ""

        # --- Clean up browser state before starting a new job ---
        # Strategy: close and recreate the Playwright context rather than
        # reset_context(). reset_context() closes individual pages while the
        # CDP background task may still be dispatching messages for them,
        # producing KeyError('page@...') that kills the whole connection.
        #
        # Additionally, agent.close() in the previous job's finally-block
        # can tear down the shared browser process. We detect that by catching
        # TargetClosedError when creating a new context, then rebuilding the
        # browser from scratch before retrying.

        # 1. Discard the old context object (already closed by agent.close()).
        if webui_manager.bu_browser_context is not None:
            try:
                pw_ctx = getattr(webui_manager.bu_browser_context, "context", None)
                if pw_ctx is not None:
                    await pw_ctx.close()
            except Exception:
                pass
            webui_manager.bu_browser_context = None

        # 2. Try to open a fresh context on the existing browser.
        #    If the browser process died, recreate it and retry once.
        for attempt in range(2):
            if webui_manager.bu_browser is None or attempt == 1:
                # (Re)create the browser from scratch.
                logger.info("(Re)creating browser for job '%s' (attempt %d)", title, attempt + 1)
                webui_manager.bu_browser = CustomBrowser(
                    config=BrowserConfig(
                        headless=False,
                        disable_security=False,
                        browser_binary_path=browser_path if use_own_browser else None,
                        browser_class=browser_class,
                        extra_browser_args=extra_args,
                        cdp_url=os.getenv("BROWSER_CDP") or None,
                        new_context_config=BrowserContextConfig(window_width=1920, window_height=1080),
                    )
                )
            try:
                webui_manager.bu_browser_context = await webui_manager.bu_browser.new_context(
                    config=BrowserContextConfig(window_width=1920, window_height=1080)
                )
                logger.info("Created fresh browser context for job '%s'", title)
                break
            except Exception as ctx_exc:
                logger.warning("Browser context creation failed (attempt %d): %s", attempt + 1, ctx_exc)
                # Mark browser as dead so next iteration rebuilds it.
                webui_manager.bu_browser = None
                webui_manager.bu_browser_context = None
                if attempt == 1:
                    logger.error("Could not create browser context after rebuild for job '%s'", title)
                    rows[idx][2] = "❌ Browser Error"
                    log_lines.append(f"    Browser unavailable: {ctx_exc}")
                    yield {log_box: gr.update(value="\n".join(log_lines)), table_comp: gr.update(value=rows)}
                    continue

        try:
            agent = BrowserUseAgent(
                task=task_prompt,
                llm=main_llm,
                browser=webui_manager.bu_browser,
                browser_context=webui_manager.bu_browser_context,
                controller=webui_manager.bu_controller,
                use_vision=True,
                max_input_tokens=128000,
                max_actions_per_step=10,
                available_file_paths=file_paths,
                source="webui",
                # Disable mem0 procedural-memory consolidation.
                # Each consolidation makes a full LLM call that can block the
                # asyncio event loop for 100+ seconds with GPT-5.5, causing the
                # Playwright CDP connection to time out and killing the browser.
                # With max_input_tokens=128000 the context window is large
                # enough to hold the full conversation without compression.
                enable_memory=False,
            )
            agent.state.agent_id = task_id

            history: AgentHistoryList = await agent.run(max_steps=50)

            final = (history.final_result() or "").strip()
            errors = [e for e in (history.errors() or []) if e]

            final_lower = final.lower()
            if final.startswith("DONE") or "confirmation url" in final_lower or ("application for" in final_lower and "complete" in final_lower) or "success" in final_lower:
                success = True
                log_lines.append(f"   ✅ Success: {final}")
            elif final.startswith("ERROR"):
                success = False
                error_msg = final
                log_lines.append(f"   ❌ Error: {error_msg}")
            elif not final and errors:
                success = False
                error_msg = str(errors[-1])
                log_lines.append(f"   ❌ Error: {error_msg}")
            else:
                success = True
                log_lines.append(f"   ✅ Completed. Result: {final[:120]}")

        except Exception as exc:
            error_msg = str(exc)
            logger.exception("Agent crashed for job %s", title)
            log_lines.append(f"    Exception: {error_msg[:200]}")

        try:
            if success:
                airtable_client.mark_as_applied(record_id)
                rows[idx][2] = "✅ Applied"
                log_lines.append("    Airtable updated: Applied=true")
            else:
                airtable_client.log_error(record_id, error_msg or "Unknown error")
                rows[idx][2] = "❌ Error"
                log_lines.append("    Airtable updated: error logged")
        except Exception as api_exc:
            log_lines.append(f"    Airtable API update failed: {api_exc}")
            rows[idx][2] = " API Error"

        yield {
            log_box: gr.update(value="\n".join(log_lines)),
            table_comp: gr.update(value=rows),
        }

        await asyncio.sleep(2)

    log_lines.append("\n Batch complete.")

    try:
        webui_manager.airtable_jobs = airtable_client.get_unapplied_jobs()
        log_lines.append(f" Remaining unapplied: {len(webui_manager.airtable_jobs)}")
    except Exception:
        pass

    yield {
        log_box: gr.update(value="\n".join(log_lines)),
        table_comp: gr.update(value=_jobs_to_table(webui_manager.airtable_jobs)),
        start_btn: gr.update(interactive=True, value="Start Batch"),
        stop_btn: gr.update(interactive=False),
        refresh_btn: gr.update(interactive=True),
    }


# ---------------------------------------------------------------------------
# Gradio tab builder
# ---------------------------------------------------------------------------

def create_job_applicator_tab(webui_manager: WebuiManager) -> None:
    """Registers the  Job Applicator tab inside the existing Gradio Blocks."""

    webui_manager.init_browser_use_agent()

    n_jobs = len(webui_manager.airtable_jobs)
    initial_rows = _jobs_to_table(webui_manager.airtable_jobs) if webui_manager.airtable_jobs else []
    initial_status = (
        f"✅ **{n_jobs} unapplied job(s) loaded from Airtable at startup.**"
        if webui_manager.airtable_jobs
        else " No jobs loaded yet. Click **Refresh from Airtable**."
    )

    with gr.Column():
        gr.Markdown(
            """
            ##  Job Applicator
            Jobs are fetched from Airtable **at startup** and stored in memory.
            The browser never touches Airtable — all status updates go directly via the REST API.
            """,
        )

        status_label = gr.Markdown(initial_status, elem_id="ja_status_label")

        # ── Candidate Profile ──────────────────────────────────────────────────
        # Load active profile values at build time so fields are pre-filled on first open
        _init_prof = candidate_manager.get_active_profile()
        _iv = list(_profile_to_form(_init_prof))
        # _iv indices: 0-8 personal, 9 resume_path, 10-29 WE (4×5), 30-34 edu,
        #              35-36 prefs, 37 work_auth, 38 years_exp
        _init_n_we = max(2, min(len(_init_prof.get("work_experience", [])), MAX_WE_SLOTS))

        with gr.Accordion("Candidate Profile", open=False):

            # Active candidate selector at the top
            profile_selector = gr.Dropdown(
                label="Active Candidate",
                choices=candidate_manager.get_all_profile_names(),
                value=candidate_manager.get_active_profile_name(),
            )

            # ── Personal Information ──────────────────────────────────────────
            with gr.Accordion("Personal Information", open=True):
                with gr.Row():
                    pf_full_name = gr.Textbox(label="Full Name *", placeholder="Jane Doe", scale=2, value=_iv[0])
                    pf_email     = gr.Textbox(label="Email *", placeholder="jane@outlook.com", scale=2, value=_iv[1])
                    pf_phone     = gr.Textbox(label="Phone", placeholder="+1 555 000 0000", scale=1, value=_iv[2])
                with gr.Row():
                    pf_years_exp = gr.Textbox(label="Years of Experience", placeholder="5", scale=1, value=_iv[38])
                    pf_work_auth = gr.Textbox(label="Visa / Work Authorization", placeholder="EU citizen, no sponsorship required", scale=3, value=_iv[37])
                gr.Markdown("**Home Address**")
                with gr.Row():
                    pf_city    = gr.Textbox(label="City", placeholder="Prague", value=_iv[3])
                    pf_country = gr.Textbox(label="Country", placeholder="Czechia", value=_iv[4])
                    pf_zip     = gr.Textbox(label="Zip Code", placeholder="110 00", value=_iv[5])
                pf_street = gr.Textbox(label="Street Address", placeholder="Main Street 1", value=_iv[6])
                with gr.Row():
                    pf_linkedin = gr.Textbox(label="LinkedIn URL", placeholder="https://linkedin.com/in/janedoe", scale=3, value=_iv[7])
                    pf_dob      = gr.Textbox(label="Date of Birth (YYYY-MM-DD)", placeholder="1995-05-05", scale=1, value=_iv[8])

            # ── Resume ────────────────────────────────────────────────────────
            with gr.Accordion("Resume", open=True):
                pf_resume_path   = gr.Textbox(label="Current Resume File", interactive=False, value=_iv[9])
                pf_resume_upload = gr.File(
                    label="Upload New Resume PDF",
                    file_types=[".pdf"],
                    file_count="single",
                )
                with gr.Row():
                    pf_autofill_btn = gr.Button(
                        "Parse & Autofill from Resume",
                        variant="secondary",
                        size="sm",
                        scale=2,
                    )
                pf_resume_status = gr.Markdown("")

            # ── Work Experience ───────────────────────────────────────────────
            with gr.Accordion("Work Experience", open=True):
                we_state  = gr.State(value=_init_n_we)
                we_groups = []
                we_fields = []

                _we_labels = [
                    "Position 1 — Current / Most Recent",
                    "Position 2 — Previous",
                    "Position 3",
                    "Position 4",
                ]
                for i in range(MAX_WE_SLOTS):
                    _base = 10 + i * 5
                    with gr.Group(visible=(i < _init_n_we)) as grp:
                        gr.Markdown(f"**{_we_labels[i]}**")
                        with gr.Row():
                            co = gr.Textbox(label="Company",   value=_iv[_base])
                            ti = gr.Textbox(label="Job Title", value=_iv[_base + 1])
                        with gr.Row():
                            st = gr.Textbox(label="Start Date", placeholder="MM/YYYY", value=_iv[_base + 2])
                            en = gr.Textbox(label="End Date", placeholder="Present" if i == 0 else "MM/YYYY", value=_iv[_base + 3])
                        de = gr.Textbox(label="Description", lines=2, value=_iv[_base + 4])
                    we_groups.append(grp)
                    we_fields.append((co, ti, st, en, de))

                add_we_btn = gr.Button("Add Another Position", size="sm")

            # ── Education ─────────────────────────────────────────────────────
            _edu_base = 10 + MAX_WE_SLOTS * 5  # 30
            with gr.Accordion("Education", open=False):
                with gr.Row():
                    pf_edu_university = gr.Textbox(label="University / School",                      value=_iv[_edu_base])
                    pf_edu_degree     = gr.Textbox(label="Degree Level", placeholder="Master's Degree", value=_iv[_edu_base + 1])
                with gr.Row():
                    pf_edu_major = gr.Textbox(label="Major / Field of Study",                        value=_iv[_edu_base + 2])
                    pf_edu_grad  = gr.Textbox(label="Graduation Year", placeholder="2022",           value=_iv[_edu_base + 3])
                pf_edu_status = gr.Textbox(label="Status", placeholder="Completed / Graduated",      value=_iv[_edu_base + 4])

            # ── Application Preferences (flat, inside Candidate Profile) ──────
            _pref_base = _edu_base + 5  # 35
            gr.Markdown("**Application Preferences**")
            with gr.Row():
                pf_salary = gr.Textbox(label="Desired Salary", placeholder="5,000 EUR",          value=_iv[_pref_base])
                pf_notice = gr.Textbox(label="Notice Period",  placeholder="Immediate / 1 month", value=_iv[_pref_base + 1])

            # ── Login Credentials ─────────────────────────────────────────────
            gr.Markdown(
                "**Login Credentials**  \n"
                "Used when the agent registers a new account on a job site. "
                "Strong password is used on sites that require special characters."
            )
            with gr.Row():
                pf_default_pw = gr.Textbox(
                    label="Default Password",
                    placeholder="Abc123!",
                    type="password",
                    value=_iv[37 + 2],   # index 39
                    scale=1,
                )
                pf_strong_pw  = gr.Textbox(
                    label="Strong Password",
                    placeholder="Abc123!@#",
                    type="password",
                    value=_iv[37 + 3],   # index 40
                    scale=1,
                )

            # ── Save / New profile buttons at the bottom ──────────────────────
            with gr.Row():
                new_profile_name_box = gr.Textbox(
                    label="Save as new profile (leave blank to update current)",
                    placeholder="Jane Doe",
                    scale=3,
                )
                add_profile_btn = gr.Button("Save as New Profile", variant="secondary", scale=1)

            profile_save_btn = gr.Button("Save Profile", variant="primary")

        # ── Jobs table ────────────────────────────────────────────────────────
        jobs_table = gr.Dataframe(
            value=initial_rows,
            headers=["Title", "Job Date", "Status", "Record ID"],
            datatype=["str", "str", "str", "str"],
            row_count=(max(1, n_jobs), "dynamic"),
            col_count=(4, "fixed"),
            label="Unapplied Jobs",
            interactive=False,
            wrap=True,
        )

        with gr.Row():
            refresh_btn     = gr.Button(" Refresh from Airtable", variant="secondary", scale=1)
            start_btn       = gr.Button("Start Batch", variant="primary", scale=2)
            stop_btn        = gr.Button("⏹ Stop", variant="stop", interactive=False, scale=1)
            reset_errors_btn = gr.Button(" Reset Errors → New", variant="secondary", scale=1)

        log_box = gr.Textbox(
            label=" Live Log",
            lines=20,
            max_lines=40,
            interactive=False,
            placeholder="Logs will appear here when the batch runs…",
        )

    # ── Flat field lists (must mirror _profile_to_form / _form_to_profile) ───
    _we_flat = [field for slot in we_fields for field in slot]   # MAX_WE_SLOTS × 5

    _form_inputs = [
        pf_full_name, pf_email, pf_phone,
        pf_city, pf_country, pf_zip, pf_street,
        pf_linkedin, pf_dob,
        pf_resume_path,
        *_we_flat,
        pf_edu_university, pf_edu_degree, pf_edu_major, pf_edu_grad, pf_edu_status,
        pf_salary, pf_notice,
        pf_work_auth, pf_years_exp,   # indices 37, 38
        pf_default_pw, pf_strong_pw,  # indices 39, 40 — must stay at end
    ]
    _form_outputs = _form_inputs  # same set for reading and writing

    # Visibility outputs: we_state + each WE group
    _we_vis_outputs = [we_state] + we_groups

    # ── Helpers shared by multiple callbacks ─────────────────────────────────

    def _visibility_for_profile(profile: dict):
        """Return (new_we_count, [gr.update(visible=...) × MAX_WE_SLOTS])."""
        n = max(2, min(len(profile.get("work_experience", [])), MAX_WE_SLOTS))
        return n, [gr.update(visible=(i < n)) for i in range(MAX_WE_SLOTS)]

    # ── Profile selector change ───────────────────────────────────────────────
    def _on_profile_select(name: str):
        candidate_manager.set_active_profile(name)
        prof = candidate_manager.get_profile_by_name(name)
        form_vals = list(_profile_to_form(prof))
        n, grp_updates = _visibility_for_profile(prof)
        return form_vals + [n] + grp_updates

    profile_selector.change(
        fn=_on_profile_select,
        inputs=[profile_selector],
        outputs=_form_outputs + _we_vis_outputs,
    )

    # ── Add Another Position button ───────────────────────────────────────────
    def _add_we_slot(count: int):
        new_count = min(count + 1, MAX_WE_SLOTS)
        grp_updates = [gr.update(visible=(i < new_count)) for i in range(MAX_WE_SLOTS)]
        btn_update  = gr.update(visible=(new_count < MAX_WE_SLOTS))
        return [new_count] + grp_updates + [btn_update]

    add_we_btn.click(
        fn=_add_we_slot,
        inputs=[we_state],
        outputs=[we_state] + we_groups + [add_we_btn],
    )

    # ── Resume upload — save file and update path display ────────────────────
    def _on_resume_upload(file_data, profile_name: str):
        if file_data is None:
            return gr.update(), gr.update(value="No file selected.")

        # Gradio 5 can return a string path, a dict, or a NamedString
        if isinstance(file_data, dict):
            src_path = file_data.get("path") or file_data.get("name", "")
            filename  = file_data.get("orig_name") or Path(src_path).name
        else:
            src_path = str(file_data)
            filename  = Path(src_path).name

        if not src_path or not Path(src_path).exists():
            return gr.update(), gr.update(value=f"❌ Could not read uploaded file (path: {src_path!r})")

        RESUMES_DIR.mkdir(parents=True, exist_ok=True)
        dest = RESUMES_DIR / filename
        shutil.copy(src_path, dest)
        dest_str = str(dest.resolve())

        # Persist the path into the candidate profile immediately
        profile = candidate_manager.get_profile_by_name(profile_name) or {}
        profile.setdefault("resume", {})
        profile["resume"]["file_path"] = dest_str
        profile["resume"]["filename"]  = filename
        candidate_manager.save_profile(profile_name, profile)

        return (
            gr.update(value=dest_str),
            gr.update(value=f"✅ Resume saved: **{filename}** — click **Parse & Autofill** to populate the form"),
        )

    # Use .upload() — fires when a file is selected; .change() can be unreliable for File in Gradio 5
    pf_resume_upload.upload(
        fn=_on_resume_upload,
        inputs=[pf_resume_upload, profile_selector],
        outputs=[pf_resume_path, pf_resume_status],
    )

    # ── Parse & Autofill button ───────────────────────────────────────────────
    def _on_autofill(profile_name: str, resume_path: str):
        # Priority: saved profile path > pf_resume_path textbox value
        # (the textbox may not reflect the upload yet if the event fired out of order)
        profile = candidate_manager.get_profile_by_name(profile_name) or {}
        path = candidate_manager.resolve_resume_path(profile)

        # Fall back to the textbox value if the profile path didn't resolve
        if not path:
            path = (resume_path or "").strip()
            if path and not Path(path).exists():
                path = ""

        if not path:
            yield [gr.update()] * len(_form_inputs) + [gr.update()] + [gr.update()] * MAX_WE_SLOTS + \
                  [gr.update(value="❌ No resume file found. Upload a PDF first, then click Parse & Autofill.")]
            return

        # Check upfront if libraries are available so we can show install message
        try:
            import pypdf as _pypdf_check  # noqa: F401
            _libs_ok = True
        except ImportError:
            try:
                from pdfminer.high_level import extract_text as _pm_check  # noqa: F401
                _libs_ok = True
            except ImportError:
                _libs_ok = False

        _status_msg = (
            "⏳ Extracting text from PDF…" if _libs_ok
            else "⏳ Installing PDF libraries (one-time, ~30 seconds)…"
        )
        yield [gr.update()] * len(_form_inputs) + [gr.update()] + [gr.update()] * MAX_WE_SLOTS + \
              [gr.update(value=_status_msg)]

        try:
            text = resume_parser.extract_text_from_pdf(path)
        except PdfExtractionError as exc:
            yield [gr.update()] * len(_form_inputs) + [gr.update()] + [gr.update()] * MAX_WE_SLOTS + \
                  [gr.update(value=f"❌ {exc}")]
            return

        if not text.strip():
            yield [gr.update()] * len(_form_inputs) + [gr.update()] + [gr.update()] * MAX_WE_SLOTS + \
                  [gr.update(value=(
                      "❌ No text found in PDF — it may be a scanned image.  \n"
                      "Try exporting your CV as a text-based PDF from Word / Google Docs."
                  ))]
            return

        yield [gr.update()] * len(_form_inputs) + [gr.update()] + [gr.update()] * MAX_WE_SLOTS + \
              [gr.update(value="⏳ Parsing resume with AI — this takes a few seconds…")]

        data = resume_parser.parse_resume_with_llm(text)
        if not data:
            yield [gr.update()] * len(_form_inputs) + [gr.update()] + [gr.update()] * MAX_WE_SLOTS + \
                  [gr.update(value="❌ AI parsing failed. Is GOOGLE_API_KEY set in Setup tab?")]
            return

        # Start from the existing profile so non-resume fields (credentials etc.) are preserved
        profile = json.loads(json.dumps(candidate_manager.get_profile_by_name(profile_name) or {}))

        # ── Personal fields: use LLM value when present ───────────────────────
        p = profile.setdefault("personal", {})
        for key in ("full_name", "email", "phone", "city", "country",
                    "zip_code", "street_address", "linkedin_url", "date_of_birth",
                    "work_authorization", "years_of_experience"):
            val = data.get(key, "")
            if val:
                p[key] = val

        # ── Work experience: ALWAYS replace with what the LLM found ──────────
        # Even if empty — old WE data should not silently persist after autofill.
        # Filter out fully-empty entries the LLM may have returned as placeholders.
        we_raw = data.get("work_experience") or []
        we_clean = [e for e in we_raw if any(v for v in e.values() if v)]
        if we_clean:
            profile["work_experience"] = we_clean
        elif we_raw is not None:
            # LLM returned an empty list — clear existing so fields go blank
            profile["work_experience"] = []

        # ── Education: same logic ─────────────────────────────────────────────
        edu_raw = data.get("education") or []
        edu_clean = [e for e in edu_raw if any(v for v in e.values() if v)]
        if edu_clean:
            profile["education"] = edu_clean
        elif edu_raw is not None:
            profile["education"] = []

        pref = profile.setdefault("preferences", {})
        if data.get("desired_salary"):
            pref["desired_salary"] = data["desired_salary"]
        if data.get("notice_period"):
            pref["notice_period"] = data["notice_period"]

        form_vals = list(_profile_to_form(profile))
        n, grp_updates = _visibility_for_profile(profile)

        # Wrap every value in gr.update() so Gradio reliably refreshes all components
        yield [gr.update(value=v) for v in form_vals] + [n] + grp_updates + \
              [gr.update(value="✅ Form autofilled from resume — review and click **Save Profile**")]

    pf_autofill_btn.click(
        fn=_on_autofill,
        inputs=[profile_selector, pf_resume_path],
        outputs=_form_outputs + _we_vis_outputs + [pf_resume_status],
    )

    # ── Save profile from form ────────────────────────────────────────────────
    def _on_profile_save(name, *form_vals):
        existing = candidate_manager.get_profile_by_name(name) or {}
        # Preserve resume path if the read-only field came back empty
        resume_path = form_vals[9]   # index of pf_resume_path in _form_inputs
        if not resume_path and "resume" in existing:
            form_vals = list(form_vals)
            form_vals[9] = existing["resume"].get("file_path", "")

        updated = _form_to_profile(existing, *form_vals)
        candidate_manager.save_profile(name, updated, set_active=True)
        gr.Info(f"Profile '{name}' saved.")
        return gr.update(choices=candidate_manager.get_all_profile_names(), value=name)

    profile_save_btn.click(
        fn=_on_profile_save,
        inputs=[profile_selector] + _form_inputs,
        outputs=[profile_selector],
    )

    # ── Add as new profile ────────────────────────────────────────────────────
    def _on_profile_add(new_name, *form_vals):
        full_name  = form_vals[0]
        new_name   = (new_name or "").strip() or (full_name or "").strip()
        if not new_name:
            raise gr.Error("Enter a name for the new profile (or fill in Full Name).")
        updated = _form_to_profile({}, *form_vals)
        resume_path = form_vals[9]
        if resume_path:
            updated["resume"] = {
                "file_path": resume_path,
                "filename":  Path(resume_path).name,
            }
        candidate_manager.save_profile(new_name, updated, set_active=True)
        gr.Info(f"New profile '{new_name}' created and set as active.")
        return (
            gr.update(choices=candidate_manager.get_all_profile_names(), value=new_name),
            gr.update(value=""),
        )

    add_profile_btn.click(
        fn=_on_profile_add,
        inputs=[new_profile_name_box] + _form_inputs,
        outputs=[profile_selector, new_profile_name_box],
    )

    # ── Reset errors button ───────────────────────────────────────────────────
    def _do_reset_errors():
        try:
            from reset_airtable_errors import reset_errors
            reset_errors()
            # Reload the job list so reset records appear
            webui_manager.airtable_jobs = airtable_client.get_unapplied_jobs()
            count = len(webui_manager.airtable_jobs)
            rows  = _jobs_to_table(webui_manager.airtable_jobs)
            return (
                gr.update(value=rows),
                gr.update(value=f"✅ Errors reset to 'new'. **{count} unapplied job(s)** now loaded."),
                gr.update(value=""),
            )
        except Exception as exc:
            return (
                gr.update(),
                gr.update(value=f"❌ Reset failed: {exc}"),
                gr.update(),
            )

    reset_errors_btn.click(
        fn=_do_reset_errors,
        inputs=None,
        outputs=[jobs_table, status_label, log_box],
    )

    # ── Refresh button ────────────────────────────────────────────────────────
    def _do_refresh():
        try:
            webui_manager.airtable_jobs = airtable_client.get_unapplied_jobs()
            rows  = _jobs_to_table(webui_manager.airtable_jobs)
            count = len(webui_manager.airtable_jobs)
            return (
                gr.update(value=rows),
                gr.update(value=f"✅ **{count} unapplied job(s) loaded from Airtable.**"),
                gr.update(value=""),
            )
        except Exception as exc:
            return (
                gr.update(),
                gr.update(value=f"❌ Refresh failed: {exc}"),
                gr.update(),
            )

    refresh_btn.click(
        fn=_do_refresh,
        inputs=None,
        outputs=[jobs_table, status_label, log_box],
    )

    # ── Start batch button ────────────────────────────────────────────────────
    async def _start_wrapper(table_data):
        async for update in _run_batch(
            webui_manager, table_data,
            log_box, jobs_table, start_btn, stop_btn, refresh_btn,
        ):
            yield update

    start_event = start_btn.click(
        fn=_start_wrapper,
        inputs=[jobs_table],
        outputs=[log_box, jobs_table, start_btn, stop_btn, refresh_btn],
    )

    # ── Stop button ───────────────────────────────────────────────────────────
    # cancels=[start_event] tells Gradio to kill the running generator immediately.
    # The flag handles the between-jobs case where the generator is between yields.
    def _do_stop():
        webui_manager.ja_stop_requested = True
        return (
            gr.update(interactive=True,  value="Start Batch"),
            gr.update(interactive=False, value=" Stopped"),
            gr.update(interactive=True),
        )

    stop_btn.click(
        fn=_do_stop,
        inputs=None,
        outputs=[start_btn, stop_btn, refresh_btn],
        cancels=[start_event],
    )
