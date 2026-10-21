---
target: NutriScan AI web app
total_score: 27
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 3
target_identity: "file:/Users/piyush/Downloads/NutriScan-AI/frontend/index.html"
target_fingerprint: "sha256:667a4c16cf8885d63ff73d0361d7f1829e76107ef4687348300f2818ce93ae7b"
target_path: /Users/piyush/Downloads/NutriScan-AI/frontend/index.html
timestamp: 2026-10-20T11-26-35Z
slug: frontend-index-html
closed: true
---
# Critique: NutriScan AI web app (frontend/index.html)
Method: dual-agent (A: design review · B: detector + browser)

## Design health: 27/40 (Acceptable)
| # | Heuristic | Score | Key issue |
|---|---|---|---|
| 1 | System status | 3 | Staged scan copy + seconds counter is strong; loading status re-announces every second to screen readers |
| 2 | Real world | 4 | Katori/cup portions, mess/kettle language, IFCT/USDA provenance |
| 3 | User control | 2 | History "Remove" deletes instantly, no undo; logged meals can't be edited; no "scan another" |
| 4 | Consistency | 2 | Turmeric goes to stale "Analyze" not "Add to my log"; scan nutrients drop the tray language; CSV still named scanmyfood-history.csv |
| 5 | Error prevention | 2 | Analyze lit with no photo; manual log saves protein/carbs/fat as 0; no allergies field |
| 6 | Recognition | 3 | Chips and presets help; chat only exists under a scan result |
| 7 | Flexibility | 2 | No re-log of frequent meals, no camera-first entry |
| 8 | Minimalist | 3 | Calm, but insight + quick checks + patterns all advise at once |
| 9 | Error recovery | 3 | Clear NOT_FOOD copy; no explicit retry |
| 10 | Help | 3 | Good inline help; health score unexplained |

## Specificity
Authored on the dashboard (mess-tray tiles, earthy macro palette, DB vs AI est. pills, Indian swaps). Generic on Rewards (badge grid), Profile (plain form) and the scan result's nutrient grid. Detector: 0 unsuppressed findings in static HTML; in-browser: nested-cards on .tray.impact (intentional pattern), low-contrast #pantry placeholder 4.4:1, cream-palette (user-sanctioned). Contrast elsewhere passes (sidebar 7-12:1, tile labels 5-8.6:1, turmeric button 5.8:1). Tap targets under 44px: History filters 34px, Remove 36px, Cook chips 36px, chat Open/Dismiss 32px, Sign out 20px. No h1 anywhere.

## Priority issues
1. [P1] Accent hierarchy broken on Scan: turmeric Analyze outshouts "Add to my log"; photo slot below mode/meal-type on phones. (layout, clarify)
2. [P1] Tray level line strikes through labels; empty band reads as glitch; clay tint near chili-soft. (polish)
3. [P1] Motivation shames by default: one samosa turns whole day bar red, "0 days", red banner, wall of locked zero badges. (delight, quieter)
4. [P2] Data-entry gaps: no allergies field, manual log zero macros, instant delete, no edit. (harden)
5. [P2] Chatbot buried; 6 phone tabs with Scan off-centre; "Is it bad for my liver?" chip invites diagnosis. (adapt, clarify)

## Personas
Casey: 6 tabs, controls above photo, Add-to-log 2 screens down, status text eats top bar. Jordan: silent default profile (veg, 2000 kcal), unexplained score, zeros on Rewards. Sam: status spam, score badge aria-label on role-less div, 3.2 s toasts, sub-44px targets. Judge: no sample plate on empty guest dashboard; provenance pills tiny; scanmyfood CSV name.

## Minor
"427 kcal" unit wraps; result sentence repeats dish name; "Not street food" tag is noise; History rows omit meal type; mock chat suggests eggs to vegetarian; no h1; Quick checks card half empty.

## Questions
- If scanning is the product, why is the landing page a dashboard rather than camera-first?
- Would "street meals this week: 1 of 21" motivate better than an all-or-nothing streak?
- Should "over" be the tray's drama, or balance across compartments?
