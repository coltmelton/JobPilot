# JobPilot MVP

A **local-first**, review-first Python dashboard for software-adjacent job applications at RTX/Raytheon, Anduril, Palantir, Lockheed Martin, Parker Hannifin, Parker Aerospace, KLA, Sartorius, Pfizer and Northrop Grumman.

## Run

Requires Python 3.10+ and a graphical desktop (Windows/macOS/Linux).
The encrypted background batch workflow currently requires Windows; resume and
discovery tools remain usable on other platforms.

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
4. In Accounts & Sessions, save your shared email/password in the encrypted vault. Add portal-specific logins if needed.
5. Go to Review & Launch, select the vacancy, and save any custom answers by the site's **exact field label** in the JSON editor. Keep screening certifications in manual answers.
6. In Batch Launch, choose jobs and a resume, optionally allow the shared login on those portals, then launch the batch. Jobs run one at a time in the background.
7. Use the assistance inbox for missing information, login/account creation, verification and final review. Employer actions clicked there operate on the live website; a Submit action sends the application. The legacy visible-browser helper remains in Review & Launch as an optional alternative.

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

Accounts & Sessions stores shared and portal-specific credentials encrypted with
Windows DPAPI under `%LOCALAPPDATA%\JobPilot\private`, outside the project and
OneDrive. There is no plaintext/key-file fallback. They are decryptable by your
Windows user, not portable project files. Shared credentials require permission
for each portal (or the selected portals at batch launch); automatic login never
sends a portal's password to a different iframe origin. Each job attempts saved
login once, then asks for help rather than retrying repeatedly.

