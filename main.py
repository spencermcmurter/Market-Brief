"""
Entry point. GitHub Actions runs this. It:
  1. checks it's really ~8 AM Eastern on a run day (Sun-Fri),
  2. reads your watchlist from the Google Sheet,
  3. pulls sector news, company news, U.S. filings, and the calendar,
  4. ranks + de-duplicates,
  5. builds the spreadsheet + email, and sends it.

Set FORCE_RUN=1 to bypass the time check (used for testing / manual runs).
"""
import datetime as dt
import os
import sys
from zoneinfo import ZoneInfo

import brief as B
import emailer
import ranking
import sources
import watchlist

EASTERN = ZoneInfo("America/Toronto")


def should_run(now_et):
    if os.environ.get("FORCE_RUN") == "1":
        return True
    # Saturday is the only day off (Python weekday: Mon=0 .. Sun=6 -> Sat=5)
    if now_et.weekday() == 5:
        return False
    # Two cron lines fire (12:00 & 13:00 UTC); only the 8 AM ET one proceeds.
    return now_et.hour == 8


# rules-based "why it matters" (upgradeable to the Claude API later)
WHY = {
    "Systemic / Geo": "Broad, immediate market impact — sets today's risk tone and can move oil, yields and your rate-sensitive holdings.",
    "Macro": "Scheduled macro release; central-bank and inflation data drive the whole tape and your banks, utility and insurers.",
    "Regulatory": "Government or regulator action with a direct, forward effect on the sector.",
    "Filing": "Official filing — the kind of disclosure (guidance, control change, material event) that can move the stock immediately.",
    "Company (top-tier)": "Top-tier corporate event (M&A, leadership, or guidance) — clears your bar for company-specific news.",
    "Company (strategic)": "Strategic move (deal, launch or partnership) that shapes the company's outlook without being a same-day shock.",
    "Company (result/rating)": "Backward-looking result or rating — lower priority per your forward-looking rule.",
    "Company": "Company mention; monitored but not a same-day catalyst.",
    "Sector / Industry": "Industry trend that shapes the sector you follow.",
}


def add_why(items):
    for it in items:
        base = WHY.get(it.get("category", ""), "Monitored for market relevance.")
        sec = it.get("sector")
        if sec and it.get("scope") == "company":
            base += f" (Sector: {sec}.)"
        it["why"] = base
    return items


def main():
    now_et = dt.datetime.now(EASTERN)
    if not should_run(now_et):
        print(f"Not a run moment ({now_et:%Y-%m-%d %H:%M %Z}); exiting quietly.")
        return

    # Sunday sweeps the weekend (Fri close -> Sun); other days ~30h.
    lookback_days = 3 if now_et.weekday() == 6 else 2
    date_label = now_et.strftime("%A, %B %d, %Y")

    companies, sectors = watchlist.load_watchlist()
    print(f"Loaded {len(companies)} companies, {len(sectors)} sectors.")

    raw = []
    raw += sources.fetch_sector_news(sectors, lookback_days)
    raw += sources.fetch_company_news(companies, lookback_days)
    raw += sources.fetch_us_filings(companies, lookback_days)
    print(f"Collected {len(raw)} raw items.")

    ranked = ranking.rank_and_dedupe(raw)
    ranked = add_why(ranked)
    sections = ranking.to_sections(ranked, cap=40)

    econ, earnings = sources.fetch_calendar(days_ahead=7)

    date_short = now_et.strftime("%Y-%m-%d")
    out_path = f"/tmp/Market_Brief_{date_short}.xlsx"
    B.build_xlsx(sections, econ, earnings, out_path, date_label)
    html_body = B.build_email_html(sections, econ, date_label)

    rf = len(sections["read_first"])
    hi = len(sections["high"])
    subject = f"Market Brief — {now_et:%a %b %-d} · {rf} read-first · {hi} high-impact"

    emailer.send_brief(subject, html_body, out_path)
    print(f"Sent: {subject}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise
