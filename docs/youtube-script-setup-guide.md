# YouTube Video Script: AI Job Applier — Full Setup Guide

**Title:** "I Built an AI That Applies to Jobs For Me — Full Setup Guide (Airtable + Email Verification + Multiple Resumes)"  
**Target length:** ~18–20 minutes  
**Audience:** Developers and tech-savvy job seekers comfortable with a terminal

---

## Proposed Simplifications (Implement Before Filming)

The following friction points should be resolved before recording so the video demonstrates the smoothest possible experience.

### 1. Single setup script

Replace 4–5 manual terminal commands with one script:

**`setup.sh` (Mac / Linux):**
```bash
#!/bin/bash
set -e
pip install uv --quiet
uv venv --python 3.11
source .venv/bin/activate
uv pip install -r requirements.txt
playwright install chromium --with-deps
cp -n .env.example .env 2>/dev/null || true
echo ""
echo "✅ Setup complete. Open .env and fill in your API keys, then run: python webui.py"
```

**`setup.bat` (Windows):**
```batch
@echo off
pip install uv --quiet
uv venv --python 3.11
call .venv\Scripts\activate
uv pip install -r requirements.txt
playwright install chromium --with-deps
if not exist .env copy .env.example .env
echo.
echo Setup complete. Open .env and fill in your API keys, then run: python webui.py
```

### 2. Resume upload via the UI

Currently users must manually copy PDF files into the project root at exact hardcoded filenames. A Gradio `gr.File` uploader in the Candidates tab should copy the uploaded file into `tmp/resumes/` and auto-update the profile's `file_path`. This removes the single most confusing step for non-technical users.

### 3. Outlook OAuth as a UI button

`python src/utils/email_auth.py` is a CLI step invisible to users working only in the Gradio UI. A "Connect Outlook Account" button in the Candidates tab should trigger the device-code OAuth flow, display the URL and code inside the UI, and save the token automatically once approved. The logic already exists in `email_auth.py` — it only needs a Gradio wrapper.

### 4. Candidate editor as a structured form

The current UI renders a raw JSON textarea for candidate profiles. A simple form (Name, Email, Phone, LinkedIn URL, Target Role, Resume upload) backed by the same JSON store makes multi-candidate setup approachable without touching JSON.

### 5. First-run setup tab

A "Setup" tab with labelled text inputs for the four mandatory keys (Gemini API key, Airtable API key, Airtable Base ID, Email address) that writes to `.env` on save and validates each key on entry. Non-technical users never need to open a text editor.

---

## Pre-Production Checklist

- [ ] Ship the simplifications above so the video shows the improved flow
- [ ] Create a throwaway Airtable base with 3–5 real open job postings for the live demo
- [ ] Create a throwaway Outlook account for the email verification demo
- [ ] Use a Greenhouse job and a Lever job in the demo batch — both have pre-built skill files and highest on-camera success rate
- [ ] Record at 1920×1080, browser zoom 100%, terminal font 18 pt
- [ ] Prepare a split-screen layout (Gradio UI left, browser window right) for Segment 7
- [ ] Links ready for description: Airtable table-setup video, repo URL, `.env.example`

---

## Architecture Diagram (use in Segment 2 as a graphic)

```
┌─────────────────┐
│   Airtable      │  State = "new"
│   Job Table     │─────────────┐
└─────────────────┘             │
                                ▼
                     ┌─────────────────────┐
                     │   Job Applicator    │  reads next job
                     │   (Gradio UI)       │─────────────────┐
                     └─────────────────────┘                 │
                                ▲                            ▼
                    updates     │              ┌─────────────────────────┐
                    State       │              │  Google Search          │
                  "applied" /   │              │  (finds careers page,   │
                   "error"      │              │   skips LinkedIn links)  │
                                │              └────────────┬────────────┘
                                │                           │
                     ┌──────────┴──────────┐               ▼
                     │  Airtable REST API  │  ┌────────────────────────┐
                     │  (no browser)       │  │  Company Careers Page  │
                     └─────────────────────┘  │  (Greenhouse / Lever / │
                                              │   Workday / custom ATS)│
                                              └────────────┬───────────┘
                                                           │
                                              ┌────────────▼───────────┐
                                              │  AI Agent              │
                                              │  · fills form fields   │
                                              │  · uploads resume PDF  │
                                              │  · auto-login if saved │
                                              └────────────┬───────────┘
                                                           │
                                              ┌────────────▼───────────┐
                                              │  Email Verification    │
                                              │  (if required)         │
                                              │  · Outlook IMAP OAuth  │
                                              │  · extracts OTP / link │
                                              │  · enters code, cont.  │
                                              └────────────────────────┘
```

