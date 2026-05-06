"""Friendly slug → SP-API report metadata.

Add new entries here. Required keys: type, format, needs_date_range.
Optional: report_options, max_request_days, max_history_days, requires_rdt, description.
"""
from __future__ import annotations

from typing import Any


REPORTS: dict[str, dict[str, Any]] = {
    # ----- Removals -----
    "removal-recommendations": {
        "type": "GET_FBA_RECOMMENDED_REMOVAL_DATA",
        "format": "tsv",
        "needs_date_range": False,
        "description": "Items Amazon recommends for removal (aged inventory, low-velocity).",
    },
    "removal-orders": {
        "type": "GET_FBA_FULFILLMENT_REMOVAL_ORDER_DETAIL_DATA",
        "format": "tsv",
        "needs_date_range": True,
        "description": "Removal orders you've placed and their statuses.",
    },
    "removal-shipments": {
        "type": "GET_FBA_FULFILLMENT_REMOVAL_SHIPMENT_DETAIL_DATA",
        "format": "tsv",
        "needs_date_range": True,
        "description": "Per-shipment detail for removal orders (carrier, tracking, qty).",
    },

    # ----- Inventory ledger -----
    "ledger-summary": {
        "type": "GET_LEDGER_SUMMARY_VIEW_DATA",
        "format": "tsv",
        "needs_date_range": True,
        # Without these the report defaults to MONTHLY/COUNTRY,
        # which makes "last 7 days" return empty or month-rolled-up data.
        "report_options": {
            "aggregatedByTimePeriod": "DAILY",
            "aggregateByLocation": "COUNTRY",
        },
        "description": "Aggregated inventory ledger (daily, country-level).",
    },
    "ledger-detail": {
        "type": "GET_LEDGER_DETAIL_VIEW_DATA",
        "format": "tsv",
        "needs_date_range": True,
        "max_history_days": 540,  # ~18 months — Amazon caps history here
        "description": "Per-event inventory movements (receipts, customer ships, removals, adjustments).",
    },

    # ----- Returns -----
    "returns-fba": {
        "type": "GET_FBA_FULFILLMENT_CUSTOMER_RETURNS_DATA",
        "format": "tsv",
        "needs_date_range": True,
        "description": "FBA customer returns with reason and disposition.",
    },
    "returns-mfn-prime": {
        "type": "GET_CSV_MFN_PRIME_RETURNS_REPORT",
        "format": "csv",
        "needs_date_range": True,
        "max_request_days": 60,
        "description": "Merchant-fulfilled Prime returns (CSV).",
    },
    "returns-mfn-all": {
        "type": "GET_FLAT_FILE_RETURNS_DATA_BY_RETURN_DATE",
        "format": "tsv",
        "needs_date_range": True,
        "description": "All MFN returns by return date (broader than Prime-only).",
    },

    # ----- Orders / sales -----
    # -by-order-date and -by-last-update are distinct reports.
    # Sellers ask for different things depending on use case.
    "orders-by-order-date": {
        "type": "GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL",
        "format": "tsv",
        "needs_date_range": True,
        "max_request_days": 30,
        "description": "All orders by purchase date (Amazon caps at 30 days per request).",
    },
    "orders-by-last-update": {
        "type": "GET_FLAT_FILE_ALL_ORDERS_DATA_BY_LAST_UPDATE_GENERAL",
        "format": "tsv",
        "needs_date_range": True,
        "max_request_days": 30,
        "description": "Orders by last-modified date — useful for picking up recent status changes.",
    },
    "sales-and-traffic": {
        "type": "GET_SALES_AND_TRAFFIC_REPORT",
        "format": "json",
        "needs_date_range": True,
        "max_history_days": 730,  # ~2 years
        # Make granularity explicit so users aren't surprised by PARENT/DAY defaults.
        "report_options": {
            "asinGranularity": "CHILD",
            "dateGranularity": "DAY",
        },
        "description": "Sales & traffic by child ASIN, daily.",
    },

    # ----- Settlement -----
    "settlement-v2": {
        "type": "GET_V2_SETTLEMENT_REPORT_DATA_FLAT_FILE_V2",
        "format": "tsv",
        "needs_date_range": True,
        "description": "Settlement reports v2 (payouts, fees, refunds, reserves).",
    },

    # ----- FBA inventory snapshots -----
    "manage-fba-inventory": {
        "type": "GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA",
        "format": "tsv",
        "needs_date_range": False,
        "display_name": "Manage FBA Inventory",
        "description": "Current FBA inventory snapshot — same data as Seller Central's Manage FBA Inventory report. Tab-delimited, written as .csv by default.",
    },
}


def display_name(slug: str) -> str:
    """Human-readable name for a slug. Used for folder/file names.

    Returns the entry's `display_name` field if set, otherwise title-cases the slug.
    """
    entry = REPORTS.get(slug, {})
    if "display_name" in entry:
        return entry["display_name"]
    return " ".join(word.capitalize() for word in slug.split("-"))


def get(slug: str) -> dict[str, Any]:
    """Look up a registry entry. Suggest close matches on miss."""
    if slug in REPORTS:
        return REPORTS[slug]
    suggestions = _close_matches(slug)
    msg = f"Unknown report slug: '{slug}'."
    if suggestions:
        msg += f" Did you mean: {', '.join(suggestions)}?"
    msg += " Run with --list to see all available aliases."
    raise KeyError(msg)


def list_slugs() -> list[str]:
    return sorted(REPORTS.keys())


def _close_matches(slug: str, n: int = 3) -> list[str]:
    import difflib

    return difflib.get_close_matches(slug, REPORTS.keys(), n=n, cutoff=0.5)
