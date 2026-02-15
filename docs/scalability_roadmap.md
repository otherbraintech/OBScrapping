# Scalability Roadmap: From 10 to 10k Requests

## Phase 1: Local Testing (Current)

- **Scale:** 1-10 requests/day.
- **Hardware:** Local machine or single small VPS (e.g., EasyPanel, DigitalOcean Droplet).
- **IP Strategy:** Single residential/datacenter IP.
- **Limitation:** High risk of IP ban if aggressive. Slow (serial processing).
- **Cost:** ~$5-10/mo (VPS).

## Phase 2: Stability & Growth (100-500 requests/day)

To scale up, we must stop relying on a single IP and start handling concurrency.

### 1. Integrate Rotating Proxies

- **Action:** Sign up for a residential proxy service (BrightData, Smartproxy, IPRoyal).
- **Code Change:**
  ```python
  # main.py
  proxy = {
      "server": "http://proxy-service.com:8000",
      "username": "user",
      "password": "pass"
  }
  browser = await playwright.chromium.launch(proxy=proxy)
  ```
- **Cost:** ~$10-30/GB bandwidth.

### 2. Database for State

- **Action:** Replace in-memory `task_id` tracking with Redis or PostgreSQL.
- **Benefit:** Persist scrape jobs even if the container restarts.

## Phase 3: High Volume (1k-10k requests/day)

At this scale, managing browsers becomes a headache (CPU/RAM usage).

### 1. Scraping Browsers (SaaS)

- **Action:** Offload the browser execution to a service like BrightData Scraping Browser or Zyte.
- **Benefit:** Zero server maintenance. They handle IP rotation and browser fingerprinting automatically.
- **Trade-off:** Meaningful cost increase.

### 2. Queue System (Celery/Bull)

- **Action:** Separate the API (FastAPI) from the workers.
- **Architecture:**
  - **API:** Pushes jobs to Redis.
  - **Workers:** Multiple Docker containers consuming from Redis and running Playwright.
- **Benefit:** Horizontal scaling. Spin up 10 worker containers to process 10 URLs in parallel.

## Phase 4: Enterprise (100k+ requests/day)

Browser automation is too slow and expensive for massive scale.

### 1. Reverse Engineering (API-based)

- **Action:** Analyze Facebook's internal GraphQL API or mobile app private API.
- **Benefit:** Extremely fast (milliseconds vs 30s), low bandwidth.
- **Risk:** High complexity, cryptographic signing (HMAC) required, higher ban risk if detected.

### 2. Hybrid Approach

- **Action:** Use API for metadata (likes, comments count) and Browsers only for complex content (video URLs).
