# n8n Integration Guide

This guide explains how to connect n8n to your local scraping API.

## 🔗 The Curl Command

Use this command to test the connection or copy the structure into n8n.

```bash
curl -X POST http://YOUR_SERVER_IP:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.facebook.com/share/r/1agjhqdRwv/",
    "network": "facebook",
    "type": "reel"
  }'
```

_> **Note:** Replace `YOUR_SERVER_IP` with your actual local IP (e.g., `192.168.1.x`) if calling from outside localhost, or `host.docker.internal` if n8n is also in Docker._

## ⚡ n8n "HTTP Request" Node Setup

If you are building a workflow in n8n, configure the **HTTP Request** node as follows:

- **Method:** `POST`
- **URL:** `http://YOUR_SERVER_IP:8000/scrape`
- **Authentication:** None
- **Send Headers:**
  - Name: `Content-Type`
  - Value: `application/json`
- **Body Content:** JSON
- **Body Parameters:**
  ```json
  {
    "url": "{{ $json.url }}",
    "network": "facebook",
    "type": "reel"
  }
  ```
  _(Assuming the previous node provides a `url` field)_

### ⚠️ Important: Localhost vs. n8n Cloud

- If n8n is **Self-Hosted (params)**: Ensure the docker container or server can reach your machine's IP.
- If n8n is **Cloud**: You must expose your local scraper to the internet using a tunnel like **ngrok**:
  ```bash
  ngrok http 8000
  ```
  Then use the `https://....ngrok-free.app/scrape` URL in n8n.
