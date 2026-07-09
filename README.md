# Atlas — Daily Market Brief

An automated email that lands in your inbox every morning (Sun–Fri, ~8:00 AM
Eastern) with a ranked spreadsheet of the day's important market news, filings,
and the week-ahead calendar — for the companies and sectors on your watchlist.

You do **not** need to be a developer. Follow the steps below once (~20 minutes).
After that it runs itself, and you only ever touch the Google Sheet to change
what you follow.

---

## What powers it (all free)

| Piece | What it does | Cost |
|---|---|---|
| GitHub Actions | Runs the program on a schedule in the cloud | Free |
| Google News RSS | Sector + company headlines | Free, no key |
| SEC EDGAR | U.S. filings (8-K etc.) for your U.S. tickers | Free, no key |
| Financial Modeling Prep | Economic + earnings calendar | Free key |
| Gmail | Delivers the email to you | Free |
| Google Sheet | Your editable watchlist | Free |

---

## One-time setup

### Step 1 — Get the free calendar key (2 min)
1. Go to **financialmodelingprep.com** and create a free account.
2. Open your **Dashboard** and copy your **API key**. Keep it handy for Step 5.

### Step 2 — Create a Gmail "App Password" (3 min)
An app password lets the program send email as you, without your real password.
1. Your Google account must have **2-Step Verification ON**
   (myaccount.google.com → Security). Turn it on if it isn't.
2. Go to **myaccount.google.com/apppasswords**.
3. Type a name like `Market Brief` and click **Create**.
4. Google shows a **16-character password**. Copy it (spaces don't matter).
   Keep it for Step 5.

### Step 3 — Put your watchlist online (4 min)
1. Open **drive.google.com** → **New → File upload** → upload
   `Atlas_Market_Brief_Watchlist.xlsx`.
2. Double-click it in Drive → **Open with → Google Sheets** →
   **File → Save as Google Sheets**.
3. Click **Share** (top right) → under General access choose
   **Anyone with the link → Viewer** → Done.
4. Look at the address bar. The URL looks like:
   `https://docs.google.com/spreadsheets/d/`**`1AbC...long-id...XyZ`**`/edit#gid=0`
   - The long id between `/d/` and `/edit` is your **SHEET_ID**.
   - Click the **Watchlist** tab; the number after `gid=` in the URL is
     **WATCHLIST_GID** (usually `0`).
   - Click the **Sectors & Themes** tab; the `gid=` number there is
     **SECTORS_GID**.
   Write down all three.

### Step 4 — Create the GitHub project (4 min)
1. Create a free account at **github.com** if you don't have one.
2. Click **New repository** → name it `market-brief` → set **Private** → Create.
3. On the new repo page click **uploading an existing file** and drag in
   **all the files from this folder** (including the `.github` folder).
   Commit the changes.

### Step 5 — Add your secrets (4 min)
In your repo: **Settings → Secrets and variables → Actions → New repository
secret**. Add each of these (name on the left, your value on the right):

| Secret name | Value |
|---|---|
| `SHEET_ID` | the long id from Step 3 |
| `WATCHLIST_GID` | usually `0` |
| `SECTORS_GID` | the Sectors tab gid from Step 3 |
| `GMAIL_ADDRESS` | spencermcmurter@gmail.com |
| `GMAIL_APP_PASSWORD` | the 16-char password from Step 2 |
| `RECIPIENT` | spencermcmurter@gmail.com |
| `FMP_API_KEY` | your key from Step 1 |
| `SEC_CONTACT` | your email (SEC asks that automated tools identify a contact) |

### Step 6 — Test it now (1 min)
1. Go to the **Actions** tab → **Daily Market Brief** → **Run workflow**.
2. Wait ~1 minute, then check your inbox. (Manual runs bypass the 8 AM check.)
3. If it doesn't arrive, open the run in the Actions tab and read the log — it
   prints exactly what went wrong. See Troubleshooting below.

Done. From now on it emails you automatically Sun–Fri around 8 AM Eastern.

---

## Changing what you follow (anytime, no code)
Just edit the **Google Sheet** from Step 3.
- **Watchlist tab** — add/remove companies (Company, Ticker, Exchange, Sector,
  Priority). Use `Core` for names you want surfaced more readily, `Watch` for
  top-tier-only.
- **Sectors & Themes tab** — this is the main driver. Add a theme, list a few
  search terms, set **Include?** to `Y` or `N`.
Changes take effect on the next morning's brief.

---

## How ranking works (the quality bar)
- **High** = immediate/critical impact: scheduled macro (CPI, jobs, GDP, rate
  decisions), systemic/geo shocks, sector regulation, and top-tier company
  events (M&A, leadership change, guidance change, dividend cut).
- **Medium** = shapes the sector but not a same-day shock (industry trends,
  product/contract news, routine dividend/buyback, secondary data).
- **Low** = delayed/backward-looking (earnings result alone, analyst ratings,
  insider trades).
- **Excluded** = opinion / stock-tip outlets (Motley Fool, Zacks, Seeking Alpha
  opinion, TipRanks, etc.).
- **★** marks the read-first shortlist; **\*** marks an item that's big for that
  specific company. Duplicate stories across outlets collapse to one line,
  keeping the most reputable source.

---

## Troubleshooting
- **No email:** check the Actions log. Most often a secret is missing/typo'd, or
  the Gmail app password was pasted with the account's normal password by mistake.
- **"SHEET_ID is not set":** the `SHEET_ID` secret is missing or misspelled.
- **Watchlist looks empty:** the Sheet isn't shared as *Anyone with the link →
  Viewer*, or a gid is wrong.
- **Calendar section empty:** the `FMP_API_KEY` is missing or the free daily
  limit was hit; the rest of the brief still sends.
- **Wrong send time / daylight saving:** handled automatically; the program only
  proceeds at 8 AM Toronto time and skips Saturday.

## Want sharper summaries later?
The "why it matters" lines are currently rule-based. Dropping in a Claude API key
to write those one-liners and the story clustering is a small change to
`main.py` (`add_why`) and `ranking.py` — we scoped this as an easy future upgrade.
