# Troubleshooting Guide

## 🚫 "blocked_or_login_wall" Error

**Symptoms:**

- Webhook receives status: `error`, error: `blocked_or_login_wall`.
- Logs show "Login keywords found in title".

**Causes:**

1.  **IP Ban:** Your IP has made too many requests too quickly.
2.  **Fingerprint Detection:** Headless chrome leaks.

**Fixes:**

- **Immediate:** Stop scraping for 24 hours.
- **Short-term:** Restart your router to get a new dynamic IP (if applicable).
- **Long-term:** Use residential proxies.

## ⏳ "timeout" Error

**Symptoms:**

- Webhook never arrives or arrives with timeout error.
- Logs show `PlaywrightTimeoutError`.

**Causes:**

- Page took too long to load (slow internet or heavy assets).
- "Wait for selector" never appeared.

**Fixes:**

- Increase `timeout` in `page.goto`: change `60000` to `90000` (90s).
- Ensure your internet connection is stable.

## 📉 "parsing_failed" or Empty Data

**Symptoms:**

- Status is `success` but fields (caption, username) are `null`.

**Causes:**

- Facebook changed their HTML structure.
- The post is private or age-restricted (requires login).

**Fixes:**

- Verify the link opens in an Incognito window without login.
- If it works in browser but not scraper: Update selectors in `main.py`.
