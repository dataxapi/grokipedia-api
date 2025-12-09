# Unofficial API for xAI's Grokipedia (not affiliated)
from api_analytics.fastapi import Analytics
from fastapi import FastAPI, HTTPException, Query, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List
from bs4 import BeautifulSoup
import requests
import re
import urllib.parse
from datetime import datetime, timedelta
from urllib.parse import urljoin  # For absolute URLs
from pathlib import Path
import sys
from collections import defaultdict
import time
import os
from dotenv import load_dotenv
from discord_webhook import DiscordWebhook, DiscordEmbed

# Load environment variables from .env file
load_dotenv()  # Add this line to load .env

app = FastAPI(
    title="Grokipedia API v0.2",
    description="Unofficial API for xAI's Grokipedia (not affiliated)",
    version="0.2.0-beta",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add FastAPI Analytics middleware with API key
app.add_middleware(Analytics, api_key=os.getenv("ANALYTICS_KEY") )

# Robust INDEX_PATH: Start from cwd, fallback to __file__ if needed
base_path = Path.cwd()
INDEX_PATH = base_path / "public" / "static" / "index.html"

# Fallback if cwd fails (rare in Vercel)
if not INDEX_PATH.exists():
    INDEX_PATH = Path(__file__).parent / "public" / "static" / "index.html"

# Conditional mount
static_dir = base_path / "public" / "static"
if static_dir.exists() and os.getenv("VERCEL") is None:
    from fastapi.staticfiles import StaticFiles
    app.mount("/static", StaticFiles(directory="public/static", html=True), name="static")

BASE_URL = "https://grokipedia.com"
_cache = {}
MAX_CACHE_SIZE = 1000  # Adjust as needed; keeps cache small (~50MB assuming avg 50KB/page)
CACHE_TTL = timedelta(days=2)

# Rate limiting setup
request_times = defaultdict(list)
RATE_LIMIT = 100  # Generous: 100 requests per window
RATE_WINDOW = 60  # 60 seconds (1 minute)

def rate_limit_dependency(request: Request):
    client_ip = request.client.host
    now = time.time()
    # Clean expired timestamps
    request_times[client_ip] = [t for t in request_times[client_ip] if now - t < RATE_WINDOW]
    if len(request_times[client_ip]) >= RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded ({RATE_LIMIT} requests per {RATE_WINDOW} seconds). Try again later."
        )
    request_times[client_ip].append(now)

class Reference(BaseModel):
    number: int
    url: str = ""

class Page(BaseModel):
    title: str
    slug: str
    url: str
    content_text: str
    char_count: int
    word_count: int
    references_count: int
    references: Optional[List[Reference]] = None

def normalize_slug(input_str: str) -> str:
    # Handle potential double-encoding from browser address bar (e.g., typing "at%26t" sends "at%2526t", decoded to "at%26t")
    input_str = urllib.parse.unquote(input_str)
    # FastAPI and query params automatically decode %26 to &, so input_str is already "AT&T" for such cases
    # This function handles both raw "AT&T" and variations like "at & t"
    # First, treat hyphens as spaces to unify with underscores and actual spaces
    normalized = input_str.replace('-', ' ')
    # Replace underscores with spaces to unify title and slug inputs
    normalized = normalized.replace('_', ' ')
    # Normalize ampersands: remove spaces around &
    normalized = re.sub(r'\s*&\s*', '&', normalized)
    has_ampersand = '&' in normalized
    if has_ampersand:
        normalized = normalized.upper()
    else:
        normalized = normalized.title()
    # Now replace spaces with underscores (ensures consistent underscore usage, no hyphens)
    normalized = re.sub(r'\s+', '_', normalized.strip())
    return normalized

def find_content_div(soup: BeautifulSoup) -> BeautifulSoup:
    div = soup.select_one('article.prose')  # Primary
    if div:
        return div
    selectors = ['div.content', 'main', 'article']
    for sel in selectors:
        div = soup.select_one(sel)
        if div:
            return div
    return soup.body

def extract_references(soup: BeautifulSoup) -> tuple[List[Reference], int]:
    # First, try to find <div id="references">
    refs_div = soup.find('div', id='references')
    if refs_div:
        # Look for ol/ul inside refs_div
        ol = refs_div.find('ol') or refs_div.find('ul')
        if ol:
            list_items = ol.find_all('li', recursive=True)
        else:
            # Fallback: direct li children of div
            list_items = refs_div.find_all('li', recursive=True)
    else:
        # Fallback: search entire soup for ol with references/citations class
        ol = soup.find('ol', class_=re.compile(r'references?|citations?', re.I))
        if ol:
            list_items = ol.find_all('li', recursive=True)
        else:
            return [], 0
    
    references = []
    for i, li in enumerate(list_items, 1):
        # Extract hrefs that are http or //, take first as singular URL
        urls = []
        for a in li.find_all('a', href=True):
            href = a.get('href')
            if href and (href.startswith(('http', '//'))):
                urls.append(urljoin(BASE_URL, href))
        url = urls[0] if urls else ""
        references.append(Reference(number=i, url=url))
    
    return references, len(references)

def get_size(obj, seen=None):
    """Recursively find size of objects"""
    size = sys.getsizeof(obj)
    if seen is None:
        seen = set()
    obj_id = id(obj)
    if obj_id in seen:
        return 0
    seen.add(obj_id)
    if isinstance(obj, dict):
        size += sum([get_size(k, seen) + get_size(v, seen) for k, v in obj.items()])
    elif hasattr(obj, '__dict__'):
        size += get_size(obj.__dict__, seen)
    if hasattr(obj, '__iter__') and not isinstance(obj, (str, bytes, tuple)):
        size += sum([get_size(i, seen) for i in obj])
    return size

