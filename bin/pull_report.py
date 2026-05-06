"""SP-API Reports v2021-06-30 workflow: create -> poll -> fetch -> parse.

Generic over report type. Pulls registry metadata from report_registry but
otherwise has no skill-specific knowledge.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from xml.etree import ElementTree as ET

import requests

from sp_api_client import SpApiClient, SpApiError


REPORTS_PATH = "/reports/2021-06-30/reports"
DOCUMENTS_PATH = "/reports/2021-06-30/documents"


class ReportFatalError(Exception):
    """Amazon returned FATAL or CANCELLED for the report."""


class ReportTimeoutError(Exception):
    """Polling exceeded max_wait. Caller can retry with --resume."""

    def __init__(self, report_id: str, message: str) -> None:
        super().__init__(message)
        self.report_id = report_id


def create_report(
    client: SpApiClient,
    report_type: str,
    marketplace_id: str,
    data_start: Optional[datetime] = None,
    data_end: Optional[datetime] = None,
    report_options: Optional[dict[str, str]] = None,
) -> str:
    """POST /reports/2021-06-30/reports. Returns reportId.

    sellerId is intentionally omitted: the refresh token's authorization
    scope identifies the seller. Amazon's schema does not accept sellerId
    in the createReport body.
    """
    body: dict[str, Any] = {
        "reportType": report_type,
        "marketplaceIds": [marketplace_id],
    }
    if data_start is not None:
        body["dataStartTime"] = _iso_z(data_start)
    if data_end is not None:
        body["dataEndTime"] = _iso_z(data_end)
    if report_options:
        body["reportOptions"] = report_options

    resp = client.request("POST", REPORTS_PATH, json_body=body)
    report_id = resp.get("reportId")
    if not report_id:
        raise SpApiError(f"createReport returned no reportId: {resp}")
    return report_id


def get_report_status(client: SpApiClient, report_id: str) -> dict[str, Any]:
    """GET /reports/2021-06-30/reports/{reportId}."""
    return client.request("GET", f"{REPORTS_PATH}/{report_id}")


def poll_until_done(
    client: SpApiClient,
    report_id: str,
    poll_interval: int = 15,
    max_wait: int = 1800,
    progress: Optional[Any] = sys.stderr,
) -> str:
    """Poll until status is DONE. Returns reportDocumentId.

    Raises ReportFatalError on FATAL/CANCELLED, ReportTimeoutError on timeout.

    Resilient to transient SP-API errors (5xx, network blips): tolerates up to
    `max_consecutive_failures` in a row before giving up. Tracks real elapsed
    time, not poll-count, so slow responses don't overshoot the deadline.
    Surfaces an unknown/empty processingStatus after a few consecutive observations.
    """
    start = time.monotonic()
    deadline = start + max_wait
    last_status = ""
    transient_failures = 0
    unknown_status_count = 0
    max_consecutive_failures = 5
    max_unknown_observations = 5
    valid_statuses = {"IN_QUEUE", "IN_PROGRESS", "DONE", "FATAL", "CANCELLED"}

    while True:
        if time.monotonic() >= deadline:
            break

        try:
            status_resp = get_report_status(client, report_id)
            transient_failures = 0
        except SpApiError as e:
            transient_failures += 1
            if transient_failures >= max_consecutive_failures:
                raise SpApiError(
                    f"poll_until_done gave up after {transient_failures} consecutive "
                    f"failures fetching status for report {report_id}. Last error: {e}"
                ) from e
            if progress is not None:
                print(
                    f"  warning: status check failed ({e}). Retry {transient_failures}/"
                    f"{max_consecutive_failures}.",
                    file=progress,
                )
            _sleep_until(deadline, poll_interval)
            continue

        status = status_resp.get("processingStatus", "")
        # Use real elapsed (post-request), not pre-request remaining,
        # so slow status fetches are reflected in user-visible timing.
        elapsed = int(time.monotonic() - start)
        if status != last_status:
            if progress is not None:
                print(f"  status: {status or '(empty)'} (waited {elapsed}s)", file=progress)
            last_status = status

        if status == "DONE":
            doc_id = status_resp.get("reportDocumentId")
            if not doc_id:
                raise SpApiError(
                    f"Report {report_id} is DONE but has no reportDocumentId: {status_resp}"
                )
            return doc_id
        if status in ("FATAL", "CANCELLED"):
            raise ReportFatalError(
                f"Report {report_id} ended with status {status}. Common causes: "
                "invalid date range, missing required reportOptions, or no data "
                "for the period requested."
            )

        if status not in valid_statuses:
            unknown_status_count += 1
            if progress is not None:
                print(
                    f"  warning: unknown processingStatus '{status}' "
                    f"({unknown_status_count}/{max_unknown_observations}).",
                    file=progress,
                )
            if unknown_status_count >= max_unknown_observations:
                # Give up rather than wait until max_wait expires — this is almost
                # always a sign of a typo in the report type or a deprecated API
                # response shape. Surface fast so the user can debug.
                raise SpApiError(
                    f"Report {report_id} returned unknown processingStatus "
                    f"'{status}' {unknown_status_count} times in a row. "
                    f"Aborting. Full last response: {status_resp}"
                )
        else:
            unknown_status_count = 0

        _sleep_until(deadline, poll_interval)

    raise ReportTimeoutError(
        report_id,
        f"Report {report_id} did not complete within {max_wait}s. Resume with: "
        f"--resume {report_id}",
    )


def _sleep_until(deadline: float, max_interval: int) -> None:
    """Sleep at most `max_interval` seconds, but never past `deadline`."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return
    time.sleep(min(max_interval, remaining))


