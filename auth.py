"""Local account storage and sessions for the VASTCAR web server."""

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from http.cookies import SimpleCookie


SESSION_COOKIE = "vastcar_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 14
FAVORITE_CHANGE_INTERVAL_SECONDS = 60 * 60 * 24
PASSWORD_N = 2 ** 14
PASSWORD_R = 8
PASSWORD_P = 1
PASSWORD_LENGTH = 32
PBKDF2_ITERATIONS = 600_000
USERNAME_RE = re.compile(r"[A-Za-z0-9_-]{3,32}\Z")
STARTING_COIN = 200
DAILY_LOGIN_COIN = 50
BET_PAYOUT = 100
MAX_BETS_PER_DRIVER = 10
SUNGLASSES_BONUS = 1000
LUCKY_TICKET_BONUS = 5

ITEMS = {
    "binoculars": {"name": "Binoculars", "cost": 100, "effect": "Every time your Favorite Racer wins, gain 10 Coin."},
    "beer": {"name": "Beer", "cost": 20, "effect": "Every time your Favorite Racer finishes in the bottom 3, gain 5 Coin."},
    "whistle": {"name": "Whistle", "cost": 25, "effect": "Every time your Favorite Racer finishes in the top 3, gain 5 Coin."},
    "camera": {"name": "Camera", "cost": 30, "effect": "Every time there is a crash, gain 10 Coin."},
    "old-scroll": {"name": "Old Scroll", "cost": 10, "effect": "Every time someone wins for the first time that season, gain 10 Coin."},
    "watch": {"name": "Watch", "cost": 10, "effect": "Gain 50 Coin when any race takes over 8 minutes."},
    "vegas-shark": {"name": "Vegas Shark", "cost": 50, "effect": "Decrease a racer's win surcharge by 2 Coin per active Shark."},
    "sunglasses": {"name": "Sunglasses", "cost": 50, "effect": "Gain 1,000 bonus Coin per active pair when a zero-win pick wins."},
    "gun": {"name": "Gun", "cost": 100, "effect": "Increase the number of bets you can place per racer by 1."},
    "lucky-ticket": {"name": "Lucky Ticket", "cost": 1, "effect": "Gain 5 bonus Coin per active ticket when you only back one driver in a race."},
}
MAX_STACK_SIZE = 10
ACTIVE_SLOT_LIMIT = 3
STASH_SLOT_LIMIT = 5
STACK_ID_RE = re.compile(r"[A-Za-z0-9_-]{8,64}\Z")
FINAL_LAP_CHOICES = ("team-work", "advertising", "explosions")
PIT_CREW_ACTIONS = {
    "car-swap": 2,
    "haunting": 1,
    "soul-swap": 2,
    "white-coffee": 1,
    "eye-exam": 1,
    "tune-down": 1,
    "reflective-paint": 1,
}
PIT_CREW_TICKET_COST = 10


class AuthError(Exception):
    """An expected account or session validation failure."""


