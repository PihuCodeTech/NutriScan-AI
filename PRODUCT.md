# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Students in India who live in hostels or on their own and eat at the mess, the canteen, street stalls, or from instant noodles in their room. They are budget-conscious, often unsure what their food does to them, and want a quick answer they can act on, not a nutrition course. Diets vary (vegetarian, eggetarian, non-vegetarian, vegan) and some have allergies.

They use the app on phones (photographing a plate at the mess or a stall), and on laptops and desktops in their room. All three must work equally well.

For this phase, a second audience matters: **hackathon judges** evaluating the project from a live demo.

## Product Purpose

ScanMyFood lets a student photograph a meal or a packet's nutrition label and get, within seconds, an estimate of what is on the plate: each item, its portion, calories and nutrients, a health score, and practical, budget-aware tips. It also tracks what they eat across the day and week, nudges them away from street food with a streak and rewards, suggests cheap home-cooked swaps from what they have in their room, and answers food questions in a chat that knows their profile, today's intake and the scan.

It is being built as a **hackathon entry**. Success right now means a demo that works end to end, reliably, and makes the problem and the solution obvious to judges. Longer term, success means students build a habit of checking and improving what they eat.

## Positioning

- **Numbers the backend can compute are never left to the AI.** Gemini identifies items and estimates portions; plate totals, daily totals, targets and the health score are computed deterministically on the server, and nutrients are grounded in a curated foods table (IFCT/USDA) where possible. The UI says which values came from the table ("DB") and which are AI estimates ("AI est.").
- **Two-stage recognition:** a transfer-learned image classifier (ViT fine-tuned on Food-101) gives dish hints before Gemini vision reads every item on the plate, including plates with several items.
- **Built for Indian hostel life:** mess thalis, canteen snacks, chaat, momos, Maggi; street-food streaks; swaps that fit "no cooking", "kettle only" or "induction/burner" kitchens and the student's diet.

## Operating Context

- Scanning happens in the moment: at a mess table or a street stall on a phone, or later from a laptop.
- AI calls are slow: a scan typically takes 10–40 s (classifier, Gemini with retries and a fallback model). The interface must always show that work is in progress and what happens next.
- Accounts or a throw-away guest session. Guests get the same AI; their session ends when the tab closes.
- The demo runs locally (`uvicorn app.main:app`, web app at `/app/`) against Supabase Postgres and the Gemini API; `MOCK_AI=true` runs everything without a key.

## Capabilities and Constraints

- **Capabilities:** meal and label scanning; per-item breakdown with confidence; health score (0–100) with flags and tips; daily dashboard against computed targets; 7-day trend and weekly salt/sugar/fibre/fried-food patterns; AI daily insight; manual meal logging; history with CSV export; home-swap recipes and AI meal ideas from pantry items; street-free streak, levels and badges; health profile (age, sex, weight, height, activity, diet, weight goal, kitchen); chat about a scan with tool calls (read intake, log a meal).
- **Frontend:** `frontend/` is the product UI (no longer just a demo client). Vanilla HTML/CSS/JS with no build step, served by FastAPI at `/app/`.
- **API contract:** every response is the envelope `{success, code, message, data}`; nutrients use fixed keys and units (`calories`, `protein_g`, `carbohydrates_g`, `fat_g`, `saturated_fat_g`, `fiber_g`, `sugar_g`, `sodium_mg`).
- **Known limits:** Gemini free-tier quotas can run out (the app falls back to a lighter model); the Supabase project's region adds latency to every request.
- **Non-goals (from the brief):** barcode scanning, payments, push notifications, admin panel, OAuth/social login.

## Brand Commitments

- **Name:** "ScanMyFood" in the web app; the backend and API are "NutriScan AI".
- **Voice:** friendly, practical and budget-aware; speaks the student's food language (mess, canteen, street food, dal, curd, sprouts, eggs, fruit).
- **Safety, non-negotiable:** no medical diagnosis or prescriptions; for medical conditions give general guidance and suggest a doctor or dietitian. Never recommend crash diets, skipping meals, or intakes below a safe floor. If someone shows signs of disordered eating, respond supportively, avoid numbers and targets, and encourage talking to a professional or trusted person.
- **Respect diet type and allergies** in every suggestion.
- **Every AI output carries the disclaimer** "Estimates only — not medical advice." where the API spec requires it.

## Evidence on Hand

- A seeded demo account (`demo@nutriscan.app`, created by `scripts/seed_demo.py`) with three days of typical hostel meals.
- Example API responses in `docs/examples/` (e.g. a rajma chawal scan).
- No real users, testimonials, usage numbers, accuracy benchmarks or press exist yet. Do not invent them.

## Product Principles

1. **Trust over cleverness.** Show where numbers come from, say when something is an estimate, and never let the AI decide a number the system can compute.
2. **Every wait is visible.** AI work is slow; the person always knows the app is working, what it is doing, and what went wrong if it fails.
3. **Advice a hostel student can act on today.** Cheap, available, diet-respecting swaps beat ideal nutrition plans.
4. **Encourage, never shame.** Streaks and flags motivate; nothing pushes restriction, guilt or unsafe targets.
5. **Demo-ready end to end.** Every path a judge might click works, on a phone and on a laptop.
