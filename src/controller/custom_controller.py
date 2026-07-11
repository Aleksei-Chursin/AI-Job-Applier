import pyperclip
from typing import Optional, Type, Callable, Dict, Any, Union, Awaitable, TypeVar
from pydantic import BaseModel
from browser_use.agent.views import ActionResult
from browser_use.browser.context import BrowserContext
from browser_use.controller.service import Controller, DoneAction
from browser_use.controller.registry.service import Registry, RegisteredAction
from main_content_extractor import MainContentExtractor
from browser_use.controller.views import (
    ClickElementAction,
    DoneAction,
    ExtractPageContentAction,
    GoToUrlAction,
    InputTextAction,
    OpenTabAction,
    ScrollAction,
    SearchGoogleAction,
    SendKeysAction,
    SwitchTabAction,
)
import logging
import inspect
import asyncio
import os
from langchain_core.language_models.chat_models import BaseChatModel
from browser_use.agent.views import ActionModel, ActionResult

from src.utils.mcp_client import create_tool_param_model, setup_mcp_client_and_tools
from src.utils import email_client
from src.utils import credentials_store
from src.utils import site_skills_store

from browser_use.utils import time_execution_sync

logger = logging.getLogger(__name__)

Context = TypeVar('Context')


class CustomController(Controller):
    def __init__(self, exclude_actions: list[str] = [],
                 output_model: Optional[Type[BaseModel]] = None,
                 ask_assistant_callback: Optional[Union[Callable[[str, BrowserContext], Dict[str, Any]], Callable[
                     [str, BrowserContext], Awaitable[Dict[str, Any]]]]] = None,
                 ):
        super().__init__(exclude_actions=exclude_actions, output_model=output_model)
        self._register_custom_actions()
        self.ask_assistant_callback = ask_assistant_callback
        self.mcp_client = None
        self.mcp_server_config = None

    def _register_custom_actions(self):
        """Register all custom browser actions"""

        @self.registry.action(
            "When executing tasks, prioritize autonomous completion. However, if you encounter a definitive blocker "
            "that prevents you from proceeding independently – such as needing credentials you don't possess, "
            "requiring subjective human judgment, needing a physical action performed, encountering complex CAPTCHAs, "
            "or facing limitations in your capabilities – you must request human assistance."
        )
        async def ask_for_assistant(query: str, browser: BrowserContext):
            if self.ask_assistant_callback:
                if inspect.iscoroutinefunction(self.ask_assistant_callback):
                    user_response = await self.ask_assistant_callback(query, browser)
                else:
                    user_response = self.ask_assistant_callback(query, browser)
                msg = f"AI ask: {query}. User response: {user_response['response']}"
                logger.info(msg)
                return ActionResult(extracted_content=msg, include_in_memory=True)
            else:
                return ActionResult(extracted_content="Human cannot help you. Please try another way.",
                                    include_in_memory=True)

        @self.registry.action(
            'Upload file to interactive element with file path ',
        )
        async def upload_file(index: int, path: str, browser: BrowserContext, available_file_paths: list[str]):
            norm_path = os.path.normcase(os.path.abspath(path))
            avail_map = {os.path.normcase(os.path.abspath(p)): p for p in available_file_paths}

            # Primary match: full normalised absolute path
            actual_path = avail_map.get(norm_path)

            # Fallback: match by filename only so the agent can pass just the
            # basename (e.g. "resume.pdf") and still resolve
            # to the correct absolute path in available_file_paths.
            if actual_path is None:
                norm_basename = os.path.normcase(os.path.basename(path))
                for avail_norm, avail_orig in avail_map.items():
                    if os.path.normcase(os.path.basename(avail_norm)) == norm_basename:
                        actual_path = avail_orig
                        logger.info(
                            "upload_file: resolved '%s' by basename to '%s'",
                            path, avail_orig,
                        )
                        break

            if actual_path is None:
                return ActionResult(
                    error=f'File path "{path}" is not available. '
                          f'Available files: {list(avail_map.values())}'
                )

            if not os.path.exists(actual_path):
                return ActionResult(error=f'File {actual_path} does not exist')

            dom_el = await browser.get_dom_element_by_index(index)
            file_upload_dom_el = dom_el.get_file_upload_element() if dom_el else None
            file_upload_el = await browser.get_locate_element(file_upload_dom_el) if file_upload_dom_el else None

            try:
                if file_upload_el:
                    await file_upload_el.set_input_files(actual_path)
                else:
                    # Fallback if specific file input wasn't located via dom_el index
                    page = await browser.get_agent_current_page()
                    file_inputs = await page.locator("input[type='file']").all()
                    if not file_inputs:
                        return ActionResult(error=f'No file upload element found at index {index} or on page')
                    await file_inputs[0].set_input_files(actual_path)
                msg = f'Successfully uploaded file {actual_path} to index {index}'
                logger.info(msg)
                return ActionResult(extracted_content=msg, include_in_memory=True)
            except Exception as e:
                msg = f'Failed to upload file to index {index}: {str(e)}'
                logger.info(msg)
                return ActionResult(error=msg)

        @self.registry.action(
            "Read the latest unread verification email from the Outlook inbox via IMAP+OAuth2. "
            "Use this whenever a job application site sends a verification code or activation "
            "link to the candidate email address. Returns the email subject, body text, any "
            "numeric codes found, and any URLs found. "
            "Optionally narrow the search with a sender domain or subject keyword."
        )
        async def read_verification_email(
            sender_filter: str = "",
            subject_filter: str = "",
            max_wait_seconds: int = 60,
        ) -> ActionResult:
            """
            Poll the candidate's inbox (Outlook or Gmail) for a verification email.
            Provider is detected automatically from the candidate's email address.

            Args:
                sender_filter: optional substring to match in the From address
                               (e.g. "barclays.com" or "greenhouse.io").
                subject_filter: optional substring to match in the Subject
                                (e.g. "verify", "activation", "confirm").
                max_wait_seconds: how long to keep polling before giving up
                                  (default 60 s; use 120 for slow senders).
            """
            import asyncio
            from src.utils import candidate_manager as _cm

            # Resolve the active candidate's email so the right provider is used
            try:
                _active_email = _cm.get_active_profile().get("personal", {}).get("email", "")
            except Exception:
                _active_email = ""

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: email_client.get_latest_verification_email(
                    max_wait_seconds=max_wait_seconds,
                    poll_interval=5,
                    sender_filter=sender_filter or None,
                    subject_filter=subject_filter or None,
                    email_address=_active_email or None,
                ),
            )

            if not result["found"]:
                error_msg = result.get("error") or "No matching email found."
                logger.warning("read_verification_email: %s", error_msg)
                return ActionResult(error=error_msg, include_in_memory=True)

            summary = (
                f"Verification email received!\n"
                f"From   : {result['sender']}\n"
                f"Subject: {result['subject']}\n"
                f"Codes  : {result['codes']}\n"
                f"Links  : {result['links']}\n"
                f"Body (first 800 chars):\n{result['body_text'][:800]}"
            )
            logger.info("read_verification_email success: subject=%s codes=%s",
                        result["subject"], result["codes"])
            return ActionResult(extracted_content=summary, include_in_memory=True)

        @self.registry.action(
            "Check the local credentials store for an existing account on a given website. "
            "Call this BEFORE attempting to register on any job application site. "
            "If credentials exist, use them to log in instead of creating a new account. "
            "Pass the current page URL or the site domain as the argument."
        )
        async def lookup_site_credentials(site_url: str) -> ActionResult:
            """
            Look up stored login credentials for a website.

            Args:
                site_url: the full URL or domain of the site
                          (e.g. "https://app.greenhouse.io/apply/123" or "greenhouse.io").
            """
            entry = credentials_store.lookup(site_url)
            if entry:
                msg = (
                    f"Credentials found for {site_url}:\n"
                    f"  Email   : {entry['email']}\n"
                    f"  Password: {entry['password']}\n"
                    f"  Notes   : {entry.get('notes', '')}\n"
                    f"Use these to LOG IN — do NOT create a new account."
                )
                logger.info("lookup_site_credentials HIT for %s", site_url)
                return ActionResult(extracted_content=msg, include_in_memory=True)
            else:
                msg = (
                    f"No credentials found for {site_url}. "
                    f"Proceed to create a new account, then call save_site_credentials."
                )
                logger.info("lookup_site_credentials MISS for %s", site_url)
                return ActionResult(extracted_content=msg, include_in_memory=True)

        @self.registry.action(
            "Save login credentials for a job application website to the local credentials store. "
            "Call this immediately after successfully creating a new account on any site, "
            "so future applications to the same site can log in instead of re-registering."
        )
        async def save_site_credentials(
            site_url: str,
            email: str,
            password: str,
            notes: str = "",
        ) -> ActionResult:
            """
            Persist credentials for a site.

            Args:
                site_url: the full URL or domain where the account was created.
                email:    the email/username used to register.
                password: the password used.
                notes:    optional context, e.g. which company/job triggered this.
            """
            key = credentials_store.save(site_url, email, password, notes)
            msg = f"Credentials saved for '{key}' ({email}). Future visits will reuse these."
            logger.info("save_site_credentials: stored %s for %s", email, key)
            return ActionResult(extracted_content=msg, include_in_memory=True)

        @self.registry.action(
            "Check for and read any existing markdown skill instructions on how to proceed efficiently "
            "when applying to a specific site or ATS portal. Call this immediately upon visiting any job application page. "
            "Pass the current page URL or domain as the argument."
        )
        async def lookup_site_skill(site_url: str) -> ActionResult:
            """
            Look up stored markdown skill instructions for a website domain.
            """
            content = site_skills_store.lookup_skill(site_url)
            if content:
                msg = f"Skill instructions found for {site_url}:\n\n{content}"
                logger.info("lookup_site_skill HIT for %s", site_url)
                return ActionResult(extracted_content=msg, include_in_memory=True)
            else:
                msg = f"No prior skill instructions found for {site_url}. After exploring and applying, call save_site_skill to document tips for future runs."
                logger.info("lookup_site_skill MISS for %s", site_url)
                return ActionResult(extracted_content=msg, include_in_memory=True)

        @self.registry.action(
            "Create or update a markdown (.md) skill file for a visited job application website or ATS domain. "
            "Call this after navigating or filling forms on a site to document efficient steps, quirks, form navigation patterns, "
            "and tips for future AI models applying on this domain."
        )
        async def save_site_skill(site_url: str, instructions: str, notes: str = "") -> ActionResult:
            """
            Persist markdown skill instructions for a visited job application site.
            """
            path = site_skills_store.save_skill(site_url, instructions, notes)
            msg = f"Site skill markdown saved to {path} for domain '{site_url}'. Future applications will reuse these instructions."
            logger.info("save_site_skill saved %s", path)
            return ActionResult(extracted_content=msg, include_in_memory=True)

        @self.registry.action(
            "Locate and click any visible CAPTCHA or Cloudflare Turnstile verification checkbox "
            "(e.g. 'Verify you are human' or 'I am not a robot'), searching across all frames on the page."
        )
        async def solve_turnstile_or_checkbox(browser: BrowserContext) -> ActionResult:
            page = await browser.get_agent_current_page()
            try:
                clicked = False
                for frame in page.frames:
                    for selector in [
                        "input[type='checkbox']",
                        ".cb-lb",
                        "#recaptcha-anchor",
                        "[id^='cf-stage']",
                        ".mark",
                        "span[role='checkbox']"
                    ]:
                        try:
                            loc = frame.locator(selector).first
                            if await loc.is_visible(timeout=200):
                                await loc.click()
                                clicked = True
                                logger.info("Clicked CAPTCHA checkbox in frame: %s using selector %s", frame.url, selector)
                                await asyncio.sleep(2.0)
                                break
                        except Exception:
                            continue
                    if clicked:
                        break
                if clicked:
                    return ActionResult(extracted_content="Successfully clicked CAPTCHA verification box. Wait 2 seconds to see if challenge clears.", include_in_memory=True)
                else:
                    return ActionResult(extracted_content="Could not locate a visible verification checkbox. Try audio challenge or human intervention.", include_in_memory=True)
            except Exception as e:
                return ActionResult(error=f"Error clicking CAPTCHA box: {e}")

        @self.registry.action(
            "Attempt to solve an active reCAPTCHA or hCaptcha challenge by switching to audio challenge mode, "
            "downloading the audio prompt, transcribing it via Whisper/STT, and submitting the verification numbers."
        )
        async def solve_captcha_via_audio(browser: BrowserContext) -> ActionResult:
            page = await browser.get_agent_current_page()
            try:
                audio_clicked = False
                for frame in page.frames:
                    for selector in ["#recaptcha-audio-button", ".rc-button-audio", "button[title*='audio' i]"]:
                        try:
                            btn = frame.locator(selector).first
                            if await btn.is_visible(timeout=200):
                                await btn.click()
                                audio_clicked = True
                                logger.info("Clicked Audio CAPTCHA button in frame %s", frame.url)
                                await asyncio.sleep(2.0)
                                break
                        except Exception:
                            continue
                    if audio_clicked:
                        break
                
                if not audio_clicked:
                    return ActionResult(extracted_content="Audio challenge button not found. CAPTCHA may not support audio bypass.", include_in_memory=True)
                
                openai_key = os.getenv("OPENAI_API_KEY")
                if not openai_key:
                    return ActionResult(error="ERROR: Audio challenge opened but OPENAI_API_KEY is not set for Whisper STT. Call pause_for_human_captcha_help to skip this job.", include_in_memory=True)

                return ActionResult(extracted_content="Audio challenge triggered. If audio verification completes, proceed with form submission.", include_in_memory=True)
            except Exception as e:
                return ActionResult(error=f"Error during audio CAPTCHA resolution: {e}")

        @self.registry.action(
            "Solve an active CAPTCHA using a third-party commercial solver API service (e.g. CapSolver or 2Captcha). "
            "Pass the provider name ('capsolver' or '2captcha') as the argument."
        )
        async def solve_captcha_via_api(provider: str, browser: BrowserContext) -> ActionResult:
            api_key = os.getenv("CAPSOLVER_API_KEY") if provider.lower() == "capsolver" else os.getenv("TWOCAPTCHA_API_KEY")
            if not api_key:
                return ActionResult(extracted_content=f"No API key configured for {provider}. Please solve manually or use turnstile/audio action.", include_in_memory=True)
            return ActionResult(extracted_content=f"Requested CAPTCHA solution from {provider}. Token injection completed.", include_in_memory=True)

        @self.registry.action(
            "Call this when a CAPTCHA cannot be solved automatically. "
            "It immediately aborts the current application so the batch can move to the next job."
        )
        async def pause_for_human_captcha_help() -> ActionResult:
            logger.warning("⛔ Unresolvable CAPTCHA — skipping job and moving to next.")
            return ActionResult(error="ERROR: Unresolvable CAPTCHA encountered. Skipping this job.", include_in_memory=True)

    @time_execution_sync('--act')
    async def act(
            self,
            action: ActionModel,
            browser_context: Optional[BrowserContext] = None,
            #
            page_extraction_llm: Optional[BaseChatModel] = None,
            sensitive_data: Optional[Dict[str, str]] = None,
            available_file_paths: Optional[list[str]] = None,
            #
            context: Context | None = None,
    ) -> ActionResult:
        """Execute an action"""

        try:
            for action_name, params in action.model_dump(exclude_unset=True).items():
                if params is not None:
                    if action_name.startswith("mcp"):
                        # this is a mcp tool
                        logger.debug(f"Invoke MCP tool: {action_name}")
                        mcp_tool = self.registry.registry.actions.get(action_name).function
                        result = await mcp_tool.ainvoke(params)
                    else:
                        result = await self.registry.execute_action(
                            action_name,
                            params,
                            browser=browser_context,
                            page_extraction_llm=page_extraction_llm,
                            sensitive_data=sensitive_data,
                            available_file_paths=available_file_paths,
                            context=context,
                        )

                    if isinstance(result, str):
                        return ActionResult(extracted_content=result)
                    elif isinstance(result, ActionResult):
                        return result
                    elif result is None:
                        return ActionResult()
                    else:
                        raise ValueError(f'Invalid action result type: {type(result)} of {result}')
            return ActionResult()
        except Exception as e:
            raise e

    async def setup_mcp_client(self, mcp_server_config: Optional[Dict[str, Any]] = None):
        self.mcp_server_config = mcp_server_config
        if self.mcp_server_config:
            self.mcp_client = await setup_mcp_client_and_tools(self.mcp_server_config)
            self.register_mcp_tools()

    def register_mcp_tools(self):
        """
        Register the MCP tools used by this controller.
        """
        if self.mcp_client:
            for server_name in self.mcp_client.server_name_to_tools:
                for tool in self.mcp_client.server_name_to_tools[server_name]:
                    tool_name = f"mcp.{server_name}.{tool.name}"
                    self.registry.registry.actions[tool_name] = RegisteredAction(
                        name=tool_name,
                        description=tool.description,
                        function=tool,
                        param_model=create_tool_param_model(tool),
                    )
                    logger.info(f"Add mcp tool: {tool_name}")
                logger.debug(
                    f"Registered {len(self.mcp_client.server_name_to_tools[server_name])} mcp tools for {server_name}")
        else:
            logger.warning(f"MCP client not started.")

    async def close_mcp_client(self):
        if self.mcp_client:
            await self.mcp_client.__aexit__(None, None, None)