def _b64url(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


class LocalAuth:
    """SQLite users, scrypt password hashes, and signed browser sessions."""

    def __init__(self, database, environ=None, clock=time.time):
        environ = os.environ if environ is None else environ
        self.session_secret = environ.get("APP_SESSION_SECRET", "") or secrets.token_urlsafe(48)
        self.clock = clock
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(database), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        with self.db:
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    is_admin INTEGER NOT NULL DEFAULT 0 CHECK (is_admin IN (0, 1)),
                    coin INTEGER NOT NULL DEFAULT 0 CHECK (coin >= 0),
                    fav_racer INTEGER,
                    inventory TEXT NOT NULL DEFAULT '[]',
                    created_at INTEGER NOT NULL
                )
            """)
            columns = {row["name"] for row in self.db.execute("PRAGMA table_info(users)")}
            if "fav_racer_changed_at" not in columns:
                self.db.execute("ALTER TABLE users ADD COLUMN fav_racer_changed_at INTEGER")
            if "last_daily_claim_day" not in columns:
                self.db.execute("ALTER TABLE users ADD COLUMN last_daily_claim_day INTEGER")
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS item_reward_races (
                    user_id INTEGER NOT NULL,
                    race_id INTEGER NOT NULL,
                    PRIMARY KEY (user_id, race_id)
                )
            """)
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS bets (
                    user_id INTEGER NOT NULL,
                    season INTEGER NOT NULL,
                    race_number INTEGER NOT NULL,
                    driver_id INTEGER NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 1),
                    spent INTEGER NOT NULL DEFAULT 0 CHECK (spent >= 0),
                    sunglasses INTEGER NOT NULL DEFAULT 0 CHECK (sunglasses >= 0),
                    lucky_tickets INTEGER NOT NULL DEFAULT 0 CHECK (lucky_tickets >= 0),
                    settled INTEGER NOT NULL DEFAULT 0 CHECK (settled IN (0, 1)),
                    PRIMARY KEY (user_id, season, race_number, driver_id)
                )
            """)
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS fan_activity (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    season INTEGER NOT NULL,
                    race_number INTEGER,
                    driver_id INTEGER,
                    kind TEXT NOT NULL,
                    item_id TEXT,
                    quantity INTEGER NOT NULL DEFAULT 1,
                    amount INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    source_key TEXT,
                    UNIQUE (user_id, source_key)
                )
            """)
            self.db.execute(
            "CREATE INDEX IF NOT EXISTS fan_activity_user_season ON fan_activity(user_id, season, id DESC)"
            )
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS final_lap_votes (
                    user_id INTEGER NOT NULL,
                    season INTEGER NOT NULL,
                    choice TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    PRIMARY KEY (user_id, season)
                )
            """)
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS pit_crew_tickets (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    season INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    target_a INTEGER NOT NULL,
                    target_b INTEGER,
                    created_at INTEGER NOT NULL
                )
            """)
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS final_lap_results (
                    season INTEGER PRIMARY KEY,
                    result TEXT NOT NULL,
                    finalized_at INTEGER NOT NULL
                )
            """)
            self._migrate_bets()

    def _migrate_bets(self):
        """Lift the original ten-bet database constraint and add item snapshots."""
        sql = self.db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='bets'").fetchone()["sql"]
        columns = {row["name"] for row in self.db.execute("PRAGMA table_info(bets)")}
        if "BETWEEN 1 AND 10" in sql:
            self.db.execute("ALTER TABLE bets RENAME TO bets_before_betting_items")
            self.db.execute("""
                CREATE TABLE bets (
                    user_id INTEGER NOT NULL, season INTEGER NOT NULL,
                    race_number INTEGER NOT NULL, driver_id INTEGER NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 1),
                    spent INTEGER NOT NULL DEFAULT 0 CHECK (spent >= 0),
                    sunglasses INTEGER NOT NULL DEFAULT 0 CHECK (sunglasses >= 0),
                    lucky_tickets INTEGER NOT NULL DEFAULT 0 CHECK (lucky_tickets >= 0),
                    settled INTEGER NOT NULL DEFAULT 0 CHECK (settled IN (0, 1)),
                    PRIMARY KEY (user_id, season, race_number, driver_id)
                )
            """)
            self.db.execute(
                """INSERT INTO bets(user_id,season,race_number,driver_id,quantity,spent,settled)
                   SELECT user_id,season,race_number,driver_id,quantity,spent,settled
                   FROM bets_before_betting_items"""
            )
            self.db.execute("DROP TABLE bets_before_betting_items")
        else:
            if "sunglasses" not in columns:
                self.db.execute("ALTER TABLE bets ADD COLUMN sunglasses INTEGER NOT NULL DEFAULT 0 CHECK (sunglasses >= 0)")
            if "lucky_tickets" not in columns:
                self.db.execute("ALTER TABLE bets ADD COLUMN lucky_tickets INTEGER NOT NULL DEFAULT 0 CHECK (lucky_tickets >= 0)")

    def close(self):
        with self.lock:
            self.db.close()

    def register(self, username, password):
        username = self._validate_username(username)
        self._validate_password(password)
        encoded_password = self._hash_password(password)
        try:
            with self.lock, self.db:
                cursor = self.db.execute(
                    "INSERT INTO users (username, password_hash, coin, last_daily_claim_day, created_at) VALUES (?, ?, ?, ?, ?)",
                    (username, encoded_password, STARTING_COIN, self._claim_day(), int(self.clock())),
                )
                return self._user_by_id(cursor.lastrowid)
        except sqlite3.IntegrityError as error:
            raise AuthError("That username is already taken") from error

    def login(self, username, password):
        if not isinstance(username, str) or not isinstance(password, str):
            raise AuthError("Username and password are required")
        with self.lock, self.db:
            row = self.db.execute("SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username.strip(),)).fetchone()
            if row is None or not self._verify_password(password, row["password_hash"]):
                raise AuthError("Invalid username or password")
            return self._public_user(self._claim_daily_login(row))

    def set_favorite_racer(self, user_id, racer_id):
        """Save a favorite racer, allowing one selection or change every 24 hours."""
        if not isinstance(user_id, int) or not isinstance(racer_id, int):
            raise AuthError("Choose a valid driver")
        now = int(self.clock())
        with self.lock, self.db:
            row = self.db.execute("SELECT fav_racer_changed_at FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                raise AuthError("Your session has expired")
            changed_at = row["fav_racer_changed_at"]
            if changed_at is not None and now < changed_at + FAVORITE_CHANGE_INTERVAL_SECONDS:
                raise AuthError("Your favorite driver can be changed once every 24 hours")
            self.db.execute(
                "UPDATE users SET fav_racer = ?, fav_racer_changed_at = ? WHERE id = ?",
                (racer_id, now, user_id),
            )
            return self._user_by_id(user_id)

    def favorite_change_available_at(self, user_id):
        with self.lock:
            row = self.db.execute("SELECT fav_racer_changed_at FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None or row["fav_racer_changed_at"] is None:
            return None
        return row["fav_racer_changed_at"] + FAVORITE_CHANGE_INTERVAL_SECONDS

    def favorite_counts(self):
        """Return the number of accounts that have selected each driver."""
        with self.lock:
            rows = self.db.execute(
                "SELECT fav_racer, COUNT(*) AS fans FROM users WHERE fav_racer IS NOT NULL GROUP BY fav_racer"
            )
            return {row["fav_racer"]: row["fans"] for row in rows}

    def final_lap_poll(self, season, user_id=None):
        with self.lock:
            totals = {choice: 0 for choice in FINAL_LAP_CHOICES}
            for row in self.db.execute(
                "SELECT choice, COUNT(*) AS total FROM final_lap_votes WHERE season=? GROUP BY choice", (season,)
            ):
                if row["choice"] in totals:
                    totals[row["choice"]] = row["total"]
            selected = None
            if user_id is not None:
                row = self.db.execute(
                    "SELECT choice FROM final_lap_votes WHERE user_id=? AND season=?", (user_id, season)
                ).fetchone()
                selected = row["choice"] if row else None
            return {"totals": totals, "selected": selected, "total": sum(totals.values())}

    def vote_final_lap(self, user_id, season, choice):
        if not isinstance(season, int) or choice not in FINAL_LAP_CHOICES:
            raise AuthError("Choose a valid Final Lap option")
        with self.lock, self.db:
            try:
                self.db.execute(
                    "INSERT INTO final_lap_votes(user_id,season,choice,created_at) VALUES (?,?,?,?)",
                    (user_id, season, choice, int(self.clock())),
                )
            except sqlite3.IntegrityError as error:
                raise AuthError("Your amendment vote is already locked in") from error
        return self.final_lap_poll(season, user_id)

    def buy_pit_crew_ticket(self, user_id, season, action, target_a, target_b=None):
        selections = PIT_CREW_ACTIONS.get(action)
        if type(season) is not int or selections is None or type(target_a) is not int:
            raise AuthError("Choose a valid pit crew change")
        if selections == 2:
            if type(target_b) is not int or target_a == target_b:
                raise AuthError("Choose two different drivers")
            target_a, target_b = sorted((target_a, target_b))
        elif target_b is not None:
            raise AuthError("That pit crew change only needs one driver")
        with self.lock, self.db:
            user = self.db.execute("SELECT coin FROM users WHERE id=?", (user_id,)).fetchone()
            if user is None:
                raise AuthError("Your session has expired")
            if user["coin"] < PIT_CREW_TICKET_COST:
                raise AuthError(f"You need {PIT_CREW_TICKET_COST} Coin for a pit crew entry")
            self.db.execute("UPDATE users SET coin=coin-? WHERE id=?", (PIT_CREW_TICKET_COST, user_id))
            cursor = self.db.execute(
                """INSERT INTO pit_crew_tickets(user_id,season,action,target_a,target_b,created_at)
                   VALUES (?,?,?,?,?,?)""",
                (user_id, season, action, target_a, target_b, int(self.clock())),
            )
            return {"ticket_id": cursor.lastrowid, "user": self._user_by_id(user_id)}

    def pit_crew_ticket_count(self, season, user_id=None):
        with self.lock:
            total = self.db.execute("SELECT COUNT(*) FROM pit_crew_tickets WHERE season=?", (season,)).fetchone()[0]
            mine = 0 if user_id is None else self.db.execute(
                "SELECT COUNT(*) FROM pit_crew_tickets WHERE season=? AND user_id=?", (season, user_id)
            ).fetchone()[0]
            return {"total": total, "mine": mine}

    def final_lap_result(self, season):
        with self.lock:
            row = self.db.execute("SELECT result FROM final_lap_results WHERE season=?", (season,)).fetchone()
            return json.loads(row["result"]) if row else None

    def finalize_election(self, season):
        """Draw at most ten unique weighted pit changes and freeze all results."""
        with self.lock, self.db:
            existing = self.db.execute("SELECT result FROM final_lap_results WHERE season=?", (season,)).fetchone()
            if existing:
                return json.loads(existing["result"])
            amendments = self.final_lap_poll(season)
            tickets = [dict(row) for row in self.db.execute(
                "SELECT id,action,target_a,target_b FROM pit_crew_tickets WHERE season=? ORDER BY id", (season,)
            )]
            secrets.SystemRandom().shuffle(tickets)
            outcomes = []
            seen = set()
            for ticket in tickets:
                key = (ticket["action"], ticket["target_a"], ticket["target_b"])
                if key in seen:
                    continue
                seen.add(key)
                outcomes.append({key: ticket[key] for key in ("action", "target_a", "target_b")})
                if len(outcomes) == 10:
                    break
            result = {"amendments": amendments["totals"], "pit_crew": outcomes}
            self.db.execute(
                "INSERT INTO final_lap_results(season,result,finalized_at) VALUES (?,?,?)",
                (season, json.dumps(result, separators=(",", ":")), int(self.clock())),
            )
            return result

    def pending_election_seasons(self):
        with self.lock:
            rows = self.db.execute("""
                SELECT season FROM final_lap_votes
                UNION SELECT season FROM pit_crew_tickets
                EXCEPT SELECT season FROM final_lap_results
            """).fetchall()
            return [row["season"] for row in rows]

    def buy_item(self, user_id, item_id):
        if not isinstance(item_id, str) or item_id not in ITEMS:
            raise AuthError("That item is not sold at the Tower")
        with self.lock, self.db:
            row = self.db.execute("SELECT coin, inventory FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                raise AuthError("Your session has expired")
            item = ITEMS[item_id]
            if row["coin"] < item["cost"]:
                raise AuthError(f"You need {item['cost']} Coin for {item['name']}")
            inventory = self._normalize_inventory(json.loads(row["inventory"]))
            stack = next((entry for entry in inventory if entry["item"] == item_id and entry["quantity"] < MAX_STACK_SIZE), None)
            if stack:
                stack["quantity"] += 1
            else:
                inactive = sum(not entry["active"] for entry in inventory)
                active = len(inventory) - inactive
                if inactive < STASH_SLOT_LIMIT:
                    inventory.append(self._new_stack(item_id, False))
                elif active < ACTIVE_SLOT_LIMIT:
                    inventory.append(self._new_stack(item_id, True))
                else:
                    raise AuthError("Your inventory and stash are full. Add to a stack with room or sell an item first.")
            self.db.execute("UPDATE users SET coin = coin - ?, inventory = ? WHERE id = ?",
                            (item["cost"], json.dumps(inventory, separators=(",", ":")), user_id))
            return self._user_by_id(user_id)

    def sell_item(self, user_id, stack_id):
        if not isinstance(stack_id, str) or not STACK_ID_RE.fullmatch(stack_id):
            raise AuthError("Choose an item stack to sell")
        with self.lock, self.db:
            row = self.db.execute("SELECT coin, inventory FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                raise AuthError("Your session has expired")
            inventory = self._normalize_inventory(json.loads(row["inventory"]))
            stack = next((entry for entry in inventory if entry["id"] == stack_id), None)
            if stack is None:
                raise AuthError("That item stack is no longer available")
            value = int(ITEMS[stack["item"]]["cost"] * .6)
            stack["quantity"] -= 1
            if stack["quantity"] == 0:
                inventory.remove(stack)
            self.db.execute("UPDATE users SET coin = coin + ?, inventory = ? WHERE id = ?",
                            (value, json.dumps(inventory, separators=(",", ":")), user_id))
            return self._user_by_id(user_id)

    def save_inventory(self, user_id, inventory):
        try:
            inventory = self._normalize_inventory(inventory)
        except (TypeError, ValueError) as error:
            raise AuthError("That inventory layout is invalid") from error
        with self.lock, self.db:
            row = self.db.execute("SELECT inventory FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                raise AuthError("Your session has expired")
            stored = self._normalize_inventory(json.loads(row["inventory"]))
            original = {entry["id"]: (entry["item"], entry["quantity"]) for entry in stored}
            proposed = {entry["id"]: (entry["item"], entry["quantity"]) for entry in inventory}
            if proposed != original:
                raise AuthError("Only the active and stash locations can be changed here")
            self.db.execute("UPDATE users SET inventory = ? WHERE id = ?", (json.dumps(inventory, separators=(",", ":")), user_id))
            return self._user_by_id(user_id)

    def settle_item_rewards(self, races):
        """Pay active equipment once for each finished race supplied by League."""
        with self.lock, self.db:
            users = self.db.execute("SELECT id, coin, fav_racer, inventory FROM users").fetchall()
            for user in users:
                inventory = self._normalize_inventory(json.loads(user["inventory"]))
                active = {item: sum(entry["quantity"] for entry in inventory if entry["active"] and entry["item"] == item) for item in ITEMS}
                for race in races:
                    if self.db.execute("SELECT 1 FROM item_reward_races WHERE user_id = ? AND race_id = ?", (user["id"], race["id"])).fetchone():
                        continue
                    self.db.execute("INSERT INTO item_reward_races (user_id, race_id) VALUES (?, ?)", (user["id"], race["id"]))
                    if not any(active.values()):
                        continue
                    standings = race["standings"]
                    favorite = next((entry for entry in standings if entry["driver_id"] == user["fav_racer"]), None)
                    rewards = []
                    if favorite and favorite["position"] == 1:
                        rewards.append(("binoculars", active["binoculars"] * 10))
                    if favorite and favorite["position"] >= len(standings) - 2:
                        rewards.append(("beer", active["beer"] * 5))
                    if favorite and favorite["position"] <= 3:
                        rewards.append(("whistle", active["whistle"] * 5))
                    crashes = sum(incident.get("type") in ("crash", "major-crash") for plan in race["plans"] for incident in plan.get("events", []))
                    rewards.append(("camera", active["camera"] * crashes * 10))
                    if race["first_season_win"]:
                        rewards.append(("old-scroll", active["old-scroll"] * 10))
                    if race["duration"] > 8 * 60:
                        rewards.append(("watch", active["watch"] * 50))
                    rewards = [(item_id, amount) for item_id, amount in rewards if amount]
                    reward = sum(amount for _item_id, amount in rewards)
                    if reward:
                        self.db.execute("UPDATE users SET coin = coin + ? WHERE id = ?", (reward, user["id"]))
                        for item_id, amount in rewards:
                            self._record_activity(
                                user["id"], race["season"], "item_payout", amount,
                                race_number=race["race_number"], driver_id=user["fav_racer"],
                                item_id=item_id, quantity=active[item_id],
                                source_key=f"item:{race['id']}:{item_id}",
                            )

    def betting_terms(self, user_id, base_cost):
        """Return the authoritative price and cap from active betting equipment."""
        with self.lock:
            row = self.db.execute("SELECT inventory FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                raise AuthError("Your session has expired")
            active = self._active_item_counts(json.loads(row["inventory"]))
        return {
            "cost": 5 + max(0, base_cost - 5 - active["vegas-shark"] * 2),
            "limit": MAX_BETS_PER_DRIVER + active["gun"],
        }

    def place_bet(self, user_id, season, race_number, driver_id, cost, driver_wins=None):
        """Buy one irreversible bet after League has validated the live offer."""
        if any(type(value) is not int or value < 1 for value in (season, race_number, driver_id, cost)):
            raise AuthError("That bet is invalid")
        with self.lock, self.db:
            user = self.db.execute("SELECT coin, inventory FROM users WHERE id = ?", (user_id,)).fetchone()
            if user is None:
                raise AuthError("Your session has expired")
            active = self._active_item_counts(json.loads(user["inventory"]))
            limit = MAX_BETS_PER_DRIVER + active["gun"]
            bet = self.db.execute(
                "SELECT quantity, settled FROM bets WHERE user_id=? AND season=? AND race_number=? AND driver_id=?",
                (user_id, season, race_number, driver_id),
            ).fetchone()
            if bet and bet["settled"]:
                raise AuthError("That race has already been settled")
            if bet and bet["quantity"] >= limit:
                raise AuthError(f"You can place up to {limit} bets on one driver")
            if user["coin"] < cost:
                raise AuthError(f"You need {cost} Coin for this bet")
            self.db.execute("UPDATE users SET coin = coin - ? WHERE id = ?", (cost, user_id))
            self.db.execute(
                """INSERT INTO bets(user_id,season,race_number,driver_id,quantity,spent,sunglasses,lucky_tickets)
                   VALUES(?,?,?,?,1,?,?,?)
                   ON CONFLICT(user_id,season,race_number,driver_id)
                   DO UPDATE SET quantity=quantity+1, spent=spent+excluded.spent,
                     sunglasses=MAX(sunglasses,excluded.sunglasses),
                     lucky_tickets=MAX(lucky_tickets,excluded.lucky_tickets)""",
                (user_id, season, race_number, driver_id, cost,
                 active["sunglasses"] if driver_wins == 0 else 0, active["lucky-ticket"]),
            )
            self._record_activity(
                user_id, season, "bet_placed", -cost, race_number=race_number,
                driver_id=driver_id,
            )
            return self._user_by_id(user_id)

    def bets_for_user(self, user_id, offers=None):
        """Return a fan's bet counters, optionally limited to offered races."""
        if user_id is None:
            return []
        allowed = None if offers is None else {(race["season"], race["race_number"]) for race in offers}
        with self.lock:
            rows = self.db.execute(
                "SELECT season,race_number,driver_id,quantity,spent,settled FROM bets WHERE user_id=? ORDER BY season,race_number,driver_id",
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows if allowed is None or (row["season"], row["race_number"]) in allowed]

    def settle_bet_rewards(self, races):
        """Pay 100 Coin per winning bet and mark every bet on that race final."""
        with self.lock, self.db:
            for race in races:
                rows = self.db.execute(
                    "SELECT user_id,driver_id,quantity,sunglasses,lucky_tickets FROM bets WHERE season=? AND race_number=? AND settled=0",
                    (race["season"], race["race_number"]),
                ).fetchall()
                drivers_per_user = {}
                for bet in rows:
                    drivers_per_user.setdefault(bet["user_id"], set()).add(bet["driver_id"])
                for bet in rows:
                    if bet["driver_id"] == race["winner"]:
                        payout = bet["quantity"] * BET_PAYOUT + bet["sunglasses"] * SUNGLASSES_BONUS
                        if len(drivers_per_user[bet["user_id"]]) == 1:
                            payout += bet["lucky_tickets"] * LUCKY_TICKET_BONUS
                        self.db.execute(
                            "UPDATE users SET coin = coin + ? WHERE id = ?",
                            (payout, bet["user_id"]),
                        )
                        self._record_activity(
                            bet["user_id"], race["season"], "bet_payout", payout,
                            race_number=race["race_number"], driver_id=bet["driver_id"],
                            quantity=bet["quantity"],
                            source_key=f"bet:{race['season']}:{race['race_number']}:{bet['driver_id']}:payout",
                        )
                    else:
                        self._record_activity(
                            bet["user_id"], race["season"], "bet_loss", 0,
                            race_number=race["race_number"], driver_id=bet["driver_id"],
                            quantity=bet["quantity"],
                            source_key=f"bet:{race['season']}:{race['race_number']}:{bet['driver_id']}:loss",
                        )
                self.db.execute(
                    "UPDATE bets SET settled=1 WHERE season=? AND race_number=? AND settled=0",
                    (race["season"], race["race_number"]),
                )

    def activity_for_user(self, user_id, season):
        """Return every saved betting action and payout for one season, newest first."""
        if type(user_id) is not int or type(season) is not int or season < 1:
            return []
        with self.lock:
            rows = self.db.execute(
                """SELECT id,season,race_number,driver_id,kind,item_id,quantity,amount,created_at
                   FROM fan_activity WHERE user_id=? AND season=? ORDER BY id DESC""",
                (user_id, season),
            ).fetchall()
        return [dict(row) for row in rows]

    def _record_activity(self, user_id, season, kind, amount, race_number=None,
                         driver_id=None, item_id=None, quantity=1, source_key=None):
        self.db.execute(
            """INSERT OR IGNORE INTO fan_activity
               (user_id,season,race_number,driver_id,kind,item_id,quantity,amount,created_at,source_key)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (user_id, season, race_number, driver_id, kind, item_id, quantity,
             amount, int(self.clock()), source_key),
        )

    @staticmethod
    def _new_stack(item_id, active):
        return {"id": secrets.token_urlsafe(9), "item": item_id, "quantity": 1, "active": active}

    @staticmethod
    def _active_item_counts(inventory):
        inventory = LocalAuth._normalize_inventory(inventory)
        return {item: sum(entry["quantity"] for entry in inventory
                          if entry["active"] and entry["item"] == item) for item in ITEMS}

    @staticmethod
    def _normalize_inventory(inventory):
        if not isinstance(inventory, list):
            raise ValueError("Inventory must be a list")
        normalized = []
        seen = set()
        for entry in inventory:
            if not isinstance(entry, dict) or entry.get("item") not in ITEMS or type(entry.get("quantity")) is not int or not 1 <= entry["quantity"] <= MAX_STACK_SIZE or type(entry.get("active")) is not bool:
                raise ValueError("Invalid item stack")
            stack_id = entry.get("id")
            if not isinstance(stack_id, str) or not STACK_ID_RE.fullmatch(stack_id) or stack_id in seen:
                raise ValueError("Invalid item stack")
            seen.add(stack_id)
            normalized.append({"id": stack_id, "item": entry["item"], "quantity": entry["quantity"], "active": entry["active"]})
        if sum(entry["active"] for entry in normalized) > ACTIVE_SLOT_LIMIT or sum(not entry["active"] for entry in normalized) > STASH_SLOT_LIMIT:
            raise ValueError("No room for that inventory layout")
        return normalized

    def make_session(self, user):
        payload = {"sub": user["id"], "exp": int(self.clock() + SESSION_TTL_SECONDS)}
        encoded = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signature = _b64url(hmac.new(self.session_secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest())
        return f"{encoded}.{signature}"

    def session_user(self, cookie_header):
        cookie = SimpleCookie()
        cookie.load(cookie_header or "")
        morsel = cookie.get(SESSION_COOKIE)
        if not morsel:
            return None
        try:
            encoded, signature = morsel.value.split(".", 1)
            expected = _b64url(hmac.new(self.session_secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest())
            if not hmac.compare_digest(signature, expected):
                return None
            payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
            if int(payload["exp"]) <= self.clock() or not isinstance(payload["sub"], int):
                return None
            with self.lock, self.db:
                row = self.db.execute("SELECT * FROM users WHERE id = ?", (payload["sub"],)).fetchone()
                return self._public_user(self._claim_daily_login(row)) if row else None
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None

    def cookie_header(self, value, secure=False, max_age=SESSION_TTL_SECONDS):
        cookie = SimpleCookie()
        cookie[SESSION_COOKIE] = value
        cookie[SESSION_COOKIE]["path"] = "/"
        cookie[SESSION_COOKIE]["httponly"] = True
        cookie[SESSION_COOKIE]["samesite"] = "Lax"
        cookie[SESSION_COOKIE]["max-age"] = str(max_age)
        if secure:
            cookie[SESSION_COOKIE]["secure"] = True
        return cookie.output(header="").strip()

    def _user_by_id(self, user_id):
        row = self.db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._public_user(row)

    def _claim_daily_login(self, row):
        """Apply a once-per-UTC-day reward to a verified account row."""
        if row["last_daily_claim_day"] == self._claim_day():
            return row
        self.db.execute("UPDATE users SET coin = coin + ?, last_daily_claim_day = ? WHERE id = ?",
                        (DAILY_LOGIN_COIN, self._claim_day(), row["id"]))
        return self.db.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()

    def _claim_day(self):
        return int(self.clock() // (60 * 60 * 24))

    @staticmethod
    def _public_user(row):
        return {
            "id": row["id"], "username": row["username"], "admin": bool(row["is_admin"]),
            "coin": row["coin"], "fav_racer": row["fav_racer"], "inventory": json.loads(row["inventory"]),
        }

    @staticmethod
    def _validate_username(username):
        if not isinstance(username, str) or not USERNAME_RE.fullmatch(username):
            raise AuthError("Username must be 3–32 letters, numbers, hyphens, or underscores")
        return username

    @staticmethod
    def _validate_password(password):
        if not isinstance(password, str) or not 8 <= len(password) <= 256:
            raise AuthError("Password must be 8–256 characters")

    @staticmethod
    def _hash_password(password):
        salt = secrets.token_bytes(16)
        if hasattr(hashlib, "scrypt"):
            digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=PASSWORD_N, r=PASSWORD_R, p=PASSWORD_P, dklen=PASSWORD_LENGTH)
            return f"scrypt${PASSWORD_N}${PASSWORD_R}${PASSWORD_P}${_b64url(salt)}${_b64url(digest)}"
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS, PASSWORD_LENGTH)
        return f"pbkdf2-sha256${PBKDF2_ITERATIONS}${_b64url(salt)}${_b64url(digest)}"

    @staticmethod
    def _verify_password(password, stored):
        try:
            parts = stored.split("$")
            if not isinstance(password, str):
                return False
            algorithm = parts[0]
            if algorithm == "scrypt" and len(parts) == 6:
                _, n, r, p, salt, expected = parts
                salt_bytes = base64.urlsafe_b64decode(salt + "=" * (-len(salt) % 4))
                expected_bytes = base64.urlsafe_b64decode(expected + "=" * (-len(expected) % 4))
                actual = hashlib.scrypt(password.encode("utf-8"), salt=salt_bytes, n=int(n), r=int(r), p=int(p), dklen=len(expected_bytes))
            elif algorithm == "pbkdf2-sha256" and len(parts) == 4:
                _, iterations, salt, expected = parts
                salt_bytes = base64.urlsafe_b64decode(salt + "=" * (-len(salt) % 4))
                expected_bytes = base64.urlsafe_b64decode(expected + "=" * (-len(expected) % 4))
                actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, int(iterations), len(expected_bytes))
            else:
                return False
            return hmac.compare_digest(actual, expected_bytes)
        except (ValueError, TypeError, AttributeError):
            return False
