# amazon-pull-report

Pull Amazon Seller Central reports via SP-API. One command per report. Output is a structured folder with the original file, a parsed JSON, and a metadata sidecar.

**New here?** Read [SETUP.md](SETUP.md) first (15-min onboarding for non-technical users).

---

## Quick start

```bash
cd .claude/skills/amazon-pull-report

# List every report you can pull
uv run bin/run.py --list

# Pull a report
uv run bin/run.py --report orders-by-order-date --days 7
uv run bin/run.py --report ledger-detail --days 7
uv run bin/run.py --report returns-fba --days 30
```

Output lands at `./reports/{slug}/{utc-timestamp}/{raw,parsed,metadata}`.

---

## CLI reference

```
uv run bin/run.py [OPTIONS]
```

### Picking the report

| Flag | Description |
|---|---|
| `--report SLUG` | A friendly slug from the registry (see `--list`). |
| `--report-type GET_*` | Raw report type for any report not aliased in the registry. |
| `--list` | Print every registered slug, the underlying `GET_*` type, and per-report constraints. |
| `--resume REPORT_ID` | Pick up after a poll timeout. Reads `.pending/{REPORT_ID}.json`. |

### Date range

| Flag | Description |
|---|---|
| `--days N` | Last N days, ending now (UTC). Mutually exclusive with `--start`/`--end`. |
| `--start DATE` | ISO date (`2026-04-01`) or full ISO datetime. UTC if no offset. |
| `--end DATE` | Same format. Defaults to now. |
| `--chunk` | If `--days` exceeds the report's `max_request_days`, split into multiple sequential pulls. |

### Format and options (raw escape hatch)

| Flag | Description |
|---|---|
| `--format {tsv,csv,json,xml}` | Required when using `--report-type`. Tells the parser how to read the file. |
| `--report-options KEY=VALUE` | Repeatable. Adds entries to the createReport `reportOptions`. |

### Output

| Flag | Description |
|---|---|
| `--output-dir DIR` | Where to write report folders (default `./reports`). |
| `--no-raw` | Skip writing the raw file. Keep only `parsed.json` + `metadata.json`. |

### Polling

| Flag | Description |
|---|---|
| `--max-wait SECONDS` | How long to wait for a report to finish (default 1800 = 30 min). |
| `--poll-interval SECONDS` | How often to ping `getReport` (default 15). |

---

## Registered reports

Run `uv run bin/run.py --list` for the live list. v0.1 includes:

| Slug | SP-API report type | Constraints |
|---|---|---|
| `removal-recommendations` | `GET_FBA_RECOMMENDED_REMOVAL_DATA` | snapshot — no date range |
| `removal-orders` | `GET_FBA_FULFILLMENT_REMOVAL_ORDER_DETAIL_DATA` | — |
| `removal-shipments` | `GET_FBA_FULFILLMENT_REMOVAL_SHIPMENT_DETAIL_DATA` | — |
| `ledger-summary` | `GET_LEDGER_SUMMARY_VIEW_DATA` | sends DAILY/COUNTRY by default |
| `ledger-detail` | `GET_LEDGER_DETAIL_VIEW_DATA` | 18-month history cap |
| `returns-fba` | `GET_FBA_FULFILLMENT_CUSTOMER_RETURNS_DATA` | — |
| `returns-mfn-prime` | `GET_CSV_MFN_PRIME_RETURNS_REPORT` | 60-day max range |
| `returns-mfn-all` | `GET_FLAT_FILE_RETURNS_DATA_BY_RETURN_DATE` | — |
| `orders-by-order-date` | `GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL` | 30-day max range |
| `orders-by-last-update` | `GET_FLAT_FILE_ALL_ORDERS_DATA_BY_LAST_UPDATE_GENERAL` | 30-day max range |
| `sales-and-traffic` | `GET_SALES_AND_TRAFFIC_REPORT` | 2-year history; sends CHILD/DAY by default |
| `settlement-v2` | `GET_V2_SETTLEMENT_REPORT_DATA_FLAT_FILE_V2` | — |

Adding a new report = appending one entry to [`bin/report_registry.py`](bin/report_registry.py).

---

## Output folder

By default reports save to `~/Documents/Amazon Reports/` (Mac/Linux) or `C:\Users\<you>\Documents\Amazon Reports\` (Windows). On first run, the skill asks where you'd like reports saved (Documents, Downloads, or a custom folder) and what format you prefer (.csv or .txt). Choices are remembered in `config/preferences.json`.

Every successful pull creates a folder named after the report and a sub-folder named after the time of the pull (local time, human-readable):

```
~/Documents/Amazon Reports/
└── Orders by Order Date/
    └── 2026-05-03 at 4-21pm/
        ├── Orders by Order Date.csv     # double-click → opens in Excel
        ├── Orders by Order Date.json    # structured copy for tools
        └── metadata.json                # reportId, document_id, params, timing, status
```

If you chose `.txt` on first run, the main file is `.txt` instead of `.csv` (Amazon's raw "flat file" download format, byte-identical to Seller Central's `.txt` download).

`.csv` output for tab-delimited reports is also byte-identical to Seller Central's CSV download: every non-empty field quoted, empty trailing fields bare, inner `"` chars escaped as `""`, CRLF line endings.

To change format or folder later, delete `config/preferences.json` and the next run will ask again. Or use `--user-format <csv|txt>` and `--output-dir <path>` flags to override per-pull.

`metadata.json` is the source of truth for what was requested, what came back, and how long it took:

