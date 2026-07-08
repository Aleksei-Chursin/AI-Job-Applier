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
from src.webui.webui_manager import WebuiManager

logger = logging.getLogger(__name__)

RESUMES_DIR = Path("tmp/resumes")


def _build_task_prompt(job: dict, profile: dict = None) -> str:
    """Build a tight, single-job task prompt for the browser agent."""
    if not profile:
        profile = candidate_manager.get_active_profile()

    title = job.get("title", "Unknown Role")
    job_link = job.get("job_link", "")
    p = profile.get("personal", {})
    r = profile.get("resume", {})
    cred = profile.get("credentials", {})

    email = p.get("email", "tom.petricek@outlook.com")
    full_name = p.get("full_name", "Tomas Petricek")
    sig = p.get("electronic_signature", full_name)
    gender = p.get("gender", "Male")
    veteran = p.get("veteran", "No")
    disability = p.get("disability", "No")
    default_pw = cred.get("default_password", "Metro_l123!")
    strong_pw = cred.get("strong_password", "Metro_l123!@#")
    resume_filename = r.get("filename", "Resume.pdf")
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
4. RESUME UPLOAD (CRITICAL): NEVER click file upload buttons (`click_element` opens an OS popup that freezes the browser). ALWAYS call `upload_file(index, "{resume_filename}")` directly on the upload element. Wait 3s for auto-fill.
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
   - If automated resolution fails or gets stuck, call `pause_for_human_captcha_help` so the user can complete it in the open browser tab.

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


def _profile_to_form(profile: dict) -> tuple:
    """Extract structured form field values from a profile dict."""
    p = profile.get("personal", {})
    work = profile.get("work_experience", [])
    edu = profile.get("education", [])
    pref = profile.get("preferences", {})
    r = profile.get("resume", {})

    we1 = work[0] if len(work) > 0 else {}
    we2 = work[1] if len(work) > 1 else {}
    ed1 = edu[0] if len(edu) > 0 else {}

    return (
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
        we1.get("company", ""),
        we1.get("title", ""),
        we1.get("start_date", ""),
        we1.get("end_date", ""),
        we1.get("description", ""),
        we2.get("company", ""),
        we2.get("title", ""),
        we2.get("start_date", ""),
        we2.get("end_date", ""),
        we2.get("description", ""),
        ed1.get("university", ""),
        ed1.get("degree_level", ""),
        ed1.get("major", ""),
        ed1.get("graduation_date", ""),
        ed1.get("status", ""),
        pref.get("desired_salary", ""),
        pref.get("notice_period", ""),
    )


