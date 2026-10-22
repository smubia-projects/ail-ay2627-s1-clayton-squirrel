# Squirrel demo (AI Lodge)

The public, no-login version of Squirrel, deployed on Vercel. It started as a
server-free copy of `../frontend`; the AI Lodge version makes its AI features
real:

- **Try the demo** opens a demo profile (Alex's sample benefits). There are no
  accounts: the benefit list, review queue, cards and ask history are kept in
  this browser's localStorage by `src/demo/server.ts`. "Reset demo data" in the
  profile menu puts it back.
- **Add benefits** (`/add`): paste an email, upload an `.eml` file or read one
  from the sample inbox (`src/demo/sampleInbox.ts`). Each goes to the real API
  (`POST /api/extract`); the AI's result is checked by plain code and saved here.
  The credit-card picker works from the bundled card catalog.
- **Assistant**: the weekly digest and questions call `POST /api/digest` and
  `POST /api/ask`, sending the current benefit list.
- No Gmail/Outlook/IMAP connections, daily scans, reminder emails or sign-in.
- A 429 from the API shows the AI Lodge rate-limit modal; a 503 shows a
  "demo temporarily paused" notice (`src/components/QuotaModals.tsx`).

The API calls live in `src/lib/aiApi.ts`, which reads `VITE_API_BASE`.

## Run it

    npm ci
    npm run dev        # http://localhost:5173

Run the API from `../backend` at the same time (it defaults to
http://localhost:8080), or set `VITE_API_BASE` to a deployed one.

## Deploy on Vercel

Import the repository in Vercel and set **Root Directory** to `demo-frontend`.
`vercel.json` sets the build (`npm run build`, output `dist`) and sends every
page to `index.html`. Set `VITE_API_BASE` to the Cloud Run URL of the API, and
add the Vercel URL to the API's `CORS_ORIGINS`.

## Refresh the sample data

`src/demo/data.json` is captured from the real app: each account's benefits,
the card catalog and the perks each card adds. Alex's account comes from
`../demo_seed.py`; the others are `PERSONAS` in `capture_demo_data.py`.
After changing any of them, run this from the project folder:

    python3 demo-frontend/capture_demo_data.py

Dates are moved to the visitor's today automatically, so it doesn't go stale.
