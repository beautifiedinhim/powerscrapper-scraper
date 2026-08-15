# PowerScrapper — Scraping Engine v2.0

Lightweight FastAPI service that crawls the web, extracts lead data, and returns JSON.
Designed to be deployed separately and called from your Base44 app.

## What changed from v1

- **No database, no auth, no Celery** — Base44 handles all of that now
- **JSON-LD + schema.org microdata extraction** — dramatically better data quality
- **SearXNG search** — privacy-focused metasearch engine, no API key needed
- **DuckDuckGo fallback** — if SearXNG is unavailable
- **Retry with exponential backoff** — resilient to rate limits and transient errors
- **Fixed meta tag crash** — `NoneType.get()` bug eliminated
- **Proper logging** — visible errors instead of silent failures
- **Single file** — easy to deploy and maintain

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SEARXNG_URL` | `http://localhost:8080` | Base URL of your SearXNG instance |
| `DDG_FALLBACK` | `true` | Enable DuckDuckGo as fallback if SearXNG fails |

## SearXNG setup

SearXNG is a free, privacy-focused metasearch engine you can self-host or use via a public instance.

### Option A: Self-host (recommended for production)
```bash
# Using Docker (easiest)
docker run -d --name searxng -p 8080:8080 \
  -e SEARXNG_BASE_URL=http://localhost:8080 \
  searxng/searxng:latest

# Or using docker-compose
# See https://docs.searxng.org/admin/installation-docker.html
```

You need to enable the JSON format in your SearXNG `settings.yml`:
```yaml
search:
  formats:
    - html
    - json
```

### Option B: Public instance
Use any public SearXNG instance that has JSON output enabled:
```bash
SEARXNG_URL=https://searx.be  # or https://search.ononok.org, etc.
```

⚠️ Public instances may rate-limit or disable JSON output. Self-hosting is recommended for production use.

## Quick start (local)

```bash
cd python_service
pip install -r requirements.txt

# Start SearXNG first (in another terminal)
docker run -d --name searxng -p 8080:8080 searxng/searxng:latest

# Start the scraper
uvicorn main:app --reload --port 8000
```

## Deploy (Railway — recommended, free tier)

1. Push the `python_service/` folder to a GitHub repo
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Railway auto-detects the Dockerfile
4. Add environment variable `SEARXNG_URL` pointing to your SearXNG instance
5. Your service URL will be `https://your-app-name.up.railway.app`
6. Set that URL as `SCRAPER_URL` in your Base44 app secrets

### Deploy SearXNG alongside (recommended)
Deploy SearXNG as a second Railway service or a separate Docker container:
1. Add SearXNG Docker image: `searxng/searxng:latest`
2. Enable JSON format in `settings.yml`
3. Set `SEARXNG_URL` to the SearXNG service's internal URL

## Deploy (Render)

1. Push to GitHub
2. Go to [render.com](https://render.com) → New → Web Service
3. Connect repo, set Docker as the build type
4. Add `SEARXNG_URL` environment variable
5. Your URL will be `https://your-service.onrender.com`

## API

### `GET /health`
Returns service status and SearXNG configuration.

### `POST /crawl`
Takes a mission configuration and returns extracted leads.

```json
{
  "objective": "Find qualified African SMEs",
  "keywords": ["construction", "logistics"],
  "locations": ["Cameroon", "Douala"],
  "connectors": [{"type": "search", "query": "construction companies Cameroon"}],
  "custom_fields": [
    {"name": "decision_maker", "label": "Decision maker", "type": "text", "description": "Name and title of the purchasing decision maker"}
  ],
  "max_results": 100,
  "max_depth": 2
}
```

Response:
```json
{
  "leads": [
    {
      "company_name": "Example Corp",
      "website": "https://example.com",
      "email": "contact@example.com",
      "phone": "+237 6XX XXX XXX",
      "city": "Douala",
      "country": "Cameroon",
      "industry": "Construction",
      "description": "...",
      "source_url": "https://example.com/about",
      "score": 85,
      "custom_data": {"decision_maker": "John Doe, CEO"},
      "evidence": {"decision_maker": "https://example.com/about"}
    }
  ],
  "stats": {
    "pages_crawled": 45,
    "leads_found": 23,
    "duration_seconds": 12.5
  }
}
```

## Responsible crawling

PowerScrapper respects `robots.txt`, uses bounded crawl depth, identifies itself with a descriptive User-Agent, and includes rate limiting with delays. Use only where source terms, applicable law, and privacy requirements permit.
