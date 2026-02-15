# Minimal Facebook Public Scraper (FastAPI + Playwright)

This project is a lightweight, stealthy scraper designed to extract public data from Facebook Reels and posts (e.g., `https://www.facebook.com/share/r/...` links) without logging in.

**Designed for:** Early testing, low volume (1-10 requests/day), no proxies, no cookies.
**Warning:** Scraping Facebook is against their TOS. Use responsibly and at your own risk.

## 🚀 Quick Start

### 1. Installation

Requires Python 3.9+.

```bash
# Create virtual environment (optional but recommended)
python -m venv venv
# Windows: venv\Scripts\activate
# Mac/Linux: source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers (Chromium)
playwright install chromium
python -m playwright install-deps  # Only needed on Linux if not using Docker
```

### 1.5 Configuration

Create a `.env` file in the root directory (or rename `.env.example` if provided):

```ini
WEBHOOK_URL=https://your-n8n-webhook-url.com/webhook/...
```

### 2. Run the Server

Start the API server locally:

```bash
uvicorn main:app --reload
```

The server will start at `http://127.0.0.1:8000`.

### 3. Usage

Send a POST request to scrape a public URL:

**Curl:**

```bash
curl -X POST http://127.0.0.1:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.facebook.com/share/r/1agjhqdRwv/", "type": "reel"}'
```

**n8n / Postman:**

- **Method:** POST
- **URL:** `http://127.0.0.1:8000/scrape`
- **Body:** JSON `{"url": "https://...", "type": "reel"}`

**Response (Immediate 202 Accepted):**

```json
{
  "status": "accepted",
  "task_id": "c5e4d3b2-...",
  "message": "Scraping started in background"
}
```

The server processes the request in the background.

## 📡 Webhook & Results

After scraping finish (success or error), the full result is sent via POST to the configured `WEBHOOK_URL` in your `.env` file.

**Example Success Payload:**

```json
{
  "task_id": "...",
  "url": "https://www.facebook.com/share/r/...",
  "status": "success",
  "scraped_at": "2026-02-15T09:00:00",
  "data": {
    "caption": "Amazing sunset! 🌅 #travel",
    "reactions_raw": "1.2K",
    "shares_raw": "50 shares",
    "comments_count_raw": "20 comments",
    "username": "User Name",
    "video_src": "https://video.xx.fbcdn.net/..."
  },
  "error": null
}
```

**Example Error Payload:**

```json
{
  "task_id": "...",
  "url": "...",
  "status": "error",
  "error": "blocked_or_login_wall", // or "timeout", "parsing_failed"
  "data": {}
}
```

## 🛡️ Anti-Detection Strategy (Stealth Mode)

- **Headless Chromium:** Configured to act like a real Chrome browser.
- **Random User-Agent:** Rotates modern user agents (Chrome/Win/Mac).
- **Random Viewport:** Varies screen resolution.
- **Human Behavior:** Simulates mouse movements, random scrolls, and variable delays (10-30s).
- **Stealth Plugin:** Uses `playwright-stealth` to mask automation signals.

## 🛠️ Maintenance: Updating Selectors

Facebook frequently changes its HTML structure (obfuscated classes like `x1yzt...`). If scraping stops working, check `main.py` and look for the parsing section.

Tips for finding new selectors:

1. Open the URL in Incognito mode (logged out).
2. Right-click likely elements -> Inspect.
3. Look for stable attributes: `aria-label`, `role`, `data-pagelet` or specific text content.
4. Update the `page.locator(...)` lines in `main.py`.

## 🐋 Docker (Production/Server)

Build and run using Docker:

```bash
docker build -t fb-scraper .
docker run -p 8000:8000 --env-file .env fb-scraper
```
