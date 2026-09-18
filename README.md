# Strange Circuit

An original, Blaseball-inspired spectator racing league. Thirty drivers and their
named cars race automatically, with oddball ratings, live timing, and persistent
results. No clicks are needed to start or finish a race.

## Run

Requires **Python 3.9+**. No packages, Node, build step, or external account
provider is required.

```sh
cd /Users/georges/Documents/Races
python3 server.py
```

Open **http://localhost:8000**. Leave the process running to keep the league live.
Stop with Ctrl+C. An alternate port or database can be selected:

```sh
python3 server.py --port 8080 --db data/another-league.sqlite3
```

The default server listens locally. To make it available on your local network,
use `--host 0.0.0.0`. Run only one server process per database. For public hosting,
put a production reverse proxy in front of this small Python HTTP server and run
it as a persistent service with a persistent data volume.

## Local accounts

The header provides registration, login, and logout. Accounts live in the same
SQLite database as the league. Passwords are never stored in plaintext: each
password is hashed with a unique salt using Python's memory-hard `scrypt`
(or a 600,000-iteration PBKDF2-HMAC-SHA256 fallback on Python builds without
`scrypt`).

Every new account begins with these values:

- `admin: false`
- `coin: 200`
- `fav_racer: null`
- `inventory: []`

Opening the app while signed in (or logging in) once per UTC calendar day
automatically adds **50 Coin**. Registering an account starts a session with
its 200 Coin balance; the daily login reward is available the next day.

Set a persistent `APP_SESSION_SECRET` in the host environment before deploying
so signed sessions remain valid over server restarts:

```sh
APP_SESSION_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
AUTH_COOKIE_SECURE=true
```

`AUTH_COOKIE_SECURE=auto` (the default) works locally. Set it to `true` in
production. If TLS terminates at a reverse proxy, it must forward
`X-Forwarded-Proto: https` so session cookies retain the Secure flag.

## The league

- Seasons reset every Monday. Current-season wins are counted only from races
  in that week, while older season results stay in the archive.
- Monday through Thursday, waves start every **20 minutes** from **9:00 AM to
  5:00 PM Eastern**. Each of those waves contains **three races**. Two extra
  5:00 PM weekday waves bring the week into balance. Friday closes the season
  with a six-race championship series: three R1 qualifiers at **11:00 AM**, two
  R2 qualifiers at **11:30 AM**, and one final championship race at **12:00 PM
  Eastern**.
- Each wave shuffles all **30 drivers** into **three races of 10**, choosing
  **three distinct locations**. A full season is **300 races**. Races are
  numbered within the season and named for their location, such as
  **Tokyo, Race 104**.
- Championship races use trophy-prefixed names. R2 contains the top five from
  each R1 race plus one random wildcard, split into two eight-driver races. The
  final contains the top four from each R2 race.
- Every driver completes **10 laps**, taking between **5 and 9½ minutes**.
  After the wave finishes, its final standings stay visible until the next wave.
- Each driver has **3 base attributes with 3 substats each**. Each car has
  **5 base attributes with 2 substats each**. The 19 substats feed acceleration,
  top speed, position-sensitive boosts, crashes, slips, and paranormal events.
  Lap variation adds uncertainty and allows overtakes. Ratings are fixed for now.
- A background scheduler advances the league every second, including when no
  browser is connected. Browsers poll shared server state once per second.
- SQLite stores the schedule, roster, lap plans, incidents, and results in
  `data/league.sqlite3`. Wins are counted from completed results, preventing
  duplicate awards after a restart. The UI shows **real results only**.
- Restarting preserves the original cadence and deterministically simulates any
  missed waves. An in-progress race resumes at its wall-clock position. No server
  process can run while the machine is asleep; catch-up happens on wake/restart.
- Race outcomes are generated privately at wave creation and revealed as their
  timestamps pass. Future lap plans, finish times, and winners are not sent to
  browsers. The last finisher closes the race and commits it to the archive.

## What the stats mean mathematically

Most displayed substats are integers from 28 to 98. **Eyes** is a raw count from
0 to 8 (70% of drivers have 2), and **Wheels** is a raw count from 1 to 10
(usually 4). The displayed base ratings remain 0-100 summaries: Eyes is
normalized as `100 × Eyes / 8`, Wheels as `100 × (Wheels − 1) / 9`, and
the normalized substats are averaged. Base ratings are summaries only; race
mechanics read the individual substats.

For a base attribute with substats `s₁ … sₙ`, its displayed base rating is:

```text
base = round((s₁ + … + sₙ) / n)
```

The driver bases are **Instinct**, **Nerve**, and **Resonance**. The car bases
are **Force**, **Handling**, **Engine**, **Frame**, and **Anomaly**. Pace begins
with separate acceleration and top-speed scores rather than one overall rating:

