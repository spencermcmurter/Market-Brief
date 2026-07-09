"""
Reads your watchlist from the Google Sheet you edit.

The sheet must be shared as "Anyone with the link -> Viewer" (see README).
We read each tab via Google's CSV export endpoint, so there are no logins or
API keys involved for the watchlist itself.
"""
import csv
import io
import os
import requests

SHEET_ID = os.environ.get("SHEET_ID", "").strip()
WATCHLIST_GID = os.environ.get("WATCHLIST_GID", "0").strip()      # first tab is usually 0
SECTORS_GID = os.environ.get("SECTORS_GID", "").strip()


def _fetch_csv(gid):
    if not SHEET_ID:
        raise RuntimeError("SHEET_ID is not set. Add it as a GitHub secret (see README).")
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={gid}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return list(csv.DictReader(io.StringIO(resp.text)))


def _get(row, *names):
    """Case/space tolerant column lookup."""
    norm = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
    for n in names:
        if n.strip().lower() in norm:
            return norm[n.strip().lower()]
    return ""


def load_watchlist():
    companies = []
    for row in _fetch_csv(WATCHLIST_GID):
        name = _get(row, "Company")
        ticker = _get(row, "Ticker")
        if not name and not ticker:
            continue
        companies.append({
            "company": name,
            "ticker": ticker,
            "exchange": _get(row, "Exchange"),
            "sector": _get(row, "Sector"),
            "priority": (_get(row, "Priority") or "Watch") or "Watch",
        })

    sectors = []
    if SECTORS_GID:
        for row in _fetch_csv(SECTORS_GID):
            name = _get(row, "Sector / Theme", "Sector/Theme", "Sector")
            include = _get(row, "Include?", "Include").upper()
            if not name or include == "N":
                continue
            raw = _get(row, "Search terms (comma-separated)", "Search terms")
            terms = [t.strip() for t in raw.split(",") if t.strip()]
            sectors.append({"sector": name, "terms": terms})

    return companies, sectors


if __name__ == "__main__":
    c, s = load_watchlist()
    print(f"{len(c)} companies, {len(s)} sectors")
    for x in c:
        print(" ", x)
    for x in s:
        print(" ", x)
