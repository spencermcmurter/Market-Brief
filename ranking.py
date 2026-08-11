"""
Ranking engine. Whole-word matching, a noise filter, an opinion/tip filter,
a central-bank guard (so "Royal Bank of Canada" is not read as the Bank of
Canada), and entity-aware de-duplication (collapses the same story even when
outlets word the headline very differently).
"""
import re
from difflib import SequenceMatcher

from sources import _source_tier

HIGH_MACRO = ["rate decision", "interest rate", "interest rates", "fomc",
              "federal reserve", "boc", "cpi", "inflation", "jobs report",
              "payrolls", "nonfarm", "unemployment rate", "gdp", "central bank",
              "rate cut", "rate hike", "monetary policy", "fed minutes",
              "fed chair", "quantitative"]
HIGH_SYSTEMIC = ["war", "warfare", "invasion", "ceasefire", "airstrike", "air strike",
                 "air strikes", "missile", "missiles", "military strike",
                 "drone strike", "sanction", "sanctions", "embargo",
                 "banking crisis", "bank failure", "sovereign default",
                 "government shutdown", "government spending", "stimulus",
                 "tariff", "tariffs", "oil price", "oil prices", "crude oil",
                 "strait of hormuz", "hormuz", "geopolitical", "reparations"]
HIGH_REG = ["osfi", "crtc", "regulator", "regulators", "regulation", "antitrust",
            "rate case", "competition bureau", "sec charges", "probe", "lawsuit"]
HIGH_COMPANY = ["acquire", "acquires", "acquisition", "merger", "merges", "takeover",
                "buyout", "to buy", "guidance", "cuts outlook", "raises outlook",
                "profit warning", "warns", "ceo", "cfo", "chief executive",
                "chief financial", "steps down", "resigns", "resign", "appoints",
                "appointment", "dividend cut", "slashes dividend", "cuts dividend"]
MED_COMPANY = ["launch", "launches", "unveils", "contract", "deal", "partnership",
               "consortium", "buyback", "share buyback", "dividend increase",
               "raises dividend", "expansion", "expands", "invests", "investment",
               "sell", "sale", "divest", "spinoff"]
LOW_COMPANY = ["beats", "misses", "earnings", "quarterly results", "reported",
               "price target", "upgrade", "downgrade", "analyst", "rated",
               "insider", "stake", "short seller"]

NOISE = ["replacement workers", "labour board", "labor board", "union", "picket",
         "collective agreement", "strike vote", "on strike", "layoff", "layoffs",
         "sponsor", "sponsorship", "donates", "donation", "charity", "foundation",
         "gala", "golf", "obituary", "passes away", "passed away", "dies", "died",
         "death of", "funeral", "memorial", "wins award", "named to", "employee of"]

OPINION = ["should you buy", "should you really buy", "should i buy", "is it time to buy",
           "time to buy", "stock to buy", "stocks to buy", "best stock", "best stocks",
           "top stock", "top stocks", "here's what i think", "heres what i think",
           "worth buying", "buy right now", "buy now", "deserves your", "could make you",
           "make you a millionaire", "is it a buy", "better buy", "reasons to buy",
           "why i'd buy", "my top", "screaming buy", "before it's too late"]

THEME_IGNORE = {"inflation", "yields", "yield", "bonds", "market", "markets", "stocks",
                "stock", "crude", "tariff", "tariffs", "hormuz", "recession", "earnings",
                "dividend", "quantum", "interest", "central", "reserve", "federal",
                "canada", "canadian", "toronto", "nasdaq", "economy", "economic", "trade"}
STOP = {"bank", "banks", "royal", "national", "billion", "million", "shares", "share",
        "price", "prices", "sell", "sale", "sold", "agree", "agrees", "agreed",
        "company", "corp", "group", "after", "over", "more", "than", "with", "from",
        "this", "that", "said", "says", "will", "could", "amid", "into", "their",
        "here", "what", "think", "about", "first", "next", "year", "years", "week",
        "today", "report", "reports", "announces", "announce", "plans"}

