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
import uuid
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


def _get_agent_setting(webui_manager: WebuiManager, key: str, default=None):
    comp = webui_manager.id_to_component.get(f"agent_settings.{key}")
    return default  # We read settings from env defaults; extend if needed


def _get_browser_setting(webui_manager: WebuiManager, key: str, default=None):
    comp = webui_manager.id_to_component.get(f"browser_settings.{key}")
    return default


# ---------------------------------------------------------------------------
# Core batch-run generator
# ---------------------------------------------------------------------------

async def _run_batch(
    webui_manager: WebuiManager,
    table_data: list,
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

    # --- Init LLM (reuse agent_settings values if set, else fall back to env defaults) ---
    llm_provider_name = os.getenv("DEFAULT_LLM", "google")
    try:
        # Try to pick up settings from agent_settings tab if available
        prov_comp = webui_manager.id_to_component.get("agent_settings.llm_provider")
        model_comp = webui_manager.id_to_component.get("agent_settings.llm_model_name")
        # We don't have the component values dict here, so use env defaults
    except Exception:
        pass

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

    # --- Init browser once for the whole batch ---
    browser_path = os.getenv("BROWSER_PATH", None) or None
    use_own_browser = os.getenv("USE_OWN_BROWSER", "false").lower() in ("true", "1", "yes")
    keep_open = os.getenv("KEEP_BROWSER_OPEN", "true").lower() in ("true", "1", "yes")

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

    # --- Build mutable table rows to update live ---
    # table_data from Gradio is a pandas DataFrame — can't use bare `or`, use explicit check
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

        # --- Clean up browser state before starting a new job ---
        # We close and recreate the context rather than calling reset_context().
        # reset_context() closes individual pages while the Playwright CDP
        # connection's background task may still dispatch messages for those
        # pages, producing a KeyError that kills the entire Playwright connection.
        # Closing the whole context and creating a fresh one avoids that race.
        if webui_manager.bu_browser_context is not None:
            try:
                # Access the underlying Playwright context and close it cleanly.
                pw_ctx = getattr(webui_manager.bu_browser_context, "context", None)
                if pw_ctx is not None:
                    await pw_ctx.close()
                else:
                    # Fallback: browser-use BrowserContext may expose close() directly
                    await webui_manager.bu_browser_context.close()
                logger.info("Closed browser context before job '%s'", title)
            except Exception as close_exc:
                logger.warning("Could not close browser context: %s", close_exc)
            finally:
                webui_manager.bu_browser_context = None

        if webui_manager.bu_browser is not None:
            try:
                webui_manager.bu_browser_context = await webui_manager.bu_browser.new_context(
                    config=BrowserContextConfig(window_width=1920, window_height=1080)
                )
                logger.info("Created fresh browser context for job '%s'", title)
            except Exception as ctx_exc:
                logger.error("Failed to create browser context for job '%s': %s", title, ctx_exc)
                rows[idx][2] = "❌ Browser Error"
                log_lines.append(f"   💥 Browser context error: {ctx_exc}")
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
                # Agent failed or ran out of steps without returning final result
                success = False
                error_msg = str(errors[-1])
                log_lines.append(f"   ❌ Error: {error_msg}")
            else:
                # Treat any other non-error completion as success
                success = True
                log_lines.append(f"   ✅ Completed. Result: {final[:120]}")

        except Exception as exc:
            error_msg = str(exc)
            logger.exception("Agent crashed for job %s", title)
            log_lines.append(f"   💥 Exception: {error_msg[:200]}")

        # --- Update Airtable via API (no browser) ---
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

        # Short pause between jobs to avoid rate limiting
        await asyncio.sleep(2)

    log_lines.append("\n🏁 Batch complete.")

    # Reload in-memory list (remove applied ones)
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

        with gr.Accordion("👤 Candidate Profile Configuration", open=False):
            with gr.Row():
                profile_selector = gr.Dropdown(
                    label="Active Candidate Profile",
                    choices=candidate_manager.get_all_profile_names(),
                    value=candidate_manager.get_active_profile_name(),
                    scale=3,
                )
                profile_save_btn = gr.Button("💾 Save Profile Changes", variant="secondary", scale=1)
            profile_json_box = gr.Code(
                label="Profile Configuration (JSON) - Edit CV path, work history, personal details",
                language="json",
                value=json.dumps(candidate_manager.get_active_profile(), indent=2, ensure_ascii=False),
                lines=15,
            )
            with gr.Row():
                new_profile_name_box = gr.Textbox(
                    label="Create New Profile from current JSON",
                    placeholder="Enter new candidate name (e.g. Jane Doe)...",
                    scale=3,
                )
                add_profile_btn = gr.Button("➕ Add as New Profile", variant="primary", scale=1)

        def _on_profile_select(name):
            candidate_manager.set_active_profile(name)
            prof = candidate_manager.get_profile_by_name(name)
            return json.dumps(prof, indent=2, ensure_ascii=False)

        def _on_profile_save(name, raw_json):
            try:
                prof_data = json.loads(raw_json)
                candidate_manager.save_profile(name, prof_data, set_active=True)
                gr.Info(f"Candidate profile '{name}' saved successfully!")
                return gr.update(choices=candidate_manager.get_all_profile_names(), value=name)
            except Exception as e:
                raise gr.Error(f"Invalid JSON format: {e}")

        def _on_profile_add(new_name, raw_json):
            new_name = (new_name or "").strip()
            if not new_name:
                raise gr.Error("Please enter a name for the new profile.")
            try:
                prof_data = json.loads(raw_json)
                if "personal" not in prof_data:
                    prof_data["personal"] = {}
                prof_data["personal"]["full_name"] = new_name
                candidate_manager.save_profile(new_name, prof_data, set_active=True)
                gr.Info(f"New profile '{new_name}' created and set as active!")
                return (
                    gr.update(choices=candidate_manager.get_all_profile_names(), value=new_name),
                    gr.update(value=""),
                    json.dumps(prof_data, indent=2, ensure_ascii=False),
                )
            except Exception as e:
                raise gr.Error(f"Invalid JSON format or save error: {e}")

        profile_selector.change(
            fn=_on_profile_select,
            inputs=[profile_selector],
            outputs=[profile_json_box],
        )
        profile_save_btn.click(
            fn=_on_profile_save,
            inputs=[profile_selector, profile_json_box],
            outputs=[profile_selector],
        )
        add_profile_btn.click(
            fn=_on_profile_add,
            inputs=[new_profile_name_box, profile_json_box],
            outputs=[profile_selector, new_profile_name_box, profile_json_box],
        )

        # Jobs table — pre-populated with the in-memory job list
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
            start_btn = gr.Button("▶ Start Batch", variant="primary", scale=2)
            stop_btn = gr.Button("⏹ Stop", variant="stop", interactive=False, scale=1)

        log_box = gr.Textbox(
            label="📜 Live Log",
            lines=20,
            max_lines=40,
            interactive=False,
            placeholder="Logs will appear here when the batch runs…",
        )

    # --- Refresh button ---
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

    # --- Stop button ---
    def _do_stop():
        webui_manager.ja_stop_requested = True
        return gr.update(interactive=False, value="⛔ Stopping…")

    stop_btn.click(fn=_do_stop, inputs=None, outputs=[stop_btn])

    # --- Start batch button ---
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
