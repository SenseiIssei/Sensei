# Ideas: web crawling & ingestion

Sensei already has the primitives — an **SSRF-guarded `fetch_url`**, **`web_search`**,
the **agent** loop, the **RAG** store, and the **compression** pipeline. Crawling is
the natural next layer: turn the open web into a compressed, searchable knowledge
base the agent can reason over. Ideas, roughly in build order.

## 1. Crawl-to-RAG (the headline)
`POST /api/rag/crawl {url, depth, max_pages}` → BFS-crawl same-domain links,
extract main text, chunk, and index into the RAG store. Then "Ask your docs"
works over a whole documentation site. Builds directly on `fetch_url` + the
`DocumentStore`.

- **Politeness:** honor `robots.txt`, per-domain rate limit, concurrency cap,
  `max_pages` / `max_bytes`, depth limit. Reuse the SSRF guard.
- **Sitemap-first:** if `/sitemap.xml` exists, enumerate from it instead of
  link-following (faster, more complete).
- **Provenance:** every chunk keeps its source URL + fetch timestamp, so RAG
  answers cite **live links**.

## 2. Clean extraction ("reader mode") ✅ (shipped)
`extract_main_text` drops chrome (nav/header/footer/aside/scripts/forms) and
keeps prose — used by `fetch_url`, the crawler, and `POST /api/rag/ingest`.
**PDF ingestion** via pypdf (`extract_pdf_text`); `fetch_url`/ingest auto-detect
PDFs. Next: `.docx`, and a possible Rust port of the extractor.

## 3. Compressed, incremental crawl cache
Store fetched pages **compressed** (the existing compressors / CCR), dedupe
near-identical pages, and re-crawl incrementally using `ETag` / `Last-Modified`.
Surface "tokens saved by ingestion" in the savings dashboard.

## 4. Scheduled / watched sources ✅ (shipped)
A background loop re-fetches configured URLs on an interval, re-indexes changed
pages into RAG, and POSTs a change alert to a notify webhook. API: `POST/GET
/api/watch`, `DELETE /api/watch/{id}`, `POST /api/watch/check`. Content-hash
diffing; first fetch is the baseline. Next: per-watch crawl (not just single
page), and richer diffs (which sections changed).

## 5. Research agent ✅ (shipped)
The agent now has `web_search`, `fetch_url`, `ingest_url`, `crawl_site`, and
`rag_search` tools — so it can `search → ingest/crawl → rag_search → synthesize`
on its own, multi-hop, with tool results compressed before feedback. Next:
auto-pick depth, and a "deep research" preset with a higher step budget.

## 6. Structured extraction
A tool that pulls tables, JSON-LD, and OpenGraph metadata from pages → then
**SmartCrusher** packs the JSON. Great for price/spec/feed monitoring.

## 7. JS-heavy sites (optional, flagged)
A headless-browser fetch (Playwright) behind a flag for sites that need
rendering — same SSRF/politeness guards, just a different fetch backend.

## Safety posture (applies throughout)
SSRF guard on every hop (already done), domain allow/block lists, global
byte/time budgets, `robots.txt`, and everything **off or rate-limited by
default**. Crawling is powerful; keep it boring and bounded.

---

**Next concrete step:** implement #1 (`crawl_site` tool + `/api/rag/crawl`) on top
of `fetch_url` + `DocumentStore`, with robots.txt + caps.
