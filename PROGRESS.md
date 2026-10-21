# Squirrel: progress notes

_Last updated: 8 October 2026_

_Renamed from BenefitApp to Squirrel on 1 October 2026. Internal names keep the old one on purpose: the database `instance/benefitapp.db`, the `BENEFITAPP_SECRET_KEY` setting and the `benefitapp_session` / `benefitapp_oauth_state` cookies. Renaming them would make existing data unreadable or sign everyone out. The project folder is still `BenefitApp/`._

Squirrel tracks memberships, vouchers and card perks so they don't expire unnoticed. Users sign in (email + password, or Google), then:

- **Connect Gmail** or **Outlook** (read-only), or **other email over IMAP** (Gmail, Yahoo, iCloud, AOL, …) with an app password. The app searches for likely benefit emails, and an OpenAI model extracts each benefit; plain code checks the result.
- **Add credit cards** from a list. Each card's recurring credits are tracked with the date they reset. No card numbers or bank connection.
- **Get email reminders** before benefits expire, set per benefit from its ⋯ menu (1 week to 1 year before), in the user's own time zone.

Anything with an uncertain expiry date goes to a review queue instead of being trusted.

---

## ⚠️ Before anything else

1. **OpenAI key: done** (5 October 2026). `OPENAI_API_KEY` is set and `OPENAI_MODEL=gpt-5.4-mini` (about 7× cheaper than the `gpt-5.5` default). Checked live on the demo account: email extraction (name, provider, value, date and code right), digest (21 benefits ranked; the second request came from the cache) and the assistant. **Still to do:** a real Gmail scan, and checking extraction accuracy on real emails. Set a monthly budget limit in the OpenAI dashboard.
2. **Google: done** (5 October 2026). `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are in `.env`, the Gmail API is enabled and the app is named Squirrel. The owner tried Google sign-in, Connect Gmail and a real scan; the only problem found (Squirrel's own reminder emails read as benefits) is fixed (section 22). While in Testing, only listed test users can sign in, and their Gmail access expires after 7 days.
3. **Email (SMTP): done.** Password resets and reminders come from `Squirrel Support <squirrelappsg@gmail.com>` (Gmail app password in `.env`). Delivery confirmed for reset emails and a sample reminder (2 October).

`server.py` loads `.env` on start, so restart it after changing `.env`.

### Google sign-in and Gmail: one-time setup

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and create a project.
2. **APIs & Services → Library:** enable the **Gmail API**.
3. **Google Auth Platform → Branding:** fill in the app name and your email. **Audience:** choose **External** and leave it in **Testing**. Add yourself and each tester under **Test users** (up to 100).
4. **Data access:** add the scopes `openid`, `email`, `profile` and `https://www.googleapis.com/auth/gmail.readonly`.
5. **Clients → Create client → Web application.** Authorised redirect URI: `http://127.0.0.1:8000/api/auth/google/callback`.
6. Copy the client ID and secret into `.env` as `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, then restart `server.py`.

Always open the app at `http://127.0.0.1:8000` (not `localhost`), so the sign-in cookie and the redirect URI match.

**Public launch warning:** `gmail.readonly` is a Google *restricted* scope. In Testing mode it works for listed test users only, and Google expires their Gmail access after 7 days, so testers must reconnect Gmail weekly (the app detects this and asks them to reconnect). Opening it to the public requires Google's verification and a yearly third-party security assessment.

### Outlook (Microsoft) sign-in: one-time setup

1. Go to [portal.azure.com](https://portal.azure.com) (a free Microsoft account works) → **Microsoft Entra ID → App registrations → New registration**.
2. Name: **Squirrel**. Supported account types: **Accounts in any organizational directory and personal Microsoft accounts**.
3. Redirect URI: platform **Web**, `http://localhost:8000/api/auth/microsoft/callback` (Microsoft only allows plain `http` on `localhost`; the server forwards the browser on to `127.0.0.1`). When hosted, add `https://<your address>/api/auth/microsoft/callback`.
4. **API permissions → Add a permission → Microsoft Graph → Delegated:** `Mail.Read`, `User.Read`, `offline_access` (plus `openid`, `email`, `profile`). No admin consent is needed for personal accounts.
5. **Certificates & secrets → New client secret.** Copy its **Value** (shown once) and the **Application (client) ID** from Overview into `.env` as `MICROSOFT_CLIENT_SECRET` and `MICROSOFT_CLIENT_ID`, then restart `server.py`. Secrets expire (up to 24 months): note the date.
6. Before launch: **Branding & properties → Publisher verification** (needs a free Microsoft Partner Network ID). Without it, people see "unverified" on Microsoft's screen, and many work and school accounts can't connect.

### Owner decisions (30 September 2026)
- **Live points balances from loyalty programs: not now** (1 October 2026). AwardWallet's API was ruled out (users need AwardWallet accounts, pricing isn't public, it needs a fixed-IP server). **Future option:** Singapore Airlines' developer portal has a KrisFlyer *Get Customer Details* API with the live miles balance, a free sandbox and a KrisFlyer partnership track; Accor's portal has partner loyalty APIs (earn, burn, account linking) but no public balance lookup. Both need a commercial partnership and a hosted app with terms and a privacy policy.
- **Other email providers: IMAP first (done), then Outlook (built 5 October 2026, section 24).** Outlook, Hotmail, Live and Microsoft 365 connect through Microsoft's own sign-in (Microsoft Graph, read-only mail), because Microsoft switched off app-password sign-in. It needs the app registration below before it works.
- **Benefit fields** (1–2 October 2026): **Type** is Membership, Subscription, Voucher or Other (Travel, Health and Retail were dropped). **Category** is Entertainment, Transport, Travel, Dining, Wellness, Shopping or Others.
- **Reminders** (2 October 2026, changed the same day): by email, 1 week before by default; each benefit's ⋯ menu → **Reminder** sets 1 week, 2 weeks, 1, 2, 3 or 6 months, 1 year before, or none. No account-wide or per-category settings.
- **No "import an email" option.** Don't build `.eml` upload or paste-an-email import; benefits come from connected inboxes, cards, or typing a benefit in by hand.

---

## How to run

```bash
cd frontend && npm run build && cd ..   # rebuild the React app after frontend changes
/opt/anaconda3/bin/python3 server.py    # then open http://127.0.0.1:8000
```

- **Server tests:** `/opt/anaconda3/bin/python3 -m pytest` in the project folder (about 10 seconds; see section 33). Run them before committing.
- **Frontend development:** run `npm run dev` in `frontend/` for live reload. It forwards `/api` requests to `server.py`, which must also be running.
- **Reset all data:** stop the server and delete `instance/` (database and the key that encrypts Gmail tokens). Users will need to sign up again.
- **Frontend dev and Google:** after Google sign-in you land on the built app at `:8000`, not the Vite dev server. Password sign-in works on both.
- `benefits.json` is from the old paste-an-email version and is **no longer used**. Safe to delete.
- **Restart after backend changes.** The server doesn't reload code; an old server keeps serving old code while the frontend is rebuilt (this caused a blank app once). Stop it with `lsof -ti:8000 | xargs kill`.
- **Python:** 3.10 or newer; dependencies are in `requirements.txt` (`cryptography`, `tzdata`): `python3 -m pip install -r requirements.txt`. On this Mac, use Anaconda Python (`/opt/anaconda3/bin/python3`), which has them. Plain `python3` in some shells is a python.org 3.13 without it. The OpenAI calls use `urllib`, so no `openai` package is needed.
- **Node:** v26 via Homebrew (`brew install node`).

---

## Project structure

