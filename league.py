"""The persistent, clock-driven engine for STRANGE CIRCUIT. No dependencies."""

import bisect
from datetime import date, datetime, time as datetime_time, timedelta
import json
import random
import sqlite3
import threading
import time
from zoneinfo import ZoneInfo

INTERVAL = 20 * 60
LAPS = 10
RACES_PER_WAVE = 3
EASTERN = ZoneInfo("America/New_York")
SEASON_NAMES = ["Eclipse", "Petals", "Networking", "Burns"]
SEASON_WAVE_BASE = 10_000
WEEKDAY_WAVE_MINUTES = [9 * 60 + offset * 20 for offset in range(24)]
EXTRA_WEEKDAY_WAVES = [(2, 17 * 60), (3, 17 * 60)]
FRIDAY_CHAMPIONSHIP_SCHEDULE = [(4, 11 * 60, 3), (4, 11 * 60 + 30, 2), (4, 12 * 60, 1)]
SEASON_SCHEDULE = sorted(
    [(day, minute, RACES_PER_WAVE) for day in range(4) for minute in WEEKDAY_WAVE_MINUTES] +
    [(day, minute, RACES_PER_WAVE) for day, minute in EXTRA_WEEKDAY_WAVES] +
    FRIDAY_CHAMPIONSHIP_SCHEDULE,
    key=lambda slot: (slot[0], slot[1]),
)
SLOTS_PER_SEASON = len(SEASON_SCHEDULE)
CHAMPIONSHIP_R1_SLOT = SLOTS_PER_SEASON - 3
CHAMPIONSHIP_R2_SLOT = SLOTS_PER_SEASON - 2
CHAMPIONSHIP_FINAL_SLOT = SLOTS_PER_SEASON - 1
SLOT_FIRST_RACE_NUMBERS = []
_race_total = 0
for _day, _minute, _race_count in SEASON_SCHEDULE:
    SLOT_FIRST_RACE_NUMBERS.append(_race_total + 1)
    _race_total += _race_count
RACES_PER_SEASON = _race_total
CITIES = [
    {"name": "Tokyo", "country": "Japan", "code": "TYO", "length": 4.8, "curve_bias": 52, "circuit": "Midnight Expressway"},
    {"name": "Montréal", "country": "Canada", "code": "YUL", "length": 4.3, "curve_bias": 56, "circuit": "Saint Static Circuit"},
    {"name": "São Paulo", "country": "Brazil", "code": "SAO", "length": 4.6, "curve_bias": 47, "circuit": "Endless Sunday"},
    {"name": "Reykjavík", "country": "Iceland", "code": "REK", "length": 3.9, "curve_bias": 72, "circuit": "The Long Way Home"},
    {"name": "Melbourne", "country": "Australia", "code": "MEL", "length": 5.1, "curve_bias": 44, "circuit": "Afterimage Park"},
    {"name": "Indianapolis", "country": "United States", "code": "IND", "length": 4.5, "curve_bias": 32, "circuit": "Brickyard Meridian"},
    {"name": "Monaco", "country": "Monaco", "code": "MCO", "length": 3.7, "curve_bias": 82, "circuit": "Mirage Harbor"},
    {"name": "Cape Town", "country": "South Africa", "code": "CPT", "length": 4.1, "curve_bias": 58, "circuit": "Table Mountain Run"},
    {"name": "Lisbon", "country": "Portugal", "code": "LIS", "length": 4.2, "curve_bias": 54, "circuit": "Atlantic Switchback"},
    {"name": "Seoul", "country": "South Korea", "code": "SEL", "length": 4.7, "curve_bias": 49, "circuit": "Neon Han Circuit"},
    {"name": "Marrakech", "country": "Morocco", "code": "RAK", "length": 5.0, "curve_bias": 42, "circuit": "Red Dust Loop"},
    {"name": "Abu Dhabi", "country": "United Arab Emirates", "code": "AUH", "length": 6.0, "curve_bias": 22, "circuit": "Long Shadow Circuit"},
]
DRIVER_ATTRIBUTES = {
    "Instinct": ["Reflexes", "Pride", "Déjà vu"],
    "Nerve": ["Focus", "Audacity", "Dread tolerance"],
    "Resonance": ["Luck", "Eyes", "Unfinished business"],
}
CAR_ATTRIBUTES = {
    "Force": ["Horsepower", "Ghostpower"],
    "Handling": ["Grip", "Hauntings"],
    "Engine": ["Smoke", "Pipes"],
    "Frame": ["Reliability", "Rust"],
    "Anomaly": ["Veil", "Wheels"],
}
MODIFIERS = {
    "haunted": {"name": "Haunted", "description": "Don't Look Behind", "implementation": "haunted"},
    "fritez": {"name": "Fritez", "description": "Good Coffee for the Souls", "implementation": "fritez"},
    "beautiful-vision": {"name": "Beautiful Vision", "description": "E F P T O Z", "implementation": "beautiful-vision"},
    "unheard-frequency": {"name": "Unheard Frequency", "description": "Car loses 30 Horsepower, gains 10 Ghostpower, and gains 10 Veil.", "implementation": "unheard-frequency"},
    "shiny": {"name": "Shiny", "description": "Car loses 50 Rust and gains 50 Hauntings.", "implementation": "shiny"},
}
ROSTER_VERSION = 5
NAMES = [
    ("Juno Static", "Saint Elsewhere"), ("Milo Afterhours", "The Debt Collector"),
    ("Velvet Okafor", "Soft Apocalypse"), ("Cassette Lee", "Side B"),
    ("Sunday Graves", "Borrowed Time"), ("Petra Moon", "Lunar Liability"),
    ("August Nobody", "Witness Protection"), ("Inez Voltage", "Little Thunder"),
    ("Basil Mercury", "Bad Idea No. 7"), ("Cleo Dust", "The Last Resort"),
    ("Echo Matsuda", "Second Opinion"), ("Romy Bell", "Minor Omen"),
    ("Nico Nightjar", "Radio Silence"), ("Alma Atlas", "Heavy Weather"),
    ("Otto Almost", "Close Enough"), ("Vera Halogen", "False Dawn"),
    ("Kit Wavelength", "Public Frequency"), ("Dante Moss", "Green Funeral"),
    ("Noor Solstice", "Daybreak Ritual"), ("Penny Orbit", "Loose Satellite"),
    ("Salvador Soft", "Velvet Engine"), ("Mika Voss", "Stray Signal"),
    ("Florence Zero", "Absolute Maybe"), ("Remy Specter", "Polite Menace"),
    ("Ada Sundown", "Exit Wound"), ("Felix Frequency", "Dead Air"),
    ("Bea Caldera", "Warm Regards"), ("Luca Elsewhere", "Wrong Address"),
    ("Marisol Finch", "Lucky Teeth"), ("Robin Reverse", "Return to Sender"),
]
COLORS = ["#eaff7b", "#bba6ff", "#ff9a76", "#8ce3d1", "#f8a6ce", "#8fbbff", "#f4cf85", "#a2caa0", "#e8b1ef", "#d3d9df"]
TEAMS = [
    {"id": "usa", "name": "United States of America", "abbreviation": "USA", "flag": "🇺🇸", "color": "#5fa8ff"},
    {"id": "ussr", "name": "Union of Soviet Socialist Republics", "abbreviation": "USSR", "flag": "☭", "color": "#ff4b4b"},
    {"id": "rome", "name": "Imperial Rome", "abbreviation": "ROME", "flag": "🦅", "color": "#d9ad54"},
    {"id": "mongol", "name": "Mongolian Empire", "abbreviation": "MGL", "flag": "🐎", "color": "#8dd4a8"},
    {"id": "brazil", "name": "Brazil", "abbreviation": "BRA", "flag": "🇧🇷", "color": "#63d56b"},
    {"id": "argentina", "name": "Argentina", "abbreviation": "ARG", "flag": "🇦🇷", "color": "#80cfff"},
    {"id": "africa", "name": "Pan-African Union", "abbreviation": "PAU", "flag": "🌍", "color": "#f1b84b"},
    {"id": "new-zealand", "name": "New Zealand", "abbreviation": "NZ", "flag": "🇳🇿", "color": "#a99cff"},
    {"id": "future-japan", "name": "Future Japan", "abbreviation": "JPN-X", "flag": "🇯🇵", "color": "#ff8eb5"},
    {"id": "napoleonic", "name": "Napoleonic Empire", "abbreviation": "NPE", "flag": "🇫🇷", "color": "#7e8fff"},
]
TEAM_BY_ID = {team["id"]: team for team in TEAMS}
WEATHER = ["Dry / mostly real", "Low-flying déjà vu", "Scattered omens", "Light existential drizzle", "Clear / probably", "A familiar headwind"]