def get_document_metadata(client: SpApiClient, document_id: str) -> dict[str, Any]:
    """GET /reports/2021-06-30/documents/{documentId}.

    Returns the pre-signed S3 URL and optional compressionAlgorithm.
    v2021-06-30 dropped the AES encryption step from older Reports API versions;
    documents come down as plain bytes (optionally GZIP-compressed).
    """
    return client.request("GET", f"{DOCUMENTS_PATH}/{document_id}")


def download_document(url: str, compressed: bool) -> bytes:
    """Download from the pre-signed S3 URL. Decompress GZIP transparently.

    Network and decompression failures are wrapped as SpApiError so callers
    only need to catch one exception type.
    """
    try:
        resp = requests.get(url, timeout=300)
        resp.raise_for_status()
        content = resp.content
    except requests.exceptions.RequestException as e:
        raise SpApiError(f"document download failed: {type(e).__name__}: {e}") from e

    if compressed:
        try:
            content = gzip.decompress(content)
        except (gzip.BadGzipFile, OSError, EOFError) as e:
            raise SpApiError(f"document gunzip failed: {e}") from e
    return content


def parse(content: bytes, fmt: str) -> Any:
    """Dispatch based on the format hint from the registry.

    Returns:
      - tsv/csv -> list[dict]
      - json    -> the parsed JSON (often a dict, sometimes a list)
      - xml     -> a list of dicts (one per top-level child element)
    """
    fmt = fmt.lower()
    if fmt == "tsv":
        return _parse_delimited(content, delimiter="\t")
    if fmt == "csv":
        return _parse_delimited(content, delimiter=",")
    if fmt == "json":
        text = content.decode("utf-8", errors="replace")
        return json.loads(text)
    if fmt == "xml":
        return _parse_xml(content)
    raise ValueError(
        f"Unknown format '{fmt}'. Supported: tsv, csv, json, xml. "
        "If this is a registry entry, fix the 'format' field."
    )


def _parse_delimited(content: bytes, delimiter: str) -> list[dict]:
    rows = _read_amazon_tabular(content, delimiter)
    if not rows:
        return []
    headers = rows[0]
    return [dict(zip(headers, r)) for r in rows[1:]]


def _read_amazon_tabular(content: bytes, delimiter: str) -> list[list[str]]:
    """Parse Amazon's quirky flat-file format: fields delimited by `delimiter`,
    optionally wrapped in `"..."` (single layer), inner `"` NOT escaped.
    Splits on the delimiter, then strips one matching pair of outer quotes per field.
    """
    text = content.decode("utf-8", errors="replace")
    rows: list[list[str]] = []
    for raw_line in text.splitlines():
        if not raw_line:
            continue
        fields = raw_line.split(delimiter)
        rows.append([_strip_outer_quotes(f) for f in fields])
    return rows