Background batches save encrypted cookies/local storage/IndexedDB in that vault.
Encrypted screenshot previews and encrypted assistance commands live in the local
workflow database. Blank input values and passwords are not included in the
persisted field metadata. The legacy manual-browser helper can still read/write
older sessions in `data/account-sessions/`; Forget saved session deletes both the
new encrypted state and legacy state. Session-storage-only or device-bound
authentication may require another login or the optional manual browser.
See [Playwright authentication](https://playwright.dev/python/docs/auth).

Browser workers acquire an OS lock for their account session, released even if
they crash. Background batches run sequentially and surface a busy portal as an
error if another helper has it open. In Review & Launch, Fill current browser page deliberately
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

- **This is an MVP, not a universal application bot.** Background batches fill known fields and advance unambiguous Apply/Next/Continue steps. Unknown controls, missing answers, account creation, MFA and final submission pause for your input.
- The autofill helper fills only empty, visible, clearly labeled text fields, and uploads the selected resume only when exactly one file input exists. It will not fill dropdowns, government-related eligibility certifications, demographic questionnaires, or security clearance answers automatically.
- Site-specific adapters are required for high success rates on Workday, Greenhouse, iCIMS, custom systems and other ATS platforms. They are **not yet implemented**.
- An employer's site might block automation. CAPTCHA/passkey/device checks may need the optional manual browser, opened only when you request it. Restrictions are not bypassed.
- Close the legacy account-login window before launching an application on that portal. A busy portal is reported in batch progress.
- Records and uploads are stored **unencrypted** in `data/` locally. Do not expose Streamlit to the public internet or add sensitive identifiers, passwords or government ID data. Back up carefully.
- The external site receives entered fields and uploads while the form is being prepared. Final submission is only clicked through an explicit employer action you send from the inbox, never as an automatic batch step. An Applied status requires employer confirmation after your action.
- On a dynamic site, the helper may miss fields or fill an unintended similarly labeled field. Always review before submission.

## Expansion plan

1. Extend discovery adapters and add optional scheduled scans.
2. Add Workday, Greenhouse, iCIMS and custom adapters with tests against each target portal.
3. Introduce an answer/required-document task queue, field-level confidence checks and optional LLM assistance without fabricating applicant claims.
4. Extend local matching, add optional semantic analysis, tailored document drafts and richer submission confirmation tracking.

## Background batch preparation and assistance inbox

Use **Bulk Import** to paste many application links at once (one line per job):

```
Anduril | Software Engineer | https://example.com/real-job-link | CA
Palantir | Backend Engineer | https://example.com/another-real-job-link | NY
```

These URLs are **format examples only**, not actual vacancies. In **Batch Launch**,
select jobs and your resume. Optional shared-login permission applies to those
selected employer portals. Each job runs in a headless browser and the next starts
after it is submitted, skipped, stopped or fails. Already-Applied jobs are skipped.
The batch pauses while an application needs assistance; the sidebar displays an
alert and an in-app toast, and the inbox refreshes automatically.

The inbox provides a masked employer-page preview, fields for text/password/code
entry, native select and checkbox choices, saved-document uploads and visible
employer action buttons. Changes are sent only when you press Send entries; choose
an employer action separately, or Resume automation. Repeated experience/education
sections and unfamiliar custom widgets may need these manual controls. Choose
Skip to leave a job for review and continue the batch. Stop cancels queued work.
After a crashed worker, End inactive batch becomes available after two minutes
without a heartbeat. Queue reset is blocked while a batch remains active.

Account-required alerts are based on the employer's explicit messages or detected
registration forms. Ambiguous invalid credentials remain a login-help request;
the app cannot determine every missing account in advance. It never creates an
account or accepts agreements without the employer action/field choices you send.

Batch status survives dashboard refreshes in `workflow_runs`/`workflow_tasks` in
SQLite. A stopped/crashed browser's unsaved DOM edits are not recoverable. Relaunch
unfinished jobs after resolving a stopped worker. Logs are in `data/logs/`.

Alternatively, run `python batch.py --job-ids 1,2,3 --resume resume.pdf` and open the
Batch Launch inbox to provide assistance. The supported worker count is one.

Only one background batch can be active at a time. Legacy `data/browser-profiles/`
directories are retained, but are not the new workflow's credential vault.

## Stopping a batch

Open **Batch Launch** and click **Force stop all batches** to immediately close this project's batch workers and their browser processes, including older batches. The app stays open. Unfinished tasks are marked stopped and queued commands are cleared; you can launch a new batch. Unsaved employer form entries may be lost. Applications already submitted remain submitted. **Stop this batch** in the inbox requests a normal stop instead.

## Smarter routine form handling

Background batches recognize required markers, common profile-field aliases and HTML autocomplete hints, native and supported custom dropdowns, country/state names and abbreviations, and iframe form fields. Resume uploads target resume fields rather than cover-letter fields. Slow pages and unchanged steps receive bounded waits/retries; two-stage email/password login is supported with approved credentials.

When the inbox needs an answer, it lists the missing fields. Sending routine missing entries resumes automation automatically. Check **Remember these routine answers for other applications** to reuse your exact answers to matching questions, such as referral source. Review or delete these answers in Batch Launch. Answers stay in the local profile; passwords, verification codes, sensitive questions and certifications are excluded from this memory.

These decisions use local profile facts and explicit answers; no model service receives your resume or page content. Unknown answers, account registration, verification and final submission still require your input. Stop and relaunch any already-running batch to load updated worker code.

Introductory **Apply** buttons are clicked automatically, including postings with search filters and repeated links to the same application. **Autofill with resume** is preferred over manual application when offered. Select a resume in Batch Launch; otherwise the saved matching resume or a single identifiable resume is used. Ambiguous or missing resumes prompt for your input. Supported upload steps include hidden file inputs and file-picker buttons, with a bounded wait for visible upload/parsing activity before continuing.

Dropdown handling includes native selects, readonly custom dropdowns and searchable menus with delayed results. When a widget identifies its menu, choices are scoped to that menu. Values come from your profile or explicit remembered answers; ambiguous choices and sensitive screening questions still need your input.

Text and information fields are processed before uploads and again after resume parsing. The worker rescans for newly revealed fields, supports rich-text inputs and common field identifiers, and fills optional fields when their answers are known. Unknown required fields pause the page. Unknown optional text fields are also shown before advancing; explicitly choose **Leave remaining optional fields blank and continue** to skip those. Save/Next/Continue/Proceed variants are recognized and associated form buttons are preferred over unrelated page controls.

Resume uploads are tracked for each application across page changes. Existing file selections, visible attachment cards and upload-success indicators prevent duplicate uploads, even when an ATS resets its file input or offers another upload widget. Uncertain upload results also block automatic repeats; inspect the employer preview and use the retry control if an upload actually failed. Existing server attachments are retained rather than automatically replaced.
