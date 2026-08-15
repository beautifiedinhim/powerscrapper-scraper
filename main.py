"""
PowerScrapper — Scraping Engine v2.1
A focused web scraping and lead extraction service.
Uses Bing search (no API key needed) + DuckDuckGo fallback.

Endpoints:
  GET  /health  — health check
  POST /crawl   — takes mission config, returns leads as JSON
"""
import os, re, time, json, logging
from urllib.parse import urlparse, urljoin, parse_qs, unquote
from urllib import robotparser
from typing import Optional
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ─── Configuration ───────────────────────────────────────────────────────────
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
REQUEST_TIMEOUT = 15
MAX_RETRIES = 3
RETRY_BACKOFF = 1.5
CRAWL_DELAY = 0.3

SEARXNG_URL = os.getenv("SEARXNG_URL", "")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("powerscrapper")

app = FastAPI(title="PowerScrapper Scraping Engine", version="2.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Request Models ─────────────────────────────────────────────────────────
class Connector(BaseModel):
    type: str = "search"
    query: str = ""
    url: str = ""
    urls: list[str] = []

class CustomField(BaseModel):
    name: str = ""
    label: str = ""
    type: str = "text"
    description: str = ""

class CrawlRequest(BaseModel):
    objective: str = ""
    keywords: list[str] = []
    locations: list[str] = []
    connectors: list[Connector] = []
    custom_fields: list[CustomField] = []
    max_results: int = Field(100, ge=1, le=5000)
    max_depth: int = Field(2, ge=0, le=5)

# ─── Core: robots.txt & fetching ────────────────────────────────────────────
def robots_ok(url: str) -> bool:
    p = urlparse(url)
    rp = robotparser.RobotFileParser()
    try:
        rp.set_url(f"{p.scheme}://{p.netloc}/robots.txt")
        rp.read()
        return rp.can_fetch("PowerScrapper", url)
    except Exception:
        return True

def fetch_with_retry(url: str, retries: int = MAX_RETRIES) -> Optional[str]:
    if not robots_ok(url):
        logger.info(f"Robots.txt disallows: {url}")
        return None
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})
            if r.status_code < 400 and "text/html" in r.headers.get("content-type", ""):
                return r.text
            if r.status_code in (429, 503):
                wait = RETRY_BACKOFF ** (attempt + 1)
                logger.warning(f"Rate limited on {url}, retrying in {wait:.1f}s")
                time.sleep(wait)
                continue
            return None
        except requests.RequestException as e:
            if attempt < retries - 1:
                wait = RETRY_BACKOFF ** (attempt + 1)
                logger.warning(f"Fetch error on {url}: {e}, retrying in {wait:.1f}s")
                time.sleep(wait)
            else:
                logger.error(f"Failed to fetch {url}: {e}")
    return None

# ─── Search: SearXNG (primary if configured) + Bing + DuckDuckGo (fallbacks) ──
def search_searxng(query: str, count: int) -> list[str]:
    """Search using self-hosted SearXNG JSON API. No API key needed."""
    if not SEARXNG_URL:
        return []
    base = SEARXNG_URL.rstrip("/")
    try:
        r = requests.get(
            f"{base}/search",
            params={"q": query, "format": "json", "pageno": 1},
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=20,
        )
        if r.status_code != 200:
            logger.warning(f"SearXNG returned {r.status_code}")
            return []
        data = r.json()
        urls = []
        for result in data.get("results", []):
            url = result.get("url", "")
            if url and url.startswith("http"):
                urls.append(url)
            if len(urls) >= count:
                break
        logger.info(f"SearXNG: {len(urls)} results for '{query[:60]}'")
        return urls
    except Exception as e:
        logger.warning(f"SearXNG error: {e}")
        return []

