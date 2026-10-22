# JobPilot MVP

A **local-first**, review-first Python dashboard for software-adjacent job applications at RTX/Raytheon, Anduril, Palantir, Lockheed Martin, Parker Hannifin, Parker Aerospace, KLA, Sartorius, Pfizer and Northrop Grumman.

## Run

Requires Python 3.10+ and a graphical desktop (Windows/macOS/Linux).

### Windows quick start

From PowerShell in this folder:

```powershell
.\setup.cmd
.\run.cmd
```

You can also double-click these files in Explorer. Setup creates `.venv`, installs
the dependencies and downloads Chromium for autofill. Run starts the dashboard
and opens your default browser at http://localhost:8501. Keep the terminal open;
press Ctrl+C there to stop the server. No environment activation is needed.
The first run automatically runs setup if `.venv` is missing.

If port 8501 is already in use, run `.\run.cmd -Port 8502`.
Rerun `.\setup.cmd` to update or repair the dependencies.

### Manual setup (all platforms)

```bash
python -m venv .venv
# Activate the virtual environment:
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
streamlit run app.py
```

Open the localhost URL Streamlit prints (usually http://localhost:8501).

## Workflow

1. Complete My Profile; upload a resume in Documents.
2. Open Resume & Matching, extract your resume text, and review your years of relevant experience. Set your self-reported clearance in My Profile.
3. Use Discover Jobs to scan careers-page links and select postings to import, or copy an individual application link into Job Queue. Fetch full descriptions for reliable requirement checks.
4. Use Accounts & Sessions to sign in manually if needed. Close that window before opening an application on the same portal.
5. Go to Review & Launch, select the vacancy, and save any custom answers by the site's **exact field label** in the JSON editor. Keep screening certifications in manual answers.
6. Select a resume and click **Open browser and autofill**. Sign in/navigate in the browser, then click **Fill current browser page** in JobPilot. Repeat after manually moving to another form page.
7. Review every answer and attachment, personally submit, and update the job's status.

## Resume matching and account sessions

To rebuild the list, open **Job Queue → Start over — clear imported jobs → Back
up and clear job queue**. This archives all job records, including statuses,
notes and answers, under `data/backups/` before clearing them. Resume/profile,
matching settings and saved logins are retained. Then run a new discovery scan,
apply filters and import your new selection. Imports append unique URLs; they
do not replace the queue. Old discovery selections are cleared after a reset.

Resume & Matching extracts PDF/DOCX/TXT text locally, detects skills, and estimates
calendar experience from explicitly labelled employment sections. Overlapping
date ranges count once; education/project dates are excluded. Internships,
work-study and part-time jobs can be included in that calendar estimate, so edit
and confirm your relevant-years baseline. Scanned PDFs need OCR or pasted text.
No resume text is sent to an external model or to the discovery websites.

Discovery and Job Queue offer explainable skill-overlap scores, clearance and
experience filters, and evidence from the posting. An explicit existing-clearance
requirement is hidden by default when your profile says None; ability-to-obtain
roles remain visible. Unknown requirements stay visible for review. After you
confirm experience, experience-stretch filtering defaults on. Filters are always
adjustable. Preferred years and education alternatives are treated separately;
this heuristic cannot determine your legal eligibility or certify qualifications.

Discovery fetches a bounded number of additional descriptions, prioritising
resume-related titles; Lever/JobPosting metadata may already include descriptions.
Known public Greenhouse/Lever boards are also prioritised locally before the
result cap, rather than taking only the first alphabetical postings.
Use Fetch more missing descriptions or the queue's Fetch missing descriptions
button for older results. Descriptions are cached locally for 24 hours. If a site
blocks reading, paste its text in Review & Launch. Select all applies only to
the currently visible filtered results and preserves edits. Completed discovery
results can be reloaded after a browser/session restart.

Accounts & Sessions opens a browser for manual registration/login/MFA and saves
cookies, local storage and IndexedDB under `data/account-sessions/`. Applications
on the same portal reuse this state, subject to expiration and the employer's
authentication rules. Passwords are not entered or stored by JobPilot. These
session files are credentials and are excluded from git with the rest of `data/`.
Use Forget saved session to delete the local state. Session-storage-only or
device-bound authentication may require signing in again in each application.
See [Playwright authentication](https://playwright.dev/python/docs/auth).

Browser workers acquire an OS lock for their account session, released even if
they crash. Batch workers wait their turn for the same portal; other portals can
run concurrently. In Review & Launch, Fill current browser page deliberately
waits for your click after login/navigation and can be repeated. Final submission,
dropdown certifications, citizenship, clearance and demographic answers remain
manual, including when those questions were accidentally placed in custom JSON.

**Inspect current browser page** in Review & Launch reads visible form controls,
including those inside frames, and reports blank required fields, available
profile/custom-answer matches, repeated labels, login controls, attachments and
questions needing manual attention. It does not change the form or record input
values. Inspection runs on opening a worker and after each autofill, and can be
requested again after login/navigation. Refresh browser status to see the latest
snapshot. Custom widgets and hidden future steps can be missed; the report does
not establish that an application is complete.

## Reference projects and reuse

Reviewed against the GitHub job-application-automation topic on October 22, 2026:

| Project | Useful design ideas | Reuse review |
| --- | --- | --- |
| [suxrobGM/jobpilot](https://github.com/suxrobGM/jobpilot) | Separate dashboard/browser worker, per-job progress, verifiable resume facts | [MIT license](https://github.com/suxrobGM/jobpilot/blob/main/LICENSE) verified; direct reuse would retain its notice |
| [Job Application Workbench](https://github.com/jimpeel-tech/job-application-workbench) | Reusable answers, local matching, source-based document generation | [MIT license](https://github.com/jimpeel-tech/job-application-workbench/blob/main/LICENSE) verified; direct reuse would retain its notice |
| [AutoApply](https://github.com/Liam-Frost/AutoApply) | Separate eligibility rules from semantic fit, durable tasks, review queue | [PolyForm Noncommercial](https://github.com/Liam-Frost/AutoApply/blob/master/LICENSE); no code imported |
| [Workday copilot](https://github.com/rifattahmid/workday-job-application-copilot) | Workday-specific sections and field detection | Root LICENSE not found during review; Australian defaults and agreement automation are unsuitable for our profile flow; no code imported |
| [JobMatchAI](https://github.com/wadekarg/JobMatchAI) | Question classification, reusable Q&A, field-level explanations | README says MIT but root LICENSE was not found during review; no code imported |

The form inspector is an independent implementation of the general field-inventory
idea. No source files or snippets from these projects have been vendored or copied.
Next candidates are an adapter interface for Workday/Greenhouse forms and optional
semantic matching with evidence-backed recommendations. They are not yet implemented.

## Discover jobs from careers pages

Choose **Discover Jobs** in the sidebar. The eight supplied employer URLs are
preloaded. Paste URLs on separate lines or separated by `|`, then click **Scan
career pages**. The scan runs in a separate background process. Use **Refresh
scan status** to check progress; other pages remain usable while it runs.

Review the per-source reports, filter by title/company/location, verify posting
links, edit titles/locations if needed, select rows, and click **Import selected
postings**. Nothing is automatically added to the queue or applied to. Duplicate
URLs are skipped. Query filters and posting IDs are retained when tracking
parameters are removed.

Click **Open job ↗** in either the discovery results or Job Queue table to open
that posting/application directly. Posting URLs are read-only in the discovery
editor so clicking opens the link rather than editing it.

Discovery uses public Greenhouse listings for Anduril, public Lever listings for
Palantir, public Workday listings for KLA and Sartorius, and rendered posting links
and JobPosting metadata for other boards, including Eightfold. Page/result limits
bound each scan; reports flag truncation where detectable. It does not guarantee
every vacancy is found. The Anduril feed reads its board rather than reproducing
marketing-page employment filters; review/filter its candidates yourself.

The RTX Yello `/collect/form/` URL is a registration form, not a vacancy list;
the report points to RTX's careers search instead. Parker returned a verification
page during validation. For consent or verification, select the visible-browser
option: it waits 30 seconds on each rendered source for you to interact manually.
This may still be blocked. Scans never bypass access restrictions, enter your
profile, or submit forms. Some sites require manual browsing or future adapters.

Scan sources, logs and results are stored under `data/discovery/`. The UI's current
scan/results belong to the current Streamlit session. A browser/session restart
may require rescanning; imported jobs remain in the database.

CLI alternative (a UTF-8 text file containing the same URL list):

```powershell
.venv\Scripts\python.exe discovery.py --sources-file careers.txt --output results.json --pages 3 --limit 100
```

Add `--headed` for visible browser assistance. No new Python dependencies are
needed beyond the existing setup.

## Scope and limitations

### Applicant profile and defense preparation

My Profile includes legal/preferred names, address, availability, compensation,
education, employment, certifications, projects, optional military experience,
and reusable written responses. History tables support multiple rows.
Existing saved profile values are preserved when you edit your profile.

Optional screening reference fields cover work authorization, current/future
sponsorship, self-reported citizenship, clearance level/status, relocation and
work preferences. These profile fields are for manual reference and are not
included in profile autofill. They do not establish eligibility. Leave sensitive
identifiers and classified information out of the app; answer demographic and
disability questionnaires directly in the employer portal if you choose.

Review & Launch now saves each job's requisition ID, deadline, recruiter,
posting-specific clearance/citizenship requirements, document requirements,
manual screening answers and a preparation checklist. Existing databases are
updated automatically. Contact/address fields can be autofilled; history and
screening reference answers remain available for you to copy and review.

Offline verification: `.venv\Scripts\python.exe -m unittest discover -v`.

- **This is an MVP, not a universal application bot.** It discovers candidate postings from supported public boards, but does not automatically move through multi-page application forms, autonomously answer screening questions, or submit applications.
- The autofill helper fills only empty, visible, clearly labeled text fields, and uploads the selected resume only when exactly one file input exists. It will not fill dropdowns, government-related eligibility certifications, demographic questionnaires, or security clearance answers automatically.
- Site-specific adapters are required for high success rates on Workday, Greenhouse, iCIMS, custom systems and other ATS platforms. They are **not yet implemented**.
- An employer's site might block automation; respect access restrictions. Authentication, MFA, CAPTCHA and final submission are handled manually. The helper does not bypass any of these.
- Close the account-login window before launching an application on the same portal. A second interactive worker reports the busy portal; batch workers wait for it.
- Records and uploads are stored **unencrypted** in `data/` locally. Do not expose Streamlit to the public internet or add sensitive identifiers, passwords or government ID data. Back up carefully.
- Personal data is never submitted by this script (the browser helper does not click Submit). The external site does receive entered fields and uploads as part of interacting with its forms.
- On a dynamic site, the helper may miss fields or fill an unintended similarly labeled field. Always review before submission.

## Expansion plan

1. Extend discovery adapters and add optional scheduled scans.
2. Add Workday, Greenhouse, iCIMS and custom adapters with tests against each target portal.
3. Introduce an answer/required-document task queue, field-level confidence checks and optional LLM assistance without fabricating applicant claims.
4. Extend local matching, add optional semantic analysis, tailored document drafts and richer submission confirmation tracking.

## Concurrent batch application preparation

Use **Bulk Import** to paste many application links at once (one line per job):

```
Anduril | Software Engineer | https://example.com/real-job-link | CA
Palantir | Backend Engineer | https://example.com/another-real-job-link | NY
```

These URLs are **format examples only**, not actual vacancies. Then go to **Batch Launch**, select jobs, and choose 1–5 workers (recommended initial setting: 3). Jobs sharing the same employer portal use the saved account session sequentially; different portals can coexist. Sessions run until you close their windows, at which point the next queued browser opens. Per-job logs are in `data/logs/`. Legacy `data/browser-profiles/` directories are retained, but new windows use the saved account sessions instead; sign in again if needed.

Alternatively, run `python batch.py --job-ids 1,2,3 --workers 3 --resume resume.pdf` from the project folder.

**Important:** Batch Launch implements concurrent *preparation/autofill*, not autonomous multi-page applications or bulk submission. Discovery is a separate review-first workflow. Sites can impose rate limits, require manual logins, and prevent browser automation. The batch queue will not bypass these restrictions. Persisted browser profiles hold session cookies locally; protect the `data/` directory. Do not run more than one batch containing the *same job ID* at a time.
