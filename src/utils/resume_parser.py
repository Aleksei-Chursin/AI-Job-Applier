"""
Resume PDF parser — extracts text and uses the configured LLM to autofill
candidate profile fields from an uploaded resume.

Extraction strategy (tried in order):
  1. pypdf  — fast, pure-Python, works on most modern PDFs
  2. pdfminer.six — more robust encoding handling, good fallback
  3. Raises PdfExtractionError with a clear install message if neither is available

Usage:
    from src.utils.resume_parser import extract_text_from_pdf, parse_resume_with_llm

    text = extract_text_from_pdf("/path/to/resume.pdf")
    data = parse_resume_with_llm(text)  # returns dict matching profile schema
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


class PdfExtractionError(RuntimeError):
    """Raised when no PDF extraction library is available or the file is unreadable."""


_PARSE_PROMPT = """You are a resume parser. Extract structured information from the resume below.

Return ONLY a valid JSON object with these exact keys. Use empty string "" for any field not found.
For lists (work_experience, education) return only entries that actually appear in the resume.

{
  "full_name": "",
  "email": "",
  "phone": "",
  "city": "",
  "country": "",
  "zip_code": "",
  "street_address": "",
  "linkedin_url": "",
  "date_of_birth": "",
  "work_experience": [
    {
      "company": "",
      "title": "",
      "start_date": "",
      "end_date": "",
      "description": ""
    }
  ],
  "education": [
    {
      "university": "",
      "degree_level": "",
      "major": "",
      "graduation_date": "",
      "status": ""
    }
  ],
  "desired_salary": "",
  "notice_period": ""
}

RESUME:
"""


def extract_text_from_pdf(file_path: str) -> str:
    """Extract plain text from a PDF file.

    Tries pypdf first, then pdfminer.six.
    Raises PdfExtractionError with installation instructions if neither is installed.
    Returns an empty string (without raising) if the file contains no extractable text
    (e.g. scanned image PDF).
    """
    path = Path(file_path)
    if not path.exists():
        raise PdfExtractionError(f"File not found: {file_path}")

    pypdf_available = False
    pdfminer_available = False

    # ── Strategy 1: pypdf ─────────────────────────────────────────────────────
    try:
        import pypdf  # noqa: F401
        pypdf_available = True
    except ImportError:
        pass

    if pypdf_available:
        try:
            import pypdf
            reader = pypdf.PdfReader(str(path))
            pages = [page.extract_text() or "" for page in reader.pages]
            text = "\n\n".join(p.strip() for p in pages if p.strip())
            if text:
                return text
            # Fall through to pdfminer for a second attempt before giving up
        except Exception as exc:
            logger.warning("pypdf extraction failed for %s: %s — trying pdfminer", file_path, exc)

    # ── Strategy 2: pdfminer.six ──────────────────────────────────────────────
    try:
        from pdfminer.high_level import extract_text as pdfminer_extract  # noqa: F401
        pdfminer_available = True
    except ImportError:
        pass

    if pdfminer_available:
        try:
            from pdfminer.high_level import extract_text as pdfminer_extract
            text = pdfminer_extract(str(path)) or ""
            return text.strip()
        except Exception as exc:
            logger.warning("pdfminer extraction failed for %s: %s", file_path, exc)

    # ── Neither library available — auto-install and retry ────────────────────
    if not pypdf_available and not pdfminer_available:
        logger.info("PDF libraries not found — installing pypdf and pdfminer.six automatically…")
        try:
            import subprocess

            # Ensure pip is available (venv may have been created without it)
            pip_check = subprocess.run(
                [sys.executable, "-m", "pip", "--version"],
                capture_output=True, text=True,
            )
            if pip_check.returncode != 0:
                logger.info("pip not found — bootstrapping via ensurepip…")
                subprocess.run(
                    [sys.executable, "-m", "ensurepip", "--upgrade"],
                    capture_output=True, timeout=60,
                )

            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "pypdf", "pdfminer.six", "--quiet"],
                timeout=120,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise PdfExtractionError(
                    f"pip install failed (exit {result.returncode}):\n{result.stderr.strip()[:400]}\n\n"
                    "Run manually in your terminal:\n"
                    "  .venv\\Scripts\\python.exe -m ensurepip --upgrade\n"
                    "  .venv\\Scripts\\pip install pypdf pdfminer.six"
                )
            logger.info("PDF libraries installed successfully. Retrying extraction…")
        except PdfExtractionError:
            raise
        except Exception as install_exc:
            raise PdfExtractionError(
                f"Could not run pip install: {install_exc}\n"
                "Run manually:\n"
                "  .venv\\Scripts\\python.exe -m ensurepip --upgrade\n"
                "  .venv\\Scripts\\pip install pypdf pdfminer.six"
            )

        # Retry after install
        try:
            import pypdf
            reader = pypdf.PdfReader(str(path))
            pages = [page.extract_text() or "" for page in reader.pages]
            text = "\n\n".join(p.strip() for p in pages if p.strip())
            if text:
                return text
        except Exception:
            pass

        try:
            from pdfminer.high_level import extract_text as _pdfminer_extract
            text = _pdfminer_extract(str(path)) or ""
            return text.strip()
        except Exception as exc:
            raise PdfExtractionError(f"Extraction failed after install: {exc}")

    # Both libraries tried but returned no text
    return ""


def parse_resume_with_llm(text: str) -> Dict[str, Any]:
    """Send extracted resume text to Gemini and return structured profile fields.

    Returns an empty dict if the API key is missing, the text is empty,
    or the LLM response cannot be parsed as JSON.
    """
    if not text.strip():
        return {}

    try:
        from src.utils import llm_provider as _lp
        from src.utils.config import model_names as _model_names
        from langchain_core.messages import HumanMessage

        provider   = os.getenv("DEFAULT_LLM", "google")
        models     = _model_names.get(provider, [])
        model_name = models[0] if models else "gemini-2.5-flash"

        api_key = os.getenv(
            {"google": "GOOGLE_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
             "openai": "OPENAI_API_KEY", "deepseek": "DEEPSEEK_API_KEY"}.get(provider, "GOOGLE_API_KEY"),
            ""
        )
        if not api_key and provider != "ollama":
            logger.warning("API key not set for provider '%s' — cannot autofill from resume", provider)
            return {}

        llm = _lp.get_llm_model(
            provider=provider,
            model_name=model_name,
            temperature=0,
            base_url=None,
            api_key=api_key or None,
        )

        response = llm.invoke([HumanMessage(content=_PARSE_PROMPT + text[:6000])])
        raw = response.content.strip()

        # Strip markdown code fences if present
        if "```" in raw:
            parts = raw.split("```")
            raw = parts[1]
            if raw.startswith("json"):
                raw = raw[4:]

        return json.loads(raw.strip())

    except json.JSONDecodeError as exc:
        logger.warning("Could not parse LLM resume response as JSON: %s", exc)
        return {}
    except Exception as exc:
        logger.warning("Resume LLM parsing failed: %s", exc)
        return {}