| Path | What it is |
|---|---|
| `config.py` | Settings from environment / `.env` (OpenAI key and model, Google client, app URL). |
| `db.py` | SQLite storage in `instance/benefitapp.db`, plus encryption (Fernet) for Gmail refresh tokens. |
| `auth.py` | Accounts (scrypt password hashes), Google-account linking, cookie sessions, wrong-password throttling, password reset links. |
| `mailer.py` | Sends the app's own emails (reset links, reminders) over SMTP; prints them in the terminal when SMTP isn't set up. |
| `reminders.py` | Emails users before benefits expire: each benefit's reminder choice, the user's time zone, which reminders are due, the email, and the 15-minute background check. |
| `google_api.py` | Google OAuth (PKCE) and the Gmail API calls, using `urllib` only. |
| `scan_jobs.py` | Shared by every inbox scan: search keywords and limits, background jobs, and the extract → store step (an email the AI fails on 3 times is skipped). Also the cost safeguards: the marketing-email filter, the daily cap of 100 AI-read emails per user (section 29). |
| `auto_scan.py` | The daily scan (section 30): per-user on/off (off by default), started only when a signed-in user opens the app, once per local day, for every connected inbox. |
| `limits.py` | Per-user hourly caps on the requests that call OpenAI: 30 questions, 10 digests, 10 scans. In memory. |
| `account.py` | Deleting an account: confirm, refuse while a scan runs, revoke Gmail, remove Outlook and IMAP, then delete the user (everything else cascades). |
| `microsoft_api.py` | Microsoft sign-in (PKCE) and the Microsoft Graph mail calls for Outlook, using `urllib` only. |
| `outlook_sync.py` | Outlook scan: Graph search (KQL, every folder but Sent, Drafts, Deleted and Junk) → `scan_jobs`. Same limits as Gmail. |
| `gmail_sync.py` | Gmail scan: Gmail search → `scan_jobs`. Up to 50 new emails per scan. |
| `imap_sync.py` | Other email over IMAP (TLS, port 993, app password): server lookup by domain, read-only inbox search → `scan_jobs`. |
| `mailtext.py` | HTML email → plain text, for both readers. |
| `loyalty.py` | Loyalty program list (sender domains, points-expiry rules) and membership detection from who emails the user. No AI. |
| `cards.py` | Credit-card perk catalog and reset-date maths. |
| `app.py` | Core AI engine: the OpenAI Responses API client (`call_structured`, `call_text`, retries, error messages), and extraction of one benefit from email text, checked with plain code (`validate`). |
| `BenefitIntelligence.py` | Weekly digest (urgency ranking) and a Q&A assistant that answers only from the user's own benefits. |
| `server.py` | Standard-library web server. JSON API under `/api/*`, and serves the React build from `frontend/dist`. |
| `frontend/` | React 19 + TypeScript + Vite + Tailwind v4. `Root.tsx` shows sign-in or the app; `App.tsx` picks the page; pages are in `src/pages/` (Dashboard, All benefits, Assistant); `lib/router.ts` is a small History API router. |
| `.env.example` | Template for `.env`. |
| `instance/` | Created at runtime: database, encryption key and `squirrel.log` (warnings and errors, last few MB). **Never commit or share.** |

### API endpoints (`server.py`)

All except `/api/session` and the `/api/auth/*` routes need a signed-in session. POSTs must be JSON, and must come from the app's own origin.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/session` | Current user, whether Google is set up, Gmail connection, daily scan status. For a signed-in user with the daily scan on, starts today's scan if it hasn't run yet |
| POST | `/api/auth/register`, `/api/auth/login`, `/api/auth/logout` | Email + password |
| POST | `/api/auth/forgot` (body: `email`), `/api/auth/reset` (body: `token`, `password`) | Password reset by emailed link |
| POST | `/api/timezone` (body: `timezone`, e.g. `Asia/Singapore`) | Sent by the browser on every load; reminders follow it |
| GET | `/api/auth/google/start?purpose=login\|connect` | Browser redirect to Google |
| GET | `/api/auth/google/callback` | Google redirects back here |
| GET | `/api/auth/microsoft/start`, `/api/auth/microsoft/callback` | Connect Outlook (browser redirects to and from Microsoft) |
| POST | `/api/auth/verify-email` (body: `token`) | Confirms the address a link was sent to. Public: works signed in or not |
| POST | `/api/account/verification` | Sends a new confirmation link (3 an hour) |
| POST | `/api/account/email` (body: `email`) | Fixes a mistyped address before it's confirmed, and sends a link to the new one |
| POST | `/api/account/delete` (body: `password`, or `email` for Google-only accounts) | Deletes the account and all its data; clears the session cookie |
| GET | `/api/outlook/status` | Outlook connection and latest scan |
| POST | `/api/outlook/scan`, `/api/outlook/disconnect` | Scan (**calls OpenAI**; counts toward the 10 scans an hour); disconnect (benefits found are kept) |
| GET | `/api/benefits` | User's active benefits (card perks refreshed for the current period) |
| GET | `/api/benefits/removed` | Recently removed benefits (30 days), newest first, with `removed_at` and `delete_on` |
| POST | `/api/benefits/<id>/restore` | Brings back a recently removed benefit |
| POST | `/api/benefits/<id>/approve`, `/dismiss` | Review queue. Dismissed items are kept hidden so scans don't re-add them. `dismiss` is also "Remove", and "Hide until it resets" for card perks. |
| POST | `/api/benefits` | Add a benefit by hand (`source: manual`). Same fields and checks as `update`, including an optional whole-number `points` balance instead of `value`. |
| POST | `/api/benefits/<id>/update` | Edit name, provider, category, value, expiry date, terms. Also clears the review flag. |
| POST | `/api/benefits/<id>/quick` | One-tap changes from a benefit's card, any of: `used` (true/false), `used_amount` (card credits: dollars spent this period, 0 to the credit's amount), `points`, `reminder` (`null` for the default 1 week, `"off"`, or 7, 14, 30, 60, 90, 180 or 365 days). Undo sends the old values back. |
| GET | `/api/gmail/status` | Connection + latest scan progress |
| POST | `/api/gmail/scan` | Starts a background scan (**calls OpenAI**). 10 an hour, with IMAP scans. |
| POST | `/api/gmail/disconnect` | Revokes Google access and deletes the stored token |
| GET | `/api/imap` | Connected IMAP accounts, each with its latest scan status |
| POST | `/api/imap` (body: `email`, `password`, optional `host`) | Checks the sign-in, then saves the account (password encrypted) |
| POST | `/api/imap/<id>/scan`, `/api/imap/<id>/remove` | Scan (**calls OpenAI**); disconnect (benefits found are kept) |
| GET | `/api/auto-scan` | The daily scan: `enabled`, `running`, and totals (`added`, `needs_review`, `memberships`, `errors`) of the scans it last started |
| POST | `/api/auto-scan` (body: `enabled`: true/false) | Turns the daily scan on or off. Turning it on starts today's scan if it hasn't run yet (**calls OpenAI**) |
| GET | `/api/cards` | User's cards + catalog |
| POST | `/api/cards` (body: `card_key`, `anniversary_month`), `/api/cards/<id>/remove` | |
| GET | `/api/digest` | **Calls OpenAI**, unless nothing changed since the last one (`digest_cache`). 10 an hour. |
| POST | `/api/ask` | **Calls OpenAI**. Saves the question and answer to the history. 30 an hour. |
| GET | `/api/ask/history` | Last 50 questions and answers, newest first |
| POST | `/api/ask/history/clear` | |

Page URLs `/`, `/benefits` and `/assistant` all serve the React app.

---

## What has been done

### 1. `app.py`: fixes to the extraction engine
- **Model:** switched to `claude-sonnet-5-5`. Sonnet 5.5 rejects forced `tool_choice`, so extraction now uses **structured outputs** (`output_config.format` with a JSON schema).
- **Shared helper:** added `call_structured()`, used by every AI feature. It handles refusals, output cut off at `max_tokens`, and JSON parsing.
- **Fallback:** enabled server-side refusal fallback (`fallbacks="default"`, beta `server-side-fallback-2026-07-01`).
- **`max_tokens`:** raised to 16,000 (thinking is always on for this model). Effort is set to `medium`.
- **Import:** the client is created lazily, so importing the module no longer needs an API key.
- **Today's date:** now sent to the model, so relative wording like "valid for 6 months" can be worked out.
- **Validation fixes:**
  - An `explicit` or `computed` confidence with no date is now flagged.
  - Every flagged record gets a `review_reason`.
  - Unexpected fields from the model are ignored.
  - The model can't set `needs_review` itself.
- **Batch processing:** one failed email no longer stops the batch. Failures go into an `errors` list.
- **Demo email:** updated so its computed date lands in the future.

### 2. `BenefitIntelligence.py`: built on the code you started
- **Import fix:** it imported from `benefit_extraction`, which doesn't exist. It now imports from `app`.
- **Renamed** from `BenefitInterlligence.py` (typo).
- **Digest:**
  - Now uses structured outputs, and the model refers to benefits by ID.
  - Code drops IDs the model made up or repeated, and uses the real names from your records.
  - Dates of benefits waiting for review are withheld from the model.
  - Days until expiry are worked out in code.
- **Q&A search:** matches whole words and skips common words. The old substring matching let "a" match almost everything.
- **Empty lists:** both functions return a short message without calling the API.