def _strip_outer_quotes(s: str) -> str:
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    return s


def _parse_xml(content: bytes) -> list[dict]:
    root = ET.fromstring(content)
    return [_xml_element_to_dict(child) for child in root]


def _xml_element_to_dict(elem: ET.Element) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if elem.attrib:
        out.update({f"@{k}": v for k, v in elem.attrib.items()})
    children = list(elem)
    if not children:
        out["#text"] = (elem.text or "").strip()
        return {elem.tag: out["#text"] or out} if not out.get("#text") else out
    for child in children:
        sub = _xml_element_to_dict(child)
        if child.tag in out:
            existing = out[child.tag]
            if not isinstance(existing, list):
                out[child.tag] = [existing]
            out[child.tag].append(sub)
        else:
            out[child.tag] = sub
    return out


def _iso_z(dt: datetime) -> str:
    """Serialize a datetime as ISO 8601 with a literal 'Z' suffix.

    SP-API rejects '+00:00' offset strings for some report types; 'Z' is universally accepted.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


# ----- Persistence helpers for --resume -----


def write_pending(pending_dir: Path, report_id: str, payload: dict[str, Any]) -> Path:
    pending_dir.mkdir(parents=True, exist_ok=True)
    path = pending_dir / f"{report_id}.json"
    path.write_text(json.dumps(payload, indent=2))
    return path


def read_pending(pending_dir: Path, report_id: str) -> dict[str, Any]:
    path = pending_dir / f"{report_id}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No pending record for reportId {report_id} at {path}. "
            "Was the report created in this directory?"
        )
    return json.loads(path.read_text())


def delete_pending(pending_dir: Path, report_id: str) -> None:
    path = pending_dir / f"{report_id}.json"
    if path.exists():
        path.unlink()


# ----- Output helpers -----


def tsv_to_csv(content: bytes) -> bytes:
    """Convert tab-delimited bytes to RFC-4180 comma-separated UTF-8 bytes.

    Uses the stdlib `csv` module for correct quoting:
      - Fields containing comma, quote, CR, or LF are wrapped in `"..."`
      - Inner double quotes are doubled (`"` → `""`)
      - Lines terminated with CRLF
    Empty rows are preserved.
    """
    rows = _read_amazon_tabular(content, "\t")
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    for row in rows:
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


def write_output(
    out_dir: Path,
    fmt: str,
    raw: bytes,
    *,
    base_name: str,
    user_format: str = "csv",
) -> Path:
    """Write the report file into out_dir and return its path.

    `fmt` is the source format from Amazon (tsv/csv/json/xml).
    `user_format` is the seller's preferred extension for tab-delimited reports
    ('csv' or 'txt'). For native csv/json/xml reports, user_format is ignored.

    Writes atomically: payload goes to `<base_name>.<ext>.tmp` first, then
    renamed to the final path. A crash mid-write leaves the .tmp behind but
    never produces a truncated final file.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    fmt_lower = fmt.lower()
    if fmt_lower == "tsv":
        if user_format == "txt":
            main_path = out_dir / f"{base_name}.txt"
            payload = raw
        else:
            main_path = out_dir / f"{base_name}.csv"
            payload = tsv_to_csv(raw)
    elif fmt_lower in ("csv", "json", "xml"):
        main_path = out_dir / f"{base_name}.{fmt_lower}"
        payload = raw
    else:
        main_path = out_dir / f"{base_name}.txt"
        payload = raw

    # Unique tmp suffix per call so concurrent runs of the same base_name don't
    # clobber each other's in-flight writes. {pid}-{uuid} is overkill for this
    # workload but free and bulletproof.
    tmp_suffix = f".{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
    tmp_path = main_path.with_suffix(main_path.suffix + tmp_suffix)
    tmp_path.write_bytes(payload)
    tmp_path.replace(main_path)
    return main_path


def append_log(skill_root: Path, record: dict[str, Any]) -> None:
    """Append one JSON record to report-log.jsonl in the skill folder."""
    log_path = skill_root / "report-log.jsonl"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")