CB_RE = re.compile(r"(?<!royal )(?<!national )(?<!laurentian )\bbank of canada\b", re.I)


def _has(text, keywords):
    for kw in keywords:
        if re.search(r"\b" + re.escape(kw) + r"\b", text):
            return kw
    return None


def _is_opinion(title):
    t = title.lower()
    return any(p in t for p in OPINION)


def _cat_and_tier(item):
    t = (item.get("title", "") + " " + item.get("subject", "")).lower()
    scope = item.get("scope", "sector")

    if item.get("is_filing"):
        form = item.get("form", "")
        return ("Filing", "High", True) if form in (
            "8-K", "6-K", "SC 13D", "SC 13D/A", "425") else ("Filing", "Medium", True)

    if _has(t, NOISE):
        return "Operational / low-signal", "Low", False

    if _has(t, HIGH_SYSTEMIC):
        return "Systemic / Geo", "High", False
    if CB_RE.search(t) or _has(t, HIGH_MACRO):
        return "Macro", "High", False
    if _has(t, HIGH_REG):
        return "Regulatory", "High", scope == "company"

    if scope == "company":
        if _has(t, HIGH_COMPANY):
            return "Company (top-tier)", "High", True
        if _has(t, MED_COMPANY):
            return "Company (strategic)", "Medium", True
        if _has(t, LOW_COMPANY):
            return "Company (result/rating)", "Low", False
        return "Company", "Low", False

    return "Sector / Industry", "Medium", False


def _score(item, tier, source_tier):
    base = {"High": 100, "Medium": 55, "Low": 20}[tier]
    base += source_tier * 6
    if item.get("scope") == "sector":
        base += 8
    if item.get("scope") == "company" and item.get("priority", "Watch") == "Core":
        base += 4
    if item.get("is_filing"):
        base += 6
    return base


def _norm_title(s):
    s = re.sub(r"[^a-z0-9 ]", "", (s or "").lower())
    return re.sub(r"\s+", " ", s).strip()


def _entities(title):
    toks = re.findall(r"[a-z]{5,}", (title or "").lower())
    return set(x for x in toks if x not in STOP and x not in THEME_IGNORE)


def _similar(a, b):
    return SequenceMatcher(None, a, b).ratio()


def _is_dup(a, b):
    na, nb = a["_norm"], b["_norm"]
    if a.get("ticker") and a["ticker"] == b.get("ticker") and _similar(na, nb) > 0.6:
        return True
    if _similar(na, nb) > 0.75:
        return True
    shared = a["_ents"] & b["_ents"]
    if shared and any(len(w) >= 6 for w in shared) and _similar(na, nb) > 0.2:
        return True
    return False


def rank_and_dedupe(raw_items):
    scored = []
    for it in raw_items:
        st = _source_tier(it.get("source", ""))
        if st == 0:
            continue
        if _is_opinion(it.get("title", "")):
            continue
        cat, tier, star = _cat_and_tier(it)
        it["category"] = cat
        it["tier"] = tier
        it["company_star"] = star
        it["score"] = _score(it, tier, st)
        it["_norm"] = _norm_title(it.get("title", ""))
        it["_ents"] = _entities(it.get("title", ""))
        scored.append(it)

    scored.sort(key=lambda x: x["score"], reverse=True)
    kept = []
    for it in scored:
        if not any(_is_dup(it, k) for k in kept):
            kept.append(it)

    order = {"Systemic / Geo": 0, "Macro": 1, "Regulatory": 2}
    highs = [x for x in kept if x["tier"] == "High"]
    highs.sort(key=lambda x: (order.get(x["category"], 9), -x["score"]))
    for x in highs[:3]:
        x["read_first"] = True
    return kept


def to_sections(items, cap=40):
    items = items[:cap]
    return {
        "read_first": [x for x in items if x.get("read_first")],
        "high": [x for x in items if x["tier"] == "High"],
        "medium": [x for x in items if x["tier"] == "Medium"],
        "low": [x for x in items if x["tier"] == "Low"],
    }