### 3. `server.py`: new
- **Endpoints:** the JSON API above, with clear error messages for a missing key, rate limits, connection failures and API errors.
- **Missing-key bug fixed:** with no key, the SDK raises a plain `TypeError`, which previously produced an empty response.
- **Catch-all:** any unexpected error returns a JSON error instead of a blank reply.
- **Safe file serving:** serves `frontend/dist` and refuses any path outside it. This was tested.
- **Caching:** hashed asset files are cached for a year; `index.html` is never cached.
- **Network and input limits:** binds to `127.0.0.1` only, and request bodies are limited to 64 KB.

### 4. Design skill
- **Installed** UI/UX Pro Max into `.claude/skills/ui-ux-pro-max/`. The `npx claude-code-templates` installer failed because the GitHub API rate limit was used up, so the folder was fetched with a git sparse checkout. Its scripts were reviewed first: standard library only, no network access.
- **Read all 28 skill files.**
- **First design run was misclassified:** it matched "Portfolio/Personal" because the query said "personal".
- **Corrected run:** matched **Productivity Tool**:
  - flat design with quick micro-interactions
  - blue `#3B82F6` as the main colour
  - orange CTA, darkened to `#C2410C` so white button text meets 4.5:1 contrast
  - Plus Jakarta Sans throughout

### 5. React frontend: new
- **Stack:** Vite + React 19 + strict TypeScript + Tailwind v4, with light and dark mode following the system setting.
- **Sections:**
  - summary counts
  - "Expiring soonest" list with days-left badges and bars
  - weekly digest
  - review queue (confirm a date, or dismiss with two clicks)
  - Add from an email
  - Ask about your benefits
- **Skill rules applied:**
  - skip link, visible labels, inline errors announced by screen readers
  - visible focus, 44px tap targets
  - spinners on busy buttons; loading placeholders; helpful empty states; notices that disappear after 4 seconds
  - "AI-generated" labels on Claude's output
  - keyboard shortcuts (`/` → Ask, `A` → Add email)
  - error boundary, reduced-motion support, dates formatted for your locale
- **Checked with** headless-Chrome screenshots in light mode, dark mode and at 375px width. The linter (oxlint) is clean.
- **Bugs fixed during testing:**
  - rows were invisible on phones because of a fade-in animation
  - the nav highlighted the wrong section on tall screens
  - the header button pushed nav links off screen on phones
- **Removed** the old single-file `static/index.html`.

---

### 6. Accounts, Gmail and credit cards (30 September 2026)
Replaced "paste an email" with connected sources:
- **Accounts:** email + password (scrypt, min 10 characters, throttled after 5 wrong tries) and "Continue with Google". A Google sign-in links to an existing account with the same email only if Google has verified it.
- **Sessions:** random token in an HttpOnly, SameSite=Lax cookie; only its hash is stored. Cross-site requests are blocked (JSON-only POSTs plus an Origin check).
- **Google OAuth:** PKCE, a single-use state that expires after 10 minutes and is tied to the browser by a cookie, and ID token issuer/audience/expiry checks.
- **Gmail:** Google sign-in asks for Gmail read access in the same step. Password users get a "Connect Gmail" button. Refresh tokens are encrypted at rest. Scans run in the background with a progress bar. Each email is read by Claude once; failed ones are retried on the next scan. A missing API key or a revoked Google grant stops the scan with a clear message.
- **Cards:** catalog of 5 US cards (Amex Platinum and Gold, Chase Sapphire Reserve and Preferred, Capital One Venture X). Perks cover monthly, quarterly, half-yearly, calendar-year and card-anniversary resets. Anniversary perks are dated the month before the anniversary month, so reminders come early.
- **Frontend:** sign-in / create-account screen, sign-out in the header, and a new **Connections** section (Gmail + Credit cards) in place of "Add from an email". Gmail benefits link back to the email.
- **Removed:** the paste form, `/api/extract` and the `benefits.json` demo store. Each user now starts empty.
- **Tested offline** with Google and Claude mocked. The throwaway scripts were not saved. They covered sign-up, login, throttling, per-user isolation, cross-site blocking, the OAuth state checks, the scan flow and the period maths. Also checked: headless-Chrome screenshots (desktop, and phone width via an iframe) and a clean lint and build.