def search_bing(query: str, count: int) -> list[str]:
    """Search using Bing HTML — no API key needed."""
    urls = []
    pages_to_try = min(3, (count // 10) + 1)
    for page in range(pages_to_try):
        try:
            r = requests.get(
                "https://www.bing.com/search",
                params={"q": query, "first": page * 10 + 1},
                timeout=15,
                headers={"User-Agent": USER_AGENT},
            )
            if r.status_code != 200:
                break
            soup = BeautifulSoup(r.text, "html.parser")
            for li in soup.select("li.b_algo"):
                cite = li.select_one("cite")
                if cite:
                    # cite contains display URL like "example.com › path"
                    parts = cite.get_text(strip=True).replace(" › ", "/").replace("›", "/")
                    if not parts.startswith("http"):
                        parts = "https://" + parts
                    # Validate it looks like a URL
                    if "." in parts and not parts.startswith("https://www.bing.com"):
                        urls.append(parts)
                if len(urls) >= count:
                    break
            if len(urls) >= count:
                break
            time.sleep(0.5)
        except Exception as e:
            logger.error(f"Bing search error (page {page}): {e}")
            break
    logger.info(f"Bing: {len(urls)} results for '{query[:60]}'")
    return urls[:count]

def search_ddg(query: str, count: int) -> list[str]:
    """Fallback search using DuckDuckGo HTML endpoint."""
    try:
        r = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            timeout=15,
            headers={"User-Agent": USER_AGENT},
        )
        soup = BeautifulSoup(r.text, "html.parser")
        urls = []
        for a in soup.select("a.result__a"):
            href = a.get("href", "")
            if "uddg=" in href:
                parsed = urlparse(href)
                params = parse_qs(parsed.query)
                if "uddg" in params:
                    urls.append(unquote(params["uddg"][0]))
            elif href.startswith("http"):
                urls.append(href)
            if len(urls) >= count:
                break
        logger.info(f"DDG fallback: {len(urls)} results for '{query[:60]}'")
        return urls
    except Exception as e:
        logger.error(f"DDG search error: {e}")
        return []

def search(query: str, count: int) -> list[str]:
    """Search with SearXNG (if configured) first, then Bing, then DDG."""
    results = search_searxng(query, count) if SEARXNG_URL else []
    if len(results) < 3:
        bing_results = search_bing(query, count)
        seen = set(results)
        for u in bing_results:
            if u not in seen:
                results.append(u)
                seen.add(u)
    if len(results) < 3:
        logger.info("Few results so far, trying DDG fallback")
        ddg_results = search_ddg(query, count)
        seen = set(results)
        for u in ddg_results:
            if u not in seen:
                results.append(u)
                seen.add(u)
    return results[:count]

def get_sitemap_urls(base_url: str, limit: int) -> list[str]:
    sitemap_url = base_url.rstrip("/") + "/sitemap.xml"
    html = fetch_with_retry(sitemap_url)
    if not html:
        return []
    soup = BeautifulSoup(html, "xml")
    return [loc.get_text(strip=True) for loc in soup.find_all("loc")[:limit]]

# ─── Extraction ─────────────────────────────────────────────────────────────
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", re.I)
PHONE_RE = re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)")

def extract_jsonld(soup: BeautifulSoup) -> dict:
    data = {}
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            j = json.loads(script.string or "{}")
            if isinstance(j, list):
                j = j[0] if j else {}
            if not isinstance(j, dict):
                continue
            for key in ["name", "email", "telephone", "description", "url"]:
                if key in j and isinstance(j[key], str):
                    data[key] = j[key]
            if "address" in j:
                addr = j["address"]
                if isinstance(addr, dict):
                    data["streetAddress"] = addr.get("streetAddress", "")
                    data["addressLocality"] = addr.get("addressLocality", "")
                    data["addressCountry"] = addr.get("addressCountry", "")
                elif isinstance(addr, str):
                    data["address"] = addr
        except (json.JSONDecodeError, TypeError):
            continue
    return data

def extract_microdata(soup: BeautifulSoup) -> dict:
    data = {}
    for el in soup.find_all(attrs={"itemtype": True}):
        for prop in el.find_all(attrs={"itemprop": True}):
            key = prop.get("itemprop", "")
            val = prop.get("content") or prop.get_text(strip=True)
            if key and val and key not in data:
                data[key] = val
    return data

