---
name: amazon-pull-report
description: Pull Amazon Seller Central reports via SP-API instead of clicking through Seller Central manually. Use whenever the user asks to download, fetch, pull, get, export, or grab a report — including removal inventory, removal orders, removal shipments, FBA returns, MFN returns, inventory ledger summary, ledger detail, orders, sales reports, sales & traffic, settlement reports, or any other GET_* SP-API report type. Saves the report file directly into one flat output folder the user picks on first run; pull metadata is appended to a single `report-log.jsonl` inside the skill folder for audit and resume.
---

# Amazon Pull Report

Replaces the manual Seller Central click-through workflow for downloading reports. One command and the report file lands in the folder you picked on first run; an audit record is appended to `report-log.jsonl` inside the skill folder.

Self-contained: drop the `amazon-pull-report/` folder into any project's `.claude/skills/`, set four SP-API env vars, run.

---

## When to use

Trigger on phrasings like:
- "Pull last month's returns"
- "Get me the ledger detail for April"
- "Download the removal orders report"
- "Fetch sales for the last 30 days"
- "Grab the FBA returns report"
- "Export sales and traffic for the past week"
- "I need the inventory ledger"

Do NOT use for: live API calls that aren't reports (use the FBA Inventory, Catalog, Pricing APIs directly), creating listings, ads/PPC data, reimbursement claims.

## Translating natural-language date ranges

When the user says a relative date phrase, map it to `--preset` (calendar-aligned, US/Pacific — matching Seller Central). Do NOT compute dates yourself and pass `--start`/`--end` — the script does it correctly and consistently.

| User says | Pass |
|---|---|
| "last month" / "last calendar month" / "previous month" | `--preset last-month` |
| "this month" / "month so far" / "MTD" / "month to date" | `--preset mtd` (or `this-month`) |
| "last week" / "previous week" (Mon→Sun) | `--preset last-week` |
| "this week" / "week so far" | `--preset this-week` |
| "today" / "last day" / "current day" | `--preset today` |
| "yesterday" / "previous day" | `--preset yesterday` |
| "year to date" / "YTD" / "this year" | `--preset ytd` |
| "last 7 / 30 / 90 days" | `--preset last-7-days` (etc.) or `--days N` |

`last-month` means the **whole previous calendar month**: in May → April 1 through April 30 inclusive. In March → Feb 1 through Feb 28 (or 29). The script returns a half-open `[first-of-last, first-of-this)` range, which Amazon treats as inclusive of every event in the prior month.

For specific months by name ("April", "Feb 2025"), use `--start`/`--end` with the explicit ISO dates.

If the seller has never used this skill before, send them to `SETUP.md` first — the manual SP-API registration step takes ~15 minutes.

---

## First-run setup (do this BEFORE the first pull)

The first time the seller uses the skill, run this **exact sequence**:

### Step A — Check `uv` and credentials

```bash
cd .claude/skills/amazon-pull-report
command -v uv >/dev/null 2>&1 && echo "OK: uv" || echo "MISSING: uv"
[ -f config/preferences.json ] && echo "OK: preferences" || echo "MISSING: preferences"
```

If `uv` is missing → tell the seller to run `bash setup.sh` (or `.\setup.ps1` on Windows). It installs uv and Python, then drops a `.env` template at the project root if no `.env` exists yet in any of the standard locations (project root, `~/.config/amazon-pull-report/.env`, or skill folder).

If credentials are missing (run.py errors with `Missing required env var(s)`) → walk them through `SETUP.md` to fill in the four LWA / SP-API values in whichever `.env` was created.

### Step B — On first run only, prompt for output preferences via AskUserQuestion

If `config/preferences.json` does NOT exist, call **AskUserQuestion** with these two questions in a single call:

**Question 1 (header: "File format"):**
> "What format would you prefer your reports saved as? You can change this anytime."
> - **CSV file (.csv)** — Universal, opens cleanly in Excel and Google Sheets. (Recommended)
> - **Tab-delimited (.txt)** — Matches what Amazon's Seller Central downloads as the "flat file" option.

**Question 2 (header: "Where to save"):**
> "Where would you like reports to be saved? All reports land in this one flat folder — no subfolders. The filename of each report includes the slug, date range, and pull timestamp, so files stay organized without nesting."
> - **Documents folder** (e.g. `~/Documents/Amazon Reports`) — Easy to find in Finder/File Explorer. (Recommended)
> - **Downloads folder** (`~/Downloads`) — Reports land directly in your Downloads folder (Mac/Windows/Linux all have one).
> - **Inside this project** (e.g. `<cwd>/amazon-reports`) — Keep reports next to the code that consumes them.
> - **A specific folder I'll choose** — User picks "Other" and types a path.

Resolve `~` and the current working directory to actual absolute paths in the labels so the seller sees real paths, not tildes or placeholders.

After the seller answers, **write `config/preferences.json` directly** with the Write tool — it's just JSON, two keys, no need to invoke the script for this:

```json
{
  "format": "csv",
  "output_dir": "/Users/<seller>/Documents/Amazon Reports",
  "created_at": "2026-05-03T20:30:00+00:00"
}
```

