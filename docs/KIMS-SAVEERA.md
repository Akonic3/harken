# KIMS Saveera (Anantapur) — setup

1. Create an Outscraper account and copy the API key (first 500 reviews are free).
2. In Render → harken → Environment, set `HARKEN_OUTSCRAPER_API_KEY`. `HARKEN_GOOGLE_PLACES`
   already maps the keyword `KIMS Saveera` to "KIMS - Saveera Hospital, 1-1348 Srinagar Colony Extension,
   Rudrampeta, Anantapur 515004" (Google Maps: 4.9, ~22,000 reviews). If the wrong place is returned, replace that
   value with the place's long Google Maps link.
3. Dashboard → create project `KIMS Saveera` → keyword `KIMS Saveera` → tick **Google Reviews** → **scan latest**.
   Use **backfill** once to pull older reviews.
4. Other keywords (Telugu spellings, doctors, departments) work with RSS/YouTube; Google Reviews only runs for
   the mapped keyword so extra scans cost nothing.
5. Open the project → **client report**.

Notes
- A 4.9 average over ~22k reviews means the average carries little signal. A first scan pulls the 100 newest plus the
  300 lowest-rated reviews (about 400, inside the free 500); later scans pull only new ones.
- Sentiment for reviews follows the star rating (4–5 positive, 1–2 negative, 3 uses the text).
- Topics (waiting time, billing, staff, doctors, cleanliness, emergency, outcome) come from a fixed
  English/Telugu/Hinglish vocabulary in `src/harken/analyze/hospital_themes.py` — tune it on real reviews.
- The Outscraper request format was written from its documented API and tested with mocked responses only.
  The first live scan is the real test; if it errors, send the message shown on the dashboard.

## Comparing with other Anantapur hospitals

1. In Render → harken → Environment, extend `HARKEN_GOOGLE_PLACES` with one entry per hospital, separated by `;`:
   `KIMS Saveera=KIMS - Saveera Hospital, 1-1348 Srinagar Colony Extension, Rudrampeta, Anantapur 515004;Rival Name=Rival Hospital Name, Anantapur`
   (use each hospital's exact Google Maps name and area; check the place on Google Maps first).
2. Dashboard → create a project such as `Anantapur hospitals` → add each hospital as a keyword using the exact name on the left of the `=`.
3. Tick **Google Reviews** and scan each keyword once. Each first scan fetches ~400 reviews (about $1 after the free 500).
4. Open the project's **client report**: "How the hospitals compare" shows Google rating, total reviews, 1–3★ share,
   growth and top complaint per hospital. The table's *own report* links open one hospital's issues alone.
5. Growth needs two scans at least a day apart (scan again a few days later); it shows how fast a hospital gains reviews,
   so a sudden jump can reveal a review drive.

Rating, total, 1–3★ share and growth cover every review on Google, so they compare fairly. "Top complaint" comes from
the collected sample (newest plus lowest-rated) and is not a count of unhappy patients.
