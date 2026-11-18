# daw-screens

Full-screen wrapper pages for the TV screens at The Warehouse @ King Mill.
Each page shows the "DaW Now Showing" player inside a frame, which hides Google's grey Apps Script bar.

| TV | Fully Kiosk Start URL |
|---|---|
| Stage | https://quemit.github.io/daw-screens/stage |
| Cooking area | https://quemit.github.io/daw-screens/cooking |

Content is managed in the Google Drive folder "DaW Now Showing", not here.

## Video shrinker

Fire TVs go white on big videos. Every 5 minutes, `.github/workflows/shrink.yml` checks the
DaW Now Showing Drive folders for videos over 12 MB, makes a TV-size copy (`name_TV.mp4`, under 9 MB,
1080p H.264) in the same folder, and moves the original into `Originals`. Until then the TVs skip
the big file. Needs the repo secret `SHRINK_KEY` (same value as `SHRINK_KEY` in Shrinker.gs).
