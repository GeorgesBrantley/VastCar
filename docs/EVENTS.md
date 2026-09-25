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
| Audacious overdrive | Boost / risk | **Audacity** raises the chance and size of a 0.46–1.04 second gain and also raises crash chance. | **Yes** |
| Backmarker boost | Boost / position | When last at a lap's start, low **Dread tolerance** raises the chance and size of a 0.46–1.18 second gain. | **Yes** |
| Many-eyed boost | Boost / paranormal | Each raw **Eye** raises the chance of a 0.35–0.85 second gain and also raises paranormal-event frequency. | **Yes** |
| Draft | Racing / position | From lap two onward, a driver within 2.5 seconds of the car ahead can gain 0.25–0.65 seconds; **Focus** raises the trigger chance with its contribution reduced by 15%. | **Yes** |
| Crash | Incident / penalty | Costs 1.8–4.5 seconds. High **Reflexes** and **Déjà vu** reduce its chance; high **Audacity** increases it. | **Yes** |
| Major Crash | Incident / major penalty | A rarer crash outcome costing 6–10 seconds. High **Déjà vu** reduces the chance that a crash becomes major. | **Yes** |
| Grip slip | Vehicle / speed loss | High **Grip** reduces slip frequency; high **Hauntings** scales the loss from roughly 0.5 to 1.8 seconds. | **Yes** |
| Paranormal event | Anomaly | **Eyes** and **Unfinished business** raise the event chance. **Luck** moves the chance of a helpful outcome from 30% to 70%. | **Yes** |

Except for the paranormal trigger itself, **Luck** multiplies helpful event odds
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
| Calculated top speed | Continuous car mechanic | Raw Engine output is 55% **Smoke** and 45% **Pipes**, then blended with **Reliability** according to Wheels. | **Yes** |
| Veil threshold | Continuous car mechanic | **Veil** linearly shifts acceleration weight toward Horsepower and away from Ghostpower. | **Yes** |
| Wheel weighting | Continuous car mechanic | **Wheels** ranges from 1–10 (usually 4). Fewer Wheels give Reliability more top-speed weight; more Wheels give Engine output more weight. | **Yes** |
| Long-race degradation | Continuous car mechanic | After 300 km, low **Reliability** gradually reduces acceleration and high **Rust** gradually reduces top speed. The degradation factor is capped at 8%. | **Yes** |

## Schema migration

Saved rosters are upgraded in place. Existing Racecraft, Corner memory, and
Slipstream values become **Pride**, **Hauntings**, and **Veil**. **Eyes** and
**Wheels** receive their new raw-count distributions; **Smoke**, **Pipes**, and
**Rust** are added deterministically. Driver and car identities, archived race
plans, results, wins, and the original schedule anchor are preserved.
