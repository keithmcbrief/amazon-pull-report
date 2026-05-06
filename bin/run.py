#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.9"
# dependencies = ["requests"]
# ///
"""amazon-pull-report — pull Amazon Seller Central reports via SP-API.

Run with `uv run bin/run.py …` from the skill folder.

Examples:
  uv run bin/run.py --list
  uv run bin/run.py --report orders-by-order-date --days 7
  uv run bin/run.py --report ledger-detail --start 2026-04-01 --end 2026-05-01
  uv run bin/run.py --report-type GET_FBA_INVENTORY_AGED_DATA --format tsv --days 30
  uv run bin/run.py --resume 50028019xyz...
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

# Ensure local imports resolve regardless of CWD.
SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT / "bin"))

from sp_api_client import SpApiClient, SpApiError  # noqa: E402
import pull_report  # noqa: E402
import preferences  # noqa: E402
import report_registry  # noqa: E402


SKILL_VERSION = "0.7.0"


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.list:
        return _cmd_list()

    # Resolve preferences (first-run prompt if needed, otherwise load).
    prefs = _resolve_preferences(args)

    _load_dotenv_if_present()

    if args.resume:
        return _cmd_resume(args, prefs)

    return _cmd_pull(args, parser, prefs)


def _resolve_preferences(args: argparse.Namespace) -> dict:
    """Load saved preferences, or prompt on first run.

    When invoked by Claude via the Skill tool, SKILL.md instructs Claude to call
    AskUserQuestion *before* invoking the script and pass `--user-format` /
    `--output-dir` flags. In that case, preferences.json may already be written
    by Claude — we just load it.

    When invoked directly from a terminal without Claude, we fall back to a CLI
    `input()` prompt the first time. Subsequent runs read the saved file silently.
    """
    if args.reset_preferences:
        try:
            preferences.PREFERENCES_PATH.unlink()
        except FileNotFoundError:
            pass

    saved = preferences.load()
    if saved is None:
        if sys.stdin.isatty() and not (args.user_format and args.output_dir):
            # Real terminal, no overrides → prompt and persist (user is committing).
            preferences.prompt_cli()
        elif args.user_format and args.output_dir:
            # Both flags explicit → caller (Claude or scripted) is committing.
            # Persist so subsequent runs can be silent.
            preferences.save(args.user_format, args.output_dir)
        else:
            # Non-interactive without explicit flags. Use in-memory defaults but
            # do NOT persist — silent persistence has surprised users in the
            # past. Warn loudly so the run doesn't silently land in an unexpected
            # folder.
            chosen_fmt = args.user_format or "csv"
            chosen_dir = args.output_dir or str(preferences.default_documents_dir())
            print(
                "warning: no preferences saved and not running in a terminal. "
                f"Using transient defaults format={chosen_fmt}, output_dir={chosen_dir} "
                f"(NOT persisted). Pass both --user-format and --output-dir to commit, "
                f"or run --reset-preferences in a terminal to set explicitly.",
                file=sys.stderr,
            )
            return {"format": chosen_fmt, "output_dir": chosen_dir}

    return preferences.get_or_default(args.user_format, args.output_dir)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="amazon-pull-report",
        description="Pull Amazon Seller Central reports via SP-API "
        "(replaces the manual Seller Central click-through workflow).",
    )

    # Mode selection
    p.add_argument(
        "--report",
        help="Friendly report slug (e.g. orders-by-order-date, ledger-detail). "
        "Use --list to see all aliases.",
    )
    p.add_argument(
        "--report-type",
        help="Raw GET_* report type for reports not in the registry.",
    )
    p.add_argument(
        "--resume",
        metavar="REPORT_ID",
        help="Resume a previously-created report (skips create+poll, fetches the document).",
    )
    p.add_argument(
        "--list",
        action="store_true",
        help="Print every registered report slug and its constraints, then exit.",
    )

    # Date range (mutually-exclusive sources)
    p.add_argument(
        "--days",
        type=int,
        help=(
            "UI-parity rolling window: N full prior calendar days (US/Pacific) "
            "plus today's partial day. Equivalent to --preset last-N-days, so "
            "output matches Seller Central's 'Last N Days' export at the same moment."
        ),
    )
    p.add_argument("--start", help="Data range start, ISO date (YYYY-MM-DD) or full ISO datetime.")
    p.add_argument("--end", help="Data range end, ISO date (default: now).")
    p.add_argument(
        "--preset",
        choices=(
            "today", "yesterday",
            "this-week", "last-week",
            "this-month", "last-month",
            "mtd", "ytd",
            "last-7-days", "last-30-days", "last-90-days",
        ),
        help=(
            "Convenience date range (US/Pacific). Closed past windows "
            "('yesterday', 'last-week', 'last-month') end at midnight PT. "
            "Rolling windows ('today', 'this-week', 'this-month', 'mtd', 'ytd', "
            "'last-7-days', 'last-30-days', 'last-90-days') extend through "
            "'now' so output matches Seller Central UI exactly."
        ),
    )

    # Format / options for --report-type fallback
    p.add_argument(
        "--format",
        choices=("tsv", "csv", "json", "xml"),
        help="Format hint when using --report-type. Required for non-TSV reports.",
    )
    p.add_argument(
        "--report-options",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Repeatable. Adds an entry to reportOptions (e.g. reportPeriod=WEEK).",
    )

    # Output controls
    p.add_argument(
        "--output-dir",
        default=None,
        help="Where to write report folders. Defaults to your saved preference, or ~/Documents/Amazon Reports/ on first run.",
    )
    p.add_argument(
        "--user-format",
        choices=("csv", "txt"),
        default=None,
        help="Output format for tab-delimited reports: csv (default) or txt (Amazon's flat-file convention).",
    )
    p.add_argument(
        "--reset-preferences",
        action="store_true",
        help="Re-prompt for format and output location, overwriting saved preferences.",
    )
    p.add_argument(
        "--chunk",
        action="store_true",
        help="If --days exceeds the report's max_request_days, split into multiple sequential pulls.",
    )

    # Polling
    p.add_argument(
        "--max-wait",
        type=int,
        default=1800,
        help="Seconds to wait for the report to finish (default 1800 = 30 min).",
    )
    p.add_argument(
        "--poll-interval",
        type=int,
        default=15,
        help="Seconds between polls (default 15).",
    )
    return p


# ----- Commands -----


def _cmd_list() -> int:
    rows: list[tuple[str, str, str]] = []
    for slug in report_registry.list_slugs():
        entry = report_registry.REPORTS[slug]
        constraints = []
        if not entry.get("needs_date_range"):
            constraints.append("no date range")
        if entry.get("max_request_days"):
            constraints.append(f"≤{entry['max_request_days']}d/request")
        if entry.get("max_history_days"):
            constraints.append(f"≤{entry['max_history_days']}d history")
        if entry.get("report_options"):
            constraints.append("has default options")
        rows.append((slug, entry["type"], ", ".join(constraints)))

    slug_w = max(len(r[0]) for r in rows)
    type_w = max(len(r[1]) for r in rows)
    print(f"{'slug'.ljust(slug_w)}  {'report type'.ljust(type_w)}  notes")
    print(f"{'-' * slug_w}  {'-' * type_w}  -----")
    for slug, rtype, notes in rows:
        print(f"{slug.ljust(slug_w)}  {rtype.ljust(type_w)}  {notes}")
    print()
    print(f"{len(rows)} reports registered. For unaliased reports, use --report-type GET_*.")
    return 0


def _cmd_pull(args: argparse.Namespace, parser: argparse.ArgumentParser, prefs: dict) -> int:
    if not args.report and not args.report_type:
        parser.error("must pass --report SLUG or --report-type GET_*")
    if args.report and args.report_type:
        parser.error("--report and --report-type are mutually exclusive")

    # Resolve report metadata
    if args.report:
        try:
            entry = dict(report_registry.get(args.report))
        except KeyError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        slug = args.report
    else:
        if not args.format:
            print(
                "error: --report-type requires --format (tsv|csv|json|xml)",
                file=sys.stderr,
            )
            return 2
        entry = {
            "type": args.report_type,
            "format": args.format,
            "needs_date_range": bool(args.days or args.start or args.end),
            "report_options": _parse_kv(args.report_options),
        }
        slug = args.report_type.lower().replace("_", "-").lstrip("get-")

    # Merge user-provided --report-options on top of registry defaults.
    user_opts = _parse_kv(args.report_options)
    if user_opts:
        merged = dict(entry.get("report_options") or {})
        merged.update(user_opts)
        entry["report_options"] = merged

    # Resolve date range.
    start_dt, end_dt = _resolve_range(args, entry, parser)
    range_token = _range_token(args, start_dt, end_dt, entry.get("needs_date_range", False))

    # Validate date range against per-report caps.
    error = _validate_range(entry, start_dt, end_dt, allow_chunk=args.chunk)
    if error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    chunks = _maybe_chunk(entry, start_dt, end_dt, args.chunk)

    # Build client.
    try:
        client = SpApiClient.from_env()
    except SpApiError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    marketplace_id = os.environ.get("SP_API_MARKETPLACE_ID")
    if not marketplace_id:
        print(
            "error: Missing required env var: SP_API_MARKETPLACE_ID. See SETUP.md.",
            file=sys.stderr,
        )
        return 2

    output_dir = Path(prefs["output_dir"]).expanduser()
    pending_dir = SKILL_ROOT / ".pending"
    user_format = prefs["format"]

    rc = 0
    for i, (chunk_start, chunk_end) in enumerate(chunks, start=1):
        if len(chunks) > 1:
            print(
                f"\n=== chunk {i}/{len(chunks)}: "
                f"{chunk_start.date()} → {chunk_end.date()} ===",
                file=sys.stderr,
            )
        chunk_token = (
            range_token
            if len(chunks) == 1
            else f"{chunk_start.strftime('%Y-%m-%d')}_to_{chunk_end.strftime('%Y-%m-%d')}"
        )
        rc = _do_one_pull(
            client=client,
            slug=slug,
            entry=entry,
            marketplace_id=marketplace_id,
            data_start=chunk_start if entry.get("needs_date_range") else None,
            data_end=chunk_end if entry.get("needs_date_range") else None,
            range_token=chunk_token,
            output_dir=output_dir,
            pending_dir=pending_dir,
            user_format=user_format,
            poll_interval=args.poll_interval,
            max_wait=args.max_wait,
        )
        if rc != 0:
            return rc
    return rc


def _cmd_resume(args: argparse.Namespace, prefs: dict) -> int:
    pending_dir = SKILL_ROOT / ".pending"
    try:
        record = pull_report.read_pending(pending_dir, args.resume)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    try:
        client = SpApiClient.from_env()
    except SpApiError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    print(
        f"Resuming {record['slug']} (reportId={args.resume})",
        file=sys.stderr,
    )
    return _continue_pull(
        client=client,
        report_id=args.resume,
        slug=record["slug"],
        entry=record["entry"],
        marketplace_id=record["marketplace_id"],
        data_start=_parse_iso(record.get("data_start")),
        data_end=_parse_iso(record.get("data_end")),
        range_token=record.get("range_token") or "snapshot",
        output_dir=Path(record.get("output_dir") or prefs["output_dir"]).expanduser(),
        pending_dir=pending_dir,
        user_format=record.get("user_format") or prefs["format"],
        poll_interval=args.poll_interval,
        max_wait=args.max_wait,
        created_at=record.get("created_at"),
    )


# ----- Pull primitives -----


def _do_one_pull(
    *,
    client: SpApiClient,
    slug: str,
    entry: dict[str, Any],
    marketplace_id: str,
    data_start: Optional[datetime],
    data_end: Optional[datetime],
    range_token: str,
    output_dir: Path,
    pending_dir: Path,
    user_format: str,
    poll_interval: int,
    max_wait: int,
) -> int:
    print(f"Pulling {slug} ({entry['type']})", file=sys.stderr)
    if data_start and data_end:
        print(
            f"  data range: {pull_report._iso_z(data_start)} → {pull_report._iso_z(data_end)}",
            file=sys.stderr,
        )

    t0 = time.time()
    try:
        report_id = pull_report.create_report(
            client=client,
            report_type=entry["type"],
            marketplace_id=marketplace_id,
            data_start=data_start,
            data_end=data_end,
            report_options=entry.get("report_options"),
        )
    except SpApiError as e:
        print(f"error: createReport failed: {e}", file=sys.stderr)
        return 1
    create_dur = time.time() - t0

    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    pending_record = {
        "slug": slug,
        "entry": entry,
        "marketplace_id": marketplace_id,
        "region": client.region,
        "data_start": data_start.isoformat() if data_start else None,
        "data_end": data_end.isoformat() if data_end else None,
        "range_token": range_token,
        "output_dir": str(output_dir),
        "user_format": user_format,
        "created_at": created_at,
    }
    pull_report.write_pending(pending_dir, report_id, pending_record)

    print(
        f"  reportId: {report_id} (created in {create_dur:.1f}s, persisted to {pending_dir}/)",
        file=sys.stderr,
    )

    return _continue_pull(
        client=client,
        report_id=report_id,
        slug=slug,
        entry=entry,
        marketplace_id=marketplace_id,
        data_start=data_start,
        data_end=data_end,
        range_token=range_token,
        output_dir=output_dir,
        pending_dir=pending_dir,
        user_format=user_format,
        poll_interval=poll_interval,
        max_wait=max_wait,
        created_at=created_at,
    )


def _continue_pull(
    *,
    client: SpApiClient,
    report_id: str,
    slug: str,
    entry: dict[str, Any],
    marketplace_id: str,
    data_start: Optional[datetime],
    data_end: Optional[datetime],
    range_token: str,
    output_dir: Path,
    pending_dir: Path,
    user_format: str,
    poll_interval: int,
    max_wait: int,
    created_at: Optional[str] = None,
) -> int:
    poll_start = time.time()
    try:
        document_id = pull_report.poll_until_done(
            client=client,
            report_id=report_id,
            poll_interval=poll_interval,
            max_wait=max_wait,
        )
    except pull_report.ReportFatalError as e:
        print(f"error: {e}", file=sys.stderr)
        _write_failure_metadata(
            output_dir, slug, report_id, entry, marketplace_id, client.region,
            data_start, data_end, "FATAL", str(e), created_at,
        )
        return 1
    except pull_report.ReportTimeoutError as e:
        print(f"timeout: {e}", file=sys.stderr)
        _write_failure_metadata(
            output_dir, slug, report_id, entry, marketplace_id, client.region,
            data_start, data_end, "TIMEOUT", str(e), created_at,
        )
        return 1

    print(f"  polled DONE in {time.time() - poll_start:.0f}s", file=sys.stderr)

    # Document fetch + download — wrap so a transient failure surfaces clearly
    # and gets logged. Pending marker is preserved so user can --resume.
    try:
        doc_meta = pull_report.get_document_metadata(client, document_id)
        url = doc_meta.get("url")
        if not url:
            raise SpApiError(f"documents/{document_id} returned no url")
        compression = doc_meta.get("compressionAlgorithm")
        if compression is None:
            compressed = False
        elif str(compression).upper() == "GZIP":
            compressed = True
        else:
            raise SpApiError(
                f"unknown compressionAlgorithm '{compression}' on documents/{document_id} — "
                f"this client only supports GZIP. Amazon may have added a new algorithm."
            )
        raw = pull_report.download_document(url, compressed=compressed)
    except (SpApiError, OSError) as e:
        print(f"error: document fetch/download failed: {e}", file=sys.stderr)
        _write_failure_metadata(
            output_dir, slug, report_id, entry, marketplace_id, client.region,
            data_start, data_end, "DOWNLOAD_FAILED", str(e), created_at,
        )
        return 1
    except Exception as e:
        # requests/network/gzip failures — keep pending marker for retry.
        print(f"error: document fetch/download failed: {type(e).__name__}: {e}", file=sys.stderr)
        _write_failure_metadata(
            output_dir, slug, report_id, entry, marketplace_id, client.region,
            data_start, data_end, "DOWNLOAD_FAILED", str(e), created_at,
        )
        return 1

    raw_size = len(raw)
    print(
        f"  document: {raw_size / 1024:.1f} KB"
        + (" (decompressed from GZIP)" if compressed else ""),
        file=sys.stderr,
    )

    fmt = entry["format"]

    try:
        parsed = pull_report.parse(raw, fmt)
        parsed_rows = len(parsed) if isinstance(parsed, list) else None
    except (json.JSONDecodeError, ValueError) as e:
        # Bad parse means the file is suspect. Still write it (the bytes are real),
        # but flag it loudly so the user knows.
        parsed_rows = None
        print(f"warning: could not parse downloaded report ({type(e).__name__}: {e}). "
              f"File will be written but row count unavailable.", file=sys.stderr)

    if parsed_rows is not None:
        print(f"  parsed: {parsed_rows} rows", file=sys.stderr)

    finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # Use UTC + microseconds so two pulls of the same report in the same second
    # never collide and the timestamp is timezone-unambiguous.
    pull_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S-%f")[:-3] + "Z"
    base_name = f"{slug}__{range_token}__pulled-{pull_ts}"

    try:
        main_path = pull_report.write_output(
            out_dir=output_dir,
            fmt=fmt,
            raw=raw,
            base_name=base_name,
            user_format=user_format,
        )
    except OSError as e:
        print(f"error: writing output failed: {e}", file=sys.stderr)
        _write_failure_metadata(
            output_dir, slug, report_id, entry, marketplace_id, client.region,
            data_start, data_end, "WRITE_FAILED", str(e), created_at,
        )
        return 1

    # Log first, THEN delete the pending marker — so a log-write failure does
    # not orphan resume metadata. If both succeed, user has audit + clean state.
    try:
        pull_report.append_log(SKILL_ROOT, {
            "skill_version": SKILL_VERSION,
            "report_slug": slug,
            "report_display_name": report_registry.display_name(slug),
            "report_type": entry["type"],
            "report_id": report_id,
            "document_id": document_id,
            "marketplace_id": marketplace_id,
            "region": client.region,
            "range_token": range_token,
            "data_start": data_start.isoformat() if data_start else None,
            "data_end": data_end.isoformat() if data_end else None,
            "report_options": entry.get("report_options"),
            "source_format": fmt,
            "user_format": user_format,
            "compressed": compressed,
            "status": "DONE",
            "created_at": created_at,
            "finished_at_utc": finished_at,
            "raw_bytes": raw_size,
            "parsed_rows": parsed_rows,
            "output_file": str(main_path),
        })
    except OSError as e:
        # File is on disk and valid; only the audit log failed. Warn but don't
        # treat as a failure. Pending marker is preserved so user can re-run --resume
        # if they want a clean log entry.
        print(f"warning: failed to append to report-log.jsonl ({e}). "
              f"Output file is on disk; pending marker preserved.", file=sys.stderr)
    else:
        pull_report.delete_pending(pending_dir, report_id)

    print(f"\nSaved to {output_dir}/", file=sys.stderr)
    print(f"  {main_path.name}", file=sys.stderr)
    return 0


# ----- Helpers -----


def _range_token(
    args: argparse.Namespace,
    start: Optional[datetime],
    end: Optional[datetime],
    needs_date_range: bool,
) -> str:
    """Build the human-readable range token used in output filenames.

    Order of preference:
      1. The preset name verbatim ('last-month', 'mtd', etc.) — most readable.
      2. 'last-{N}-days' when --days is used.
      3. 'YYYY-MM-DD_to_YYYY-MM-DD' for explicit --start/--end ranges.
      4. 'snapshot' for date-less reports.
    """
    if not needs_date_range or start is None or end is None:
        return "snapshot"
    if args.preset:
        return args.preset
    if args.days:
        return f"last-{args.days}-days"
    return f"{start.strftime('%Y-%m-%d')}_to_{end.strftime('%Y-%m-%d')}"


def _pacific_tz():
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo  # type: ignore[no-reattr]
    return ZoneInfo("America/Los_Angeles")


def _resolve_range(
    args: argparse.Namespace,
    entry: dict[str, Any],
    parser: argparse.ArgumentParser,
) -> tuple[Optional[datetime], Optional[datetime]]:
    needs = entry.get("needs_date_range", False)
    if not needs:
        if args.days or args.start or args.end:
            print(
                f"warning: report '{entry['type']}' does not use a date range; ignoring --days/--start/--end",
                file=sys.stderr,
            )
        return None, None

    sources = sum(bool(x) for x in (args.days, args.start or args.end, args.preset))
    if sources > 1:
        parser.error("--days, --preset, and --start/--end are mutually exclusive")

    if args.preset:
        return _resolve_preset(args.preset)

    if args.end and not args.start and not args.days:
        parser.error("--end requires --start (or use --days/--preset)")

    if args.days is not None and args.days <= 0:
        parser.error(f"--days must be a positive integer (got {args.days})")

    # All date math anchors to Pacific midnight to match Seller Central calendar days.
    pacific = _pacific_tz()
    now_pt = datetime.now(pacific).replace(microsecond=0)
    today = datetime(now_pt.year, now_pt.month, now_pt.day, tzinfo=pacific)

    if args.days:
        # Match Seller Central UI's "Last N Days": N full prior calendar days
        # plus today's partial day. Equivalent to --preset last-N-days, so
        # `--days 7` and `--preset last-7-days` always agree.
        end = today + timedelta(days=1)
        start = today - timedelta(days=args.days)
    elif args.start:
        start = _parse_iso(args.start, pacific) or parser.error(f"invalid --start: {args.start}")
        if args.end:
            end = _parse_iso(args.end, pacific) or parser.error(f"invalid --end: {args.end}")
        else:
            end = today + timedelta(days=1)
    else:
        parser.error(
            f"report needs a date range. Pass --days N, --preset NAME, or --start/--end."
        )

    return start, end


def _resolve_preset(name: str) -> tuple[datetime, datetime]:
    """Calendar-aligned date ranges anchored to US/Pacific (Amazon's timezone).

    Ranges are returned as half-open [start, end): start is 00:00 Pacific of the
    first included day; end is 00:00 Pacific of the day AFTER the last included day.
    Both datetimes are timezone-aware (Pacific offset, auto-adjusting for DST), so
    Amazon receives the correct UTC equivalent that matches what Seller Central shows.
    """
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo  # type: ignore[no-reattr]

    pacific = ZoneInfo("America/Los_Angeles")
    now_pt = datetime.now(pacific).replace(microsecond=0)
    today = datetime(now_pt.year, now_pt.month, now_pt.day, tzinfo=pacific)

    def month_first(y: int, m: int) -> datetime:
        return datetime(y, m, 1, tzinfo=pacific)

    if name == "today":
        return today, today + timedelta(days=1)
    if name == "yesterday":
        return today - timedelta(days=1), today
    if name == "this-week":
        # ISO week: Monday=0
        start = today - timedelta(days=today.weekday())
        return start, today + timedelta(days=1)
    if name == "last-week":
        this_mon = today - timedelta(days=today.weekday())
        last_mon = this_mon - timedelta(days=7)
        return last_mon, this_mon
    if name == "this-month":
        return month_first(today.year, today.month), today + timedelta(days=1)
    if name == "last-month":
        first_of_this = month_first(today.year, today.month)
        if today.month == 1:
            first_of_last = month_first(today.year - 1, 12)
        else:
            first_of_last = month_first(today.year, today.month - 1)
        return first_of_last, first_of_this
    if name == "mtd":
        return month_first(today.year, today.month), today + timedelta(days=1)
    if name == "ytd":
        return datetime(today.year, 1, 1, tzinfo=pacific), today + timedelta(days=1)
    # last-N-days matches Seller Central UI: N full prior calendar days plus
    # today's partial day, so a pull at 7pm gives the same rows as clicking
    # "Last N Days" → Download in the UI at the same moment.
    if name == "last-7-days":
        return today - timedelta(days=7), today + timedelta(days=1)
    if name == "last-30-days":
        return today - timedelta(days=30), today + timedelta(days=1)
    if name == "last-90-days":
        return today - timedelta(days=90), today + timedelta(days=1)
    raise ValueError(f"unknown preset: {name}")


def _validate_range(
    entry: dict[str, Any],
    start: Optional[datetime],
    end: Optional[datetime],
    allow_chunk: bool,
) -> Optional[str]:
    if start is None or end is None:
        return None
    if end <= start:
        return f"--end must be after --start (got start={start.isoformat()}, end={end.isoformat()})"

    span = end - start

    max_req = entry.get("max_request_days")
    if max_req and span > timedelta(days=max_req) and not allow_chunk:
        days_display = span.total_seconds() / 86400
        # `--days N` and `--preset last-N-days` resolve to N+1 calendar days
        # (N full prior + today partial) for UI parity. Tell the user when
        # that's why they're hitting the cap, so they don't think we're broken.
        suffix = ""
        if abs(days_display - (max_req + 1)) < 0.001:
            suffix = (
                f" (Note: --days {max_req} / --preset last-{max_req}-days now "
                f"includes today's partial day, so the span is {max_req}+1 = "
                f"{max_req + 1} days. Pass --chunk to split into two pulls.)"
            )
        return (
            f"requested {days_display:.2f}-day range exceeds the {max_req}-day cap for this report. "
            f"Pass --chunk to split into sequential pulls, or use a shorter --days/--start range."
            + suffix
        )

    max_hist = entry.get("max_history_days")
    if max_hist:
        # Compare in Pacific midnight space — `start` is always midnight PT, so
        # using a wall-clock `now()` would flag a valid request late in the day.
        pacific = _pacific_tz()
        now_pt = datetime.now(pacific)
        today_pt = datetime(now_pt.year, now_pt.month, now_pt.day, tzinfo=pacific)
        oldest = today_pt - timedelta(days=max_hist)
        # Make start tz-aware if somehow naive (defensive — _parse_iso normally handles this).
        start_cmp = start if start.tzinfo else start.replace(tzinfo=pacific)
        if start_cmp < oldest:
            return (
                f"--start {start.date()} is older than this report's history limit "
                f"({max_hist} days, earliest allowed ≈ {oldest.date()})."
            )

    return None


def _maybe_chunk(
    entry: dict[str, Any],
    start: Optional[datetime],
    end: Optional[datetime],
    enabled: bool,
) -> list[tuple[Optional[datetime], Optional[datetime]]]:
    if start is None or end is None:
        return [(None, None)]
    if not enabled:
        return [(start, end)]
    max_req = entry.get("max_request_days")
    if not max_req or (end - start) <= timedelta(days=max_req):
        return [(start, end)]

    # Chunk on Pacific calendar midnights so each chunk covers exactly N calendar
    # days even across DST. A "30-day chunk" is always 30 calendar days regardless
    # of whether DST starts/ends in the middle. The UTC span may be 30×24h ± 1h
    # but the Pacific calendar boundaries are clean, which is what Amazon validates.
    pacific = _pacific_tz()
    cur = start.astimezone(pacific) if start.tzinfo else start.replace(tzinfo=pacific)
    end_pt = end.astimezone(pacific) if end.tzinfo else end.replace(tzinfo=pacific)

    chunks: list[tuple[datetime, datetime]] = []
    while cur < end_pt:
        # Snap nxt to Pacific midnight at cur.date() + max_req days. Constructing
        # a fresh datetime with tzinfo=pacific (vs adding a timedelta) gives us a
        # true calendar-day boundary that auto-handles DST transitions.
        nxt_date = (cur + timedelta(days=max_req)).date()
        nxt = datetime(nxt_date.year, nxt_date.month, nxt_date.day, tzinfo=pacific)
        if nxt > end_pt:
            nxt = end_pt
        chunks.append((cur, nxt))
        cur = nxt
    return chunks  # type: ignore[return-value]


def _parse_iso(value: Optional[str], default_tz=None) -> Optional[datetime]:
    """Parse an ISO date or datetime string.

    For date-only strings (YYYY-MM-DD), midnight in `default_tz` is assumed —
    Pacific by default to match Seller Central. Full ISO datetimes with an
    explicit offset (e.g. 2026-04-01T00:00:00-07:00 or ...Z) are taken as-is.
    """
    if not value:
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        if "T" in s:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                tz = default_tz or _pacific_tz()
                dt = dt.replace(tzinfo=tz)
        else:
            tz = default_tz or _pacific_tz()
            dt = datetime.fromisoformat(s + "T00:00:00").replace(tzinfo=tz)
    except ValueError:
        return None
    return dt


def _parse_kv(items: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            print(
                f"warning: ignoring --report-options '{item}' (expected KEY=VALUE)",
                file=sys.stderr,
            )
            continue
        k, v = item.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _candidate_env_paths() -> list[Path]:
    """Where the skill looks for a .env, in priority order.

    1. CWD .env (project root if the user cd'd there).
    2. Walk up from CWD until filesystem root, picking up a project-root .env
       even when invoked from a subdirectory.
    3. ~/.config/amazon-pull-report/.env (XDG-style user-level config —
       honors $XDG_CONFIG_HOME if set).
    4. <skill folder>/.env (legacy fallback for installs that pre-date
       the user-config layout; keeps existing setups working).
    """
    out: list[Path] = []
    seen: set[Path] = set()

    def _push(p: Path) -> None:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            out.append(p)

    cwd = Path.cwd()
    _push(cwd / ".env")
    parent = cwd.resolve()
    # Bounded walk — stop at filesystem root.
    while parent.parent != parent:
        parent = parent.parent
        _push(parent / ".env")

    xdg = os.environ.get("XDG_CONFIG_HOME")
    config_root = Path(xdg) if xdg else Path.home() / ".config"
    _push(config_root / "amazon-pull-report" / ".env")

    _push(SKILL_ROOT / ".env")
    return out


def _load_dotenv_if_present() -> None:
    """Load KEY=VALUE pairs from the first .env found in the candidate list.

    No external dep — this is a tiny, forgiving parser. Skips lines that don't
    look like KEY=VALUE. Existing env vars are not overwritten, so an
    explicitly-exported shell var always wins.

    After loading, applies project-style aliases (SP_API_ID, SP_API_SECRET,
    SP_API_TOKEN) for sellers reusing a project .env that follows the older
    naming convention. Canonical names always win when both are set.
    """
    for path in _candidate_env_paths():
        if not path.exists():
            continue
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
        # Use the first .env we find, do not stack
        break

    # Project-style aliases. Read-only fallback — does not overwrite if the
    # canonical name is already set, so an explicit `LWA_CLIENT_ID` wins
    # over an alias-derived value every time.
    aliases = {
        "LWA_CLIENT_ID": "SP_API_ID",
        "LWA_CLIENT_SECRET": "SP_API_SECRET",
        "SP_API_REFRESH_TOKEN": "SP_API_TOKEN",
    }
    for canonical, alias in aliases.items():
        if canonical not in os.environ and os.environ.get(alias):
            os.environ[canonical] = os.environ[alias]


def _write_failure_metadata(
    output_dir: Path,
    slug: str,
    report_id: str,
    entry: dict[str, Any],
    marketplace_id: str,
    region: str,
    data_start: Optional[datetime],
    data_end: Optional[datetime],
    status: str,
    error: str,
    created_at: Optional[str],
) -> None:
    range_token = (
        f"{data_start.strftime('%Y-%m-%d')}_to_{data_end.strftime('%Y-%m-%d')}"
        if data_start and data_end else "snapshot"
    )
    pull_report.append_log(SKILL_ROOT, {
        "skill_version": SKILL_VERSION,
        "report_slug": slug,
        "report_type": entry["type"],
        "report_id": report_id,
        "marketplace_id": marketplace_id,
        "region": region,
        "range_token": range_token,
        "data_start": data_start.isoformat() if data_start else None,
        "data_end": data_end.isoformat() if data_end else None,
        "status": status,
        "error": error,
        "created_at": created_at,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "output_file": None,
    })
    print(f"  failure logged to report-log.jsonl", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
