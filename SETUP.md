# Setup guide — amazon-pull-report

If you've never used SP-API before and don't have Python installed: this is the right page. ~15 minutes.

If you already have a working SP-API setup and Python on your machine: skip to the [README](README.md).

---

## What this skill does

Instead of clicking through Seller Central → Reports → Inventory → Date range → Request → Wait → Download → Unzip, you run one command:

```
uv run bin/run.py --report ledger-detail --days 30
```

Amazon's API does the same thing the website does. The skill just talks to the API for you and saves the file to the folder you pick on first run (Documents, Downloads, or anywhere else).

---

## Before you start

Have all of these ready:

- [ ] An Amazon Seller Central account (you log into sellercentral.amazon.com).
- [ ] A Mac, Windows, or Linux computer.
- [ ] About 15-20 minutes (most of it is Amazon's own setup forms).

---

## Step 1 — Install the tools (one command)

You don't need to install Python yourself. The setup script handles everything.

### macOS or Linux

Open Terminal, then:

```bash
cd .claude/skills/amazon-pull-report
bash setup.sh
```

### Windows

Open PowerShell, then:

```powershell
cd .claude\skills\amazon-pull-report
.\setup.ps1
```

You should see something like:

```
amazon-pull-report setup
========================

Installing uv (a tiny tool that manages Python for you)...
✓ uv installed (uv 0.5.0)

Installing Python and dependencies (one-time, ~30 seconds)...
✓ Python and 'requests' ready

Setup complete!
```

If you see "uv installed but not yet on your PATH", close the terminal, open a fresh one, and re-run the command. PATH changes need a new shell to take effect.

---

## Step 2 — Get your Amazon SP-API credentials

This is the part you have to do by hand on Seller Central. You'll end up with four values you'll paste into a file in Step 3.

### 2a. Open the Develop Apps page

Go to: **Seller Central → Apps & Services → Develop Apps**.

Direct link: https://sellercentral.amazon.com/developer/register

If it's your first time here, Amazon will ask you to register as a developer (a one-time form: name, email, basically asking "are you the seller or building this for someone else?"). Pick "I'm the seller" if you're using this for your own account.

### 2b. Create a new app

Click **"Add new app client"**.

Fill in:
- **App name:** anything (e.g. `My Reports Puller`).
- **API type:** SP-API.
- **IAM ARN:** Amazon needs an IAM ARN here. If you don't already have one, follow Amazon's guide at https://developer-docs.amazon.com/sp-api/docs/creating-and-configuring-iam-policies-and-entities — a minimal read-only IAM role is fine for this skill.

### 2c. Pick API roles

Amazon will show a list of "roles" — these are permissions for what the app can read. Check at minimum:

- **Inventory and Order Tracking** — covers FBA inventory, returns, removals, ledger.
- **Pricing** — only if you also want pricing data.

You can edit these later if you need more. Don't worry about the long list of roles you're not using.

### 2d. Self-authorize the app

After the app is created, find it in your app list. Click the dropdown next to your app's status and pick **"Authorize"** (sometimes labeled **"Generate refresh token"** depending on Seller Central version). Amazon will show you a consent screen listing the API roles you picked in 2c — review and confirm.

When done, **a Refresh Token appears on screen**. It looks like:

```
Atzr|IwEBIA-very-long-string-of-characters...
```

⚠️ **The Refresh Token is shown ONCE on this screen. Copy it RIGHT NOW** before you click anything else. Paste it into a password manager, sticky note, or temp file. If you close this page or navigate away without saving, the token is gone and you'll have to revoke and re-authorize the app to get a new one.

**Where people get stuck here:**
- The "Authorize" button is hidden behind a status dropdown on the app row, not on the app's detail page.
- Some Seller Central regions show the refresh token only inside a modal popup that doesn't persist if you close it.
- If you don't see a refresh token after authorizing, check the Develop Apps page — your app may need draft → live status approval first (rare, mostly affects new developer accounts).

### 2e. Copy your LWA Client ID and Secret

Back on the app's page, you'll see two more values:

- **LWA Client ID** — looks like `amzn1.application-oa2-client.aaaaaaaa…`
- **LWA Client Secret** — a long hex string (treat like a password).

Copy both of these.

### 2f. Note your Marketplace ID

You also need to know which marketplace you sell in. The most common ones:

| Marketplace | ID | Region |
|---|---|---|
| US | `ATVPDKIKX0DER` | NA |
| Canada | `A2EUQ1WTGCTBG2` | NA |
| Mexico | `A1AM78C64UM0Y8` | NA |
| UK | `A1F83G8C2ARO7P` | EU |
| Germany | `A1PA6795UKMFR9` | EU |
| France | `A13V1IB3VIYZZH` | EU |
| Italy | `APJ6JRA9NG5V4` | EU |
| Spain | `A1RKKUPIHCS9HS` | EU |
| Japan | `A1VC38T7YXB528` | FE |
| Australia | `A39IBJ37TRP1C6` | FE |

Full list: https://developer-docs.amazon.com/sp-api/docs/marketplace-ids

---

## Step 3 — Save your credentials

The skill looks for `.env` in three places, in this order:

1. **Your project root** (recommended) — same place your `package.json` / `pyproject.toml` lives. The skill walks up from the directory you ran the command in until it finds one.
2. **`~/.config/amazon-pull-report/.env`** — user-level, shared across all projects on your machine. Use this if you want one set of credentials regardless of which project you're in.
3. **The skill folder itself** — works but discouraged: keep credentials out of code that might get distributed or copied.

The `setup.sh` / `setup.ps1` script already created a template `.env` at your project root for you (or skipped if one already exists somewhere the skill checks). If you want to use the user-level path instead, run:

```bash
# macOS / Linux
mkdir -p ~/.config/amazon-pull-report
cp .env.example ~/.config/amazon-pull-report/.env
chmod 600 ~/.config/amazon-pull-report/.env
```

```powershell
# Windows
New-Item -ItemType Directory -Force "$env:USERPROFILE\.config\amazon-pull-report"
Copy-Item .env.example "$env:USERPROFILE\.config\amazon-pull-report\.env"
```

Open whichever `.env` you created in any text editor (TextEdit, Notepad, VS Code, anything). It looks like this:

```
LWA_CLIENT_ID=
LWA_CLIENT_SECRET=
SP_API_REFRESH_TOKEN=
SP_API_MARKETPLACE_ID=ATVPDKIKX0DER
SP_API_REGION=NA
```

Paste each value after the `=` (no spaces, no quotes). Example:

```
LWA_CLIENT_ID=amzn1.application-oa2-client.abcd1234efgh5678
LWA_CLIENT_SECRET=a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0
SP_API_REFRESH_TOKEN=Atzr|IwEBIA-this-is-the-long-token-from-step-2d
SP_API_MARKETPLACE_ID=ATVPDKIKX0DER
SP_API_REGION=NA
```

Save and close.

⚠️ **Credential security — read this before continuing.**

Treat your `.env` file like a password. The four values in it can read every report Amazon has on your business: orders, payouts, customer info, fees, inventory.

- **Never commit `.env` to git.** Add to `.gitignore`:
  ```
  .env
  reports/
  .pending/
  ```
- **Never paste your `.env` contents into a chat, screenshot, Slack, email, or anywhere semi-public** — including AI assistants. If you need to share a config sample, use `.env.example` (the empty template) instead.
- **Lock down the file permissions** so other accounts on the machine can't read it:
  ```bash
  chmod 600 .env       # macOS / Linux only
  ```
  On Windows, right-click `.env` → Properties → Security → restrict to your user.
- **If a credential ever leaks** (you accidentally pushed `.env`, pasted it in a screenshot, suspect a teammate has it):
  1. Go back to Develop Apps in Seller Central.
  2. Click your app → **Rotate LWA credentials** (this gives you a fresh client secret).
  3. **Revoke the old refresh token** by un-authorizing and re-authorizing the app (this invalidates any token in the wild).
  4. Update your `.env` with the new values.
- **Rotate the LWA client secret every ~6 months** as a baseline hygiene practice, even if nothing seems wrong.

---

## Which slug replaces which Seller Central report?

When you used to download these manually, here's what to type instead. Use these exact slugs with `--report SLUG`:

| What you used to click in Seller Central | Skill slug |
|---|---|
| **Reports → Fulfillment → Customer Returns** (FBA) | `returns-fba` |
| **Reports → Fulfillment → MFN Returns** (Prime) | `returns-mfn-prime` |
| **Reports → Fulfillment → All Returns by Return Date** | `returns-mfn-all` |
| **Reports → Fulfillment → Removal Order Detail** | `removal-orders` |
| **Reports → Fulfillment → Removal Shipment Detail** | `removal-shipments` |
| **Reports → Fulfillment → Recommended Removal** | `removal-recommendations` |
| **Reports → Fulfillment → Inventory Ledger (Summary view)** | `ledger-summary` |
| **Reports → Fulfillment → Inventory Ledger (Detail view)** | `ledger-detail` |
| **Reports → Fulfillment → Manage FBA Inventory** | `manage-fba-inventory` |
| **Orders → Order Reports → All Orders by Order Date** | `orders-by-order-date` |
| **Orders → Order Reports → All Orders by Last Update** | `orders-by-last-update` |
| **Brand Analytics / Business Reports → Sales and Traffic by Child ASIN** | `sales-and-traffic` |
| **Reports → Payments → Statement view** (V2 settlement) | `settlement-v2` |

Run `uv run bin/run.py --list` to see every registered report along with date constraints (which ones cap at 30 days, which have an 18-month history limit, etc.).

If you don't see your report here, it might still be supported via the raw escape hatch:

```bash
uv run bin/run.py --report-type GET_FBA_INVENTORY_AGED_DATA --format tsv --days 30
```

The full list of GET_* report type codes Amazon supports:
https://developer-docs.amazon.com/sp-api/docs/report-type-values

---

## Step 4 — Run your first report

```bash
uv run bin/run.py --report orders-by-order-date --days 7
```

**On the very first run, the skill (when launched through Claude) asks you two quick questions:**
1. Which file format do you prefer — `.csv` (recommended, opens in Excel/Numbers) or `.txt` (Amazon's flat-file format)?
2. Where should reports be saved — Documents folder (recommended), Downloads folder, or a custom path?

Your answers are saved to `config/preferences.json` so you're only asked once. To change them later, delete that file and the next run will re-prompt.

You should see something like:

```
Pulling orders-by-order-date (GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL)
  data range: 2026-04-28T07:00:00Z → 2026-05-05T07:00:00Z
  reportId: 50028019xyz... (created in 0.4s, persisted to .pending/)
  status: IN_QUEUE (waited 0s)
  status: IN_PROGRESS (waited 15s)
  status: DONE (waited 38s)
  polled DONE in 38s
  document: 412.7 KB (decompressed from GZIP)
  parsed: 312 rows

Saved to /Users/<you>/Documents/Amazon Reports/
  orders-by-order-date__last-7-days__pulled-2026-05-04-153012-123Z.csv
```

The skill writes ONE file per pull (the report itself), into the folder you picked on first run. The pull is also recorded in `report-log.jsonl` inside the skill folder (skill version, report id, byte counts, success/failure status — useful for audit and `--resume`). Open the file in Excel/Numbers to verify it looks right.

If you see something different, jump to **Troubleshooting** below.

---

## Troubleshooting

### `command not found: uv`

The setup script didn't finish, or PATH wasn't updated. Open a **new** terminal window and re-run `bash setup.sh` (or `.\setup.ps1`).

### `error: Missing required env var(s): LWA_CLIENT_ID, ...`

The skill couldn't find your credentials. It looks in three places (in this order):
1. `<your-project-root>/.env` (walks up from CWD until found)
2. `~/.config/amazon-pull-report/.env`
3. The skill folder itself (legacy fallback)

Check:
- Is the file actually named `.env` (with the leading dot), not `.env.txt`?
- Is it in one of the three locations above?
- Are the values pasted in correctly — no quotes, no extra spaces around the `=`?

You can also export them in your shell as a quick test:

```bash
export LWA_CLIENT_ID=...
export LWA_CLIENT_SECRET=...
export SP_API_REFRESH_TOKEN=...
export SP_API_MARKETPLACE_ID=ATVPDKIKX0DER
uv run bin/run.py --report orders-by-order-date --days 7
```

### `401 Unauthorized` from Amazon

Your refresh token is wrong, expired, or for a different app. Redo Step 2d (re-authorize the app and grab a fresh refresh token). A refresh token can also be revoked silently if Amazon rotates the underlying app or detects suspicious activity — re-authorize and you're back in business.

### `403 Unauthorized` / `Access denied` / `Insufficient permissions`

Your app is authorized, but the API role you picked in 2c doesn't cover the report you're trying to pull. Most common cases:
- Pulling FBA returns or ledger but only chose the `Pricing` role → enable **Inventory and Order Tracking**.
- Pulling settlement / payment reports → you need the **Finance and Accounting** role (rename varies by Seller Central region).
- Pulling Brand Analytics / sales-and-traffic → you need **Brand Analytics**, and your seller account must actually have brand registry.

Fix: go back to your app in Develop Apps, edit roles, save, then re-authorize (Step 2d) so the new permissions stick.

### `FATAL` status from Amazon

The most common causes:
- **Date range too large.** Some reports cap at 30 or 60 days per request. The skill checks this for known reports, but the raw `--report-type` escape hatch doesn't. Run with `--days 30` and try again, or pass `--chunk` to auto-split.
- **Date range too far back.** `ledger-detail` only goes 18 months back; `sales-and-traffic` only 2 years.
- **Missing required reportOptions** for that report type. Some reports (especially Vendor reports) require fields like `reportPeriod` or `sellingProgram`. Pass them with repeated `--report-options key=value`.
- **Report not available for your account type.** Vendor-only reports requested from a Seller Central account (or vice versa) come back FATAL with no helpful message. Confirm the report type matches your account type at https://developer-docs.amazon.com/sp-api/docs/report-type-values.

### `CANCELLED` status

You (or another tool using the same app) cancelled the report through Seller Central or via DELETE /reports/{reportId}. The skill doesn't cancel reports, so this is something external. Just re-run.

### `DONE` but the file looks empty / has only headers

This is usually correct — Amazon really has no data for that date range. Common cases:
- Asked for `last-week`'s removals on a seller who hasn't done any removals.
- Asked for FBA returns on an MFN-only seller.
- Asked for sales-and-traffic the day after enabling Brand Analytics (data backfills with a 24–48h delay).

Try a wider date range first to confirm the API + permissions work, then narrow back down.

### `DONE but has no reportDocumentId`

Rare. Amazon marked the report DONE but didn't attach a document — usually a transient bug on their side. Just re-run; if it persists, open Develop Apps and confirm your app status hasn't been suspended.

### `429 Too Many Requests` / throttled

The skill retries automatically with backoff (up to 6 times). If you're seeing it constantly, you're either:
- Running multiple skill invocations in parallel against the same SP-API app (don't — Amazon throttles per refresh token).
- Hitting Amazon's per-account create-report rate limit (one createReport per 60s for some reports). Just wait a minute and retry.

### `Report did not complete within 1800s`

Some reports legitimately take >30 minutes (large historical pulls, sales-and-traffic with WEEK granularity). The skill saves the `reportId` to `.pending/`. Resume with:

```bash
uv run bin/run.py --resume <reportId-printed-on-screen>
```

You can also pass a higher deadline upfront: `--max-wait 3600` for an hour.

### Numbers don't match what Seller Central shows

99% of the time this is a timezone issue. Seller Central uses **US/Pacific** for date boundaries. The skill anchors all date math to Pacific by default — but if you pass a full ISO datetime with a different offset (e.g. `--start 2026-04-01T00:00:00Z`), you'll get UTC midnight instead of Pacific midnight, and the totals will be off by 7–8 hours on each end.

Fix: use bare dates (`--start 2026-04-01`) or `--preset` instead of full ISO datetimes. They're treated as Pacific midnight automatically.

### Something else

Re-run with the default verbose output (it goes to stderr — pipe with `2>&1 | tee log.txt` to capture it). The skill also writes every successful and failed pull to `report-log.jsonl` in the skill folder, including the raw error message from Amazon.

---

## What the skill actually does on your machine

For the cautious seller:

- **Pulls reports only.** The skill cannot create, edit, or delete listings, prices, inventory, orders, or payouts in your Seller Central account. It calls only the SP-API Reports endpoints (create report, poll status, fetch the document URL, download from S3). The roles you picked in Step 2c determine which report types you can pull.
- **What gets sent to Amazon:** your four credentials (LWA Client ID/Secret + Refresh Token to api.amazon.com, plus access tokens to sellingpartnerapi-*.amazon.com), the report type, marketplace ID, date range, and any `reportOptions` for the request you're making. Nothing else leaves your computer.
- **What gets written locally:** the report file (in the folder you picked on first run), a pull marker in `.pending/{reportId}.json` while the report runs (deleted on success), and one-line audit records in `report-log.jsonl` inside the skill folder.
- **No third-party services.** The skill imports only the Python `requests` library. No analytics, no telemetry, no cloud storage, no OpenAI/Anthropic/anything else.

---

## Next steps

- See [`README.md`](README.md) for the full CLI reference, every report you can pull, and the per-report date constraints.
- Add new reports by editing [`bin/report_registry.py`](bin/report_registry.py) — one entry per report.
