# Deployment Guide

## ❌ Why NOT Vercel?

You asked about Vercel, but **it is not recommended** for this specific project.

### The Reasons:

1.  **Timeout Limits:** Vercel Serverless Functions have a hard limit of **10 seconds** (Hobby) or **60 seconds** (Pro). Our scraper intentionally waits 10-30 seconds to simulate human behavior. It will be killed before it finishes.
2.  **Binary Size:** Vercel has a 50MB function size limit. The Chromium browser required by Playwright is ~150MB+.
3.  **Ephemeral Filesystem:** Taking screenshots or saving logs to disk is difficult.

---

## ✅ Recommended: Docker-based Hosting

Since you have a `Dockerfile`, the best way to deploy is using a service that runs containers.

### Option A: EasyPanel (Recommended)

_I see you use EasyPanel for your n8n instance (`easypanel.host`). This is the easiest path._

1.  **Login** to your EasyPanel dashboard.
2.  **Create Project** (or use existing).
3.  **Add Service** -> **App**.
4.  **Source:**
    - If your code is on GitHub: Select your repo.
    - If not: You can use the "Image" option if you push your image to Docker Hub, but GitHub is easier.
5.  **Build Method:** Select "Dockerfile".
6.  **Environment Variables:**
    - Key: `WEBHOOK_URL`
    - Value: `https://intelexia-labs-n8n.af9gwe.easypanel.host/webhook-test/...`
7.  **Deploy.**

EasyPanel will build the Docker container and run it. It doesn't have the 10s timeout limit.

### Option B: Railway / Render (Alternatives)

If you don't have access to the EasyPanel server for this app:

1.  **Push** your code to a GitHub repository.
2.  **Sign up** for [Railway.app](https://railway.app) or [Render.com](https://render.com).
3.  **New Project** -> Select your GitHub repo.
4.  They will automatically detect the `Dockerfile`.
5.  **Variables:** Add `WEBHOOK_URL` in the settings.
6.  **Deploy.**

---

## 🌍 Exposing to Internet

Once deployed, you will get a public URL (e.g., `https://my-scraper.up.railway.app`).

**Update your n8n workflow:**
Change the HTTP Request URL from `http://127.0.0.1:8000/scrape` to `https://my-scraper.up.railway.app/scrape`.

---

## 🔧 Troubleshooting

### "No such image" Error (EasyPanel)

If the deployment fails with `No such image: easypanel/intelexia-labs/obscrapping:latest`, it means the **Build Phase failed**.

**Common Cause: Typo in Dockerfile Path**
If the Build Log says `failed to read dockerfile: open Dockefile...`:

1.  Go to **Project -> Services -> App -> Build**.
2.  Find **Docker File Path**.
3.  Change it from `Dockefile` to `Dockerfile`.
4.  Click **Save** and then **Rebuild**.
