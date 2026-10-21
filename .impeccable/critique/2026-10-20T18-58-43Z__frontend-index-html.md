---
target: NutriScan AI web app
total_score: 27
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 3
target_identity: "file:/Users/piyush/Downloads/NutriScan-AI/frontend/index.html"
target_fingerprint: "sha256:d11775905b438eea7053f11823534d2638810e019ff7bbbddbb285300aea971c"
target_path: /Users/piyush/Downloads/NutriScan-AI/frontend/index.html
timestamp: 2026-10-20T18-58-43Z
slug: frontend-index-html
closed: true
---
# Critique: NutriScan AI web app (frontend/index.html), run 2
Method: dual-agent (A: design review · B: detector + browser)

## Design health: 27/40 (Acceptable), same total as run 1, different problems
| # | Heuristic | Run 1 | Run 2 | Key issue now |
|---|---|---|---|---|
| 1 | System status | 3 | 3 | Mock insight praises "Nice work logging today!" at 0 kcal |
| 2 | Real world | 4 | 4 | Katori portions, mess/kettle language |
| 3 | User control | 2 | 3 | Undo on Remove; no cancel during a scan; "Add to my log" not undoable |
| 4 | Consistency | 2 | 2 | Phone: Scan pill and active pill look alike; Dashboard vs Today naming; tray vs flat chips in result; two overlapping insight cards |
| 5 | Error prevention | 2 | 3 | Analyze gated on photo; calorie goal free-text overrides computed target |
| 6 | Recognition | 3 | 3 | Dashboard never lists today's meals |
| 7 | Flexibility | 2 | 2 | No re-log of frequent meal, no sample photo, Ask chips persist |
| 8 | Minimalist | 3 | 3 | Cook: 14 chips + 10 equal cards; dense history meta |
| 9 | Error recovery | 3 | 2 | Focus lost to body after Remove; chat errors have no retry |
| 10 | Help | 3 | 2 | Silent default profile (2000 kcal, 50 g protein) for guests |

## Detector
Static: 0 (2 sanctioned ignores). Browser: nested-cards x8 on tray tiles, x2 in scan result (.score, .nutri) — intentional tray metaphor, judgement call. Field border #b4b1a1 on white 2.16:1 (below 3:1). Remove button 40px wide on phone. No h1 per view (brand is h1). All text passes AA. No overflow, no console errors.

## Priority issues
1. [P1] Scan result has no hierarchy or payoff: photo absent from result, small score, everything equal weight, nothing happens after Add to my log. (layout, delight)
2. [P1] Dashboard contradicts itself: praise at 0 kcal (mock fixture), AI insight + Quick checks overlap, no today's-meals list. (distill, clarify)
3. [P1] No first-run onboarding; guests get silent default targets. (onboard)
4. [P2] Phone nav ambiguity: Scan pill reads as active; Rewards/streak hook hidden. (adapt)
5. [P2] Keyboard/SR gaps: focus lost after Remove; whole result card in a live region; field borders 2.16:1. (harden)

## Persona flags
Casey: street-food checkbox right under Add to my log; Export CSV first on History. Jordan: zero tray + praise, silent defaults, no sample photo. Sam: focus loss, verbose live region. Judge: two-stage ViT+Gemini story is a footnote; no "Try a sample plate"; Rewards sparse.

## Questions
- Should a phone open camera-first instead of on the dashboard?
- Should the scan result itself look like a tray, one compartment per item?
- Is Cook a destination, or the answer to "Find a home swap"?
