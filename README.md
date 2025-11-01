# Grokipedia API
**Unofficial REST API for accessing full-text content and references from Grokipedia.com** (xAI's Wikipedia-inspired knowledge base with 885K+ articles). This API scrapes and caches articles for fast, developer-friendly access—ideal for AI tools, research apps, or data pipelines.

> **Disclaimer**: This is an unofficial, community-built tool. It is not affiliated with xAI or Grokipedia. Use responsibly and respect rate limits/terms of service. Grokipedia's structure may change, affecting reliability.

## Features
* Full-Text Extraction: Get clean, parsed article text (up to ~50KB avg; truncate option available).
* References: Optional list of citation URLs (numbered).
* Caching: In-memory LRU cache (TTL: 2 days; max 1000 items) for performance.
* Rate Limiting: 100 requests/min per IP (generous for testing).
* Free & Open-Source: No API keys needed.

## API Endpoints
| Endpoint | Method | Description |Parameters | Response |
|---|---|---|---|---|
| /article/{slug} | GET | Fetch article by slug (e.g., "Elon_Musk").| Path: slug (str), Query: same as above | Article |

* Rate Limit: 100 req/min per IP. Exceeds → 429 Too Many Requests.
* Errors: 400 (Bad Request), 401 (Unauthorized), 404 (Not Found), 500 (Internal).

### Article Model
```
{
  "title": "Elon Musk",
  "slug": "Elon_Musk",
  "url": "https://grokipedia.com/page/Elon_Musk",
  "content_text": "Full extracted text...",
  "char_count": 45237,
  "word_count": 7854,
  "references_count": 42,
  "references": [
    {"number": 1, "url": "https://example.com/ref1"}
  ]
}
```

## Usage Examples

### cURL (Basic)
Fetch "Elon Musk" article:
```
curl https://grokipedia-api.com/article/Elon_Musk
```

## Contributing
1. Fork the repo.
2. Create a feature branch (git checkout -b feature/slug-normalization).
3. Commit changes (git commit -m 'Add slug normalization for ampersands').
4. Push & PR to main.

Report issues for scraping bugs or feature requests!

### License
MIT License. See LICENSE for details.

### Acknowledgments
* Built with [FastAPI](https://fastapi.tiangolo.com/).
* Scraping powered by [BeautifulSoup](https://www.crummy.com/software/BeautifulSoup/).
* Inspired by Wikipedia APIs—shoutout to xAI's [Grokipedia](https://grokipedia.com)!

---
⭐ Star this repo if it helps your project! Questions? Open an issue.