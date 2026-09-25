# Modifiers

This file tracks driver and car modifiers from design through implementation.
The catalog is intentionally empty until modifier designs are added.

## Data shape

Modifiers live in either a driver's `modifiers` array or the driver's car's
`modifiers` array. Each modifier has:

- `name` — the short label shown in the Driver Dossier.
- `description` — player-facing hover text explaining the modifier.
- `implementation` — the stable mechanic identifier used by the race engine.

```json
{
  "name": "",
  "description": "",
  "implementation": ""
}
```

The interface displays a modifier only when it exists in one of these arrays.
Its description is available as hover text and to keyboard/screen-reader users.
The `implementation` value is reserved for simulator behavior and is not shown
to players.

## Driver modifiers

RESPECT MAXIUM and MINIMUMs of these values

| Name | Type | Description | Mechanical implementation | Implemented? |
| --- | --- | --- | --- |
| Haunted | Driver | Don't Look Behind | Driver Unifinished Buisness is +25, Focus is -30 | **Yes** |
|Fritez | Driver | Good Coffee for the Souls | Driver Reflexes + 25, Deja Vu -30 | **Yes** |
| Beautiful Vision | Driver | E F P T O Z | Driver eye count changes to a random other value | **Yes** |
| Visited | Driver | A memorable visit. | Driver Reflexes -25, Eyes -1 (minimum 1), Audacity -25, Unfinished business +10 | **Yes** |


## Car modifiers

| Name | Type| Description | Mechanical implementation | Implemented? |
| --- | --- | --- | --- |
| Unheard Frequency | Car | Car loses 30 Horse Power, gains 10 Ghostpower, gains 10 Veil | Stats are clamped from 0–100. | **Yes** |
| Shiny | Car| Car loses 50 Rust, +50 Hauntings | Stats are clamped from 0–100. | **Yes** |

## Implementation checklist

- Add the modifier to the appropriate catalog above.
- Assign it to the intended driver or car in `make_roster()`.
- Implement its mechanic in `league.py` using its stable `implementation` key.
- Mark it implemented only after both assignment and simulator behavior exist.