def text_page(html: str):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    meta_desc = soup.find("meta", attrs={"name": "description"})
    desc = meta_desc.get("content", "") if meta_desc else ""
    return soup, text, title, desc

def normalize_phone(v: str) -> str:
    return re.sub(r"\s+", " ", v).strip()

def smart_extract(url: str, html: str, fields: list[dict]) -> tuple[dict, dict]:
    soup, text, title, desc = text_page(html)
    host = urlparse(url).netloc

    jsonld = extract_jsonld(soup)
    microdata = extract_microdata(soup)
    structured = {**microdata, **jsonld}

    emails = list(dict.fromkeys(EMAIL_RE.findall(text)))
    phones = list(dict.fromkeys(normalize_phone(p) for p in PHONE_RE.findall(text)))[:10]

    og_site = soup.find("meta", attrs={"property": "og:site_name"})
    h1 = soup.find("h1")
    company = (
        (og_site.get("content", "").strip() if og_site else "")
        or (h1.get_text(" ", strip=True) if h1 else "")
        or (title.split(" - ")[0].split(" | ")[0].strip() if title else "")
        or structured.get("name", "")
        or host.split(".")[0].capitalize()
    )

    phone_val = (
        structured.get("telephone", "")
        or (phones[0] if phones else "")
    )
    email_val = structured.get("email", "") or (emails[0] if emails else "")

    data = {
        "company_name": company,
        "website": host,
        "email": email_val,
        "phone": phone_val,
        "description": (desc or structured.get("description", ""))[:1500],
        "source_url": url,
        "industry": "",
        "address": "",
        "city": "",
        "country": "",
    }

    if structured.get("streetAddress"):
        data["address"] = structured["streetAddress"]
    if structured.get("addressLocality"):
        data["city"] = structured["addressLocality"]
    if structured.get("addressCountry"):
        c = structured["addressCountry"]
        data["country"] = c if isinstance(c, str) else str(c)
    if structured.get("address") and not data["address"]:
        data["address"] = structured["address"]

    evidence = {}

    for f in fields:
        name = (f.get("name") or f.get("label") or "").strip()
        label = (f.get("label") or name).lower()
        ftype = f.get("type", "text")
        hint = (f.get("description") or "").lower()
        aliases = " ".join([label, hint, name.lower()])
        value = ""

        if any(x in aliases for x in ["email", "e-mail", "mail"]):
            value = data["email"]
        elif any(x in aliases for x in ["phone", "telephone", "mobile", "whatsapp"]):
            value = data["phone"]
        elif any(x in aliases for x in ["company", "business name", "organisation"]):
            value = data["company_name"]
        elif any(x in aliases for x in ["website", "url", "domain"]):
            value = data["website"]
        elif any(x in aliases for x in ["description", "about", "summary"]):
            value = data["description"]
        elif any(x in aliases for x in ["country", "pays"]):
            value = data["country"] or (
                m.group(1).strip() if (m := re.search(r"(?:country|pays)\s*[:\-]\s*([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .'-]{2,60})", text, re.I)) else ""
            )
        elif any(x in aliases for x in ["city", "ville", "location"]):
            value = data["city"] or (
                m.group(1).strip() if (m := re.search(r"(?:city|ville|location)\s*[:\-]\s*([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .'-]{2,60})", text, re.I)) else ""
            )
        elif any(x in aliases for x in ["industry", "sector"]):
            value = (
                m.group(1).strip() if (m := re.search(r"(?:industry|sector)\s*[:\-]\s*([^|.;]{3,80})", text, re.I)) else ""
            )
        else:
            rx = re.compile(re.escape(label.replace("_", " ")) + r"\s*[:\-]\s*([^|;\n]{2,180})", re.I)
            m = rx.search(text)
            value = m.group(1).strip() if m else ""
            if not value and ftype == "url":
                a = soup.find("a", string=re.compile(re.escape(label), re.I))
                value = a.get("href", "") if a else ""

        if value:
            data[name] = value
            evidence[name] = url

    return data, evidence

