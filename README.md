# AI Job Applier

**Automated job applications on company career pages — with Airtable, email verification, and multi-candidate support.**

> A fork of [browser-use/web-ui](https://github.com/browser-use/web-ui) extended for end-to-end job application automation.

---

## What It Does

Most AI job-application tools work on LinkedIn Easy Apply. This tool targets the applications that actually matter — on company career pages directly: **Greenhouse, Lever, Workday**, and custom ATS portals.

For each job in your Airtable queue, the agent:

1. **Searches Google** for the company's official careers page (ignores LinkedIn links)
2. **Fills the application form** using your candidate profile — name, email, phone, work history, education, resume upload
3. **Handles email verification** automatically — reads the OTP from your Outlook or Gmail inbox and enters it without any input from you
4. **Logs in automatically** on repeat visits — site credentials are saved locally per candidate
5. **Updates Airtable** via REST API when done — `State` flips from `new` → `applied` or `error`

The batch runs unattended. You check Airtable when it's done.

---

## Architecture

```
┌─────────────────┐
│   Airtable      │  State = "new"
│   Job Table     │────────────────────┐
└─────────────────┘                    │
                                       ▼
                            ┌─────────────────────┐
                            │   Job Applicator    │  picks next job
                            │   (Gradio UI)       │
                            └──────────┬──────────┘
                                       │
                                       ▼
                            ┌─────────────────────┐
                            │  Google Search      │  finds official
                            │  (skips LinkedIn)   │  careers page
                            └──────────┬──────────┘
                                       │
                                       ▼
                            ┌─────────────────────┐
                            │  AI Browser Agent   │
                            │  · fills form       │
                            │  · uploads resume   │
                            │  · auto-login       │
                            └──────────┬──────────┘
                                       │
                          ┌────────────▼────────────┐
                          │  Email Verification     │
                          │  Outlook or Gmail IMAP  │
                          │  reads OTP automatically│
                          └────────────┬────────────┘
                                       │
                            ┌──────────▼──────────┐
                            │  Airtable REST API  │
                            │  State → applied    │
                            │  or error + reason  │
                            └─────────────────────┘
```

---

## Quick Start

### Prerequisites
- Python 3.11+
- Git
- Google Chrome or Edge

### 1. Clone and install

**Mac / Linux:**
```bash
git clone https://github.com/YOUR_REPO.git job-applier
cd job-applier
./setup.sh
```

**Windows (Command Prompt):**
```batch
git clone https://github.com/YOUR_REPO.git job-applier
cd job-applier
setup.bat
```

The setup script handles everything: creates a virtual environment, installs packages, and installs Chromium.

### 2. Start the app

```bash
python start.py
```

Open **http://127.0.0.1:7788** in your browser.

### 3. Configure API keys

Go to the **Setup tab**. Fill in:
- **Google Gemini API key** — free at [aistudio.google.com](https://aistudio.google.com)
- **Airtable API key + Base ID** — from [airtable.com/create/tokens](https://airtable.com/create/tokens)
- **Email address** (Outlook or Gmail) — for reading verification codes

### 4. Connect your inbox

In the Setup tab → Email & Inbox Connection:
- **Outlook/Hotmail/Live** — click "Connect Outlook Account", sign in via the device-code flow
- **Gmail** — create an App Password at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords), enable IMAP in Gmail settings, paste the 16-character code

### 5. Add your candidate profile

Go to **Job Applicator → Candidate Profile**:
- Upload your resume PDF — click "Parse & Autofill from Resume" to auto-populate all fields with AI
- Review and edit: name, email, phone, address, work experience, education, visa status, desired salary
- Click **Save Profile**

### 6. Run your first batch

1. Ensure your Airtable job table has rows with `State = new`
2. Click **Refresh from Airtable**
3. Click **Start Batch** — walk away

---

## Choosing an AI Model

This tool uses [Browser Use](https://github.com/browser-use/browser-use) under the hood. The model you choose has a significant impact on success rate.

### BU Bench V1 — Success Rate

Browser Use publishes an official benchmark ([BU Bench](https://github.com/browser-use/browser-use)) measuring model performance on real browser automation tasks:

| Model | Success Rate | Notes |
|---|---|---|
| claude-opus-4-6 | **62%** | Best in class (paid) |
| gemini-3-1-pro | **59%** | Best value |
| claude-sonnet-4-6 | **59%** | Good balance |
| gpt-5 | **52%** | Solid performer |
| gpt-5-mini | 37% | Limited |
| gemini-2.5-flash | **35%** | Free tier default |

> Source: [BU Bench V1](https://github.com/browser-use/browser-use) — measured on standardized browser tasks

### BrowserCode Best Models

A separate benchmark ranks models across score, speed, and cost:

| Model | Score | Best for |
|---|---|---|
| Claude Opus 4.7 | **89.5%** | Best overall score |
| GLM 5.2 | **84%** | Best open-weight |
| Gemini 3.1 Pro | **82.6%** | Best value |
| GPT-5.5 | **80%** | Best speed |
| Minimax M3 | **78%** | Lowest cost |

> Source: BrowserCode benchmark — measured on BU Bench

### Recommendation

| Budget | Model | How to set |
|---|---|---|
| Free | gemini-2.5-flash (default) | `DEFAULT_LLM=google` |
| Value upgrade | Gemini 3.1 Pro or Claude Sonnet 4.6 | `DEFAULT_LLM=google` or `DEFAULT_LLM=anthropic` |
| Best results | Claude Opus 4.7 | `DEFAULT_LLM=anthropic` |

To switch, edit `.env`:

```env
DEFAULT_LLM=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

Supported providers: `google`, `openai`, `anthropic`, `deepseek`, `mistral`, `ollama` (local), and more — see `.env.example`.

---

## Features

### Core
- **Gradio web UI** with dark Legion theme
- **Airtable job queue** — reads `State = new`, writes `applied` or `error`
- **Multi-candidate profiles** — switch between candidates in the UI; each has their own resume, email, credentials
- **PDF resume autofill** — upload a PDF, AI extracts and populates all form fields automatically
- **Dynamic work experience** — up to 4 positions with Add Position button

### Email Verification
- **Outlook OAuth2** — device-code sign-in, token auto-refreshes
- **Gmail App Password** — standard IMAP, no OAuth setup needed
- **Auto-detection** — uses the right provider based on the candidate's email domain
- **End-to-end test** — connection test reads your latest inbox subject as proof it works

### Automation Intelligence
- **Site credential memory** — logs in automatically on repeat ATS visits, no re-registration
- **Pre-built site skill files** — Greenhouse, Lever, Workday, BairesDev, HackerX, Natek, Xitee
- **Custom agent actions** — file upload via Playwright (no OS dialog), CAPTCHA solving, email reading
- **CAPTCHA handling** — Turnstile/checkbox auto-solve; audio challenge via Whisper; unresolvable CAPTCHAs skip to next job immediately
- **Resume path fallback** — resolves PDF path across machines and environments

### UI
- **Reset Errors button** — resets all `error` rows back to `new` in one click
- **Live batch log** — streaming status per job
- **Stop button** — cancels the running batch immediately (not after current job)
- **Connection status on startup** — shows whether Outlook/Gmail is still connected without re-testing

---

## Configuration

All settings live in `.env`. Key variables:

```env
# AI Model
DEFAULT_LLM=google
GOOGLE_API_KEY=

# Airtable
AIRTABLE_API_KEY=
AIRTABLE_BASE_ID=
AIRTABLE_TABLE_NAME=Job Table

# Email (Outlook or Gmail)
EMAIL_ADDRESS=

# Optional: CAPTCHA solving
CAPSOLVER_API_KEY=
TWOCAPTCHA_API_KEY=
OPENAI_API_KEY=   # for Whisper audio CAPTCHA solving

# Optional: observability
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
```

See `.env.example` for the full list.

---

## Airtable Schema

Your Airtable base needs a table (default name: `Job Table`) with these columns:

| Column | Type | Description |
|---|---|---|
| `Title` | Text | Job title |
| `Job Description` | Long text | Job description (optional) |
| `Job Link` | URL | LinkedIn/job board link (agent ignores this, searches Google instead) |
| `Job Date` | Date | When the job was found |
| `State` | Single select | `new` → `applied` or `error` |
| `Error Message` | Long text | Error reason when State = error |

---

## Candidate Profile Structure

Profiles are stored in `tmp/candidates.json`. Each profile includes:

- **Personal** — name, email, phone, address, LinkedIn, date of birth, visa/work authorization, years of experience
- **Resume** — PDF file path (stored in `tmp/resumes/` when uploaded via UI)
- **Work Experience** — up to 4 positions with company, title, dates, description
- **Education** — university, degree, major, graduation year
- **Preferences** — desired salary, notice period
- **Credentials** — passwords for site registrations

---

## Utility Scripts

```bash
# Reset all 'error' jobs back to 'new' (also available as button in UI)
python reset_airtable_errors.py

# Set up Outlook OAuth for a specific email (also available in Setup tab)
python src/utils/email_auth.py you@outlook.com
```

---

## How It Works (Technical)

This project is a fork of [browser-use/web-ui](https://github.com/browser-use/web-ui). [Browser Use](https://github.com/browser-use/browser-use) is an open-source library that gives an AI model control over a real browser — it takes screenshots, sends them to the LLM, and executes actions (click, type, scroll, upload).

**What was added on top:**

1. **Job Applicator tab** — batch processing of Airtable jobs with sequential agent runs
2. **Custom prompt** (`_build_task_prompt`) — detailed instructions for job application behavior, credential management, email verification, resume upload
3. **Custom controller actions** — `read_verification_email`, `lookup_site_credentials`, `save_site_credentials`, `upload_file`, `lookup_site_skill`, `save_site_skill`, `solve_turnstile_or_checkbox`, `solve_captcha_via_audio`, `pause_for_human_captcha_help`
4. **Site skill files** (`.agents/skills/`) — markdown cheat sheets for specific ATS platforms
5. **Candidate manager** — multi-profile JSON store with UI
6. **Email client** — Outlook (OAuth2/XOAUTH2) and Gmail (App Password) IMAP
7. **Airtable client** — REST API for job queue management

The prompt, skill files, and controller actions are the three places where most improvements can be made. They're all readable plain text or Python.

---

## Contributing

This tool is still early and has known failure modes:

- Complex multi-step forms on unusual ATS platforms
- JavaScript-heavy pages that load content dynamically
- Sites with sophisticated CAPTCHA that defeats audio solving
- Form validation errors the agent misreads on retry

If you hit a site that consistently fails, please open a GitHub issue with the site name and the error message from Airtable. Pull requests for new site skill files or improved controller actions are very welcome.

---

## Docker

```bash
cp .env.example .env
docker compose up --build
```

- Web UI: `http://localhost:7788`
- VNC (watch the browser): `http://localhost:6080/vnc.html` (password: `youvncpassword`)
