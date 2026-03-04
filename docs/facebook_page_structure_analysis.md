# Facebook Page Structure Analysis (Public/Logged-out)

This document analyzes the DOM structure of Facebook pages when viewed without being logged in, which differs significantly from the structure seen by logged-in users.

## Identification of Post Containers

On public pages (like `https://www.facebook.com/MarioCronenboldOficial`), the traditional `role="article"` attribute is often missing from post containers. Instead, the page relies on deep nested `div` structures.

### Key Indicators of a Post Container:

1.  **Timestamp Link**: A link (`<a>`) with `role="link"` and an `aria-label` containing time information (e.g., "10 h", "Hace 2 días", "Yesterday").
2.  **Profile Link**: A link to the page's profile within the container.
3.  **Engagement Metrics**: Text or aria-labels matching patterns like "reactions", "comments", or "shares".

## Current Extraction Strategy (v1.1.1+)

To robustly identify posts, the scraper now follows this dual approach:

1.  **Selective Broad Selectors**: We target common class patterns like `.x1yzt60o` and structural paths.
2.  **Reverse Lookup from Timestamps**:
    - Find all `<a>` elements with `role="link"` that have a time-based `aria-label`.
    - Burbujeo (Bubble up) from these links to find a common parent container that has a minimum amount of text (potential post content).
    - Dedup containers to ensure each post is captured only once.

## Debugging Scrapes

If a scrape returns `total_posts_found: 0`, the scraper is configured to dump the full page HTML into the `_debug["full_html"]` field of the response and save it locally in `docs/last_failed_scrape_[task_id].html`.

### How to analyze the HTML:

1.  Open the dumped `.html` file in a browser.
2.  Inspect the posts and note the current parent container class.
3.  Check if the "Login Wall" (Interstital) is covering the content, which might prevent scrolling or extraction.

## Future Improvements

- **Adaptive Selectors**: Using AI to dynamically identify container patterns from the raw HTML if traditional selectors fail.
- **Session Refresh**: Automated detection of "Session Expired" states even when scraping public content, as Facebook sometimes forces a login wall.
