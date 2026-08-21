# Job Acquisition Engine

An AI-powered resume tailoring and cover letter generation system built on top of the existing Visa-Sponsorship-Daily-Jobs radar.

## Architecture

```
engine/
├── api/                    ← FastAPI backend
│   ├── main.py             ← App entry point + all routes
│   ├── config.py           ← Pydantic settings
│   ├── models.py           ← Request/response schemas
│   ├── gemini_client.py    ← Gemini 3.7 Flash (Hybrid Reasoning)
│   ├── google_docs.py      ← Public Google Doc fetcher
│   ├── pdf_service.py      ← WeasyPrint PDF generation + HMAC tokens
│   ├── session_store.py    ← In-memory session cache with TTL
│   └── templates/
│       ├── resume.html     ← ATS-safe resume PDF template
│       └── cover_letter.html
├── extension/              ← Chrome Extension (Manifest V3)
│   ├── manifest.json
│   ├── background.js       ← Service worker
│   ├── content.js          ← JD scraper (10+ job boards)
│   └── popup/
│       ├── popup.html
│       ├── popup.js
│       └── popup.css
├── prompts/
│   ├── resume_tailor_v1.txt    ← Gemini 3.7 Flash prompt
│   └── cover_letter_v1.txt     ← Gemini 3.7 Flash prompt
├── requirements.txt
├── Dockerfile
├── railway.toml
└── .env.example
```

## Quick Start — Local Development

### 1. Backend

```bash
cd engine
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env — add GEMINI_API_KEY and SESSION_SECRET

# Start the server
uvicorn engine.api.main:app --reload --port 8000
```

Open [http://localhost:8000/docs](http://localhost:8000/docs) to see the interactive API docs.

### 2. Chrome Extension

1. Open Chrome → `chrome://extensions/`
2. Enable **Developer mode** (top right)
3. Click **Load unpacked**
4. Select `engine/extension/`
5. Click the extension icon → open Settings
6. Enter your Google Doc ID and name

### 3. Google Doc Setup

Your master resume must be shared as **"Anyone with the link can view"**.

Get the Doc ID from the URL:
```
https://docs.google.com/document/d/THIS_IS_YOUR_DOC_ID/edit
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Liveness check |
| `POST` | `/api/v1/session/init` | Fetch resume from Google Doc, create session |
| `POST` | `/api/v1/resume/tailor` | ATS-optimize resume (Gemini 3.7 Flash) |
| `POST` | `/api/v1/cover-letter/generate` | Generate cover letter (Gemini 3.7 Flash) |
| `GET` | `/api/v1/document/{session_id}/{doc_id}` | Download generated PDF |

## Deployment — Railway.app

1. Push to GitHub
2. Create a new [Railway](https://railway.app) project → Deploy from GitHub
3. Set environment variables in Railway dashboard (see `.env.example`)
4. Railway auto-detects `engine/Dockerfile` via `railway.toml`
5. Update `API_BASE` in extension settings to the Railway URL

## Security

- **Gemini API key** stays on the backend — never exposed to the extension
- **Session IDs** are UUIDv4, expire after 2 hours server-side
- **PDF download URLs** include HMAC-signed tokens
- **Rate limiting**: 10 requests/hour per IP (configurable)
- **Input truncation**: JD capped at 8,000 tokens before Gemini call

## Supported Job Boards (content.js)

LinkedIn, Indeed, Greenhouse, Lever, Ashby, Workday, JustJoin.it, SmartRecruiters, Wellfound, YC Jobs, and any site with `/jobs/` or `/careers/` in the URL.