def _form_to_profile(
    existing: dict,
    full_name: str, email: str, phone: str,
    city: str, country: str, zip_code: str, street: str,
    linkedin: str, dob: str,
    we1_company: str, we1_title: str, we1_start: str, we1_end: str, we1_desc: str,
    we2_company: str, we2_title: str, we2_start: str, we2_end: str, we2_desc: str,
    edu_university: str, edu_degree: str, edu_major: str, edu_grad: str, edu_status: str,
    salary: str, notice: str,
) -> dict:
    """Merge structured form values back into a profile dict, preserving fields not in the form."""
    profile = json.loads(json.dumps(existing))  # deep copy

    p = profile.setdefault("personal", {})
    parts = (full_name or "").split(" ", 1)
    p["full_name"] = full_name
    p["first_name"] = parts[0] if parts else ""
    p["last_name"] = parts[1] if len(parts) > 1 else ""
    p["email"] = email
    p["phone"] = phone
    p["city"] = city
    p["country"] = country
    p["zip_code"] = zip_code
    p["street_address"] = street
    p["linkedin_url"] = linkedin
    p["date_of_birth"] = dob
    p["electronic_signature"] = full_name
    # Derive current_location from city/country if present
    if city and country:
        p["current_location"] = f"{country} (CEST)"

    work = []
    if we1_company:
        work.append({
            "company": we1_company,
            "title": we1_title,
            "start_date": we1_start,
            "end_date": we1_end,
            "description": we1_desc,
        })
    if we2_company:
        work.append({
            "company": we2_company,
            "title": we2_title,
            "start_date": we2_start,
            "end_date": we2_end,
            "description": we2_desc,
        })
    if work:
        profile["work_experience"] = work

    if edu_university:
        profile["education"] = [{
            "university": edu_university,
            "degree_level": edu_degree,
            "major": edu_major,
            "graduation_date": edu_grad,
            "status": edu_status,
        }]

    pref = profile.setdefault("preferences", {})
    pref["desired_salary"] = salary
    pref["notice_period"] = notice

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
            log_box: gr.update(value="⚠️ No unapplied jobs loaded. Click Refresh first."),
            start_btn: gr.update(interactive=True),
            stop_btn: gr.update(interactive=False),
            refresh_btn: gr.update(interactive=True),
        }
        return

    llm_provider_name = os.getenv("DEFAULT_LLM", "google")

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
    log_lines = ["🚀 Batch started. Processing {} job(s)…".format(len(jobs))]

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
            log_lines.append("⛔ Batch stopped by user.")
            yield {
                log_box: gr.update(value="\n".join(log_lines)),
                table_comp: gr.update(value=rows),
            }
            break

        title = job.get("title", f"Job #{idx + 1}")
        record_id = job["id"]
        log_lines.append(f"\n▶ [{idx + 1}/{len(jobs)}] Applying to: {title}")
        rows[idx][2] = "🔄 In Progress"

        yield {
            log_box: gr.update(value="\n".join(log_lines)),
            table_comp: gr.update(value=rows),
        }

        active_prof = candidate_manager.get_active_profile()
        task_prompt = _build_task_prompt(job, active_prof)
        resume_file = active_prof.get("resume", {}).get("file_path", "")
        file_paths = [resume_file] if resume_file and os.path.exists(resume_file) else []

        task_id = str(uuid.uuid4())
        history_dir = os.path.join(save_path, task_id)
        os.makedirs(history_dir, exist_ok=True)

        success = False
        error_msg = ""

        if webui_manager.bu_browser_context:
            try:
                await webui_manager.bu_browser_context.reset_context()
                await webui_manager.bu_browser_context.create_new_tab("about:blank")
                logger.info("Reset browser context and opened blank tab for job %s", title)
            except Exception as reset_exc:
                logger.warning("Could not reset browser tabs before job: %s", reset_exc)

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
            log_lines.append(f"   💥 Exception: {error_msg[:200]}")

        try:
            if success:
                airtable_client.mark_as_applied(record_id)
                rows[idx][2] = "✅ Applied"
                log_lines.append("   📋 Airtable updated: Applied=true")
            else:
                airtable_client.log_error(record_id, error_msg or "Unknown error")
                rows[idx][2] = "❌ Error"
                log_lines.append("   📋 Airtable updated: error logged")
        except Exception as api_exc:
            log_lines.append(f"   ⚠️ Airtable API update failed: {api_exc}")
            rows[idx][2] = "⚠️ API Error"

        yield {
            log_box: gr.update(value="\n".join(log_lines)),
            table_comp: gr.update(value=rows),
        }

        await asyncio.sleep(2)

    log_lines.append("\n🏁 Batch complete.")

    try:
        webui_manager.airtable_jobs = airtable_client.get_unapplied_jobs()
        log_lines.append(f"🔄 Remaining unapplied: {len(webui_manager.airtable_jobs)}")
    except Exception:
        pass

    yield {
        log_box: gr.update(value="\n".join(log_lines)),
        table_comp: gr.update(value=_jobs_to_table(webui_manager.airtable_jobs)),
        start_btn: gr.update(interactive=True, value="▶ Start Batch"),
        stop_btn: gr.update(interactive=False),
        refresh_btn: gr.update(interactive=True),
    }