### 7. OpenAI instead of Claude, and two new pages (30 September 2026)
- **AI provider:** all AI calls now go to the **OpenAI Responses API** (`gpt-5.5` by default, `OPENAI_MODEL` to change). The Anthropic code and the `anthropic` dependency are gone.
  - Uses Python's `urllib`, like `google_api.py`; nothing new to install.
  - Structured outputs use strict JSON schemas; both existing schemas already met the strict rules.
  - `store: false`, so OpenAI doesn't keep responses (the input is personal email).
  - Retries rate limits, 5xx and connection errors up to 3 times, respecting `retry-after`.
  - Clear messages for no key, bad key, out of credit, rate limit, unavailable model and no connection. Scans stop on any of those instead of failing every email.
  - Refusals and cut-off output become `ExtractionError`, as before.
  - Tested offline with the API mocked (every case above, plus the digest's check that drops invented IDs).
- **Pages:** the single scrolling page is now three pages with real URLs (back/forward and new-tab links work):
  - **Dashboard** (`/`): summary counts, the 5 soonest-expiring benefits with a link to the full list, review queue, connections.
  - **All benefits** (`/benefits`): search (`/` to focus), filters for category, source and status, and sorting. Each benefit can be **edited**; Gmail benefits can be **removed**; card perks can be **marked as used**, which hides them until the credit resets. The last two need a second click to confirm.
  - **Assistant** (`/assistant`): Ask, with a saved **history** of questions and answers (last 50 per user, can be cleared), and the weekly digest.
  - Each page sets the tab title and moves focus to its heading for screen readers. Shorter nav labels on phones.
- **Checked:** type check, build and oxlint clean; API tests with `curl` (edit validation, history trimming, cross-site blocking); signed-in headless-Chrome screenshots of every page, including the edit form and a 375px-wide phone. No console errors. The test account was deleted afterwards.

### 8. Adding benefits by hand, and the demo account (30 September 2026)
- **All Benefits** (heading and nav now capitalised) has an **Add a benefit** button for things not in Gmail or a card, like a paper gift card. They show as "Added by you", have their own Source filter, and can be edited or removed. They're included in the digest and the assistant.
- **`demo_seed.py`** creates or resets `demo@example.com` / `demo-benefits-2026`, with fictional Gmail benefits (3 in review), an Amex Platinum card, one hand-added benefit, a fake Gmail connection and two hand-written assistant answers. `--delete` removes it.

### 9. Other email over IMAP (30 September 2026)
- **Dashboard → Connections → Other email:** enter an address and an **app password** (the panel links to where Yahoo, iCloud and AOL create them). The server is found automatically for Yahoo, iCloud, AOL, Fastmail, Zoho, GMX, mail.com and Yandex; for anything else the user types the IMAP server. Several addresses can be connected.
- **Safety:** TLS only (port 993); the sign-in is tested before anything is saved; the inbox is opened **read-only** and emails are fetched with `BODY.PEEK`, so nothing is marked as read. App passwords are encrypted like Gmail tokens. A typed-in server must be a public host (no `localhost` or private addresses). Outlook/Hotmail and Gmail addresses are turned away with a pointer to the right option.
- **Same pipeline as Gmail:** the scan loop was moved into `scan_jobs.py`, so both use the same keywords, 6-month window, per-scan limit (now 50), AI extraction and review queue. Benefits show as "From you@yahoo.com", with an "Other email" source filter.
- **Gmail errors fixed:** a disabled Gmail API is now reported as such, instead of "access revoked" (which also deleted the connection).
- **Tested offline** with a fake IMAP server and fake AI: server lookup, the search command, email parsing (plain, HTML-only, broken), wrong password, duplicates, a 20-email inbox over two scans, disconnecting, and the Gmail scan after the refactor. Browser-checked the panel and its errors. **Not yet tried against a real provider.**

### 10. Loyalty memberships found from who emails you, and points (1 October 2026)
- **Detection (no AI, works without the OpenAI key):** every Gmail and IMAP scan first checks 13 programs in `loyalty.py`: Marriott Bonvoy, Hilton Honors, World of Hyatt, IHG One Rewards, ALL Accor Live Limitless, Wyndham Rewards, AAdvantage, Singapore Airlines KrisFlyer, British Airways Club, Delta SkyMiles, United MileagePlus, Southwest Rapid Rewards, JetBlue TrueBlue.
  - KrisFlyer miles expire a fixed 36 months after they're earned (not after inactivity), so for KrisFlyer the app shows the rule and asks for the date instead of estimating it. Accor and KrisFlyer sending domains are best guesses (`accor.com`, `accorhotels.com`, `singaporeair.com`, `singaporeair.com.sg`); add any others they really use.
  - It looks back 3 years for any email from the program's domains, reading **only the sender, subject and date**. The sender's domain is checked exactly, so lookalikes like `saa.com` or `hilton.com.evil.net` don't count.
  - The newest email whose subject looks like activity (confirmation, receipt, folio, itinerary, "thanks for staying", points earned, …) dates the last activity. Plus the program's inactivity rule (e.g. 24 months for Marriott), that gives an **estimated expiry**. Programs whose points don't expire say so; with promo emails only, the user is asked for the date.
  - Detections land in the **review queue** (source `loyalty`, "Membership found in your email"), showing how the date was worked out. Rescans refresh a detection only while it's unconfirmed; a dismissed one never returns. The scan result reports memberships found, even if the AI step then fails.
- **Points:** benefits have an optional `points` balance. The Add/Edit form has a **Value / Points** choice (memberships default to Points), and lists show "48,250 points". Points go to the digest too.
- **Demo:** `demo_seed.py` adds a detected Marriott membership (estimated date) and Delta (no expiry).
- **Tested** offline with fake Gmail/IMAP inboxes (detection, lookalike senders, dated and undated activity, rescans, dismissals) and in the browser (review queue, confirming, adding with points). Not yet run against a real inbox.
- **Limits:** activity is guessed from subject lines, so a promo titled like a receipt could shift the estimate (the user confirms every date). Only the programs listed are detected; rules and domains were written from knowledge as of mid-2025 and need checking.

### 11. Forgot password and bigger scans (1 October 2026)

- **Forgot password:** "Forgot password?" on the sign-in screen asks for an email and sends a one-time link (`/reset-password#token=…`) that works for 1 hour. The token sits after `#`, so it never reaches server logs; only its SHA-256 is stored. Choosing a new password signs out every other session and signs the user in. The form answers the same whether or not the account exists, the email is sent in the background (so timing doesn't reveal it either), and each address gets at most 3 links an hour. Google-only accounts can use it to add a password.
- **Sending email:** `mailer.py` uses the `SMTP_*` / `MAIL_FROM` settings in `.env` (see `.env.example`). **Until they're set, the reset email is printed in the server terminal**, and the form says so. Fine locally; set up SMTP before anyone else uses the app.
- **Bigger scans:** "Scan inbox" now reads up to **50** new emails per press (was 15; briefly 100, lowered by the owner to save tokens), with **5 read by the AI model at once** (`scan_jobs.extract_all`, `AI_WORKERS`). Emails are still fetched one at a time on the scan thread (an IMAP connection can't be shared). A fatal error such as a missing API key stops the scan early. Cost per scan is up to ~3× higher than at 15; change `MAX_EMAILS_PER_SCAN` in `scan_jobs.py` if needed.
- **Tested:** the reset flow end to end (unknown email, short password, reused link, old session signed out, old password rejected, rate limit) and in the browser; parallel extraction with a fake AI model (30 emails, 5 at once, correct counts, stops on a fatal error). **Not yet tried with real SMTP or a real 50-email scan.**

### 12. Type and category (1 October 2026)

- What used to be "Category" is now **Type**: Membership, Subscription, Voucher or Other. Travel, Health and
  Retail were dropped since the categories cover them; existing ones became a membership (points, miles, plans)
  or a voucher (credits, certificates, discounts), and card credits are vouchers.
- The new **Category** is what a benefit is spent on: Entertainment, Transport, Travel, Dining, Wellness, Shopping
  or Others. The AI picks it for new emails, each card perk has one, and the All Benefits page filters by both.
- Benefits saved before this got their category guessed from their name, provider and terms when the server
  started (`_add_benefit_types` in db.py, runs once per row). Fix any wrong guess with Edit.

- **App icon:** the original is `design/app-icon.jpg`. `frontend/public/` holds the sizes made from it (corners
  cut transparent): `favicon.png`, `icon-192.png` (also the logo in the header and sign-in screens), `icon-512.png`,
  `apple-touch-icon.png` (corners filled blue for iOS) and `manifest.webmanifest`. To change the icon, regenerate
  these from a new square image.

### 13. Expiry reminders by email (2 October 2026)

- **Reminders card** (now on the Connections page): on or off, "Usually remind me" (on the day, 1, 2 or 3 days, 1 or 2
  weeks, 1, 2, 3 or 6 months before), and **By category**: a different choice, or none, per category (say travel
  6 months, dining 1 month). Precedence: the benefit's own choice, then its category's, then the usual one. New accounts start on, 1 week before. The demo account has them off, since
  example.com isn't a real inbox.
- **Per benefit:** "Remind me" in the Add/Edit form overrides the usual setting or turns it off for that benefit
  (stored as `reminder` in the benefit's data). The row shows "No reminder" or "Reminder 3 days before" when set.
- **Time zones:** the browser reports its time zone (`Intl`) to `/api/timezone` each time the app loads, stored in
  `reminder_settings.timezone`. "Today" and the 8am start follow it; until it's known, the server's zone is used.
  The card says "after 8am Singapore time". Someone who travels gets the zone of the last device they opened.
- **Sending:** `server.py` starts a background thread that checks every 15 minutes, from 8am the user's time. Each
  user gets one email listing everything whose reminder day has come; each benefit is reminded once per expiry
  date (`reminders_sent`). Benefits waiting for review are skipped. The email links to `/benefits` and
  `/connections#reminders` using `APP_URL`, so set that in `.env` when the app is deployed (see Next steps).
- **Limits:** reminders only go out while `server.py` is running; one missed while it was off goes out at the next
  check, unless the benefit has expired by then.
- **Tested:** the rules (default, per-benefit override and off, already sent, expired, needs review, before 8am),
  the API, and the UI in light/dark and at phone width. A sample reminder (demo benefits, travel 6 months / dining 1 month) was delivered to the owner's inbox on 2 October; dates in a later year now show the year. **Not yet watched: the background thread sending one on its own** (Next steps).

### 14. Connections page (2 October 2026)

- Gmail, Other email, Credit cards and Reminders moved off the dashboard to their own page, `/connections`
  (`ConnectionsPage.tsx`), fourth in the header. On phones the header links are icons, with the current page's
  name beside its icon from 360px wide. Connecting Gmail returns to this page; "Set up connections" on an empty
  dashboard links to it.
- **All Benefits:** "Search and filter" is collapsed until its header is clicked (or "/" is pressed, which also
  focuses the search box). Filters keep applying while it's closed, and the header shows "1 filter on" etc.

### 15. The Claude Design look, and using benefits (2 October 2026)

- **Look:** restyled to match the Claude Design prototype (`design/Squirrel.html`): frosted-glass cards and header,
  a soft background glow, the design's light and dark colours, a hero panel on the dashboard and a squirrel
  illustration per category (`CategoryArt.tsx`, drawings in `src/assets/category-scenes.svg`).
- **Using benefits:** each benefit has a main button by kind (`lib/usage.ts`): vouchers and other one-time
  benefits get **Mark as used**, which moves them to a **Used** section on All Benefits (with Restore); card
  credits with a dollar amount get **Log a use** and a "$3 of $15 left" balance, and stay listed as
  "Used up · resets …" when spent; points balances get **Update balance**. Subscriptions had a renewal reminder
  switch here, replaced by the ⋯ menu's Reminder (section 16). Every change shows a toast with **Undo**.
- New saved fields `used_on` and `used_amount` (never set by the model). Used benefits get no reminders and are
  left out of the digest and the Assistant. `credit_total` is worked out from a card perk's value; Uber Cash's
  December period uses the $35.
- **Edit and Remove** moved into a ⋯ menu (`ui/MoreMenu.tsx`), drawn on `<body>` so cards can't cover it.
- Stamp cards from the design were skipped on purpose.
- **Credit cards** on Connections show as an Apple Wallet-style stack (`WalletStack.tsx`): each card's top strip
  shows; tapping one slides it to the top with the rest piled underneath, and shows its perks and Remove. Card
  faces are plain gradients by card key (no issuer logos); unknown cards get slate.
- **Animations** (from the design; all fall back to fades or nothing with Reduce Motion):
  - A 3D acorn in the dashboard hero (`acorn/HeroAcorn.tsx`, model in `acorn/model.ts`, ported from three.js r149).
    It spins as you scroll, bobs, shakes when something expires within 3 days and settles when nothing needs
    review. three.js loads only on the dashboard, as a separate file.
  - 50 falling acorns (`acorn/AcornRain.tsx`, the owner's choice), as in the prototype: on
    each Mark as used and Log a use, and when the review queue is cleared. Call `celebrate()` from `lib/motion.ts`.
  - Scanning an inbox shows the digging squirrel with "Checked 18 of 48 emails…" and an orange bar, then
    "Found 3 new benefits" with links to the review queue (`/#review`) and All Benefits. Links with a `#section`
    now scroll to that section.
  - The Assistant shows the question at once with a "Squirrel is thinking" typing indicator, and a new answer
    appears line by line (sentence by sentence for one paragraph). Only the look is staggered; screen readers get
    the whole answer at once.
  - Stat numbers count up; rows and stat cards slide in one after another; "Mark as used" shows a check and the
    row folds away; confirming a review item flies its name to the All Benefits link with "+1"; badges expiring
    within 3 days pulse once; the page links have a sliding highlight; an empty review queue shows the digging
    "All caught up" squirrel.
- **Copy code:** benefits have a `code` field. The model copies a voucher or promo code from the email, and
  `validate()` keeps it only if it appears in the email word for word, so a made-up code is dropped. Users can
  type or change it in the Add and Edit form. Cards with a code show it (selectable) and a **Copy code** button.
  The demo's Birthday drink, Store credit, Companion fare and Glow Spa vouchers have codes.

### 16. Reminders move to each benefit's ⋯ menu (2 October 2026)

- Replaces section 13's settings. The **Reminders** card on Connections, the "Usually remind me" and per-category
  choices, the Add/Edit form's "Remind me" field and the subscriptions' "Remind me before renewal" switch are gone.
- Each benefit with an expiry date has **Reminder** in its ⋯ menu. It opens "Email me": 1 week, 2 weeks, 1 month,
  2 months, 3 months, 6 months or 1 year before, or Don't remind me. Saving shows a toast with Undo. Every row with
  an expiry date shows its reminder ("Reminder 1 week before", "No reminder"); benefits waiting for review don't.
- Benefits nobody has set a reminder for get one 1 week before (`DEFAULT_DAYS`). Editing a benefit keeps its reminder.
- `/api/reminders` is removed. `reminder_settings` now holds the time zone and an on/off switch with no screen,
  which keeps the demo account quiet (`reminders.set_enabled`). Its `days_before` and `categories` columns are
  unused leftovers. The email now says to use the benefit's ⋯ menu instead of linking to Connections.
- **Tested:** setting 1 year, off and back to default through the API; a 3-day value is refused; Edit keeps the
  reminder; which benefits are due for the default, 30-day, 1-year and off choices; the picker and menu in the browser.

### 17. Hidden voucher codes (2 October 2026)

- A benefit's code shows as drifting dots, like Telegram's spoilers (`spoiler` utility in `index.css`), until it's
  tapped; then it shows as selectable text until the page is left. **Copy code** works without revealing it, and a
  failed copy reveals it so it can be selected by hand. Screen readers hear "Show the code for …" until revealed.

### 18. Light/dark toggle on phones (3 October 2026)

- The light/dark button now sits next to the account button on phones too (it was inside the account panel). To
  fit the four page icons, the logo is hidden below 400px (Home is in the nav) and the current page's name shows
  from 460px. Checked from 320px to 639px: no nav or page overflow.

### 19. The assistant reads every benefit (3 October 2026)

- `ask_about_benefits` used to send OpenAI only the 8 benefits sharing the most words with the question, so a
  question worded differently ("flights" vs "KrisFlyer") could miss the right one. It now sends all of a user's
  unused benefits, up to `SEND_ALL_UP_TO` (300), as compact JSON with empty fields left out (about 115 tokens a
  benefit; the demo account's 22 are ~2,500). Only past 300 does keyword matching pick which ones to send.
  Embeddings and a vector database were considered and skipped: one person's benefits fit in a single prompt.

### 20. Landing page and new sign-in screen (4 October 2026)

- Signed out, the app now opens on a scrolling landing page from the Claude Design file "Squirrel Login"
  (`components/landing/`): a large "Squirrel" hero with parallax hills, an acorn and leaves; three pinned
  "how it works" steps; a sideways row of example benefits with squirrel drawings; a closing line on privacy;
  then "Ready when you are." beside Snowball, a white squirrel spinning an acorn (`Snowball.tsx`), and "Sign in to Squirrel". `useLandingMotion` runs the scroll effects in one animation frame loop; Reduce
  Motion turns off the glide, parallax and sway. Colours are the `--land-*` tokens in `index.css`, with dark ones.
- The sign-in form (`AuthScreen.tsx`, now `SignInView`) keeps its logic (Google, register, forgot password,
  errors) in the design's layout: Back, "Sign in to Squirrel", the card. It opens directly after a failed Google
  sign-in or when signed out on an inner page.
- Left out from the design: its "$240 saved on average" counter (no real figure behind it). Step 3 was changed
  to match how reminders work (one email, a week before by default), not "a week before and the day before".

### 21. Backend fixes: failed emails, dates, AI limits, digest cache (4 October 2026)

- **Failed emails stop blocking scans.** `processed_emails` has `done` and `failures` (older rows count as done).
  An email the AI fails on (a refusal, bad output, an API error that isn't fatal) is tried again by the next scans,
  then skipped after `scan_jobs.MAX_TRIES` (3), so it can't use up every scan's 50-email limit. Fatal errors (no
  key, out of credit) still stop the scan without counting against the email.
- **Dates follow the user's time zone.** `reminders.user_today` gives today's date where the user is. It's used for
  days left, "used on", card credit periods (`sync_card_benefits` now requires the date), the digest, the assistant,
  scans (the date given to the AI model, the IMAP search window) and loyalty detection.
- **Per-user AI limits** (`limits.py`): 30 questions, 10 digests and 10 scans (Gmail and IMAP together) an hour.
  Past that the endpoint returns 429 with "Try again in N minutes", which the page shows as the error.
- **Digest cache** (`digest_cache` table): keyed on a hash of the user's unused benefits, their date and the model.
  Pressing Generate again with nothing changed returns the saved digest without calling OpenAI or counting against
  the limit. (The dashboard only asks for a digest when the button is pressed, not on every page load.)
- **Tested** on a copy of the database with the AI faked: 3 model calls then skipped; a once-failed email that then
  reads is done; 20:00 UTC on 31 October is 1 November in Singapore and the card credits rolled to November; the
  digest was built once for two requests and again after a change; the 31st question in an hour got a 429.

### 22. Scans skip Squirrel's own emails (5 October 2026)

- Reminder emails list expiring benefits, so a Gmail scan read the sample reminder back in as two new benefits. Gmail
  and IMAP scans now leave out email from `config.MAIL_FROM_ADDRESS` (`-from:` / `NOT FROM`). The two benefits were
  removed (dismissed, so they don't come back).

### 23. Anyone can sign in with Google, and connect Gmail with an app password (5 October 2026)

- **Google sign-in asks only for `openid email profile`** (`google_api.SIGN_IN_SCOPES`). These need no
  restricted-scope verification, so once the app is hosted, the Google client can be published (Audience → Publish
  app) and anyone can sign in. `gmail.readonly` is only requested by **Connect Gmail**, which stays limited to test
  users (and 7-day access) until Google verifies the app; its card says so and points to the app-password route.
- **Gmail over IMAP** with an app password (needs 2-Step Verification; myaccount.google.com/apppasswords). The
  "Other email" card is now **Email accounts** and lists Gmail first. For `imap.gmail.com` the scan matches the
  Gmail API scan: it opens All Mail (found by its `\All` flag, so archived email and other languages work), searches
  with the same Gmail query (`gmail_sync.SEARCH_QUERY` via `X-GM-RAW`, sent as a literal), and adds an "Open the
  email" link from `X-GM-THRID`. A rejected Gmail sign-in explains how to make an app password.
- **Tested** with a fake IMAP server (folder lookup, search, links) and a real sign-in attempt to imap.gmail.com with
  a wrong password (the new message). **Not yet tried with a real Gmail app password.**
- Someone who connects the same Gmail both ways gets each benefit twice (different sources); use one or the other.

### 24. Outlook, Hotmail and Microsoft 365 (5 October 2026)

- **Connect Outlook** card on Connections, for personal (Outlook.com, Hotmail, Live) and work or school accounts.
  Microsoft sign-in with PKCE asks for `Mail.Read`, `User.Read` and `offline_access`; the callback checks the state
  cookie like Google's, refuses a sign-in without mail access, and saves the address and refresh token
  (`outlook_connections`, encrypted). Microsoft replaces the refresh token on each use, so each scan saves the new one.
- **Scan** (`outlook_sync.py`): one Graph `$search` (KQL: `received>=` 6 months, the same keywords, not from Squirrel's
  address) across every folder, leaving out Sent, Drafts, Deleted and Junk, so archived email counts. Immutable ids,
  so moving an email doesn't make it new. Bodies come as text; each benefit links to the email in Outlook on the web.
  Membership detection runs first (sender domains in KQL). Same 50-email cap, retries, user date and hourly limit.
- On this computer Microsoft redirects to `localhost` (it refuses plain `http` elsewhere) and the server forwards the
  browser to `127.0.0.1`, where the cookies are. Disconnecting deletes the token; Microsoft has no way for an app to
  give up its own access, so the toast points to account.live.com/consent/Manage.
- Also: an error from connecting Gmail or Outlook now shows as a toast when signed in (before, it only showed on the
  signed-out page). "Outlook isn't allowed" in the app-password form now points to Connect Outlook.
- **Tested** with Microsoft and the AI faked: connect (and the localhost hop), a bad state refused, a scan that skipped
  a Sent email and added 2 with links, the rotated refresh token saved, a second scan with nothing new, disconnect.
  A real Graph request with a fake token got Microsoft's "token could not be read" error. **Not yet tried with a real
  Microsoft account.**

### 25. Account deletion, privacy policy, terms and a reviewable homepage (5 October 2026)

Step 2 of getting Connect Gmail and Connect Outlook open to everyone (Google verification and Microsoft publisher
verification both need these).
- **Delete account** in the account menu opens a dialog. Confirmed with the password, or for Google-only accounts the
  email typed out; wrong passwords count toward the sign-in limit. Refused while a scan runs. Revokes Gmail at Google,
  removes Outlook and IMAP connections, then deletes the user: every table cascades (sessions, reset links,
  connections, processed emails, cards, benefits, reminders, assistant history, digest cache), plus `oauth_states`.
- **`/privacy` and `/terms`** (`LegalPage.tsx`), public whether signed in or not. The privacy policy describes exactly
  what the code collects and keeps (extracted details, not emails; sender and subject only for memberships), OpenAI
  processing, Google's Limited Use statement (verbatim) with its four commitments, who else handles data, security,
  retention and deletion, rights, children (13+) and changes. Terms: as-is free service, "check dates yourself",
  fair use, liability, Singapore law. **Draft, not legal advice: the owner should read both, and ideally have them
  checked.** Update them whenever data handling changes (dates are in `LegalPage.tsx`).
- **Homepage** (the landing page): a "How Squirrel uses your email" section (read-only, only likely benefit emails,
  processed by AI and not kept, removable), a footer with privacy, terms and contact, and "By continuing, you agree
  to the terms and privacy policy" on the sign-in screen. The account menu links to both too.
- **Tested** on a copy of the database: a wrong password refused; the right one left nothing in any table for that
  user, revoked the Gmail token and cleared the session, other users untouched; Google-only confirmation by email.
  Screenshots of the privacy page, homepage section, footer, account menu and dialog.

### 26. Scan a code, and a sharper tab icon (5 October 2026)

- **Scan a code** on All Benefits (`ScanCodeDialog.tsx`): reads a QR code or barcode with the camera, from a photo, or
  typed in, and says which saved benefit it belongs to. Matching (`lib/codes.ts`) is on the device: letters and digits
  only, any case, so "bday 7q2k" matches BDAY-7Q2K; codes of 5+ characters also match inside a longer scan, like a
  redemption link ending in the code. A link shows its website and an "Open the link" button. No match offers "Add as
  a new benefit" with the code filled in. A code only holds text, so unknown codes can't be looked up anywhere.
- Reading uses `barcode-detector` (ponyfill, MIT) over ZXing WebAssembly, pinned with `zxing-wasm` 3.1.3. Both load
  only when the scanner opens (43 KB script + 1.1 MB `.wasm`), and the `.wasm` is served by Squirrel, not a CDN.
  The camera needs https (or `127.0.0.1` on this computer), so phones need Squirrel hosted; photos and typing work
  anywhere. The camera stops whenever the dialog closes or shows a result.
- **Tested** in headless Chrome with a fake camera: the stream starts; typed "bday 7q2k" matched; a QR photo of
  `https://shop.example.com/redeem?c=BDAY-7Q2K` decoded, matched and showed the link; an unknown code opened Add with
  the code filled in; "Show it in my list" opened the right ticket. **Not yet tried with a real camera on a phone.**
- Tab icon: `favicon.ico` (16, 32, 48 px) and `favicon-32.png` made from the 512 px app icon, with `?v=2` on the links
  so browsers fetch the new icon instead of a saved one.

### 27. Security fixes: account pre-hijacking, headers, timeouts; requirements.txt (6 October 2026)

- **Pre-hijacking fixed.** Before, someone could sign up with another person's address and a password of their own,
  wait for that person to sign in with Google (which linked to the same account), and then read their benefits with
  the password. Now `users.email_verified_at` records when the address was proven (Google said it's verified, or a
  reset link sent to it was used; existing Google-linked accounts were marked on upgrade). Linking Google to a
  password account whose address was never proven removes the password and signs out its sessions; the page says so
  ("password_removed" notice) and "Forgot password" sets a new one. This column is also the start of email
  verification (next steps).
- **Security headers** on every response (`SECURITY_HEADERS` in `server.py`): `X-Frame-Options: DENY`, `nosniff`,
  `Referrer-Policy: same-origin`, `Cross-Origin-Opener-Policy`, a `Permissions-Policy` that allows only the camera
  (for the scanner), and HSTS once `APP_URL` is https. The page gets a **Content-Security-Policy**: Squirrel itself
  plus Google Fonts, inline scripts allowed by hash (worked out from the built `index.html`, so the theme script
  keeps working if edited), `'unsafe-inline'` styles for React style attributes, `'wasm-unsafe-eval'` for the
  scanner, `frame-ancestors 'none'`. **Adding a new outside script, font or API means updating the CSP.**
- **30-second timeout** on idle connections (`Handler.timeout`), so stalled clients can't hold threads.
- **`requirements.txt`**: `cryptography` and `tzdata` (for `zoneinfo` on systems without time-zone data); Python 3.10+.
- **Tested:** on a database copy, the attacker's password and session stopped working while a verified owner kept
  theirs; headers present on pages and the API; a stalled connection closed after 30 s; in Chrome with the CSP, the
  homepage, Google font, theme script, dashboard, privacy page and the scanner (WebAssembly) all worked with no
  violations, and framing Squirrel from another site was refused while a control page framed fine.

### 28. Email verification (soft gate) (6 October 2026)

- Sign-up emails a **"Confirm your email for Squirrel"** link (`/verify-email#token=…`, one use, 24 hours, token
  hashed in `email_verifications`, after `#` so it stays out of logs). People use Squirrel straight away; until they
  confirm, a banner offers **Resend** (3 an hour) and **Wrong address?** (password accounts, before confirming), and
  **no reminder emails go to the address** (`reminders.run_due` skips unconfirmed users). That stops Squirrel
  emailing someone whose address a stranger typed in.
- The link works signed in or not; a link sent to an old address stops working once the address is changed.
  Confirming also means adding Google sign-in later keeps the password (section 27). Google sign-in and reset links
  already count as confirming.
- **Owner's choice:** the 7 accounts that existed on 6 October 2026 were all marked as confirmed (one-time, when the
  `email_verifications` table was first created).
- **Tested** on a database copy with email captured: sign-up sent one link; reminders skipped the address; resend
  limit; changing the address killed the old link and sent a new one; a taken address refused; the link confirmed
  once and not twice; Google sign-in afterwards kept the password. In Chrome: banner, "Wrong address?" form, the
  confirmation page (token removed from the address bar) and the banner gone afterwards.

### 29. Cost safeguards before automatic scans (6 October 2026)
Three limits on what reaches OpenAI, ready for the planned daily automatic scan. All are in `scan_jobs.py`.
- **Daily cap:** at most `DAILY_EMAIL_CAP` (100) emails per user per day go to the AI model, across Gmail, Outlook and IMAP scans together. The day is the user's own date. The count is kept in the database (`ai_email_usage`), so a restart doesn't reset it, and each email is claimed in one SQL statement, so scans running at once can't go over. Emails over the cap wait for a later scan, and the scan result says "That's the most Squirrel reads in a day." A failed AI call still counts (it was paid for); an error that stops the whole scan (such as a missing key) gives its slot back.
- **Marketing filter (no AI):** `looks_promotional` skips an email that has an unsubscribe link and a marketing phrase ("% off", "shop now", "view in browser", …) but none of the phrases that point to the user's own benefit ("your voucher", "valid until", "you've earned", "promo code", …). It's cautious on purpose. Skipped emails are marked `filtered = 1` in `processed_emails` and never checked again; to have them read again after changing the filter, delete those rows. The scan result shows "N marketing emails skipped". Filtered emails don't count toward the daily cap.
- **Active users:** `users.last_active_at` is updated whenever a signed-in user uses the app (at most hourly). It was meant to choose whom an automatic scan covers; the daily scan (section 30) runs only while the user is in the app instead, so nothing reads it now.
- Checked with the AI mocked, on a copy of the database: the filter cases, the cap stopping at its limit in a scan and across days, and the activity time being recorded.

### 30. Daily scan, on or off per user (6 October 2026)
- **Off for everyone until they turn it on:** Connections → **Daily scan** switch (`users.auto_scan`, default 0).
- **Only while the user is in the app.** There's no background schedule and nothing runs while users are away. When a signed-in user opens Squirrel (`GET /api/session`), or turns the switch on, `auto_scan.maybe_start` scans every connected inbox (Gmail, Outlook, each IMAP account) if it hasn't already run that day in the user's time zone (`users.auto_scan_last_on`, claimed in one SQL statement so two requests can't both start it).
- Same limits as pressing Scan inbox: the daily cap and marketing filter (section 29), 50 emails per inbox per scan. It doesn't use up the hourly manual-scan limit.
- The app follows the scan from any page (`App.tsx` polls `/api/auto-scan`), reloads the benefit list when it finishes, and shows a toast when it found something ("Daily scan found 3 new benefits", with a link) or an inbox failed. Turning the switch on while on Connections remounts the inbox panels so they show the scan's progress.
- **Checked:** the on/off and once-a-day logic with the scans mocked, on a copy of the database; in the browser (demo account, with today's scan pre-marked so its fake Gmail wasn't scanned): the switch turns on, stays on after a reload, turns off, and fits at phone width. **Not yet watched: a real daily scan of a real inbox.**
- A Gmail connection in Testing mode expires after 7 days; a daily scan then fails like a manual one would and asks the user to reconnect.

### 31. Singapore credit cards (6 October 2026)
- **20 Singapore cards added to the card list** in `cards.py`, chosen from the cards Singapore comparison sites (SingSaver, MoneySmart and others) ranked most popular in 2026. There's no public data on which cards are used most, so popularity rankings stood in for it. Cashback: UOB One, DBS Live Fresh, Citi Cash Back, Citi Cash Back+, OCBC 365, OCBC FRANK, UOB Absolute Cashback, UOB EVOL, Maybank Family & Friends, Standard Chartered Simply Cash. Rewards: HSBC Revolution, Citi Rewards, DBS Woman's World, UOB Lady's. Miles: Citi PremierMiles, DBS Altitude, UOB PRVI Miles, HSBC TravelOne, KrisFlyer UOB, Amex KrisFlyer Ascend. None were already in the list (it had 5 US cards).
- **Rates, caps and fees were checked against each issuer's own pages (October 2026)**, except the UOB Lady's bonus cap and fee and the Maybank annual fee, which came from SingSaver/MoneySmart, and were left out where no source was found (DBS Live Fresh fee, Maybank fee).
- **Two kinds of benefit per card now:** `perks` reset on a schedule and become tracked benefits with reminders (lounge visits on Citi PremierMiles, DBS Altitude, UOB PRVI Miles and HSBC TravelOne; the Amex KrisFlyer Ascend Hilton night). `features` (cashback and miles rates, caps, fees) are shown for reference only, in the picker and in the opened card in the wallet, since nothing there expires. Most Singapore cards have only features.
- **Left out on purpose:** monthly cashback caps as tracked perks (a cap isn't money you lose, and many reset on the statement month, whose dates Squirrel doesn't know); the Amex Ascend's lounge passes (in an older terms PDF but not on Amex's current page).
- The dropdown groups cards under Singapore and United States. Each card has a plain colour in the wallet (no logos). Each card says when it was last checked (`SG_CHECKED`, `CATALOG_CHECKED`).

### 32. Recently removed, with undo (6 October 2026)
- **Removing a benefit is no longer final.** It goes to **Recently removed**, a collapsible list at the bottom of All Benefits, with the date it was removed, the date it will be deleted, and a **Restore** button. The "Removed …" toast also has **Undo**. This covers everything removed: Remove, "Hide until it resets" on card perks, and dismissals in the review queue.
- **After 30 days it's deleted for good** (`db.REMOVED_KEEP_DAYS`). The reminder thread's 15-minute check also runs `db.purge_removed_benefits`, so this happens even if the user never opens the list; the list and Restore purge first too. A deleted benefit's details are wiped (`status = 'deleted'`, `data = '{}'`), but the row and its `source_ref` stay, so a rescan, the loyalty check or the card perks can't add it back.
- New column `benefits.dismissed_at`. Benefits removed before this change were given the date of the upgrade, so they have the full 30 days from 6 October 2026.
- A removed card perk still disappears when its period resets (as before), since the next period's perk is a new benefit.
- API: `GET /api/benefits/removed`, `POST /api/benefits/<id>/restore`.
- Checked on a copy of the database (remove, restore, the 30-day deletion, and a deleted benefit not coming back) and in the browser on the demo account (remove from the ⋯ menu, Restore from the list, Undo on the toast; the demo data was left as it was).

### 33. Automated server tests (7 October 2026)
- **111 tests in `tests/`**, run with `python3 -m pytest` (pytest comes with Anaconda; elsewhere `pip install -r requirements-dev.txt`). They take about 10 seconds.
- **They never touch real data or the outside world.** `tests/conftest.py` gives every test its own empty database in a temporary folder, captures email instead of sending it (`.env`'s SMTP settings are switched off before `config.py` loads), and fails any test that tries to reach OpenAI, Google, Microsoft or an SMTP server. Checked: the real `instance/benefitapp.db` is unchanged after a run.
- **What they cover:** `test_extraction.py` (the plain-code checks on AI output), `test_scan_safeguards.py` (marketing filter, daily cap, retries), `test_auto_scan.py` (daily scan on/off, once a day), `test_cards.py` (reset dates incl. leap years and anniversaries, the card list, perks becoming benefits), `test_recently_removed.py` (restore, 30-day deletion, nothing coming back after a rescan), `test_auth.py` (sign-up, lockout, sessions, reset and confirmation links, the Google account takeover protection, account deletion), `test_reminders.py` (who's emailed, when, in which time zone, only once), `test_api.py` (the real server on a spare port: sign-in, JSON and origin checks, one user never seeing or changing another's benefits).
- **Shown to catch real bugs:** re-creating section 29's lost-lines bug, ignoring the daily cap, and letting one user restore another's benefit each made tests fail.
- **Not covered yet:** the Gmail, Outlook and IMAP scanners themselves (they need fake mail servers), the assistant and digest (OpenAI), and the React screens.

### 34. US cards checked against the issuers' pages (8 October 2026)

- Checked the 5 US cards against American Express, Chase and Capital One's own card pages (`CATALOG_CHECKED`).
- **Amex Platinum:** added the Uber One credit ($120 a calendar year) and the Walmart+ credit ($12.95 plus tax a
  month); CLEAR+ is now $219 (was $209); the digital entertainment and hotel terms name what's eligible. The Saks
  credit (retired 1 July 2026) was never listed. Oura wasn't on the card page, so it isn't listed.
- **Amex Gold:** the dining credit's partners are now Grubhub (and Seamless), Buffalo Wild Wings, Five Guys, The
  Cheesecake Factory and Wonder.
- **Chase Sapphire Reserve:** The Edit is now up to $250 a stay, $500 a calendar year (was $250 each half); DoorDash
  is $25 a month ($5 restaurant + two $10 other orders, was $5); added the Peloton credit ($10 a month, through 2027).
  Not added: the 2026-only $250 select-hotel credit (the catalog has no end dates) and the $75,000-spend credits.
  Some news sites report the $5 restaurant promo becoming $15 from 1 October 2026; Chase's page didn't show it yet.
- **Chase Sapphire Preferred:** the hotel credit is $100 (was $50, since June 2026); added the $10 monthly DoorDash
  non-restaurant promo.
- **Capital One Venture X:** the $300 travel credit is now taken off at checkout on Capital One Travel, not refunded.
- A perk already saved for the current period keeps its old value until it resets (next month for monthly credits,
  the next anniversary for the Sapphire Preferred hotel credit).

### 35. Extraction checked against real emails; date, benefit and duplicate fixes (8 October 2026)

- **Check:** the 22 benefits a Gmail scan found on the owner's account were compared with their emails (read
  through the Gmail connector). Every value, date and voucher code that was saved matched its email (5 of 5 codes
  word for word). Problems: 3 missed expiry dates (`Valid Till: 11/10/2026`, `until midnight 4/10/26`,
  `expiring end of October 2026`), 1 duplicate (the same iShopChangi code in two emails) and 3 non-benefits (a
  menu price, an ad for a new credit card, a product announcement). 15 of 22 fully right.
- **Fixed on the account:** the two dates added; the expired offer, the duplicate and the three non-benefits removed
  (they're in Recently removed).
- **Scanner:** the extraction prompt now reads numeric dates as day/month (Singapore), "end of <month>" as its last
  day and a date range as its last day, and says what isn't a benefit (announcements, menu prices, ads for new
  cards, loans or accounts). `scan_jobs.extract_and_store` skips an offer that has already expired and one whose
  voucher code is already tracked. The five problem emails, re-run live, all came out right. 3 new tests (114).
- The owner's Gmail now connects with an app password over IMAP (the Google connection had hit its 7-day expiry);
  a read-only test signed in and found 710 matching emails.
- **Gmail read both ways:** an IMAP scan of a Gmail inbox now skips emails a Gmail API scan already read
  (`imap_sync.gmail_message_ids`: Gmail's IMAP `X-GM-MSGID` is the API's message id in decimal). Without it, the
  first app-password scan re-read them and added duplicates and previously removed entries.
- **First app-password scan** (50 emails): 9 marketing, 28 not kept, 13 saved; 6 of the 13 right. The 7 wrong were
  5 already-expired emails listing several dated coupons (the AI called the date "ambiguous") and 2 non-benefits.
  The prompt now takes the latest of the offers' own "valid until" dates (never event, travel or application
  dates), gives ongoing membership perks no expiry, and excludes "buy more, get a bonus" offers and bonuses that
  need a new card. Re-run, 11 of the 13 came out right (KrisFlyer lost its date and goes to review; a PAssion
  newsletter picked a deal's date). The earlier five problem emails still pass.

### 36. Failures the user couldn't see (21 October 2026)

- **Retry failed emails:** an email the AI model fails on 3 times is skipped by scans. Connections now says how
  many there are, with a "Try them again" button (`/api/scan-failures`, `scan_jobs.retry_given_up`).
- **Reminder emails that don't get through:** a failed send records `reminder_settings.failing_since` (the first
  failure; cleared by the next send that works). The session returns it and the app shows a banner.
- **Scans cut short by a restart** now show "The scan stopped when Squirrel restarted. Scan again to continue"
  instead of disappearing: running scans are kept in the `running_scans` table, and `scan_jobs.mark_interrupted`
  reads what's left there at startup.
- **Log file:** warnings and errors (failed scans, reminder sends, unexpected server errors) go to
  `instance/squirrel.log` as well as the terminal, with dates, rotated at 1 MB (3 old files kept). Request lines and
  emails printed when SMTP isn't set (they hold reset links) stay in the terminal only.
- 5 new tests (120).

## Known gaps and limitations

- **Extraction checked once on real emails** (22 benefits, section 35), not with a repeatable eval. Offers without a code that arrive in several emails can still be listed twice.
- **Card perk catalog is hand-written**: US cards checked 8 October 2026 (section 34), Singapore cards 6 October 2026 (section 31). A perk already saved for the current period keeps its old value or wording until the period resets. Issuers change perks; verify each card before trusting it. Custom cards and user-defined perks aren't supported yet.
- **Unconfirmed accounts are kept forever.** Email verification is a soft gate (section 28); accounts that never confirm aren't deleted automatically.
- **AI request limits live in server memory** (`limits.py`), so a restart resets them and several server processes would each count separately.
- **Scan jobs live in server memory.** Restarting the server mid-scan loses progress (already-processed emails are kept); the scan then shows as stopped, with a message to scan again.
- **No automated browser tests.** The screens are checked by hand in a browser (light, dark, phone width).
- **Tests cover the server only** (section 33): not the inbox scanners, the AI features or the React screens.
- **Reminders are email only**, sent by a thread inside `server.py`: none go out while the server is stopped (a missed one is sent at the next check if the benefit hasn't expired). No push or in-app notifications. The email has no one-click unsubscribe; it says to change or stop a reminder from the benefit's ⋯ menu. The background thread's own send hasn't been watched end to end yet; the sample was sent by calling the same code directly.
- **Time zone comes from the last device used.** Someone travelling gets reminders on that device's clock; there's no manual time-zone picker.
- **Sending through a personal Gmail account** is limited (about 500 emails a day) and may be flagged as bulk mail. Fine for testers; use a sending service (e.g. Amazon SES, Postmark, Resend) with a custom domain before launch.
- **Categories of benefits saved before 1 October were guessed** from their names (`_add_benefit_types` in `db.py`). Wrong guesses need fixing by hand with Edit.
- **Outlook not yet tried with a real Microsoft account** (the app registration is done). IMAP reads only the inbox (Gmail: All Mail), and a server that can't search message text can't be scanned.
- **Long emails are cut to 8,000 characters** (a known limitation for long forwarded threads).
- **SQLite, one server process.** Fine for testers; not built for many users or several servers.
- **Assistant answers appear all at once** (the blocks then rise in one by one). Streaming them as they're written would need the server to stream.
- Filters on the All benefits page aren't kept in the URL.
- **The database isn't backed up.** The code is on GitHub, but `instance/` (all user data and the encryption key `secret.key`) is deliberately not; losing the key makes saved Gmail and Outlook tokens and IMAP passwords unreadable.

---

## Next steps (suggested order)

The code is on GitHub (private): https://github.com/haid1lau/squirrel, default branch `main`. `.env` and `instance/` are never committed.

1. **Set a monthly budget limit** in the OpenAI dashboard (scans, the digest, the assistant and daily scans all cost money).
2. **Keep checking extraction on real emails** (first check done 8 October, section 35: values and codes right, dates and non-benefits fixed). Re-check after the next scan, especially dates in other formats.
3. **Back up `instance/`** (database + `secret.key`) somewhere safe from time to time.
4. **Watch a real reminder arrive.** Once your account has benefits, leave reminders on, keep `server.py` running past 8am Singapore time, and check that the email arrives once (and not again at the next 15-minute check). The demo account has reminders off on purpose (example.com isn't a real inbox).
5. **Watch a real daily scan:** turn on Daily scan on your own account, open Squirrel the next day, and check the toast, the new benefits and the OpenAI usage page.
6. **Try Connect Outlook with a real Outlook.com account.** The Microsoft app registration is done and its ID and secret are in `.env` (5 October 2026).
7. **Keep the card catalog and loyalty programs current** (`cards.py`, `loyalty.py`): issuers change perks. Add more programs (non-US hotels and airlines) as needed.
8. **Custom cards and perks.**
9. **More tests:** the server has tests (section 33). Still to add: the inbox scanners with fake mail servers, and React Testing Library for sign-in, connections and the benefit pages.
10. **Build an extraction eval** from real benefit emails.
11. **Live KrisFlyer balances (optional):** prototype against Singapore Airlines' free sandbox, then apply for a KrisFlyer partnership once the app is hosted (see Owner decisions). Talk to Accor about balance access at the same time.
12. **When Squirrel is put online, set `APP_URL` in `.env`** to its real address (e.g. `https://squirrel.example.com`). Links in emails (reminders, password resets) and the Google sign-in return address are built from it; it's `http://127.0.0.1:8000` until then, which only works on this computer. Add the new address's `/api/auth/google/callback` to the Google client's authorised redirect URIs, and `/api/auth/microsoft/callback` to the Microsoft app's.
13. **Before any public launch:** HTTPS hosting, Postgres, Google's restricted-scope verification and security assessment, Microsoft publisher verification, a lawyer's read of the draft privacy policy and terms (section 25), a proper email sending service with a custom domain (instead of a Gmail account), a one-click unsubscribe link in reminder emails, and moving reminders and daily scans out of the web server (scheduled jobs) so they keep running across restarts and several servers.