```text
v = Veil / 100
acceleration = Horsepower × (0.70 + 0.25v) + Ghostpower × (0.30 − 0.25v)

engine = 0.55 × Smoke + 0.45 × Pipes
reliability weight = 0.18 × (10 − Wheels) / 9
top speed = engine × (1 − reliability weight)
            + Reliability × reliability weight
```

Horsepower is always the larger acceleration influence, while Veil changes how
much room Ghostpower has. Fewer Wheels make Reliability more important to final
top speed; more Wheels let Engine output dominate. After 300 km, poor
Reliability gradually reduces effective acceleration and Rust gradually reduces
effective top speed, capped at an 8% degradation factor.

Each track has a **Curves/Straightaways** profile. Most tracks sit near the
middle, while a few lean clearly toward long straights or tight cornering. Curvy
tracks weight acceleration more; straight tracks weight top speed more:

```text
track bias = (curve_bias − 50) / 50
acceleration weight = 1 + 0.41 × track bias
top-speed weight = 1 − 0.41 × track bias
pace = acceleration × acceleration weight + top speed × top-speed weight
```

Those weighted scores set the entrant's per-race lap-time baseline, in seconds:

```text
baseline = 53 − 0.075 × pace + U(−1.6, 1.6)
```

where `U(a, b)` is one uniformly random draw between `a` and `b`. The field is
then simulated one lap at a time so an entrant's actual position at the start of
the lap can trigger leader, backmarker, and drafting rules.

Each lap is then calculated as:

```text
lap time = clamp(baseline + U(−3, 3) + sum(event effects), 30, 60)
```

There is no longer a flat incident chance. Each boost, crash, slip, draft, or
paranormal event has its own stat-driven probability and signed time effect;
the exact rules are listed in [`EVENTS.md`](EVENTS.md). Luck changes favorable
and harmful event odds by at most 10% in either direction. Race time is the sum
of ten laps, and the lowest total wins (with earlier grid position breaking an
exact tie). Weather is selected and displayed but has no mechanical effect.

## Stat design notes

This is the working worksheet for the implemented rules. Base attributes are
display summaries; their substats supply the mechanics below.

The proposed and existing race events derived from these notes are tracked in
[`EVENTS.md`](EVENTS.md), including their effects and implementation status.

### Driver
Driver stats should be behavior driven. think of these as the wacky modifiers to the power of the car.
Drivers affect events such as boosting, crashing, anamolies, and drafting, etc.
These are scaled, so a 0 to 100 may look like a lot, but it just may be the difference of 1.1 to 1.4 in a math formula.

#### Instinct

- **Mechanical notes:** Controls crash avoidance and the leader's situational risk.
- **Flavor notes:** How quickly a driver understands what the circuit is doing to them.
- **Substats:**
  - **Reflexes:** High Reflexes decrease crash chances. Implemented as a small reduction to each lap's crash roll.
  - **Pride:** Higher Pride is bad. When leading, it increases the chance and size of an overdriving mistake.
  - **Déjà vu:** High DV decreases crash chance and the chance of a BAD crash. It affects both rolls separately.

#### Nerve

- **Mechanical notes:** Changes behavior at the front, at the back, and when taking risks.
- **Flavor notes:** What a driver does when a sensible person would lift off the throttle.
- **Substats:**
  - **Focus:** Slight increase to acceleration when in first. It also provides a modest, reduced trigger for drafting when a car is close enough.
  - **Audacity:** High Audacity gives a slight Top Speed bonus, but increases crash chance. The bonus is an occasional overdrive event; the risk is applied on every crash roll.
  - **Dread tolerance:** Low Dread Tolerance means a driver hates being in last place. Lower values increase both the chance and size of a last-place boost.

#### Resonance

- **Mechanical notes:** Weird stuff: how often paranormal events happen and whether events tend to help or hurt.
- **Flavor notes:** The driver's relationship with the parts of racing that cannot be inspected afterward.
- **Substats:**
  - **Luck:** Affects the occurrence of things happening. Bad Luck (0) and good Luck (100) are a spectrum, not certainty; it shifts helpful and harmful event odds by at most 10% and changes the chance that a paranormal event is helpful.
  - **Eyes:** Usually (70%) 2, but can be 0 (very rare), 1, or all the way up to 8. Each Eye adds to many-eyed boost and paranormal-event chance. It is displayed as a raw count.
  - **Unfinished business:** Higher means more likely for some paranormal events. It adds gradually to paranormal-event chance on every lap.