---

## Full Video Script

---

### SEGMENT 1 — Hook (0:00–0:50)

**Goal:** Establish that this is a more serious tool than generic Browser Use / LinkedIn Easy Apply demos.

**On screen:** Split screen — Workday application form filling automatically on the left; Airtable row flipping from "new" to "applied" on the right.

**Script:**
> "Most AI job application videos show you how to click Easy Apply on LinkedIn. That works for some jobs, but most serious roles — especially in tech — live on Greenhouse, Lever, Workday, or the company's own custom portal. Those require creating an account, verifying your email, uploading a resume, answering screening questions. Basically everything that's annoying to repeat 50 times.
>
> Today I'm going to show you a tool I built that handles all of that automatically. It reads your job list from Airtable, navigates directly to each company's careers page, fills the application, verifies emails when the site asks for it, saves your credentials so it doesn't re-register on the same site twice, and marks every job as applied when it's done — all while you do something else.
>
> And it supports multiple candidates, so if you're helping a few people job hunt at the same time, one tool covers everyone. Let's build it from scratch."

---

### SEGMENT 2 — How It Works (Architecture Overview) (0:50–2:45)

**Goal:** Orient the viewer so nothing is surprising later. Show the diagram.

**On screen:** Animated flow diagram (see Architecture Diagram above).

**Script:**
> "Before we touch the terminal, let me walk you through exactly what happens when this tool runs, so you understand why each setup step exists.
>
> Everything starts in Airtable. You have a table of jobs — I cover how to set that table up in the linked video. Each row has a job title, company, a link to the job posting, and a status column that starts as 'new'. This tool is your worker: it polls Airtable for anything with status 'new' and processes them one by one.
>
> For each job, the agent does not use the LinkedIn link you saved. Instead it Googles the company name and role title to find the official careers or ATS page. This is deliberate — LinkedIn links expire, and your application needs to live on the company's actual system.
>
> Once it finds the application page, the AI agent takes over. It fills every form field using whichever candidate profile you've selected — name, email, phone, work history, education. It uploads the resume PDF associated with that candidate. If the site asks for a cover letter, it generates one from your profile data.
>
> Here's where it gets interesting: if the site asks you to create an account and sends a verification email — which happens constantly with Greenhouse, Workday, and dozens of others — the tool automatically opens your Outlook inbox, finds the email, extracts the code or confirmation link, enters it, and keeps going. No manual intervention.
>
> If it's a site the tool has visited before, it has the credentials saved locally, so it logs in directly and skips registration entirely.
>
> When the application is submitted, the tool calls the Airtable API directly — not through the browser — and flips that job's status to 'applied'. If something went wrong, it writes 'error' with a description so you can investigate.
>
> That's the whole loop. Now let's set it up."

---

### SEGMENT 3 — Prerequisites (2:45–3:45)

**Goal:** Confirm the viewer has everything before running a single command.

**On screen:** Checklist that ticks off each item as it's mentioned.

**Script:**
> "You need four things. First: Python 3.11 or newer. On Mac, open Terminal and type `python3 --version`. On Windows, download the installer from python.org — check 'Add Python to PATH' during install or nothing will work.
>
> Second: Git. On Mac, typing `git` in Terminal will prompt you to install it if it's missing. On Windows, download Git for Windows from git-scm.com.
>
> Third: Google Chrome or Microsoft Edge already installed. We'll use your existing browser session so the agent inherits any cookies or logins you already have.
>
> Fourth: your Airtable job table already set up with at least one row in 'new' status. Link to that setup video is in the description.
>
> Everything else — packages, the AI browser, config files — we'll install right now."

---

### SEGMENT 4 — Clone and Install (3:45–6:15)