```json
{
  "skill_version": "0.1.0",
  "report_slug": "orders-by-order-date",
  "report_type": "GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL",
  "report_id": "50028019xyz",
  "document_id": "amzn1.spdoc.1.4.na...",
  "marketplace_id": "ATVPDKIKX0DER",
  "region": "NA",
  "data_start": "2026-04-25T00:00:00+00:00",
  "data_end": "2026-05-02T00:00:00+00:00",
  "report_options": null,
  "format": "tsv",
  "compressed": true,
  "status": "DONE",
  "created_at": "2026-05-02T14:31:35+00:00",
  "finished_at": "2026-05-02T14:32:13+00:00",
  "raw_bytes": 422620,
  "parsed_rows": 312
}
```

---

## Resuming after a timeout

Long-running reports (sales-and-traffic over a year, or any large historical pull) can take >30 minutes. If polling times out, the script exits non-zero with the `reportId` printed and a record persisted to `.pending/{reportId}.json`.

Resume with:
```bash
uv run bin/run.py --resume 50028019xyz...
```

The skill skips create+poll and goes straight to checking status, then downloading. Pending records are deleted on success.

---

## Per-report data range constraints

These are enforced offline before the skill makes any API call — saves you 30-60s of polling for a `FATAL`.

- **`orders-by-order-date` / `orders-by-last-update`** — Amazon caps each request at 30 days. Use `--chunk` to split a longer range into sequential pulls, or accept the limit.
- **`returns-mfn-prime`** — 60-day max per request.
- **`ledger-detail`** — Amazon only retains 18 months of detail. Older `--start` is rejected.
- **`sales-and-traffic`** — 2-year history limit. Granularity defaults to `CHILD` ASIN, `DAY` (overridable with `--report-options`).

For unknown reports pulled via `--report-type`, no caps are enforced — Amazon may return `FATAL` if the range is bad.

---

## Raw escape hatch (for unaliased reports)

```bash
# A report with no required options
uv run bin/run.py --report-type GET_FBA_INVENTORY_AGED_DATA --format tsv --days 30

# A report that needs reportOptions
uv run bin/run.py --report-type GET_VENDOR_FORECASTING_REPORT --format json \
    --report-options reportPeriod=WEEK \
    --report-options sellingProgram=RETAIL
```

Once you've used a raw report a few times, consider adding it to `bin/report_registry.py` so the skill knows its constraints.

---

## Troubleshooting

### `error: Missing required env var(s): ...`

Either you haven't created `.env` yet, or one of the four required values is missing. See [SETUP.md Step 3](SETUP.md#step-3--save-your-credentials).

### `error: Unknown report slug: 'foo'. Did you mean: ...?`

Typo in `--report`. Use the suggestions or run `--list`.

### `error: orders-by-order-date is capped at 30 days per request; pass --chunk to split`

Either pass a smaller `--days N` or add `--chunk` to auto-split.

### `error: --start 2024-01-01 is older than this report's history limit`

The report's `max_history_days` (e.g. 540 for `ledger-detail`) doesn't go back that far. Pick a more recent `--start`.

### `Report ... ended with status FATAL`

Amazon rejected the report. The error message includes its reasoning, but the most common causes are:
- Invalid date range for that specific report.
- Missing `reportOptions` (vendor reports especially).
- No data in the period requested (sometimes Amazon returns FATAL rather than empty).

A `metadata.json` is still written with `status: FATAL` for inspection.

### `Report ... did not complete within 1800s`

Use `--resume <reportId>`. The script printed the ID; it's also in `.pending/`.

### `parse failed (format=json): ...`

You used `--format json` but the report came back as something else (often XML or HTML error page). Try `--format tsv` or `--format xml`. For unaliased reports, the format guess is your responsibility.

---

## Compliance note

Amazon's docs warn against keeping unencrypted report content on disk. The skill writes report files locally for usability — sellers usually want to open the `.csv` or `.txt` in Excel.

`reports/` and `.pending/` should be in `.gitignore`. Both contain sensitive sales data.

---

## Adding a new report

Edit [`bin/report_registry.py`](bin/report_registry.py). Each entry is a dict:

```python
"my-new-report": {
    "type": "GET_MY_NEW_REPORT",
    "format": "tsv",                          # tsv | csv | json | xml
    "needs_date_range": True,                 # False for snapshots
    # optional:
    "report_options": {"foo": "BAR"},         # baked into createReport body
    "max_request_days": 30,                   # enforced offline
    "max_history_days": 540,                  # enforced offline
    "requires_rdt": False,                    # for restricted reports (not yet implemented)
    "description": "What this report contains.",
},
```

The skill picks it up immediately — no other code changes needed.

---

## What's NOT in scope

- Live API calls that aren't reports — use the FBA Inventory, Catalog, or Pricing APIs directly. This skill only wraps `/reports/2021-06-30/*`.
- Restricted reports requiring a Restricted Data Token (RDT) for PII — `requires_rdt` is in the schema but the RDT flow isn't implemented in v0.1.
- Schedule management (`createReportSchedule`, etc.) — out of scope. Use `cron` or your scheduler of choice to run this skill on a schedule.
- Analysis on top of the data — that's a separate skill (e.g. `amazon-restock` for inventory forecasting).

---

## Reference

- [Reports API v2021-06-30](https://developer-docs.amazon.com/sp-api/docs/reports-api-v2021-06-30-reference)
- [Report types index](https://developer-docs.amazon.com/sp-api/docs/report-type-values)
- [Reports API rate limits](https://developer-docs.amazon.com/sp-api/docs/reports-api-rate-limits)
- [LWA authorization](https://developer-docs.amazon.com/sp-api/docs/authorizing-selling-partner-api-applications)
- [Marketplace IDs](https://developer-docs.amazon.com/sp-api/docs/marketplace-ids)
