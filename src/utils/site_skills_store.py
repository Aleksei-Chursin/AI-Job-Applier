"""
Persistent store and generator for job application site skill markdown (.md) files.

For each visited job application site or ATS domain, creates and maintains an .md skill file
under `.agents/skills/site_<domain>/SKILL.md` (and `tmp/site_skills/<domain>.md`).
Models and agents use these skills to proceed more efficiently on future job applications.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

SKILLS_ROOT = Path(".agents/skills").resolve()
TMP_SKILLS_DIR = Path("tmp/site_skills").resolve()


def _root_domain(raw: str) -> str:
    """Extract the registrable root domain from a URL or hostname."""
    if raw.startswith("http://") or raw.startswith("https://"):
        host = urlparse(raw).netloc
    else:
        host = raw.strip().lstrip("www.")

    parts = host.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:]).lower()
    return host.lower()


def _host_from(raw: str) -> str:
    """Extract the full hostname from a URL or domain string."""
    if raw.startswith("http://") or raw.startswith("https://"):
        return urlparse(raw).netloc.lower().lstrip("www.")
    return raw.strip().lower().lstrip("www.")


def _sanitize_domain(domain: str) -> str:
    """Convert domain to a clean directory/identifier name (e.g. greenhouse.io -> greenhouse_io)."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", domain.lower()).strip("_")


def save_skill(site_url_or_domain: str, instructions: str, notes: str = "") -> str:
    """
    Create or update an .md skill file for a visited site domain.

    Args:
        site_url_or_domain: URL or domain name (e.g. "https://barclays.wd3.myworkdayjobs.com" or "greenhouse.io")
        instructions: Detailed instructions on efficient form filling, navigation, and gotchas for this site.
        notes: Optional context or notes about the job/application.

    Returns:
        The path to the created skill file.
    """
    host = _host_from(site_url_or_domain)
    root = _root_domain(site_url_or_domain)

    # Prefer root domain for standard ATS platforms unless it's a subdomain tenant that needs special rules
    domain_key = root if len(root.split(".")) >= 2 else host
    clean_name = _sanitize_domain(domain_key)
    skill_dir = SKILLS_ROOT / f"site_{clean_name}"
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"

    TMP_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    tmp_file = TMP_SKILLS_DIR / f"{domain_key}.md"

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    md_content = f"""---
name: site_{clean_name}
description: Job application instructions and efficiency workflow for {domain_key}
---

# Job Application Skill: {domain_key}

## Overview
This skill provides proven navigation instructions, form filling patterns, and efficiency guidelines when applying to jobs on `{domain_key}`.

## Efficient Workflow & Instructions
{instructions.strip()}

## Notes & Context
- **Last Updated**: {now_str}
- **Domain**: `{domain_key}`
"""
    if notes:
        md_content += f"- **Notes**: {notes.strip()}\n"

    skill_file.write_text(md_content, encoding="utf-8")
    tmp_file.write_text(md_content, encoding="utf-8")
    logger.info("Saved site skill for %s to %s", domain_key, skill_file)
    return str(skill_file)


def lookup_skill(site_url_or_domain: str) -> Optional[str]:
    """
    Look up and read the .md skill instructions for a given site URL or domain.
    Checks exact host, suffix match, and root domain.
    """
    host = _host_from(site_url_or_domain)
    root = _root_domain(site_url_or_domain)

    candidates = [host, root]
    parts = host.split(".")
    if len(parts) > 2:
        candidates.append(".".join(parts[-3:]))

    for cand in candidates:
        clean_name = _sanitize_domain(cand)
        skill_file = SKILLS_ROOT / f"site_{clean_name}" / "SKILL.md"
        if skill_file.exists():
            return skill_file.read_text(encoding="utf-8")

        tmp_file = TMP_SKILLS_DIR / f"{cand}.md"
        if tmp_file.exists():
            return tmp_file.read_text(encoding="utf-8")

    return None


def list_all_skills() -> dict[str, str]:
    """Return a mapping of domain name to skill file path for all saved site skills."""
    skills = {}
    if SKILLS_ROOT.exists():
        for d in SKILLS_ROOT.iterdir():
            if d.is_dir() and d.name.startswith("site_"):
                sf = d / "SKILL.md"
                if sf.exists():
                    skills[d.name[5:]] = str(sf)
    return skills