Set `format` to `"csv"` or `"txt"` based on Q1, and `output_dir` to the absolute path the seller chose in Q2. Use the seller's actual home folder — never write `~` or `$HOME`; resolve it. The `created_at` field is informational; any ISO-8601 UTC timestamp works.

### Step C — Run the actual pull

Now run the requested report. Preferences are read silently going forward:

```bash
uv run bin/run.py --report orders-by-order-date --days 7
```

If the seller later says "switch to txt" or "save reports to a different folder", run with `--reset-preferences` and prompt again.

### If `MISSING: uv`

Tell the user to run the bootstrap script:
```bash
bash setup.sh   # macOS / Linux
.\setup.ps1     # Windows
```
This installs uv (one curl command), then auto-installs Python 3.9+ and the `requests` dependency. ~30 seconds.

### If any env var is `MISSING`

Tell the user they need to set up SP-API credentials. Walk them through `SETUP.md` (the file in this skill folder) — it's the friendly onboarding path. The TL;DR:

1. Go to Seller Central → Apps & Services → Develop Apps (or directly to https://sellercentral.amazon.com/developer/register).
2. Create a new app, pick the API roles you need (Inventory and Order Tracking covers most reports).
3. Self-authorize the app — the **Refresh Token** is shown ONCE, save it now.
4. Either run `bash setup.sh` to drop a `.env` template at your project root, or manually copy `.env.example` to `<project-root>/.env` (or `~/.config/amazon-pull-report/.env`). Paste in the four values:
   - `LWA_CLIENT_ID` (looks like `amzn1.application-oa2-client.…`)
   - `LWA_CLIENT_SECRET` (long hex string)
   - `SP_API_REFRESH_TOKEN` (looks like `Atzr|…`)
   - `SP_API_MARKETPLACE_ID` (e.g. `ATVPDKIKX0DER` for US)

`SP_API_REGION` is optional and defaults to `NA`. Set to `EU` or `FE` for those regions.

---

## Quick start

```bash
cd .claude/skills/amazon-pull-report

# See every report you can pull (no API call)
uv run bin/run.py --list

# Pull a report by friendly slug + last-N-days
uv run bin/run.py --report orders-by-order-date --days 7
uv run bin/run.py --report ledger-detail --days 7
uv run bin/run.py --report returns-fba --days 30

# US/Pacific presets (today, yesterday, this-week, last-week, this-month,
# last-month, mtd, ytd, last-7-days, last-30-days, last-90-days). Closed past
# windows (yesterday, last-week, last-month) end at midnight PT. Rolling
# windows end at start-of-tomorrow PT (effectively "now" — SP-API has no
# future data) so output matches Seller Central UI exactly.
uv run bin/run.py --report orders-by-order-date --preset last-month
uv run bin/run.py --report ledger-summary --preset mtd

# Explicit date range. Bare YYYY-MM-DD = midnight US/Pacific.
uv run bin/run.py --report orders-by-order-date --start 2026-04-01 --end 2026-05-01

# Pull a report not in the registry (raw escape hatch)
uv run bin/run.py --report-type GET_FBA_INVENTORY_AGED_DATA --format tsv --days 30

# Resume a long-running report after a poll timeout
uv run bin/run.py --resume 50028019xyz...

# Auto-split when the requested range exceeds the per-report cap
uv run bin/run.py --report orders-by-order-date --days 90 --chunk
```

Output is **flat** — every pull writes ONE file (the report itself) directly into the user's chosen output folder, no nested subfolders:

```
{output_dir}/
└── orders-by-order-date__last-month__pulled-2026-05-04-153012-123Z.csv
```

Filename shape: `{slug}__{range}__pulled-{YYYY-MM-DD-HHMMSS-mmm}Z.{ext}` (UTC + milliseconds, no collision risk). The `{range}` is the preset name (`last-month`), `last-{N}-days`, an explicit `YYYY-MM-DD_to_YYYY-MM-DD`, or `snapshot` for date-less reports.

Pull metadata (skill version, report id, document id, byte counts, status, error if any) is appended to a single `report-log.jsonl` file inside the skill folder — useful for auditing and for `--resume` after a timeout. No parsed JSON or per-pull metadata files are written.

---

## How the skill works

1. **Resolve the report.** Look up the slug in `bin/report_registry.py` to get the `GET_*` type, format hint, and any constraints (date caps, history limits, required `reportOptions`).
2. **Validate before calling Amazon.** If `--days 90` is passed for a 30-day-capped report, fail fast with a clear error (and offer `--chunk` to auto-split). If `--start` predates the report's history, fail fast.
3. **Create the report.** `POST /reports/2021-06-30/reports` with the registry's `report_options` baked in. Capture the `reportId` and persist it to `.pending/` immediately so timeouts are recoverable.
4. **Poll.** Every 15s, `GET /reports/2021-06-30/reports/{reportId}` until status is `DONE`. `FATAL` / `CANCELLED` exit non-zero with the cause; timeout (default 30 min) exits with the reportId for `--resume`.
5. **Download the document.** `GET /reports/2021-06-30/documents/{documentId}` returns a pre-signed S3 URL and an optional `compressionAlgorithm: GZIP`. Download, gunzip if needed.
6. **Write the file.** Atomic write of the report to the user's chosen output folder. Append a record to `report-log.jsonl` with status, byte counts, IDs, and errors. Delete the `.pending/` marker on success.

---

## File layout

```
.claude/skills/amazon-pull-report/
├── SKILL.md             # this file
├── SETUP.md             # non-technical onboarding (15-min path)
├── README.md            # CLI reference, troubleshooting, report caps
├── .env.example         # credential template
├── requirements.txt     # `requests` (also auto-installed via uv)
├── setup.sh             # one-command bootstrap (macOS / Linux)
├── setup.ps1            # one-command bootstrap (Windows)
├── bin/
│   ├── sp_api_client.py    # LWA auth + retries + throttling
│   ├── report_registry.py  # friendly slug → SP-API metadata
│   ├── pull_report.py      # generic create/poll/fetch/parse
│   └── run.py              # argparse CLI (PEP 723 inline-deps header)
└── config/
    └── defaults.json       # poll interval, max wait, default region
```

The skill is fully self-contained: the only external requirements are `uv` (or any Python 3.9+) and a valid set of SP-API credentials. There are no imports from outside this folder.

---

## Reports registered in v0.7

| Slug | What it is | Date caps |
|---|---|---|
| `removal-recommendations` | Items Amazon recommends for removal | none (snapshot) |
| `removal-orders` | Removal orders you've placed | — |
| `removal-shipments` | Per-shipment detail for removal orders | — |
| `ledger-summary` | Aggregated inventory ledger (DAILY / COUNTRY) | — |
| `ledger-detail` | Per-event inventory movements | 18-month history |
| `returns-fba` | FBA customer returns | — |
| `returns-mfn-prime` | MFN Prime returns (CSV) | 60-day max range |
| `returns-mfn-all` | All MFN returns by return date | — |
| `orders-by-order-date` | All orders by purchase date | 30-day max range |
| `orders-by-last-update` | All orders by last-modified date | 30-day max range |
| `sales-and-traffic` | Sales & traffic by child ASIN, daily | 2-year history |
| `settlement-v2` | Settlement reports v2 (payouts, fees) | — |
| `manage-fba-inventory` | Current FBA inventory snapshot (Manage FBA Inventory) | none (snapshot) |

For anything not listed, use `--report-type GET_FOO --format tsv` (or `csv`/`json`/`xml`).

---

## Common flags

| Flag | Purpose |
|---|---|
| `--report SLUG` | Friendly report name from the registry |
| `--report-type GET_*` | Raw report type for unaliased reports |
| `--days N` | UI-parity rolling window: N full prior days (PT) + today's partial day. Equivalent to `--preset last-N-days`. |
| `--preset NAME` | US/Pacific. Closed past windows (`yesterday`, `last-week`, `last-month`) end at midnight PT. Rolling windows (`today`, `this-week`, `this-month`, `mtd`, `ytd`, `last-7-days`, `last-30-days`, `last-90-days`) extend through "now" to match Seller Central UI exactly. |
| `--start DATE --end DATE` | Explicit date range. Bare YYYY-MM-DD is interpreted as Pacific midnight; full ISO datetimes with offset are taken as-is |
| `--report-options k=v` | Repeatable. Adds entries to `reportOptions` |
| `--format tsv\|csv\|json\|xml` | Required when using `--report-type` |
| `--resume REPORT_ID` | Pick up after a poll timeout (reads `.pending/{reportId}.json`) |
| `--chunk` | Auto-split when range exceeds the per-report cap |
| `--output-dir DIR` | Override the saved preference for this run |
| `--user-format csv\|txt` | Override the saved preference for this run |
| `--reset-preferences` | Re-prompt for format and output location on next run |
| `--max-wait SECONDS` | Poll deadline (default 1800 = 30 min) |
| `--poll-interval SECONDS` | Seconds between status polls (default 15) |
| `--list` | Show all registered slugs and constraints |

---

## Compliance note

Amazon's Reports API documentation advises against keeping unencrypted report content on disk. The skill writes the report file for usability, since downstream analysis is what sellers actually need. If your environment requires encrypted-at-rest output, configure FileVault (macOS) / BitLocker (Windows) / dm-crypt (Linux) on the volume holding your output folder, and protect `report-log.jsonl` similarly — it contains sales metadata (report IDs, byte counts, date ranges).

If your output folder lives inside a git repo, add it (and `.pending/` + `report-log.jsonl`) to `.gitignore` — these all contain or reference sensitive sales data.

---

## Reference

- [SP-API Reports API v2021-06-30](https://developer-docs.amazon.com/sp-api/docs/reports-api-v2021-06-30-reference)
- [Report type values index](https://developer-docs.amazon.com/sp-api/docs/report-type-values)
- [LWA authorization](https://developer-docs.amazon.com/sp-api/docs/authorizing-selling-partner-api-applications)
- [Marketplace IDs](https://developer-docs.amazon.com/sp-api/docs/marketplace-ids)