**Goal:** Get the project running. Show the simplified one-command install.

**On screen:** Terminal full-screen, then VS Code with `.env` open.

#### 4a — Clone the repo (3:45–4:15)

**Script:**
> "Open your terminal. Navigate to wherever you want this to live — I'll use the Desktop:"
```bash
cd ~/Desktop
git clone https://github.com/YOUR_REPO_HERE.git job-applier
cd job-applier
```
> "Now you have the full project."

#### 4b — Run the setup script (4:15–5:30)

**Script:**
> "There's a single setup script that handles everything. On Mac or Linux:"
```bash
./setup.sh
```
> "On Windows, open Command Prompt — not PowerShell — and run:"
```batch
setup.bat
```
> "This installs UV, which is a fast Python package manager; creates a virtual environment locked to Python 3.11; installs all required packages; and downloads the Chromium browser the AI will control. You'll see a lot of output. Normal. Wait for the green 'Setup complete' message — usually about 2 to 3 minutes."

#### 4c — Open .env (5:30–6:15)

**Script:**
> "The script already copied `.env.example` to `.env` for you. Open `.env` in VS Code or any text editor:"
```bash
code .env
```
> "You'll see clearly labelled sections for each API key. We'll fill these in now, one by one."

---

### SEGMENT 5 — Getting Your API Keys (6:15–10:30)

**Goal:** Walk through each required key quickly and concretely. This is the highest drop-off risk segment — keep it moving.

#### 5a — Google Gemini (AI brain) (6:15–7:15)

**On screen:** Browser navigating to aistudio.google.com.

**Script:**
> "The AI model powering this is Google Gemini 2.5 Flash. It has a free tier that handles all the reasoning without you paying anything.
>
> Go to aistudio.google.com. Sign in with any Google account. Click 'Get API key' in the left sidebar. Click 'Create API key', choose any project. Copy the key.
>
> Back in `.env`, paste it on the line that says `GOOGLE_API_KEY=`. That's it for the AI."

#### 5b — Airtable API key and Base ID (7:15–9:00)

**On screen:** Airtable developer hub, then the browser URL bar showing the base ID.

**Script:**
> "Now Airtable. You need two things: an API token and your Base ID.
>
> For the token: in Airtable, click your profile picture in the top right, go to 'Developer Hub', then 'Personal access tokens'. Click 'Create new token'. Name it 'job-applier'. Under scopes, add `data.records:read` and `data.records:write`. Under access, select your workspace. Click 'Create token', copy it, paste it into `AIRTABLE_API_KEY=` in your `.env`.
>
> For the Base ID: open your job table in Airtable in the browser. Look at the URL — it starts with `airtable.com/` followed by something like `appXXXXXXXXXXXXXX` — that `app...` part is your Base ID. Copy it and paste into `AIRTABLE_BASE_ID=`.
>
> The `AIRTABLE_TABLE_NAME=` line defaults to 'Job Table'. Change it if your table has a different name."

#### 5c — Outlook email (the key differentiator) (9:00–10:30)

**On screen:** Terminal showing the OAuth device-code flow, then browser approving it.

**Script:**
> "This step is what most tutorials skip, and it's why this tool succeeds where others don't. When a job site sends a verification email during account creation, most automation tools get stuck. This one reads your inbox automatically.
>
> You need a Microsoft Outlook or Microsoft 365 account. A free outlook.com account works perfectly. If you don't have one, create one now at outlook.com — takes 2 minutes.
>
> Put that email address in `.env` on the `EMAIL_ADDRESS=` line.
>
> Now run this one-time command to connect the account:"
```bash
source .venv/bin/activate
python src/utils/email_auth.py
```
> "The terminal will print a URL and a short code. Copy the URL, open it in your browser, sign into your Microsoft account when prompted, and enter the code you saw in the terminal. Click 'Approve'. Switch back to the terminal — it'll say 'Token saved'. Done. This never expires as long as the tool runs at least once every 90 days."

---

### SEGMENT 6 — Set Up Candidate Profiles and Resumes (10:30–13:30)

**Goal:** Show the multi-resume system — a key differentiator.

**On screen:** Gradio UI open in browser, Candidates tab.

