# Maintenance Guide: Keeping the Scraper Alive

## 🔄 Routine Checks (Auto-Manage)

### Daily Health Check

- **Endpoint:** `GET /health`
- **Action:** Check if the service returns `200 OK`. If not, restart the container.

### Weekly Selector Review

Facebook often randomizes CSS classes. If you see `parsing_failed` errors frequenting in logs:

1.  **Open** the target URL in a clean browser (Incognito).
2.  **Inspect** the element that failed (e.g., Description, Likes).
3.  **Check** if the `aria-label` or structure changed.
4.  **Update** `main.py` -> `run_scraper` function -> Parsing Logic section.

## 🕵️‍♂️ Anti-Bot Evasion Tuning

If you start getting "blocked_or_login_wall":

1.  **Increase Delays:**
    Change `get_random_delay(10.0, 30.0)` to `(30.0, 60.0)` in `main.py`. Slower is safer.

2.  **Rotate User Agents:**
    Add more modern User Agents to the `USER_AGENTS` list in `main.py`.

3.  **Use Proxies:**
    (See `scalability_roadmap.md`). IP reputation is the #1 blocking factor.

## 📝 Logging & Debugging

- **Logs:** Check `scraper.log` for details.
  - `INFO`: Normal operation.
  - `WARNING`: Partial parsing failure (e.g., could not find shares count).
  - `ERROR`: Critical failure (Login wall, Timeout).

To debug a specific `task_id`, grep the log file:

```bash
grep "task-uuid-here" scraper.log
```