# ---------------------------------------------------------------------------
# Gradio tab builder
# ---------------------------------------------------------------------------

def create_job_applicator_tab(webui_manager: WebuiManager) -> None:
    """Registers the 🚀 Job Applicator tab inside the existing Gradio Blocks."""

    webui_manager.init_browser_use_agent()

    n_jobs = len(webui_manager.airtable_jobs)
    initial_rows = _jobs_to_table(webui_manager.airtable_jobs) if webui_manager.airtable_jobs else []
    initial_status = (
        f"✅ **{n_jobs} unapplied job(s) loaded from Airtable at startup.**"
        if webui_manager.airtable_jobs
        else "⚠️ No jobs loaded yet. Click **Refresh from Airtable**."
    )

    with gr.Column():
        gr.Markdown(
            """
            ## 🚀 Job Applicator
            Jobs are fetched from Airtable **at startup** and stored in memory.
            The browser never touches Airtable — all status updates go directly via the REST API.
            """,
        )

        status_label = gr.Markdown(initial_status, elem_id="ja_status_label")

        # ── Candidate Profile ──────────────────────────────────────────────────
        with gr.Accordion("👤 Candidate Profile", open=False):

            with gr.Row():
                profile_selector = gr.Dropdown(
                    label="Active Candidate",
                    choices=candidate_manager.get_all_profile_names(),
                    value=candidate_manager.get_active_profile_name(),
                    scale=3,
                )
                profile_save_btn = gr.Button("💾 Save Profile", variant="primary", scale=1)

            # ── Personal Information ──────────────────────────────────────────
            with gr.Accordion("Personal Information", open=True):
                with gr.Row():
                    pf_full_name = gr.Textbox(label="Full Name *", placeholder="Jane Doe", scale=2)
                    pf_email     = gr.Textbox(label="Email *", placeholder="jane@outlook.com", scale=2)
                    pf_phone     = gr.Textbox(label="Phone", placeholder="+1 555 000 0000", scale=1)
                with gr.Row():
                    pf_city    = gr.Textbox(label="City", placeholder="Prague")
                    pf_country = gr.Textbox(label="Country", placeholder="Czechia")
                    pf_zip     = gr.Textbox(label="Zip Code", placeholder="110 00")
                pf_street  = gr.Textbox(label="Street Address", placeholder="Main Street 1")
                with gr.Row():
                    pf_linkedin = gr.Textbox(label="LinkedIn URL", placeholder="https://linkedin.com/in/janedoe", scale=3)
                    pf_dob      = gr.Textbox(label="Date of Birth (YYYY-MM-DD)", placeholder="1995-05-05", scale=1)

            # ── Resume ────────────────────────────────────────────────────────
            with gr.Accordion("📄 Resume", open=True):
                pf_resume_path   = gr.Textbox(label="Current Resume File", interactive=False)
                pf_resume_upload = gr.File(
                    label="Upload New Resume PDF",
                    file_types=[".pdf"],
                    file_count="single",
                )
                pf_resume_status = gr.Markdown("")

            # ── Work Experience ───────────────────────────────────────────────
            with gr.Accordion("💼 Work Experience", open=True):
                gr.Markdown("**Position 1 — Current / Most Recent**")
                with gr.Row():
                    pf_we1_company = gr.Textbox(label="Company")
                    pf_we1_title   = gr.Textbox(label="Job Title")
                with gr.Row():
                    pf_we1_start = gr.Textbox(label="Start Date", placeholder="MM/YYYY")
                    pf_we1_end   = gr.Textbox(label="End Date", placeholder="Present")
                pf_we1_desc = gr.Textbox(label="Key Achievements / Description", lines=3)

                gr.Markdown("**Position 2 — Previous**")
                with gr.Row():
                    pf_we2_company = gr.Textbox(label="Company")
                    pf_we2_title   = gr.Textbox(label="Job Title")
                with gr.Row():
                    pf_we2_start = gr.Textbox(label="Start Date", placeholder="MM/YYYY")
                    pf_we2_end   = gr.Textbox(label="End Date", placeholder="MM/YYYY")
                pf_we2_desc = gr.Textbox(label="Key Achievements / Description", lines=3)

            # ── Education ─────────────────────────────────────────────────────
            with gr.Accordion("🎓 Education", open=False):
                with gr.Row():
                    pf_edu_university = gr.Textbox(label="University / School")
                    pf_edu_degree     = gr.Textbox(label="Degree Level", placeholder="Master's Degree")
                with gr.Row():
                    pf_edu_major = gr.Textbox(label="Major / Field of Study")
                    pf_edu_grad  = gr.Textbox(label="Graduation Year", placeholder="2022")
                pf_edu_status = gr.Textbox(label="Status", placeholder="Completed / Graduated")

            # ── Application Preferences ───────────────────────────────────────
            with gr.Accordion("⚙️ Application Preferences", open=False):
                with gr.Row():
                    pf_salary = gr.Textbox(label="Desired Salary", placeholder="5,000 EUR")
                    pf_notice = gr.Textbox(label="Notice Period", placeholder="Immediate / 1 month")

            # ── Outlook OAuth ─────────────────────────────────────────────────
            with gr.Accordion("📧 Connect Outlook for Email Verification", open=False):
                gr.Markdown(
                    "Run the one-time Microsoft sign-in so the agent can read verification codes "
                    "from your inbox. The account is taken from the **Email** field above."
                )
                pf_oauth_btn    = gr.Button("🔗 Connect Outlook Account", variant="primary")
                pf_oauth_status = gr.Markdown("")

            # ── Add new profile ───────────────────────────────────────────────
            with gr.Row():
                new_profile_name_box = gr.Textbox(
                    label="Save as new profile (leave blank to update current)",
                    placeholder="Jane Doe",
                    scale=3,
                )
                add_profile_btn = gr.Button("➕ Save as New Profile", variant="secondary", scale=1)

        # ── Jobs table ────────────────────────────────────────────────────────
        jobs_table = gr.Dataframe(
            value=initial_rows,
            headers=["Title", "Job Date", "Status", "Record ID"],
            datatype=["str", "str", "str", "str"],
            row_count=(max(1, n_jobs), "dynamic"),
            col_count=(4, "fixed"),
            label=f"📋 Unapplied Jobs — {n_jobs} loaded from Airtable",
            interactive=False,
            wrap=True,
        )

        with gr.Row():
            refresh_btn = gr.Button("🔄 Refresh from Airtable", variant="secondary", scale=1)
            start_btn   = gr.Button("▶ Start Batch", variant="primary", scale=2)
            stop_btn    = gr.Button("⏹ Stop", variant="stop", interactive=False, scale=1)

        log_box = gr.Textbox(
            label="📜 Live Log",
            lines=20,
            max_lines=40,
            interactive=False,
            placeholder="Logs will appear here when the batch runs…",
        )

    # ── All form field components in order (must match _profile_to_form / _form_to_profile) ──
    _form_inputs = [
        pf_full_name, pf_email, pf_phone,
        pf_city, pf_country, pf_zip, pf_street,
        pf_linkedin, pf_dob,
        pf_resume_path,
        pf_we1_company, pf_we1_title, pf_we1_start, pf_we1_end, pf_we1_desc,
        pf_we2_company, pf_we2_title, pf_we2_start, pf_we2_end, pf_we2_desc,
        pf_edu_university, pf_edu_degree, pf_edu_major, pf_edu_grad, pf_edu_status,
        pf_salary, pf_notice,
    ]
    # Outputs for form population (all form fields except resume_path which is read-only)
    _form_outputs = [
        pf_full_name, pf_email, pf_phone,
        pf_city, pf_country, pf_zip, pf_street,
        pf_linkedin, pf_dob,
        pf_resume_path,
        pf_we1_company, pf_we1_title, pf_we1_start, pf_we1_end, pf_we1_desc,
        pf_we2_company, pf_we2_title, pf_we2_start, pf_we2_end, pf_we2_desc,
        pf_edu_university, pf_edu_degree, pf_edu_major, pf_edu_grad, pf_edu_status,
        pf_salary, pf_notice,
    ]

    # ── Populate form on startup ──────────────────────────────────────────────
    def _load_active_profile_into_form():
        prof = candidate_manager.get_active_profile()
        return list(_profile_to_form(prof))

    # ── Profile selector change ───────────────────────────────────────────────
    def _on_profile_select(name: str):
        candidate_manager.set_active_profile(name)
        prof = candidate_manager.get_profile_by_name(name)
        return list(_profile_to_form(prof))

    profile_selector.change(
        fn=_on_profile_select,
        inputs=[profile_selector],
        outputs=_form_outputs,
    )

    # ── Resume upload ─────────────────────────────────────────────────────────
    def _on_resume_upload(file_data, profile_name: str):
        if file_data is None:
            return gr.update(), gr.update(value="No file selected.")

        # Gradio 5 returns a tempfile path string or a NamedString/dict
        if isinstance(file_data, dict):
            src_path = file_data.get("path") or file_data.get("name", "")
            filename = file_data.get("orig_name") or Path(src_path).name
        else:
            src_path = str(file_data)
            filename = Path(src_path).name

        RESUMES_DIR.mkdir(parents=True, exist_ok=True)
        dest = RESUMES_DIR / filename
        shutil.copy(src_path, dest)

        # Update the candidate profile with the new path
        profile = candidate_manager.get_profile_by_name(profile_name)
        if "resume" not in profile:
            profile["resume"] = {}
        profile["resume"]["file_path"] = str(dest.resolve())
        profile["resume"]["filename"] = filename
        candidate_manager.save_profile(profile_name, profile)

        return (
            gr.update(value=str(dest.resolve())),
            gr.update(value=f"✅ Resume saved: **{filename}**"),
        )

    pf_resume_upload.change(
        fn=_on_resume_upload,
        inputs=[pf_resume_upload, profile_selector],
        outputs=[pf_resume_path, pf_resume_status],
    )

    # ── Save profile from form ────────────────────────────────────────────────
    def _on_profile_save(
        name, full_name, email, phone, city, country, zip_code, street, linkedin, dob,
        resume_path,
        we1_company, we1_title, we1_start, we1_end, we1_desc,
        we2_company, we2_title, we2_start, we2_end, we2_desc,
        edu_university, edu_degree, edu_major, edu_grad, edu_status,
        salary, notice,
    ):
        existing = candidate_manager.get_profile_by_name(name) or {}
        # Preserve existing resume path if form field is empty
        if not resume_path and "resume" in existing:
            resume_path = existing["resume"].get("file_path", "")

        updated = _form_to_profile(
            existing, full_name, email, phone, city, country, zip_code, street, linkedin, dob,
            we1_company, we1_title, we1_start, we1_end, we1_desc,
            we2_company, we2_title, we2_start, we2_end, we2_desc,
            edu_university, edu_degree, edu_major, edu_grad, edu_status,
            salary, notice,
        )
        candidate_manager.save_profile(name, updated, set_active=True)
        gr.Info(f"Profile '{name}' saved.")
        return gr.update(choices=candidate_manager.get_all_profile_names(), value=name)

    profile_save_btn.click(
        fn=_on_profile_save,
        inputs=[profile_selector] + _form_inputs,
        outputs=[profile_selector],
    )

    # ── Add as new profile ────────────────────────────────────────────────────
    def _on_profile_add(
        new_name,
        full_name, email, phone, city, country, zip_code, street, linkedin, dob,
        resume_path,
        we1_company, we1_title, we1_start, we1_end, we1_desc,
        we2_company, we2_title, we2_start, we2_end, we2_desc,
        edu_university, edu_degree, edu_major, edu_grad, edu_status,
        salary, notice,
    ):
        new_name = (new_name or "").strip() or full_name.strip()
        if not new_name:
            raise gr.Error("Enter a name for the new profile (or fill in Full Name).")
        updated = _form_to_profile(
            {}, full_name, email, phone, city, country, zip_code, street, linkedin, dob,
            we1_company, we1_title, we1_start, we1_end, we1_desc,
            we2_company, we2_title, we2_start, we2_end, we2_desc,
            edu_university, edu_degree, edu_major, edu_grad, edu_status,
            salary, notice,
        )
        if resume_path:
            updated["resume"] = {
                "file_path": resume_path,
                "filename": Path(resume_path).name,
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

    # ── Outlook OAuth button ──────────────────────────────────────────────────
    async def _do_oauth_flow(email_address: str):
        if not email_address or "@" not in email_address:
            yield gr.update(value="❌ Enter a valid email address in the **Email** field first, then save the profile.")
            return

        yield gr.update(value=f"⏳ Starting OAuth for **{email_address}**…")

        try:
            import msal
            from src.utils.email_client import CLIENT_ID, TENANT_ID, SCOPES, get_token_path, _save_cache

            token_path = get_token_path(email_address)
            cache = msal.SerializableTokenCache()
            app = msal.PublicClientApplication(
                CLIENT_ID,
                authority=f"https://login.microsoftonline.com/{TENANT_ID}",
                token_cache=cache,
            )

            flow = app.initiate_device_flow(scopes=SCOPES)
            if "user_code" not in flow:
                yield gr.update(value=f"❌ Could not start device flow: {flow}")
                return

            uri = flow["verification_uri"]
            code = flow["user_code"]
            yield gr.update(
                value=(
                    f"### Action Required\n\n"
                    f"1. Open **[{uri}]({uri})** in your browser\n"
                    f"2. Enter code: **`{code}`**\n"
                    f"3. Sign in as: {email_address}\n\n"
                    f"⏳ Waiting for you to complete sign-in…"
                )
            )

            result = await asyncio.to_thread(app.acquire_token_by_device_flow, flow)

            if "access_token" in result:
                _save_cache(cache, token_path)
                yield gr.update(
                    value=f"✅ **Connected!** Token saved for {email_address}. The agent will now read verification emails automatically."
                )
            else:
                desc = result.get("error_description", str(result))
                yield gr.update(value=f"❌ Authentication failed: {desc}")

        except Exception as exc:
            yield gr.update(value=f"❌ Error during OAuth: {exc}")

    pf_oauth_btn.click(
        fn=_do_oauth_flow,
        inputs=[pf_email],
        outputs=[pf_oauth_status],
    )

    # ── Refresh button ────────────────────────────────────────────────────────
    def _do_refresh():
        try:
            webui_manager.airtable_jobs = airtable_client.get_unapplied_jobs()
            rows = _jobs_to_table(webui_manager.airtable_jobs)
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

    # ── Stop button ───────────────────────────────────────────────────────────
    def _do_stop():
        webui_manager.ja_stop_requested = True
        return gr.update(interactive=False, value="⛔ Stopping…")

    stop_btn.click(fn=_do_stop, inputs=None, outputs=[stop_btn])

    # ── Start batch button ────────────────────────────────────────────────────
    async def _start_wrapper(table_data):
        async for update in _run_batch(
            webui_manager,
            table_data,
            log_box,
            jobs_table,
            start_btn,
            stop_btn,
            refresh_btn,
        ):
            yield update

    start_btn.click(
        fn=_start_wrapper,
        inputs=[jobs_table],
        outputs=[log_box, jobs_table, start_btn, stop_btn, refresh_btn],
    )