def get_cache_size_bytes():
    """Calculate total memory size of the cache in bytes"""
    total = 0
    for key, value in _cache.items():
        page, ts = value
        total += get_size(key) + get_size(value)  # key is str, value is tuple (Page, datetime)
    return total

def get_cached_slugs():
    """Extract unique slugs from cache keys"""
    slugs = set()
    for key in _cache:
        slug = key.split(':')[0]  # First part is slug
        slugs.add(slug)
    return sorted(list(slugs))  # Sort alphabetically for consistency

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def read_root():
    if INDEX_PATH.exists():
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    else:
        # Fallback if file doesn't exist
        return HTMLResponse(
            content="<h1>File not found!</h1><p>Please try again.</p>",
            status_code=404
        )

@app.get("/page/{slug:path}", response_model=Page, dependencies=[Depends(rate_limit_dependency)])
async def get_page(
    slug: str,
    extract_refs: bool = Query(True),
    truncate: Optional[int] = Query(None),
    citations: bool = Query(False),
    discord: bool = Query(False)
):
    slug = normalize_slug(slug)
    
    cache_key = f"{slug}:{extract_refs}:{truncate or 'full'}:{citations}"
    now = datetime.now()
    
    if cache_key in _cache:
        page, ts = _cache[cache_key]
        if now - ts > CACHE_TTL:
            _cache.pop(cache_key)
        else:
            return page
    
    url = f"{BASE_URL}/page/{urllib.parse.quote(slug)}"
    
    resp = requests.get(url, headers={"User-Agent": "Grokipedia-API/0.1"})
    if resp.status_code != 200:
        raise HTTPException(status_code=404, detail=f"Not found: {slug}")
    
    soup = BeautifulSoup(resp.text, "html.parser")
    
    # Clean up: remove unwanted tags, but preserve references div
    unwanted_tags = ["script", "style", "nav", "header", "footer", "aside"]
    if not citations:
        unwanted_tags.append("sup")
    for tag in soup(unwanted_tags):
        tag.decompose()
    
    content_div = find_content_div(soup)
    
    h1 = content_div.find("h1")
    page_title = h1.get_text(strip=True) if h1 else slug.replace("_", " ")
    
    content_text = re.sub(r'\n{3,}', '\n\n', content_div.get_text(separator="\n\n", strip=True))
    if truncate:
        content_text = content_text[:truncate]
    if discord:
        discord_content_text = content_text[:500]
    
    words = len(re.split(r'\s+', content_text.strip()))
    
    references, refs_count = extract_references(soup) if extract_refs else ([], 0)
    
    page_dict = {
        "title": page_title,
        "slug": slug,
        "url": url,
        "content_text": content_text,
        "char_count": len(content_text),
        "word_count": words,
        "references_count": refs_count,
        "references": references,
    }
    page = Page(**page_dict)
    
    # Cache the new page (evict oldest if at max size)
    if len(_cache) >= MAX_CACHE_SIZE:
        _cache.popitem(last=False)  # Evict oldest (FIFO)
    _cache[cache_key] = (page, now)
    
    if discord:
        discord_clean_txt = discord_content_text.replace("\n\n", " ")
        webhook = DiscordWebhook(url="https://discord.com/api/webhooks/1448029503224807454/jJg3_K94BFDdwocK6bBrF6XXO3hpemqJSdfCyVHln107K5USSjyIg_ABlhrXSUa3coqi")
        embed = DiscordEmbed(title=page_title, description=discord_clean_txt, color="03b2f8")
        embed.set_thumbnail(url="https://images-ext-1.discordapp.net/external/ArUio-9FyAik8zLqdBDPhiNbQt1ozYbSL0FYvUaXXAQ/https/grokipedia.com/icon-512x512.png?format=webp&quality=lossless")
        embed.set_author(name="Grokipedia", url=url, icon_url="https://images-ext-1.discordapp.net/external/ArUio-9FyAik8zLqdBDPhiNbQt1ozYbSL0FYvUaXXAQ/https/grokipedia.com/icon-512x512.png?format=webp&quality=lossless")
        embed.set_timestamp()
        embed.set_url(url)
        embed.set_footer(text=f"{page_title} entry from Grokipedia")
        webhook.add_embed(embed)
        webhook.execute()
    # webhook = SyncWebhook.from_url("https://discord.com/api/webhooks/1371612004803936286/uhqqHO-7diNFx4JDGJxuNV8c3STc5J6YUyaPuWMj1Em_UyMqYB1vqSZ8Bu54LS-Sxk1Z")
    # webhook.send(content=f"Title: {page_dict.title}")

    return page

@app.get("/health", include_in_schema=False)
async def health(key: str = Query(..., description="Secret key for health endpoint access")):
    health_secret = os.getenv("HEALTH_SECRET")  # Load from .env
    if not health_secret:
        raise HTTPException(status_code=500, detail="Health secret not configured in .env")
    if key != health_secret:
        raise HTTPException(status_code=401, detail="Unauthorized access to health endpoint")
    cache_size_bytes = get_cache_size_bytes()
    cache_size_mb = round(cache_size_bytes / (1024 * 1024), 2)
    cached_slugs = get_cached_slugs()
    return {
        "status": "Live",
        "cached_items": len(_cache),
        "cache_size_bytes": cache_size_bytes,
        "cache_size_mb": cache_size_mb,
        "cached_slugs": cached_slugs,
        "timestamp": datetime.now().isoformat()
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)