# Race stat bible

Reference for the current simulation in [league.py](../league.py), especially `stat_map()` and `_make_wave()`.

1. **Winning:** Each driver completes 10 laps. Lowest total time wins; an exact tie uses the earlier grid position. Positions for event eligibility are calculated at the start of each lap.

2. **Individual stats determine results:** **INSTINCT, NERVE, RESONANCE, FORCE, HANDLING, ENGINE, FRAME, ANOMALY** are rounded averages for display, not inputs to race calculations. **EYES** is a raw count of 0–8; **WHEELS** is a raw count of 1–10. Their display contributions are normalized to `100 × EYES / 8` and `100 × (WHEELS − 1) / 9`.

3. **Acceleration:** `HORSEPOWER × (0.70 + 0.25 × VEIL / 100) + GHOSTPOWER × (0.30 − 0.25 × VEIL / 100)`. **HORSEPOWER** supplies 70–95% of the score; **GHOSTPOWER** supplies 5–30%. Higher **VEIL** favors **HORSEPOWER**, so it helps only when **HORSEPOWER** exceeds **GHOSTPOWER**.

4. **Top speed:** Set `s = 0.55 + 0.02 × (WHEELS − 4)`; top speed is `SMOKE × s + PIPES × (1 − s)`. Four **WHEELS** give 55% **SMOKE** and 45% **PIPES**. Each extra Wheel shifts two percentage points toward **SMOKE**; each fewer Wheel shifts two toward **PIPES**. Whether that helps depends on which score is higher. **RELIABILITY** does not affect top speed.

5. **Track and lap time:** Set `b = (track curve rating − 50) / 50`. Pace is `acceleration × (1 + 0.41b) + top speed × (1 − 0.41b)`: curves favor acceleration, straights favor top speed. Lap time is `53 − 0.075 × pace`, plus a random −1.6 to +1.6 seconds fixed per driver for the race, a fresh −3 to +3 seconds each lap, and event effects. Each lap is clamped to 30–60 seconds.

6. **Leading and drafting:** Higher **FOCUS** increases the chance and size of a leader's time-saving surge. From lap two, it also increases drafting chance when within 2.5 seconds of the car ahead, saving 0.25–0.65 seconds. Both use 85% of **FOCUS**. Higher **PRIDE** increases the chance and time penalty of overdriving while leading.

7. **Risk and recovery:** Higher **AUDACITY** increases the chance and size of an overdrive boost on any lap, but also increases control-loss chance. Higher **REFLEXES** and **DÉJÀ VU** reduce control-loss chance; **DÉJÀ VU** also reduces the chance control loss becomes major. Lost Control incidents cost 1.8–4.5 seconds; Lost Major Control incidents cost 6–10 seconds. Lower **DREAD TOLERANCE** increases the chance and size of a boost when last.

8. **Slips:** Higher **GRIP** reduces slip chance. Higher **HAUNTINGS** increases the time penalty when a slip occurs; it does not increase slip chance.

9. **Openings and paranormal events:** Each **EYES** count increases the chance of a 0.35–0.85 second boost. Paranormal chance per lap is `0.025 + 0.008 × EYES + 0.0005 × UNFINISHED BUSINESS`. A paranormal event saves or costs 1.5–4.5 seconds, with helpful probability `0.30 + 0.004 × LUCK`.

10. **Event luck:** Helpful event chances are multiplied by `0.9 + LUCK / 500`; harmful event chances, including control loss, by `1.1 − LUCK / 500`. Higher **LUCK** favors boosts and reduces penalties. These multipliers do not apply to the paranormal trigger or the control-loss severity roll. Multiple events can occur in one lap.

11. **Long-distance wear:** After more than 32 km completed, set `d = min(0.08, (distance − 32) × 0.0004)`. Acceleration is multiplied by `1 − d × (100 − RELIABILITY) / 100`; top speed by `1 − d × RUST / 100`. Low **RELIABILITY** and high **RUST** therefore hurt endurance. Current races cover 37–60 km, so wear affects their later laps. Distance is measured at the start of each lap; neither wear effect applies through 32 km. **RELIABILITY** only affects acceleration through this wear rule.

12. **Modifiers and randomness:** Race calculations use stats after modifier adjustments, clamped to 0–100 (Visited gives **EYES** a minimum of 1). Haunted changes **UNFINISHED BUSINESS** +25 and **FOCUS** −30; Fritez changes **REFLEXES** +25 and **DÉJÀ VU** −30; Visited changes **REFLEXES** −25, **EYES** −1, **AUDACITY** −25, and **UNFINISHED BUSINESS** +10; Unheard Frequency changes **HORSEPOWER** −30, **GHOSTPOWER** +10, and **VEIL** +10; Shiny changes **RUST** −50 and **HAUNTINGS** +50. Beautiful Vision changes the stored **EYES** count when awarded. Random draws are seeded by league seed, season, and wave slot. Weather is cosmetic. Stats influence outcomes; they do not guarantee victory.

12. **Crash events:** Separate from control loss, approximately one in three baseline races has an initiating crash. Pride increases risk; Reflexes and Déjà vu reduce it. Luck + Reliability determine severity: at 50 each, 60% Minor Crash (N/A Finish), 25% Major Crash (miss two following races), 10% Beyond Crash (miss three), and 5% avoid the crash. Beyond Crash checks the racers immediately ahead and behind and can cascade, checking each racer only once. A secondary Minor Crash also misses one following race. Recovery counts scheduled opportunities, with one opportunity per wave, and persists across seasons.
