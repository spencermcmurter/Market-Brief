"""
Where the news comes from. Everything here is free.

  1. Google News RSS   -> sector/theme headlines + company headlines (no key)
  2. SEC EDGAR         -> U.S. filings (8-K etc.) for your NYSE/Nasdaq tickers (no key)
  3. FMP calendar      -> "coming today / this week" economic + earnings events
                          (one free API key -> FMP_API_KEY)

Each source is wrapped so that if one fails, the brief still goes out.
"""
import datetime as dt
import os
import time
from urllib.parse import quote_plus

import feedparser
import requests

FMP_API_KEY = os.environ.get("FMP_API_KEY", "").strip()
SEC_CONTACT = os.environ.get("SEC_CONTACT", "atlas-brief@example.com").strip()

# Outlets we trust for deep, reputable coverage (used to rank + pick the survivor
# when the same story appears in several places).
TIER1 = {
    "reuters", "bloomberg", "the globe and mail", "globe and mail", "financial post",
    "bnn bloomberg", "wall street journal", "wsj", "financial times", "ft",
    "cbc", "the canadian press", "cnbc",
}
TIER2 = {"marketwatch", "yahoo finance", "yahoo", "the street", "thestreet", "barron's", "forbes"}

# Hard blocklist: the tip / low-signal / opinion mills you asked to cut.
BLOCKLIST = {
    "motley fool", "fool.com", "zacks", "seeking alpha", "seekingalpha",
    "stocktwits", "tipranks", "24/7 wall st", "247wallst", "simply wall st",
    "insider monkey", "benzinga", "investorplace", "gurufocus",
}


def _source_tier(source_name):
    s = (source_name or "").lower()
    if any(b in s for b in BLOCKLIST):
        return 0            # excluded
    if any(t in s for t in TIER1):
        return 3
    if any(t in s for t in TIER2):
        return 2
    return 1                # unknown but not blocked


def _google_news(query, region="CA", lookback_days=2, limit=8):
    """One Google News RSS search -> list of normalized items."""
    q = f'{query} when:{lookback_days}d'
    url = (
        "https://news.google.com/rss/search?q="
        + quote_plus(q)
        + f"&hl=en-{region}&gl={region}&ceid={region}:en"
    )
    out = []
    try:
        feed = feedparser.parse(url)
    except Exception:
        return out
    for e in feed.entries[:limit]:
        title = getattr(e, "title", "") or ""
        # Google News appends " - Source" to the title; also exposes e.source.title
        source = ""
        if getattr(e, "source", None) and getattr(e.source, "title", None):
            source = e.source.title
        elif " - " in title:
            source = title.rsplit(" - ", 1)[-1]
            title = title.rsplit(" - ", 1)[0]
        published = None
        if getattr(e, "published_parsed", None):
            published = dt.datetime(*e.published_parsed[:6])
        out.append({
            "title": title.strip(),
            "link": getattr(e, "link", ""),
            "source": source.strip(),
            "published": published,
        })
    return out


def fetch_sector_news(sectors, lookback_days=2):
    items = []
    for s in sectors:
        # Combine a few terms per query with OR to keep the request count low.
        terms = s["terms"][:6] or [s["sector"]]
        query = " OR ".join(f'"{t}"' if " " in t else t for t in terms)
        for it in _google_news(query, lookback_days=lookback_days):
            it.update({"scope": "sector", "subject": s["sector"], "ticker": "",
                       "exchange": "", "sector": s["sector"]})
            items.append(it)
        time.sleep(0.4)
    return items


def fetch_company_news(companies, lookback_days=2):
    items = []
    for c in companies:
        if not c["company"] and not c["ticker"]:
            continue
        query = c["company"] or c["ticker"]
        for it in _google_news(query, lookback_days=lookback_days):
            it.update({"scope": "company", "subject": c["company"] or c["ticker"],
                       "ticker": c["ticker"], "exchange": c["exchange"],
                       "sector": c["sector"], "priority": c.get("priority", "Watch")})
            items.append(it)
        time.sleep(0.4)
    return items


