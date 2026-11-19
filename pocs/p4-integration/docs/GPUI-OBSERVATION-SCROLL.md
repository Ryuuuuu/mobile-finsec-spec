# Synthetic observation small-window regression

2026-11-19: the prior window's Results / Load final result flow was reduced through the normal Windows Size menu to a 1538x343 viewport. Coverage summaries remained visible, but evidence and timing rows below them could not be reached by a 700-pixel wheel scroll. This reproduced a real layout omission: the body had no constrained scrolling container.

The independent observation window now places its body in a stable-ID, flexible, minimum-height-zero vertical scrolling viewport. The title, navigation and status remain outside it. No report or replay semantics change. This applies to the Check body as well so its controls do not become unreachable at reduced height.

## Repeatable interactive regression

1. Use a fresh private synthetic output root and the existing observation executable; load the fixed v2 plan, approve its displayed hash, run, and wait for finalization.
2. Open Results and separately press Load final result. Reduce height using the normal window Size menu; do not change desktop settings.
3. At height about 277 pixels, scroll down within the body. Require the last timing row and observation-only disclaimer to become visible while the top navigation remains reachable.
4. Keep this visual test distinct from string/data assertions. Do not use Android, capture, models, inspection skills or other apps.

Actual post-fix Windows run: loaded and finalized the fixed fixture, reached Results, loaded result: ok, reduced to 1538x277, scrolled 700 pixels and visibly reached the final AMBIGUOUS/MATCHED rows and the bottom disclaimer. The body moved while title/navigation/status remained fixed. Accessibility reads were intermittently unavailable, so supported screenshots and normal coordinate controls were used. No screenshots or run artifacts were published.

Offline Windows build passed. Five focused Rust tests passed (three opt-in tests ignored by the default command); the observation Rust-to-Python communication test then passed explicitly. The storage follow-up separately passed five archive tests and three stdio tests. Horizontal narrow-width wrapping, alternate display scaling, keyboard-only scrolling, generic UI accessibility and minimum usable window size remain unverified. This is an independent synthetic POC, not product integration or an Android result.