### Car
Car Stats shoudl be a little bit more standard, they are the fundlementals of the vehicle. These do not need to be 0-100 values, or they can be abstracted to 0-100 values with 100 being the 'best' and 0 being the worst (like a low horse power is shown to the viewer as 12 but the value isn't 12.) Except Wheels. We should have wheels be "X Wheels", thats funny.

The basics of the math is making Top Speed and Acceleration intersting. We do this by making Top Speed actually a value that is calculated from mulitple inputs and weights, and Acceleration applies to different parts of that equation.

#### Force

- **Mechanical notes:** These factors deal with acceleration to a fixed point (determined by Veil), then past that point toward total top speed.
- **Flavor notes:** The competing ordinary and impossible ways a car gets moving.
- **Generation notes:** Most cars sit in the 40-60 range for both Force stats.
  Roughly 15% of the roster gets a more unusual Force profile, but outliers are
  capped so no car receives both Horsepower and Ghostpower in the 90s.
- **Substats:**
  - **Horsepower:** Big Acceleration influence. It always supplies 70-95% of the acceleration score, depending on Veil.
  - **Ghostpower:** Minor Acceleration influence. It supplies the remaining 5-30%, becoming more important when Veil is low.

#### Handling

- **Mechanical notes:** Adds texture to performance without becoming the only source of randomness.
- **Flavor notes:** Whether the machine agrees to continue pointing in the intended direction.
- **Substats:**
  - **Grip:** Controls how often the car slips from top speed. The probability range stays deliberately narrow, so 0 is not wildly different from 100.
  - **Hauntings:** Higher Hauntings increase the speed lost when a slip occurs. It changes the penalty, not the trigger chance.

#### Engine

- **Mechanical notes:** These values contribute to top speed. We should weight them based on Wheels.
- **Flavor notes:** Two imperfect measures of what comes out of the back of the machine.
- **Substats:**
  - **Smoke:** The larger Top Speed factor, weighted at 55% of raw Engine output.
  - **Pipes:** The second Top Speed factor, weighted at 45% of raw Engine output.


#### Frame

- **Mechanical notes:** These values govern longer races. Their gradual effects begin after 300 km and grow by distance, with a small hard cap.
- **Flavor notes:** What remains after the quick parts have been quick for too long.
- **Substats:**
  - **Reliability:** Higher Reliability keeps Force-derived acceleration effective after 300 km. It also contributes modestly to final Top Speed when a car has fewer Wheels.
  - **Rust:** Higher Rust causes more Engine-derived Top Speed loss after 300 km. It has no effect before that threshold.

#### Anomaly

- **Mechanical notes:** Defines the boundary between acceleration regimes and how much the Frame stabilizes final Top Speed.
- **Flavor notes:** The vehicle's geometry, including the parts that may only be metaphorically circular.
- **Substats:**
  - **Veil:** The higher the number, the more Horsepower matters; the lower the number, the more Ghostpower matters. Its linear blend splits acceleration behavior without allowing Ghostpower to become the larger factor.
  - **Wheels:** A raw value between 1 and 10, usually 4. Fewer Wheels make Reliability count more toward final Top Speed; more Wheels let Engine output count more directly.

## Pages

**Live races:** three circuits with moving numbered markers, all ten positions,
completed lap counts, progress bars, timing gaps, and a next-wave countdown.
“Follow race” opens distance telemetry and a timestamped incident feed.

**Drivers & cars:** search by driver, car, or racing number; sort by number, name,
or wins. The season selector defaults to the current season and can inspect past
season performance when past seasons exist. Open any dossier to see all 19
substats and eight base ratings.

**The archive:** completed races with winners and winning times, searchable by
city or race number and filterable by city. Each result opens the full finishing order.

The interface supports narrow screens, keyboard navigation, reduced motion,
and reconnects automatically if the server goes away.

## Verify

```sh
python3 -B -m unittest discover -s tests -v
```

The tests use an injected clock and temporary databases to cover race duration,
all-driver assignment, venue exclusivity, progress, attribute structure,
stat-driven event effects, roster migration, completion and wins, precise
boundaries, restart catch-up, concurrent requests, history queries, and keeping
future results private.

## Files and API

- `league.py` — deterministic race generation, persistent state, time-based timing.
- `server.py` — static files, read-only JSON API, and background scheduler.
- `public/` — dependency-free HTML/CSS/JavaScript interface and original SVG cars.
- `tests/test_league.py` — simulation and persistence tests.
- `EVENTS.md` — event design catalog, stat hooks, and implementation status.

Read-only endpoints: `/api/state`, `/api/drivers?season=`, `/api/history?page=1&q=&city=`,
and `/api/races/{id}`. Timestamps are UTC epoch seconds; the browser displays
dates in your local time zone. Distances are kilometers; gaps are seconds.

The inspiration is Blaseball’s automated, surreal spectator-sport format:
https://www.thegameband.com/game/blaseball . This project uses original names,
visuals, and simulation code. Voting, betting, accounts, and evolving league
rules are outside this first version.