def score_lead(lead: dict, objective: str) -> float:
    s = 0
    if lead.get("company_name"): s += 20
    if lead.get("website"): s += 10
    if lead.get("email"): s += 25
    if lead.get("phone"): s += 15
    filled = sum(1 for v in lead.get("custom_data", {}).values() if v)
    s += min(20, filled * 5)
    obj = (objective or "").lower()
    txt = " ".join(str(v) for v in lead.values()).lower()
    if obj:
        s += min(10, sum(1 for w in re.findall(r"\w+", obj) if len(w) > 3 and w in txt) * 2)
    return float(min(100, s))

# ─── Discovery & Crawling ────────────────────────────────────────────────────
def discover_urls(req: CrawlRequest, limit: int) -> list[str]:
    urls = []
    for c in req.connectors:
        if c.type == "url":
            urls.extend(c.urls[:limit])
        elif c.type == "sitemap":
            urls.extend(get_sitemap_urls(c.url, limit))
        elif c.type == "search":
            q = c.query or " ".join(req.keywords + req.locations) or "business companies"
            urls.extend(search(q, limit))

    if not urls:
        q = " ".join(req.keywords + req.locations) or "business companies"
        urls = search(q, limit)

    return list(dict.fromkeys(urls))[:limit]

def crawl(start_urls: list[str], max_depth: int, cap: int) -> list[tuple[str, str]]:
    queue = [(u, 0) for u in start_urls]
    seen: set[str] = set()
    pages: list[tuple[str, str]] = []

    while queue and len(pages) < cap:
        url, depth = queue.pop(0)
        if url in seen or depth > max_depth:
            continue
        seen.add(url)

        html = fetch_with_retry(url)
        if not html:
            continue

        pages.append((url, html))
        time.sleep(CRAWL_DELAY)

        if depth < max_depth:
            soup = BeautifulSoup(html, "html.parser")
            base_host = urlparse(url).netloc
            for a in soup.find_all("a", href=True):
                next_url = urljoin(url, a["href"]).split("#")[0]
                if urlparse(next_url).netloc == base_host and next_url not in seen:
                    queue.append((next_url, depth + 1))

    return pages

# ─── API Endpoints ───────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "PowerScrapper Scraping Engine",
        "version": "2.2.0",
        "searxng_url": SEARXNG_URL or "not configured",
        "search_engine": "searxng+bing+ddg" if SEARXNG_URL else "bing+ddg (searxng not configured)",
    }

@app.post("/crawl")
def crawl_endpoint(req: CrawlRequest):
    start_time = time.time()
    logger.info(f"Starting crawl: {req.objective[:80]} | max_results={req.max_results} depth={req.max_depth}")

    fields = [f.model_dump() for f in req.custom_fields]

    start_urls = discover_urls(req, req.max_results)
    logger.info(f"Discovered {len(start_urls)} starting URLs")

    pages = crawl(start_urls, req.max_depth, req.max_results * 2)
    logger.info(f"Crawled {len(pages)} pages")

    leads = []
    seen_hosts: set[str] = set()

    for url, html in pages:
        data, evidence = smart_extract(url, html, fields)
        host = data["website"]
        if host in seen_hosts:
            continue
        seen_hosts.add(host)

        custom = {
            k: v for k, v in data.items()
            if k not in {"company_name", "website", "email", "phone", "address", "city", "country", "industry", "description", "source_url"}
        }

        lead = {
            "company_name": data["company_name"],
            "website": host,
            "email": data["email"],
            "phone": data["phone"],
            "address": data["address"],
            "city": data["city"],
            "country": data["country"],
            "industry": data["industry"],
            "description": data["description"],
            "source_url": data["source_url"],
            "score": score_lead({**data, "custom_data": custom}, req.objective),
            "custom_data": custom,
            "evidence": evidence,
        }
        leads.append(lead)

    duration = time.time() - start_time
    logger.info(f"Crawl complete: {len(leads)} leads in {duration:.1f}s")

    return {
        "leads": leads,
        "stats": {
            "pages_crawled": len(pages),
            "leads_found": len(leads),
            "duration_seconds": round(duration, 1),
        },
    }