# ---------- SEC EDGAR (U.S. filings) ----------
_CIK_CACHE = None


def _load_cik_map():
    global _CIK_CACHE
    if _CIK_CACHE is not None:
        return _CIK_CACHE
    _CIK_CACHE = {}
    try:
        r = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers={"User-Agent": f"Atlas Market Brief ({SEC_CONTACT})"},
            timeout=30,
        )
        r.raise_for_status()
        for _, v in r.json().items():
            _CIK_CACHE[v["ticker"].upper()] = str(v["cik_str"]).zfill(10)
    except Exception:
        pass
    return _CIK_CACHE


def fetch_us_filings(companies, lookback_days=2):
    """Recent notable filings (8-K, 6-K, etc.) for U.S.-listed tickers."""
    items = []
    cik_map = _load_cik_map()
    cutoff = dt.datetime.utcnow() - dt.timedelta(days=lookback_days)
    interesting = {"8-K", "6-K", "SC 13D", "SC 13D/A", "425", "DEFM14A"}
    for c in companies:
        exch = (c.get("exchange") or "").upper()
        if exch not in ("NYSE", "NASDAQ", "NYSEARCA"):
            continue
        cik = cik_map.get((c.get("ticker") or "").upper())
        if not cik:
            continue
        try:
            r = requests.get(
                f"https://data.sec.gov/submissions/CIK{cik}.json",
                headers={"User-Agent": f"Atlas Market Brief ({SEC_CONTACT})"},
                timeout=30,
            )
            r.raise_for_status()
            recent = r.json().get("filings", {}).get("recent", {})
            forms = recent.get("form", [])
            dates = recent.get("filingDate", [])
            accns = recent.get("accessionNumber", [])
            docs = recent.get("primaryDocument", [])
            for i, form in enumerate(forms):
                if form not in interesting:
                    continue
                try:
                    fdate = dt.datetime.strptime(dates[i], "%Y-%m-%d")
                except Exception:
                    continue
                if fdate < cutoff:
                    continue
                accn = accns[i].replace("-", "")
                link = (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                        f"{accn}/{docs[i]}") if i < len(docs) and docs[i] else \
                       f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"
                items.append({
                    "title": f"{c['company'] or c['ticker']} filed a {form} with the SEC",
                    "link": link, "source": "SEC EDGAR", "published": fdate,
                    "scope": "company", "subject": c["company"] or c["ticker"],
                    "ticker": c["ticker"], "exchange": exch, "sector": c.get("sector", ""),
                    "priority": c.get("priority", "Watch"), "is_filing": True, "form": form,
                })
        except Exception:
            continue
        time.sleep(0.3)
    return items


# ---------- FMP economic + earnings calendar ----------
def fetch_calendar(days_ahead=7):
    """Upcoming U.S./Canada economic releases + earnings for the week ahead."""
    econ, earnings = [], []
    if not FMP_API_KEY:
        return econ, earnings
    today = dt.date.today()
    frm, to = today.isoformat(), (today + dt.timedelta(days=days_ahead)).isoformat()
    try:
        r = requests.get(
            "https://financialmodelingprep.com/api/v3/economic_calendar",
            params={"from": frm, "to": to, "apikey": FMP_API_KEY}, timeout=30,
        )
        r.raise_for_status()
        for e in r.json():
            if e.get("country") not in ("US", "CA"):
                continue
            if (e.get("impact") or "").lower() not in ("high", "medium"):
                continue
            econ.append({
                "event": e.get("event", ""), "country": e.get("country", ""),
                "date": e.get("date", ""), "impact": e.get("impact", ""),
            })
    except Exception:
        pass
    try:
        r = requests.get(
            "https://financialmodelingprep.com/api/v3/earning_calendar",
            params={"from": frm, "to": to, "apikey": FMP_API_KEY}, timeout=30,
        )
        r.raise_for_status()
        earnings = r.json()
    except Exception:
        pass
    return econ, earnings