#### 6a — Start the tool for the first time (10:30–11:00)

**Script:**
> "With the keys configured, start the tool:"
```bash
python webui.py
```
> "Open your browser to http://127.0.0.1:7788. You'll see the Job Applicator dashboard."

#### 6b — Edit the default candidate profile (11:00–12:30)

**Script:**
> "Go to the 'Job Applicator' tab. On the left panel you'll see 'Candidate Profile' with a dropdown. There's a placeholder profile loaded. Click 'Edit Profile'.
>
> You'll see fields for all your personal information. Fill in: your full name, email address — use the same Outlook address from the last step — phone number, LinkedIn profile URL, target job title, years of experience, and a short professional summary.
>
> Then upload your resume PDF using the file picker. The tool will save it and link it to this profile automatically.
>
> Click 'Save Profile' when you're done."

#### 6c — Adding a second candidate (12:30–13:30)

**Script:**
> "If you want to add another candidate — a different resume version, or someone else you're helping — click 'New Profile'. Fill in their details and upload their resume. You can switch between candidates from the dropdown at any time before you start a batch. Whoever is active when you click 'Start Batch' is who the agent applies as.
>
> The credentials and site history are stored separately per candidate, so their login to Greenhouse doesn't conflict with yours."

---

### SEGMENT 7 — Run Your First Batch (13:30–17:00)

**Goal:** The payoff demo. Show the full loop working in real time.

**On screen:** Split view — Gradio UI on left, browser window on right.

#### 7a — Load jobs and start (13:30–14:15)

**Script:**
> "Click 'Refresh Jobs'. Your Airtable jobs with status 'new' appear in the table. Review the list. If there's a job you're not ready for yet, flip its status in Airtable and it'll be skipped on the next refresh.
>
> Confirm your candidate is selected in the dropdown, then click 'Start Batch'."

#### 7b — Live demo: Greenhouse application (14:15–15:45)

**On screen:** Browser showing the agent navigating a Greenhouse job page.

**Script:**
> "Watch the browser on the right. The agent just Googled the company name plus job title and landed on their Greenhouse application page — not LinkedIn.
>
> It's filling the work experience section now, pulling from the candidate profile: job title, company, dates, responsibilities. The tool has a pre-built instruction set specifically for Greenhouse, so it knows the exact order of steps and where each field lives.
>
> Now it needs to create an account on this company's Greenhouse instance. It's entered the email address and clicked 'Send verification code'."

**On screen:** Terminal log showing `read_verification_email` being called.

**Script:**
> "Right there in the logs you can see it called `read_verification_email`. It's now polling the Outlook inbox. The email arrived, it extracted the 6-digit code, and it's typing it into the form now. This whole exchange took about 8 seconds. No input from me.
>
> Application submitted."

#### 7c — Airtable update (15:45–16:15)

**On screen:** Airtable base refreshed, row showing "applied".

**Script:**
> "Back in Airtable — that job just flipped from 'new' to 'applied'. The tool called the Airtable API directly after the submission, without the browser touching Airtable at all.
>
> The batch continues to the next job automatically."

#### 7d — Error handling (16:15–17:00)

**Script:**
> "If a job fails — let's say the careers page has a CAPTCHA the agent can't solve, or the form has an unusual layout it can't navigate — it marks the job 'error' in Airtable with a plain-English reason in the 'Error Message' column. You review it, decide whether to retry, and if you want to re-queue it:"
```bash
python reset_airtable_errors.py
```
> "That resets all 'error' rows back to 'new' so the next batch picks them up again."

---

### SEGMENT 8 — How the Site Memory Works (17:00–18:00)

**Goal:** Explain credential store and skill files — the compounding value over time.

**Script:**
> "The tool gets smarter the more you use it, in two ways.
>
> First, credentials. The first time it visits a Lever-powered site, it creates an account, saves the login, and applies. The second time it visits any Lever site — different company, same ATS — it logs in directly. No re-registration, no new email verification. These are stored locally in a JSON file per candidate.
>
> Second, site skills. The repo ships with pre-built instruction files for the most common platforms: Greenhouse, Lever, Workday, and several others. These tell the AI exactly how each platform's form is structured — where the resume upload button is, how multi-page forms are sequenced, which fields are optional. On platforms with these files, the success rate is dramatically higher than on unknown platforms.
>
> For sites the tool encounters that aren't covered yet, it figures out the form visually — and you can save those instructions for future runs from within the UI."

