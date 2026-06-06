# ProAppsFactory — Public Assets

Static public assets for the iOS micro-app factory. Served via GitHub Pages.

## Files

- **`dashboard.html`** — Factory cockpit (pipeline kanban, team view, standup log). State stored in browser `localStorage`.
- **`cross-promo.json`** — Featured app list read by each shipped app's cross-promo surface. Edit this to feature/swap promoted apps without resubmitting any app.
- **`icons/`** — App icon images referenced in `cross-promo.json` (add per app).

## URLs (after GitHub Pages is enabled)

| Asset | URL |
|---|---|
| Dashboard | `https://proappsfactory.github.io/public-assets/dashboard.html` |
| Cross-promo JSON | `https://raw.githubusercontent.com/ProAppsFactory/public-assets/main/cross-promo.json` |

## Updating cross-promo

1. Edit `cross-promo.json` — add/remove app entries.
2. Drop the app's icon PNG into `icons/<app-store-id>.png`.
3. Push to `main`. Apps fetch the new list on next launch (cached, graceful offline fallback).

## Dashboard notes

- Data is stored in `localStorage` in **your browser** — it is not shared across devices.
- The dashboard is a daily cockpit only. `05_APP_REGISTRY.md` in `factory-core` is the canonical record.
- The Orchestrator keeps both in sync.