def season_name(season_number):
    return SEASON_NAMES[season_number - 1] if 1 <= season_number <= len(SEASON_NAMES) else f"Season {season_number}"


def monday_for(timestamp):
    local = datetime.fromtimestamp(timestamp, EASTERN).date()
    return local - timedelta(days=local.weekday())


def parse_date(value):
    return date.fromisoformat(value)


def season_start_date(zero_date, season_number):
    return zero_date + timedelta(days=(season_number - 1) * 7)


def slot_start_timestamp(zero_date, season_number, season_slot):
    day, minute, _race_count = SEASON_SCHEDULE[season_slot]
    local_date = season_start_date(zero_date, season_number) + timedelta(days=day)
    local_time = datetime_time(minute // 60, minute % 60)
    return datetime.combine(local_date, local_time, EASTERN).timestamp()


def season_number_for(zero_date, timestamp):
    current_monday = monday_for(timestamp)
    return max(1, (current_monday - zero_date).days // 7 + 1)


def due_slot_for(zero_date, season_number, timestamp):
    for season_slot in range(SLOTS_PER_SEASON - 1, -1, -1):
        if slot_start_timestamp(zero_date, season_number, season_slot) <= timestamp:
            return season_slot
    return None


def season_slot_for_start(zero_date, season_number, timestamp):
    for season_slot in range(SLOTS_PER_SEASON):
        if abs(slot_start_timestamp(zero_date, season_number, season_slot) - timestamp) < 1:
            return season_slot
    return None


def next_slot_after(zero_date, season_number, season_slot):
    if season_slot is None:
        return season_number, 0
    if season_slot + 1 < SLOTS_PER_SEASON:
        return season_number, season_slot + 1
    return season_number + 1, 0


def global_wave_id(season_number, season_slot):
    return SEASON_WAVE_BASE + (season_number - 1) * SLOTS_PER_SEASON + season_slot


def race_number(season_slot, lane):
    """Return the one-based race ordinal for the current season."""
    return SLOT_FIRST_RACE_NUMBERS[season_slot] + lane


def race_name(city, season_slot, lane, season_number):
    if season_slot == CHAMPIONSHIP_R1_SLOT:
        return f"🏆 Qualifiers Series at {city}"
    if season_slot == CHAMPIONSHIP_R2_SLOT:
        return f"🏆 Finalist Series at {city}"
    if season_slot == CHAMPIONSHIP_FINAL_SLOT:
        return f"🏆 {season_name(season_number)} Season Championship at {city}"
    return f"{city}, Race {race_number(season_slot, lane)}"


def stat_value(rng, name):
    if name == "Eyes":
        # Two eyes are ordinary; every other result is deliberately unusual.
        return rng.choices(range(9), weights=(1, 10, 70, 7, 5, 3, 2, 1, 1), k=1)[0]
    if name == "Wheels":
        return rng.choices(range(1, 11), weights=(1, 3, 8, 60, 12, 6, 4, 3, 2, 1), k=1)[0]
    return rng.randint(28, 98)


def force_stats(rng, outlier=False):
    if not outlier:
        return [
            {"name": "Horsepower", "value": rng.randint(40, 60)},
            {"name": "Ghostpower", "value": rng.randint(40, 60)},
        ]
    shape = rng.choice(("horsepower", "ghostpower", "underpowered", "volatile"))
    if shape == "horsepower":
        horsepower, ghostpower = rng.randint(61, 84), rng.randint(34, 58)
    elif shape == "ghostpower":
        horsepower, ghostpower = rng.randint(34, 58), rng.randint(61, 84)
    elif shape == "underpowered":
        horsepower, ghostpower = rng.randint(28, 39), rng.randint(34, 52)
    else:
        if rng.random() < .5:
            horsepower, ghostpower = rng.randint(28, 39), rng.randint(65, 84)
        else:
            horsepower, ghostpower = rng.randint(65, 84), rng.randint(28, 39)
    return [
        {"name": "Horsepower", "value": horsepower},
        {"name": "Ghostpower", "value": ghostpower},
    ]


def normalized_stat(name, value):
    """Put count stats on the 0-100 scale used by displayed base ratings."""
    if name == "Eyes":
        return value / 8 * 100
    if name == "Wheels":
        return (value - 1) / 9 * 100
    return value


def attribute_value(stats):
    return round(sum(normalized_stat(stat["name"], stat["value"]) for stat in stats) / len(stats))


def attributes(rng, schema, force_outlier=False):
    groups = []
    for name, stats in schema.items():
        values = force_stats(rng, force_outlier) if name == "Force" else [
            {"name": stat, "value": stat_value(rng, stat)} for stat in stats
        ]
        groups.append({"name": name, "value": attribute_value(values), "stats": values})
    return groups


def make_roster():
    rng = random.Random(19880417)
    force_rng = random.Random(19880418)
    force_outliers = set(force_rng.sample(range(len(NAMES)), int(len(NAMES) * .15 + .5)))
    roster = [{
        "id": i + 1, "number": f"{i + 1:02d}", "name": name,
        "color": COLORS[i % len(COLORS)], "hometown": CITIES[i % 5]["name"],
        "modifiers": [],
        "attributes": attributes(rng, DRIVER_ATTRIBUTES),
        "car": {"name": car, "modifiers": [],
                "attributes": attributes(rng, CAR_ATTRIBUTES, i in force_outliers)},
    } for i, (name, car) in enumerate(NAMES)]
    # Every nation gets one driver from each strength tier. The seeded shuffles
    # keep the draw feeling organic while making affiliations stable forever.
    ranked = sorted(roster, key=lambda driver: (
        -sum(group["value"] for group in driver["attributes"] + driver["car"]["attributes"]),
        driver["id"],
    ))
    team_rng = random.Random(19681012)
    tiers = [ranked[index:index + len(TEAMS)] for index in range(0, len(ranked), len(TEAMS))]
    for tier in tiers:
        team_rng.shuffle(tier)
    for team_index, team in enumerate(TEAMS):
        for tier in tiers:
            tier[team_index]["team_id"] = team["id"]
    return roster


def stat_map(driver, effective=True):
    groups = driver["attributes"] + driver["car"]["attributes"]
    stats = {stat["name"]: stat["value"] for group in groups for stat in group["stats"]}
    if not effective:
        return stats
    implementations = {modifier.get("implementation") for modifier in driver.get("modifiers", [])}
    car_implementations = {modifier.get("implementation") for modifier in driver["car"].get("modifiers", [])}
    adjustments = {}
    if "haunted" in implementations:
        adjustments.update({"Unfinished business": 25, "Focus": -30})
    if "fritez" in implementations:
        adjustments.update({"Reflexes": 25, "Déjà vu": -30})
    if "unheard-frequency" in car_implementations:
        adjustments.update({"Horsepower": -30, "Ghostpower": 10, "Veil": 10})
    if "shiny" in car_implementations:
        adjustments.update({"Rust": -50, "Hauntings": 50})
    for name, change in adjustments.items():
        stats[name] = max(0, min(100, stats[name] + change))
    return stats


def migrate_driver(driver, template):
    """Upgrade the original roster names without disturbing identity or history."""
    old = stat_map(driver, effective=False)
    renamed = {
        "Pride": "Racecraft",
        "Hauntings": "Corner memory",
        "Veil": "Slipstream",
    }
    result = {
        **driver,
        "team_id": driver.get("team_id", template["team_id"]),
        "modifiers": driver.get("modifiers", []),
        "attributes": [],
        "car": {**driver["car"], "modifiers": driver["car"].get("modifiers", []), "attributes": []},
    }
    for destination, source in ((result["attributes"], template["attributes"]),
                                (result["car"]["attributes"], template["car"]["attributes"])):
        for group in source:
            stats = []
            for fallback in group["stats"]:
                name = fallback["name"]
                value = old.get(name, old.get(renamed.get(name), fallback["value"]))
                # Eyes and Wheels are counts, so old 0-100 surrogate values are
                # intentionally not carried into their new representations.
                if name in ("Eyes", "Wheels", "Horsepower", "Ghostpower"):
                    value = fallback["value"]
                stats.append({"name": name, "value": value})
            destination.append({"name": group["name"], "value": attribute_value(stats), "stats": stats})
    return result


class League:
    def __init__(self, database, clock=time.time):
        self.clock = clock
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(database), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS drivers (id INTEGER PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS races (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wave INTEGER NOT NULL, lane INTEGER NOT NULL,
                start REAL NOT NULL, end REAL NOT NULL, city TEXT NOT NULL,
                name TEXT NOT NULL, data TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0, winner INTEGER,
                UNIQUE(wave, lane)
            );
            CREATE INDEX IF NOT EXISTS race_start ON races(start);
            CREATE INDEX IF NOT EXISTS race_finished ON races(completed, id);
        """)
        with self.db:
            self._migrate_schema()
            if not self.db.execute("SELECT 1 FROM meta WHERE key='anchor'").fetchone():
                self.db.execute("INSERT INTO meta VALUES ('anchor', ?)", (str(clock()),))
                self.db.execute("INSERT INTO meta VALUES ('seed', ?)", (str(random.SystemRandom().randrange(2**32)),))
                self.db.executemany("INSERT INTO drivers VALUES (?, ?)", [(d["id"], json.dumps(d)) for d in make_roster()])
                self.db.execute("INSERT INTO meta VALUES ('roster_version', ?)", (str(ROSTER_VERSION),))
            if not self.db.execute("SELECT 1 FROM meta WHERE key='season_zero_date'").fetchone():
                self.db.execute("INSERT INTO meta VALUES ('season_zero_date', ?)", (monday_for(clock()).isoformat(),))
            version = self.db.execute("SELECT value FROM meta WHERE key='roster_version'").fetchone()
            if version is None or int(version[0]) < ROSTER_VERSION:
                templates = {driver["id"]: driver for driver in make_roster()}
                rows = self.db.execute("SELECT id,data FROM drivers ORDER BY id").fetchall()
                upgraded = [(json.dumps(migrate_driver(json.loads(row["data"]), templates[row["id"]])), row["id"])
                            for row in rows]
                self.db.executemany("UPDATE drivers SET data=? WHERE id=?", upgraded)
                self.db.execute("INSERT OR REPLACE INTO meta VALUES ('roster_version', ?)", (str(ROSTER_VERSION),))
        self.anchor = float(self.db.execute("SELECT value FROM meta WHERE key='anchor'").fetchone()[0])
        self.seed = int(self.db.execute("SELECT value FROM meta WHERE key='seed'").fetchone()[0])
        self.season_zero_date = parse_date(self.db.execute("SELECT value FROM meta WHERE key='season_zero_date'").fetchone()[0])
        with self.db:
            self._normalize_season_schedule()
        self.roster = {row["id"]: json.loads(row["data"]) for row in self.db.execute("SELECT * FROM drivers ORDER BY id")}
        self.tick()

    def _migrate_schema(self):
        columns = {row["name"] for row in self.db.execute("PRAGMA table_info(races)")}
        if "season" not in columns:
            self.db.execute("ALTER TABLE races ADD COLUMN season INTEGER")
        if "season_slot" not in columns:
            self.db.execute("ALTER TABLE races ADD COLUMN season_slot INTEGER")
        if "season_race_number" not in columns:
            self.db.execute("ALTER TABLE races ADD COLUMN season_race_number INTEGER")
        self.db.execute("UPDATE races SET season=0 WHERE season IS NULL")
        self.db.execute("UPDATE races SET season_slot=wave WHERE season_slot IS NULL")
        self.db.execute("UPDATE races SET season_race_number=wave * ? + lane + 1 WHERE season_race_number IS NULL",
                        (RACES_PER_WAVE,))
        self.db.execute("DELETE FROM races WHERE season>0 AND lane>=?", (RACES_PER_WAVE,))
        self.db.execute("UPDATE races SET season_race_number=season_slot * ? + lane + 1 WHERE season>0",
                        (RACES_PER_WAVE,))
        self.db.execute("CREATE INDEX IF NOT EXISTS race_season_slot ON races(season, season_slot)")

    def _normalize_season_schedule(self):
        self.db.execute("UPDATE races SET wave=-id WHERE season>0")
        bracket_version = self.db.execute("SELECT value FROM meta WHERE key='championship_bracket_version'").fetchone()
        rebuild_championship = bracket_version is None or int(bracket_version[0]) < 2
        if rebuild_championship:
            self.db.execute("DELETE FROM races WHERE season>0 AND season_slot>=?", (CHAMPIONSHIP_R2_SLOT,))
        updates = []
        deletes = []
        for row in self.db.execute("SELECT id,season,start,lane,city,name FROM races WHERE season>0").fetchall():
            season_slot = season_slot_for_start(self.season_zero_date, row["season"], row["start"])
            if season_slot is None or row["lane"] >= SEASON_SCHEDULE[season_slot][2]:
                deletes.append((row["id"],))
                continue
            name = race_name(row["city"], season_slot, row["lane"], row["season"])
            updates.append((
                global_wave_id(row["season"], season_slot),
                season_slot,
                race_number(season_slot, row["lane"]),
                name,
                row["id"],
            ))
        self.db.executemany("DELETE FROM races WHERE id=?", deletes)
        self.db.executemany("UPDATE races SET wave=?, season_slot=?, season_race_number=?, name=? WHERE id=?", updates)
        if rebuild_championship:
            self.db.execute("INSERT OR REPLACE INTO meta VALUES ('championship_bracket_version', '2')")

    def _planned_finishers(self, row):
        data = json.loads(row["data"])
        return [
            plan["driver_id"]
            for plan in sorted(data["plans"], key=lambda plan: (plan["splits"][-1], plan["grid"]))
        ]

    def _championship_rows(self, season_number, season_slot):
        return self.db.execute(
            "SELECT * FROM races WHERE season=? AND season_slot=? ORDER BY lane",
            (season_number, season_slot),
        ).fetchall()

    def _previous_round_is_public(self, season_number, season_slot):
        rows = self._championship_rows(season_number, season_slot)
        expected = SEASON_SCHEDULE[season_slot][2]
        return len(rows) == expected and all(row["completed"] for row in rows)

    def _championship_driver_groups(self, season_number, season_slot, rng):
        if season_slot == CHAMPIONSHIP_R2_SLOT:
            rows = self._championship_rows(season_number, CHAMPIONSHIP_R1_SLOT)
            qualifiers = [driver_id for row in rows for driver_id in self._planned_finishers(row)[:5]]
            pool = [driver["id"] for driver in self.roster.values() if driver["id"] not in qualifiers]
            entrants = qualifiers + rng.sample(pool, 1)
            rng.shuffle(entrants)
            return [entrants[:8], entrants[8:16]]
        if season_slot == CHAMPIONSHIP_FINAL_SLOT:
            rows = self._championship_rows(season_number, CHAMPIONSHIP_R2_SLOT)
            finalists = [driver_id for row in rows for driver_id in self._planned_finishers(row)[:4]]
            return [finalists]
        return None

    def _public_racers(self, driver_ids, season_number):
        wins = dict(self.db.execute("SELECT winner, COUNT(*) FROM races WHERE completed=1 AND season=? GROUP BY winner",
                                    (season_number,)))
        return [{
            "driver_id": driver_id,
            "number": self.roster[driver_id]["number"],
            "name": self.roster[driver_id]["name"],
            "color": self.roster[driver_id]["color"],
            "team": self._driver_team(self.roster[driver_id]),
            "wins": wins.get(driver_id, 0),
        } for driver_id in driver_ids]

    @staticmethod
    def _team_public(team):
        return {key: team[key] for key in ("id", "name", "abbreviation", "flag", "color")}

    def _driver_team(self, driver):
        return self._team_public(TEAM_BY_ID[driver["team_id"]])

    def _make_wave(self, season_number, season_slot):
        day, minute, race_count = SEASON_SCHEDULE[season_slot]
        rng = random.Random(self.seed + season_number * 1_000_003 + season_slot * 100_003)
        drivers = list(self.roster.values())
        rng.shuffle(drivers)
        start = slot_start_timestamp(self.season_zero_date, season_number, season_slot)
        wave = global_wave_id(season_number, season_slot)
        cities = rng.sample(CITIES, race_count)
        driver_groups = self._championship_driver_groups(season_number, season_slot, rng)
        if driver_groups is None:
            driver_groups = [[driver["id"] for driver in drivers[lane * 10:lane * 10 + 10]]
                             for lane in range(race_count)]
        for lane, city in enumerate(cities):
            plans = []
            for grid, driver_id in enumerate(driver_groups[lane]):
                driver = self.roster[driver_id]
                plans.append({"driver_id": driver["id"], "grid": grid + 1, "splits": [], "events": [],
                              "total": 0.0, "pace_noise": rng.uniform(-1.6, 1.6)})

            # Laps are built as rounds so first/last place and nearby traffic at
            # the beginning of each lap can drive events without seeing the future.
            for lap in range(LAPS):
                order = sorted(plans, key=lambda plan: (plan["total"], plan["grid"]))
                positions = {plan["driver_id"]: position for position, plan in enumerate(order, 1)}
                previous_totals = {plan["driver_id"]: plan["total"] for plan in plans}
                for plan in plans:
                    driver = self.roster[plan["driver_id"]]
                    stats = stat_map(driver)
                    position = positions[driver["id"]]
                    distance = lap * city["length"]
                    veil = stats["Veil"] / 100
                    acceleration = stats["Horsepower"] * (.70 + .25 * veil) + stats["Ghostpower"] * (.30 - .25 * veil)

                    engine = stats["Smoke"] * .55 + stats["Pipes"] * .45
                    reliability_weight = .18 * (10 - stats["Wheels"]) / 9
                    top_speed = engine * (1 - reliability_weight) + stats["Reliability"] * reliability_weight
                    if distance > 300:
                        degradation = min(.08, (distance - 300) * .0004)
                        acceleration *= 1 - degradation * (100 - stats["Reliability"]) / 100
                        top_speed *= 1 - degradation * stats["Rust"] / 100

                    track_bias = (city["curve_bias"] - 50) / 50
                    acceleration_weight = 1 + .41 * track_bias
                    top_speed_weight = 1 - .41 * track_bias
                    pace = acceleration * acceleration_weight + top_speed * top_speed_weight
                    duration = 53 - .075 * pace + plan["pace_noise"] + rng.uniform(-3, 3)
                    effects = []
                    luck_good = .9 + stats["Luck"] / 500
                    luck_bad = 1.1 - stats["Luck"] / 500

                    def event(chance, low, high, text, kind, beneficial=False):
                        nonlocal duration
                        chance *= luck_good if beneficial else luck_bad
                        if rng.random() >= chance:
                            return
                        delta = rng.uniform(low, high) * (-1 if beneficial else 1)
                        duration += delta
                        effects.append({"text": text, "delta": round(delta, 1), "type": kind})

                    if position == 1:
                        focus_score = stats["Focus"] * .85
                        event(.08 + focus_score * .0008, .35 + focus_score * .003,
                              .55 + focus_score * .003, "surges at the front", "boost", True)
                        event(.02 + stats["Pride"] * .0006, .25 + stats["Pride"] * .0025,
                              .45 + stats["Pride"] * .004, "overdrives the lead", "mistake")

                    event(.015 + stats["Audacity"] * .00055, .35 + stats["Audacity"] * .004,
                          .65 + stats["Audacity"] * .004, "commits to an audacious overdrive", "boost", True)

                    if position == len(plans):
                        desperation = 100 - stats["Dread tolerance"]
                        event(.04 + desperation * .0015, .45 + desperation * .006,
                              .75 + desperation * .006, "refuses to remain last", "boost", True)

                    event(.005 + stats["Eyes"] * .006, .35, .85,
                          "sees an opening nobody else can", "boost", True)

                    if lap and position > 1:
                        ahead = order[position - 2]
                        gap = previous_totals[plan["driver_id"]] - previous_totals[ahead["driver_id"]]
                        if gap <= 2.5:
                            event(.06 + stats["Focus"] * .85 * .0008, .25, .65,
                                  "catches the wake ahead", "draft", True)

                    crash_chance = max(.006, .03 + (stats["Audacity"] - 50) * .00025
                                       - (stats["Reflexes"] - 50) * .00015
                                       - (stats["Déjà vu"] - 50) * .00012)
                    if rng.random() < crash_chance * luck_bad:
                        major_chance = .08 + (100 - stats["Déjà vu"]) * .0012
                        major = rng.random() < major_chance
                        delay = rng.uniform(6, 10) if major else rng.uniform(1.8, 4.5)
                        duration += delay
                        effects.append({"text": "survives a major crash" if major else "spins and recovers",
                                        "delta": round(delay, 1), "type": "major-crash" if major else "crash"})

                    event(.02 + (100 - stats["Grip"]) * .0003,
                          .35 + stats["Hauntings"] * .006, .65 + stats["Hauntings"] * .012,
                          "slips away from top speed", "slip")

                    paranormal_chance = .025 + stats["Eyes"] * .008 + stats["Unfinished business"] * .0005
                    if rng.random() < paranormal_chance:
                        good = rng.random() < .30 + stats["Luck"] * .004
                        delta = rng.uniform(1.5, 4.5) * (-1 if good else 1)
                        duration += delta
                        text = rng.choice(["receives a pep talk", "jumps forward"] if good else
                                          ["negotiates with a shadow", "briefly remembers tomorrow"])
                        effects.append({"text": text, "delta": round(delta, 1), "type": "paranormal"})

                    duration = max(30.0, min(60.0, duration))
                    for effect in effects:
                        plan["events"].append({"at": plan["total"] + duration * .5, "lap": lap + 1, **effect})
                    plan["total"] += duration
                    plan["splits"].append(round(plan["total"], 3))

            for plan in plans:
                del plan["total"]
                del plan["pace_noise"]
            name = race_name(city["name"], season_slot, lane, season_number)
            data = {"city": city, "weather": rng.choice(WEATHER), "plans": plans}
            winner = min(plans, key=lambda p: (p["splits"][-1], p["grid"]))["driver_id"]
            self.db.execute(
                "INSERT OR IGNORE INTO races(wave,lane,start,end,city,name,data,winner,season,season_slot,season_race_number) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (wave, lane, start, start + max(p["splits"][-1] for p in plans), city["name"], name, json.dumps(data),
                 winner, season_number, season_slot, race_number(season_slot, lane)),
            )

    def _next_wave(self, season_number, season_slot):
        """Return the public grid for a future wave without revealing race plans."""
        _day, _minute, race_count = SEASON_SCHEDULE[season_slot]
        rng = random.Random(self.seed + season_number * 1_000_003 + season_slot * 100_003)
        drivers = list(self.roster.values())
        rng.shuffle(drivers)
        cities = rng.sample(CITIES, race_count)
        driver_groups = None
        if season_slot == CHAMPIONSHIP_R2_SLOT and self._previous_round_is_public(season_number, CHAMPIONSHIP_R1_SLOT):
            driver_groups = self._championship_driver_groups(season_number, season_slot, rng)
        elif season_slot == CHAMPIONSHIP_FINAL_SLOT and self._previous_round_is_public(season_number, CHAMPIONSHIP_R2_SLOT):
            driver_groups = self._championship_driver_groups(season_number, season_slot, rng)
        elif season_slot not in (CHAMPIONSHIP_R2_SLOT, CHAMPIONSHIP_FINAL_SLOT):
            driver_groups = [[driver["id"] for driver in drivers[lane * 10:lane * 10 + 10]]
                             for lane in range(race_count)]
        return [{
            "name": race_name(city["name"], season_slot, lane, season_number),
            "race_number": race_number(season_slot, lane),
            "wave": season_slot + 1,
            "season": season_number,
            "start": slot_start_timestamp(self.season_zero_date, season_number, season_slot),
            "city": city,
            "racers": self._public_racers(driver_groups[lane], season_number) if driver_groups else [],
        } for lane, city in enumerate(cities)]

    def tick(self, now=None):
        now = self.clock() if now is None else now
        with self.lock, self.db:
            current_season = season_number_for(self.season_zero_date, now)
            for season_number in range(1, current_season + 1):
                due = SLOTS_PER_SEASON - 1 if season_number < current_season else due_slot_for(self.season_zero_date, season_number, now)
                if due is None:
                    continue
                existing = {
                    (row["season_slot"], row["lane"])
                    for row in self.db.execute("SELECT season_slot,lane FROM races WHERE season=?", (season_number,))
                }
                for season_slot in range(due + 1):
                    if any((season_slot, lane) not in existing for lane in range(SEASON_SCHEDULE[season_slot][2])):
                        self._make_wave(season_number, season_slot)
            self.db.execute("UPDATE races SET completed=1 WHERE completed=0 AND end<=?", (now,))

    def _standings(self, data, elapsed):
        standings = []
        for plan in data["plans"]:
            splits = plan["splits"]
            laps = bisect.bisect_right(splits, elapsed)
            previous = splits[laps - 1] if laps else 0
            fraction = (elapsed - previous) / (splits[laps] - previous) if laps < LAPS else 0
            progress = min(LAPS, laps + max(0, fraction))
            driver = self.roster[plan["driver_id"]]
            standings.append({"driver_id": driver["id"], "name": driver["name"], "number": driver["number"],
                              "car": driver["car"]["name"], "color": driver["color"], "grid": plan["grid"],
                              "team": self._driver_team(driver),
                              "laps": laps, "progress": round(progress, 5), "distance": round(progress * data["city"]["length"], 2),
                              "finished": laps == LAPS, "finish_time": splits[-1] if laps == LAPS else None,
                              "last_lap": round(splits[laps - 1] - (splits[laps - 2] if laps > 1 else 0), 3) if laps else None})
        standings.sort(key=lambda s: (0, s["finish_time"], s["grid"]) if s["finished"] else (1, -s["progress"], s["grid"]))
        leader = standings[0]
        leader_plan = next(p for p in data["plans"] if p["driver_id"] == leader["driver_id"])
        for position, row in enumerate(standings, 1):
            row["position"] = position
            if row["finished"]:
                row["gap"] = round(row["finish_time"] - leader["finish_time"], 2)
            else:
                whole = min(9, int(row["progress"]))
                before = leader_plan["splits"][whole - 1] if whole else 0
                crossing = before + (leader_plan["splits"][whole] - before) * (row["progress"] - whole)
                row["gap"] = max(0, round(elapsed - crossing, 2)) if position > 1 else 0
        return standings

    def _race(self, row, now, detail=True):
        data = json.loads(row["data"])
        duration = max(plan["splits"][-1] for plan in data["plans"])
        # Use the original duration after completion: subtracting epoch floats
        # can otherwise leave the last driver a fraction short of the flag.
        elapsed = duration if row["completed"] else max(0, min(now - row["start"], duration))
        standings = self._standings(data, elapsed)
        season = row["season"] if "season" in row.keys() else 0
        season_slot = row["season_slot"] if "season_slot" in row.keys() else row["wave"]
        season_race_number = row["season_race_number"] if "season_race_number" in row.keys() else row["wave"] * RACES_PER_WAVE + row["lane"] + 1
        result = {"id": row["id"], "name": row["name"],
                  "race_number": season_race_number, "wave": season_slot + 1, "season": season,
                  "start": row["start"], "end": row["end"] if row["completed"] else None,
                  "status": "finished" if row["completed"] else "live", "city": data["city"], "weather": data["weather"],
                  "elapsed": round(elapsed, 3), "laps": LAPS, "standings": standings if detail else standings[:3]}
        if detail:
            events = [{"at": 0, "text": f"Green lights. {len(data['plans'])} drivers. One questionable destination.", "type": "start"}]
            for plan in data["plans"]:
                driver = self.roster[plan["driver_id"]]
                for incident in plan.get("events", plan.get("incidents", [])):
                    if incident["at"] <= elapsed:
                        delta = incident.get("delta", incident.get("delay", 0))
                        sign = "−" if delta < 0 else "+"
                        events.append({"at": incident["at"],
                                       "text": f"{driver['name']} {incident['text']}. {sign}{abs(delta):.1f}s.",
                                       "type": incident.get("type", "paranormal")})
                if plan["splits"][-1] <= elapsed:
                    pos = next(s["position"] for s in standings if s["driver_id"] == driver["id"])
                    events.append({"at": plan["splits"][-1], "text": f"{driver['name']} takes the flag in P{pos}.", "type": "finish"})
            result["events"] = sorted(events, key=lambda e: e["at"], reverse=True)[:20]
        return result

    def state(self):
        with self.lock:
            now = self.clock()
            self.tick(now)
            season_number = season_number_for(self.season_zero_date, now)
            season_slot = due_slot_for(self.season_zero_date, season_number, now)
            if season_slot is None:
                rows = []
            else:
                rows = self.db.execute(
                    "SELECT * FROM races WHERE season=? AND season_slot=? ORDER BY lane",
                    (season_number, season_slot),
                ).fetchall()
            races = [self._race(row, now) for row in rows]
            next_season, next_slot = next_slot_after(self.season_zero_date, season_number, season_slot)
            total = self.db.execute("SELECT COUNT(*) FROM races WHERE completed=1 AND season=?", (season_number,)).fetchone()[0]
            return {"now": now, "next_start": slot_start_timestamp(self.season_zero_date, next_season, next_slot),
                    "interval": INTERVAL, "wave": (season_slot + 1) if season_slot is not None else 0,
                    "races": races, "next_races": self._next_wave(next_season, next_slot),
                    "completed_races": total, "season_total_races": RACES_PER_SEASON, "cities": CITIES,
                    "season": {"number": season_number, "name": season_name(season_number), "total_races": RACES_PER_SEASON}}

    def seasons(self):
        with self.lock:
            self.tick()
            current = season_number_for(self.season_zero_date, self.clock())
            generated = [row[0] for row in self.db.execute("SELECT DISTINCT season FROM races WHERE season>0 ORDER BY season DESC")]
            numbers = sorted(set(generated + [current]), reverse=True)
            return [{"number": number, "name": season_name(number), "current": number == current} for number in numbers]

    def final_lap(self):
        """Return the newest champion and the current weekly election window."""
        with self.lock:
            now = self.clock()
            self.tick(now)
            row = self.db.execute(
                "SELECT * FROM races WHERE completed=1 AND season_slot=? ORDER BY season DESC LIMIT 1",
                (CHAMPIONSHIP_FINAL_SLOT,),
            ).fetchone()
            if row is None:
                return {"winner": None}
            winner_id = row["winner"]
            wins = self.db.execute(
                "SELECT COUNT(*) FROM races WHERE completed=1 AND season=? AND winner=?",
                (row["season"], winner_id),
            ).fetchone()[0]
            driver = self.roster[winner_id]
            result = {
                "season": {"number": row["season"], "name": season_name(row["season"])},
                "winner": {key: driver[key] for key in ("id", "name", "number", "color")},
                "wins": wins,
            }
            teams = self.teams(row["season"])
            result["team_champion"] = teams[0] if teams else None
            local_now = datetime.fromtimestamp(now, EASTERN)
            reveal_date = local_now.date() - timedelta(days=(local_now.weekday() - 3) % 7)
            reveal = datetime.combine(reveal_date, datetime_time(), EASTERN).timestamp()
            closes = datetime.combine(reveal_date + timedelta(days=3), datetime_time(13), EASTERN).timestamp()
            results_end = datetime.combine(reveal_date + timedelta(days=5), datetime_time(), EASTERN).timestamp()
            election_row = self.db.execute(
                """SELECT * FROM races WHERE completed=1 AND season_slot=? AND end<=?
                   ORDER BY season DESC LIMIT 1""",
                (CHAMPIONSHIP_FINAL_SLOT, reveal),
            ).fetchone()
            if election_row:
                phase = "open" if now < closes else "results" if now < results_end else "locked"
                result["election"] = {
                    "season": election_row["season"],
                    "season_name": season_name(election_row["season"]),
                    "phase": phase,
                    "opens_at": reveal,
                    "closes_at": closes,
                    "results_end_at": results_end,
                }
            else:
                result["election"] = None
            return result

    def election_timing(self, season):
        """Return the Thursday-to-Tuesday election timing following a season."""
        reveal_date = season_start_date(self.season_zero_date, season) + timedelta(days=10)
        opens = datetime.combine(reveal_date, datetime_time(), EASTERN).timestamp()
        closes = datetime.combine(reveal_date + timedelta(days=3), datetime_time(13), EASTERN).timestamp()
        results_end = datetime.combine(reveal_date + timedelta(days=5), datetime_time(), EASTERN).timestamp()
        return {"opens_at": opens, "closes_at": closes, "results_end_at": results_end}

    def apply_pit_outcomes(self, season, outcomes):
        """Apply one finalized election's unique pit-crew changes exactly once."""
        marker = f"pit_crew_effects:{season}"
        with self.lock, self.db:
            if self.db.execute("SELECT 1 FROM meta WHERE key=?", (marker,)).fetchone():
                return False
            changed = set()

            def stat(driver, name):
                for group in driver["attributes"] + driver["car"]["attributes"]:
                    for entry in group["stats"]:
                        if entry["name"] == name:
                            return entry
                raise KeyError(name)

            def refresh(driver):
                for group in driver["attributes"] + driver["car"]["attributes"]:
                    group["value"] = attribute_value(group["stats"])

            def add_modifier(container, key):
                implementation = MODIFIERS[key]["implementation"]
                modifiers = container.setdefault("modifiers", [])
                if not any(item.get("implementation") == implementation for item in modifiers):
                    modifiers.append(dict(MODIFIERS[key]))

            for outcome in outcomes:
                action = outcome.get("action")
                first_id = outcome.get("target_a")
                second_id = outcome.get("target_b")
                if first_id not in self.roster or (second_id is not None and second_id not in self.roster):
                    continue
                first = self.roster[first_id]
                if action == "car-swap" and second_id != first_id:
                    second = self.roster[second_id]
                    first["car"], second["car"] = second["car"], first["car"]
                    changed.update((first_id, second_id))
                elif action == "soul-swap" and second_id != first_id:
                    second = self.roster[second_id]
                    for name in ("Reflexes", "Pride", "Focus"):
                        one, two = stat(first, name), stat(second, name)
                        one["value"], two["value"] = two["value"], one["value"]
                    refresh(first)
                    refresh(second)
                    changed.update((first_id, second_id))
                elif action == "haunting":
                    add_modifier(first, "haunted")
                    changed.add(first_id)
                elif action == "white-coffee":
                    add_modifier(first, "fritez")
                    changed.add(first_id)
                elif action == "eye-exam":
                    eye = stat(first, "Eyes")
                    choices = [value for value in range(9) if value != eye["value"]]
                    eye["value"] = random.Random(f"{season}:eye-exam:{first_id}").choice(choices)
                    add_modifier(first, "beautiful-vision")
                    refresh(first)
                    changed.add(first_id)
                elif action == "tune-down":
                    add_modifier(first["car"], "unheard-frequency")
                    changed.add(first_id)
                elif action == "reflective-paint":
                    add_modifier(first["car"], "shiny")
                    changed.add(first_id)

            for driver_id in changed:
                self.db.execute("UPDATE drivers SET data=? WHERE id=?",
                                (json.dumps(self.roster[driver_id]), driver_id))
            self.db.execute("INSERT INTO meta(key,value) VALUES (?,?)", (marker, json.dumps(outcomes)))
            return True

    def eternals(self):
        """Return all-time championship honors and the completed season archive."""
        with self.lock:
            self.tick()
            records = {
                driver_id: {
                    "id": driver_id,
                    "name": driver["name"],
                    "number": driver["number"],
                    "color": driver["color"],
                    "championship_wins": 0,
                    "championship_seconds": 0,
                    "championship_thirds": 0,
                    "championship_appearances": 0,
                    "finalist_appearances": 0,
                }
                for driver_id, driver in self.roster.items()
            }

            finalist_rows = self.db.execute(
                "SELECT * FROM races WHERE completed=1 AND season_slot=? ORDER BY season,lane",
                (CHAMPIONSHIP_R2_SLOT,),
            ).fetchall()
            for row in finalist_rows:
                for driver_id in self._planned_finishers(row):
                    records[driver_id]["finalist_appearances"] += 1

            championship_rows = self.db.execute(
                "SELECT * FROM races WHERE completed=1 AND season_slot=? ORDER BY season DESC",
                (CHAMPIONSHIP_FINAL_SLOT,),
            ).fetchall()
            seasons = []
            for row in championship_rows:
                finishers = self._planned_finishers(row)
                for driver_id in finishers:
                    records[driver_id]["championship_appearances"] += 1
                for field, driver_id in zip(
                    ("championship_wins", "championship_seconds", "championship_thirds"),
                    finishers[:3],
                ):
                    records[driver_id][field] += 1
                seasons.append({
                    "number": row["season"],
                    "name": season_name(row["season"]),
                    "start_date": season_start_date(self.season_zero_date, row["season"]).isoformat(),
                    "winner": {key: records[finishers[0]][key] for key in ("id", "name", "number", "color")},
                    "second": {key: records[finishers[1]][key] for key in ("id", "name", "number", "color")},
                    "third": {key: records[finishers[2]][key] for key in ("id", "name", "number", "color")},
                    "team_champion": self.teams(row["season"])[0],
                })

            current_season = season_number_for(self.season_zero_date, self.clock())
            if seasons and seasons[0]["number"] == current_season:
                next_season = current_season + 1
                seasons.insert(0, {
                    "number": next_season,
                    "name": season_name(next_season),
                    "start_date": season_start_date(self.season_zero_date, next_season).isoformat(),
                    "winner": None,
                    "second": None,
                    "third": None,
                    "team_champion": None,
                })

            drivers = []
            for record in records.values():
                record["eternal_score"] = (
                    record["championship_wins"] * 7
                    + record["championship_seconds"] * 5
                    + record["championship_thirds"] * 3
                    + record["championship_appearances"] * 2
                    + record["finalist_appearances"]
                )
                if record["eternal_score"] > 0:
                    drivers.append(record)
            drivers.sort(key=lambda record: (
                -record["eternal_score"],
                -record["championship_wins"],
                -record["championship_seconds"],
                -record["championship_thirds"],
                -record["championship_appearances"],
                -record["finalist_appearances"],
                record["name"],
            ))
            team_records = [{**self._team_public(team), "drivers": [
                {key: driver[key] for key in ("id", "name", "number", "color")}
                for driver in self.roster.values() if driver["team_id"] == team["id"]
            ], "championship_wins": sum(
                season.get("team_champion", {}).get("id") == team["id"]
                for season in seasons if season.get("team_champion")
            )} for team in TEAMS]
            team_records.sort(key=lambda team: (-team["championship_wins"], team["name"]))
            return {"teams": team_records, "drivers": drivers, "seasons": seasons}

    def drivers(self, season=None):
        with self.lock:
            self.tick()
            current = season_number_for(self.season_zero_date, self.clock())
            selected = current if season is None else max(1, min(int(season), current))
            wins = dict(self.db.execute("SELECT winner, COUNT(*) FROM races WHERE completed=1 AND season=? GROUP BY winner",
                                        (selected,)))
            starts = {driver_id: 0 for driver_id in self.roster}
            for row in self.db.execute("SELECT data FROM races WHERE season=?", (selected,)):
                for plan in json.loads(row["data"])["plans"]:
                    starts[plan["driver_id"]] += 1
            return [{**d, "team": self._driver_team(d), "wins": wins.get(d["id"], 0), "starts": starts.get(d["id"], 0)} for d in self.roster.values()]

    def teams(self, season=None, sponsor_counts=None):
        """Return the ten nations with race points and their current drivers."""
        with self.lock:
            current = season_number_for(self.season_zero_date, self.clock())
            selected = current if season is None else max(1, min(int(season), current))
            points = {team["id"]: 0 for team in TEAMS}
            rows = self.db.execute(
                "SELECT * FROM races WHERE completed=1 AND season=? ORDER BY season_slot,lane", (selected,)
            ).fetchall()
            for row in rows:
                scale = (6, 4, 2) if row["season_slot"] >= CHAMPIONSHIP_R1_SLOT else (3, 2, 1)
                for driver_id, score in zip(self._planned_finishers(row)[:3], scale):
                    points[self.roster[driver_id]["team_id"]] += score
            sponsor_counts = sponsor_counts or {}
            result = []
            for team in TEAMS:
                result.append({
                    **self._team_public(team),
                    "points": points[team["id"]],
                    "sponsors": sponsor_counts.get(team["id"], 0),
                    "drivers": [driver["id"] for driver in self.roster.values() if driver["team_id"] == team["id"]],
                })
            result.sort(key=lambda team: (-team["points"], team["name"]))
            return result

    def history(self, page=1, query="", city="", season=None):
        with self.lock:
            self.tick()
            current = season_number_for(self.season_zero_date, self.clock())
            selected = current if season is None else max(1, min(int(season), current))
            clause = "completed=1 AND season=?"
            args = [selected]
            if query:
                # Literal substring search: SQL wildcard characters stay literal.
                clause += " AND instr(lower(name),lower(?))>0"
                args.append(query)
            if city:
                clause += " AND city=?"
                args.append(city)
            total = self.db.execute("SELECT COUNT(*) FROM races WHERE " + clause, args).fetchone()[0]
            page = min(max(1, page), max(1, (total + 11) // 12))
            rows = self.db.execute("SELECT * FROM races WHERE " + clause + " ORDER BY start DESC,id DESC LIMIT 12 OFFSET ?", args + [(page - 1) * 12]).fetchall()
            return {"races": [self._race(row, self.clock(), detail=False) for row in rows], "total": total,
                    "page": page, "pages": max(1, (total + 11) // 12),
                    "season": {"number": selected, "name": season_name(selected), "total_races": RACES_PER_SEASON}}

    def tracks(self):
        """Return every circuit with its ten most recent completed podiums."""
        with self.lock:
            self.tick()
            result = []
            for city in CITIES:
                rows = self.db.execute(
                    "SELECT * FROM races WHERE completed=1 AND city=? ORDER BY start DESC,id DESC LIMIT 10",
                    (city["name"],),
                ).fetchall()
                result.append({
                    "name": city["name"], "country": city["country"], "code": city["code"],
                    "circuit": city["circuit"], "length": city["length"], "curve_bias": city["curve_bias"],
                    "races": [self._race(row, self.clock(), detail=False) for row in rows],
                })
            return result

    def race(self, race_id):
        with self.lock:
            self.tick()
            row = self.db.execute("SELECT * FROM races WHERE id=?", (race_id,)).fetchone()
            return self._race(row, self.clock()) if row else None

    def bet_offer(self, season, race_number, driver_id):
        """Validate that a driver is on the currently offered future grid."""
        with self.lock:
            now = self.clock()
            self.tick(now)
            current_season = season_number_for(self.season_zero_date, now)
            current_slot = due_slot_for(self.season_zero_date, current_season, now)
            next_season, next_slot = next_slot_after(self.season_zero_date, current_season, current_slot)
            for race in self._next_wave(next_season, next_slot):
                if race["season"] != season or race["race_number"] != race_number or now >= race["start"]:
                    continue
                driver = next((entry for entry in race["racers"] if entry["driver_id"] == driver_id), None)
                if driver:
                    return {"season": season, "race_number": race_number, "driver_id": driver_id,
                            "cost": 5 + driver["wins"], "wins": driver["wins"]}
            return None

    def completed_item_races(self):
        """Return compact immutable race facts used for fan-equipment payouts."""
        with self.lock:
            self.tick()
            rows = self.db.execute("SELECT * FROM races WHERE completed=1 ORDER BY id").fetchall()
            results = []
            for row in rows:
                data = json.loads(row["data"])
                standings = self._standings(data, max(plan["splits"][-1] for plan in data["plans"]))
                prior = self.db.execute(
                    "SELECT 1 FROM races WHERE completed=1 AND season=? AND winner=? AND (start<? OR (start=? AND id<?)) LIMIT 1",
                    (row["season"], row["winner"], row["start"], row["start"], row["id"]),
                ).fetchone()
                results.append({"id": row["id"], "season": row["season"],
                                "race_number": row["season_race_number"],
                                "standings": standings, "plans": data["plans"],
                                "duration": max(plan["splits"][-1] for plan in data["plans"]),
                                "first_season_win": prior is None})
            return results

    def completed_bet_races(self):
        """Return stable identifiers and winners for finished-race bet settlement."""
        with self.lock:
            self.tick()
            return [dict(row) for row in self.db.execute(
                "SELECT season,season_race_number AS race_number,winner FROM races WHERE completed=1 ORDER BY id"
            )]

    def close(self):
        with self.lock:
            self.db.close()
