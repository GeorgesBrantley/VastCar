# Event catalog

This is the design checklist for race events. It is intentionally separate from
the simulator so an event can be agreed on before it becomes a rule in
`league.py`.

Implementation labels:

- **Yes** — the simulator creates the event and applies the stated effect.
- **Partial** — some presentation or generic behavior exists, but the intended
  stat-driven rule does not.
- **No** — design guidance only; the simulator does not create it yet.

## Current race events

| Event name | Type | Effect | Implemented yet? |
| --- | --- | --- | --- |
| Green lights | Race control | Starts the race and adds the opening timing-tower message. | **Yes** |
| Takes the flag | Race control | Records a driver's finish and reports their final position. | **Yes** |
| Race weather | Environment | Selects and displays one surreal weather condition for the race. Weather does not currently change pace or event odds. | **Partial** |


## Stat-driven events

| Event name | Type | Effect | Implemented yet? |
| --- | --- | --- | --- |
| Leader surge | Boost / position | When first at a lap's start, **Focus** slightly increases the chance and size of a small gain. Focus's contribution is reduced by 15%. | **Yes** |
| Leader overdrive | Mistake / position | When first at a lap's start, high **Pride** increases the chance and size of a mistake costing roughly 0.5–0.9 seconds. | **Yes** |
| Audacious overdrive | Boost / risk | **Audacity** raises the chance and size of a 0.46–1.04 second gain and also raises control-loss chance. | **Yes** |
| Backmarker boost | Boost / position | When last at a lap's start, low **Dread tolerance** raises the chance and size of a 0.46–1.18 second gain. | **Yes** |
| Many-eyed boost | Boost / paranormal | Each raw **Eye** raises the chance of a 0.35–0.85 second gain and also raises paranormal-event frequency. | **Yes** |
| Draft | Racing / position | From lap two onward, a driver within 2.5 seconds of the car ahead can gain 0.25–0.65 seconds; **Focus** raises the trigger chance with its contribution reduced by 15%. | **Yes** |
| Lost Control | Incident / penalty | Costs 1.8–4.5 seconds. High **Reflexes** and **Déjà vu** reduce its chance; high **Audacity** increases it. | **Yes** |
| Lost Major Control | Incident / major penalty | A rarer control-loss outcome costing 6–10 seconds. High **Déjà vu** reduces the chance that control loss becomes major. | **Yes** |
| Minor Crash | Retirement | New crash events occur in about one-third of baseline races. Pride increases risk; Reflexes and Déjà vu decrease it. Baseline Luck + Reliability gives 60% Minor Crash: N/A Finish, no further absence. Secondary minor impacts miss one following race. | **Yes** |
| Major Crash | Retirement / recovery | Baseline 25%: N/A Finish and miss the next two scheduled race opportunities. Luck + Reliability reduce severity. | **Yes** |
| Beyond Crash | Retirement / cascade | Baseline 10%: N/A Finish and miss three scheduled race opportunities. The racers immediately ahead and behind at the incident each take the same severity check; further Beyond Crashes cascade. Each racer is checked at most once. | **Yes** |
| Crash recovery | Recovery | The unspecified remaining 5% avoids the crash and continues racing. | **Yes** |
| Grip slip | Vehicle / speed loss | High **Grip** reduces slip frequency; high **Hauntings** scales the loss from roughly 0.5 to 1.8 seconds. | **Yes** |
| Paranormal event | Anomaly | **Eyes** and **Unfinished business** raise the event chance. **Luck** moves the chance of a helpful outcome from 30% to 70%. | **Yes** |

For time-changing lap events, except the paranormal trigger itself, **Luck** multiplies helpful event odds
from 0.9× to 1.1× and harmful event odds from 1.1× to 0.9× across its
full 0–100 range. This keeps Luck influential without making outcomes certain.

## Paranormal Event

| Event name | Type | Effect | Implemented yet? |
| --- | --- | --- | --- |
| Negotiates with a shadow | Paranormal event | Adds a random **1.5–4.5 seconds** to the affected lap. | **Yes** |
| Briefly remembers tomorrow | Paranormal event | Adds a random **1.5–4.5 seconds** to the affected lap. | **Yes** |
| Receives a Pep Talk | Paranormal event | Removes a random **1.5–4.5 seconds** from the affected lap. | **Yes** |
| Jumps forward | Paranormal event | Removes a random **1.5–4.5 seconds** from the affected lap. | **Yes** |

The old flat incident roll is gone. Paranormal chance is now
`2.5% + 0.8% per Eye + 0.05% per Unfinished business point`, and Luck selects
between the helpful and harmful outcome pools.


## Continuous mechanics (not random events)

These stat notes affect the speed model and should not be implemented as event
rolls unless the design changes:

| Event name | Type | Effect | Implemented yet? |
| --- | --- | --- | --- |
| Horsepower acceleration | Continuous car mechanic | **Horsepower** supplies 70–95% of the acceleration score, according to **Veil**. | **Yes** |
| Ghostpower acceleration | Continuous car mechanic | **Ghostpower** supplies the remaining 5–30% of the acceleration score. | **Yes** |
| Calculated top speed | Continuous car mechanic | Top speed blends **Smoke** and **Pipes** with Smoke weight `0.55 + 0.02 × (Wheels − 4)` and Pipes weight equal to the remainder. **Reliability** has no top-speed effect. | **Yes** |
| Veil threshold | Continuous car mechanic | **Veil** linearly shifts acceleration weight toward Horsepower and away from Ghostpower. | **Yes** |
| Wheel weighting | Continuous car mechanic | **Wheels** ranges from 1–10 (usually 4). Four Wheels give 55% Smoke / 45% Pipes. Each extra Wheel shifts two percentage points toward Smoke; each fewer Wheel shifts two toward Pipes. | **Yes** |
| Long-race degradation | Continuous car mechanic | After 32 km completed (measured at the start of each lap), low **Reliability** gradually reduces acceleration and high **Rust** gradually reduces top speed. Reliability only affects acceleration through this wear rule. The degradation factor is `min(0.08, (distance − 32) × 0.0004)`, capped at 8%. | **Yes** |

## Schema migration

Saved rosters are upgraded in place. Existing Racecraft, Corner memory, and
Slipstream values become **Pride**, **Hauntings**, and **Veil**. **Eyes** and
**Wheels** receive their new raw-count distributions; **Smoke**, **Pipes**, and
**Rust** are added deterministically. Driver and car identities, archived race
plans, results, wins, and the original schedule anchor are preserved.

Crash frequency is a probability, not a fixed every-third-race schedule. At 50 in all relevant stats, the initiating chance is 1/3 per race. Recovery is stored in race plans and carries across seasons; parallel races in the same wave count as one scheduled opportunity per driver. Retired drivers receive no finish position, podium points, or finishing rewards. Existing race plans are preserved.
