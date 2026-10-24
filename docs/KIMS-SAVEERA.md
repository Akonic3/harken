# KIMS Saveera (Anantapur) — setup

1. Create an Outscraper account and copy the API key (first 500 reviews are free).
2. In Render → harken → Environment, set `HARKEN_OUTSCRAPER_API_KEY`. `HARKEN_GOOGLE_PLACES`
   already maps the keyword `KIMS Saveera` to the Google Maps search "KIMS Saveera Hospital Anantapur".
   If the wrong place is returned, replace that value with the exact name or the place's Google Maps link.
3. Dashboard → create project `KIMS Saveera` → keyword `KIMS Saveera` → tick **Google Reviews** → **scan latest**.
   Use **backfill** once to pull older reviews.
4. Other keywords (Telugu spellings, doctors, departments) work with RSS/YouTube; Google Reviews only runs for
   the mapped keyword so extra scans cost nothing.
5. Open the project → **client report**.

Notes
- Sentiment for reviews follows the star rating (4–5 positive, 1–2 negative, 3 uses the text).
- Topics (waiting time, billing, staff, doctors, cleanliness, emergency, outcome) come from a fixed
  English/Telugu/Hinglish vocabulary in `src/harken/analyze/hospital_themes.py` — tune it on real reviews.
- The Outscraper request format was written from its documented API and tested with mocked responses only.
  The first live scan is the real test; if it errors, send the message shown on the dashboard.