---

### SEGMENT 9 — Daily Use and Restart (18:00–19:00)

**Goal:** Make the ongoing workflow feel lightweight.

**Script:**
> "Once you're set up, the daily workflow is minimal. Add new jobs to Airtable with status 'new' — the linked video shows how to automate that part too with a job-board scraper. Then:"
```bash
cd ~/Desktop/job-applier
source .venv/bin/activate
python webui.py
```
> "Or save a shell alias so it's one command:"
```bash
echo 'alias jobapply="cd ~/Desktop/job-applier && source .venv/bin/activate && python webui.py"' >> ~/.zshrc
source ~/.zshrc
```
> "Then it's just `jobapply` from anywhere. Open localhost:7788, refresh, start batch, walk away."

---

### SEGMENT 10 — Tips for Better Results (19:00–20:00)

**Goal:** Manage expectations; reduce comment-section questions.

**Script:**
> "A few things that'll save you headaches.
>
> Run batches of 10 to 15 at a time while you're getting started. Not 100. This gives you time to review errors before they stack up.
>
> For your first few runs, keep an eye on the browser window. Some sites have CAPTCHA flows the tool will pause on and wait for you to solve manually. Once you've seen how it handles your target sites, you'll know when you can safely walk away.
>
> Don't switch to a cheaper or smaller AI model to save costs. Gemini 2.5 Flash is already free and it's genuinely the minimum capable model for multi-step form filling. Going smaller causes more errors and you'll spend more time fixing them than you saved.
>
> Keep your resume PDFs current. The tool applies exactly what's in the file — it doesn't rewrite or summarise your resume for each job. Tailor it before you add a batch.
>
> And read the Error Message column in Airtable before mass-resetting errors. Some failures are expected — the job closed, the site has unsupported CAPTCHA, the role requires a form the tool can't reach. Resetting those will just fail again."

---

### SEGMENT 11 — Outro (20:00–20:30)

**On screen:** Airtable with a full column of "applied" rows.

**Script:**
> "That's the complete setup. Airtable as your job queue, Gemini as the AI, your own browser session for sites that need authentication, automatic email verification so no application gets stuck at the inbox step, and a credential store that makes every repeat visit faster.
>
> The Airtable table setup video is linked below. If you hit a specific error — paste it in the comments with the site name and I'll address the most common ones in a follow-up.
>
> Like if this saved you time, and subscribe for the follow-up where I show how to automatically populate Airtable with fresh job listings from job boards every morning."

---

## Chapter Markers (for YouTube)

| Timestamp | Chapter |
|-----------|---------|
| 0:00 | What this tool does |
| 0:50 | How it works (architecture) |
| 2:45 | Prerequisites |
| 3:45 | Clone and install |
| 6:15 | API keys: Gemini, Airtable, Outlook |
| 10:30 | Set up candidate profiles and resumes |
| 13:30 | Run your first batch (live demo) |
| 17:00 | Site memory: credentials and skill files |
| 18:00 | Daily use and restart alias |
| 19:00 | Tips for better results |
| 20:00 | Outro |

---

## Description Template

```
In this video I walk through the complete setup of an AI job application tool
that reads from Airtable, applies to jobs on company career pages directly,
handles email verification automatically, and supports multiple candidates.

⏱ Chapters:
0:00 What this tool does
0:50 How it works (architecture)
2:45 Prerequisites
3:45 Clone and install
6:15 API keys
10:30 Candidate profiles and resumes
13:30 Live demo
17:00 Site memory
18:00 Daily use
19:00 Tips

🔗 Links:
→ GitHub repo: [REPO URL]
→ Airtable table setup video: [LINK]
→ Google AI Studio (free Gemini key): https://aistudio.google.com
→ Airtable: https://airtable.com

📋 Supported ATS platforms (pre-built skill files included):
Greenhouse · Lever · Workday · BairesDev · HackerX · Natek · Xitee

#jobsearch #ai #automation #airtable #browseruse #python
```
