import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from auth import AuthError, BET_PAYOUT, DAILY_LOGIN_COIN, FAVORITE_CHANGE_INTERVAL_SECONDS, LUCKY_TICKET_BONUS, LocalAuth, MAX_BETS_PER_DRIVER, SESSION_COOKIE, STARTING_COIN, SUNGLASSES_BONUS


class LocalAuthTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database = Path(self.directory.name) / "test.sqlite3"
        self.now = 1_700_000_000
        self.auth = LocalAuth(self.database, environ={"APP_SESSION_SECRET": "test-secret"}, clock=lambda: self.now)

    def tearDown(self):
        self.auth.close()
        self.directory.cleanup()

    def test_registration_uses_a_salted_hash_and_default_account_values(self):
        user = self.auth.register("track_rider", "a secure password")
        self.assertEqual(user, {"id": 1, "username": "track_rider", "admin": False, "coin": STARTING_COIN,
                                "fav_racer": None, "sponsored_team": None, "inventory": []})
        with sqlite3.connect(self.database) as database:
            password_hash = database.execute("SELECT password_hash FROM users WHERE id = 1").fetchone()[0]
        self.assertNotIn("a secure password", password_hash)
        self.assertTrue(password_hash.startswith(("scrypt$", "pbkdf2-sha256$")))

    def test_login_and_signed_session_round_trip(self):
        registered = self.auth.register("racer-one", "a secure password")
        logged_in = self.auth.login("RACER-ONE", "a secure password")
        self.assertEqual(logged_in["coin"], STARTING_COIN)
        self.assertEqual(self.auth.login("RACER-ONE", "a secure password")["coin"], logged_in["coin"])
        self.now += 60 * 60 * 24
        self.assertEqual(self.auth.login("RACER-ONE", "a secure password")["coin"], logged_in["coin"] + DAILY_LOGIN_COIN)
        self.assertIsNone(self.auth.session_user(""))
        value = self.auth.make_session(logged_in)
        self.assertEqual(self.auth.session_user(f"{SESSION_COOKIE}={value}")["coin"], logged_in["coin"] + DAILY_LOGIN_COIN)

    def test_signed_in_visit_claims_the_daily_coin_once(self):
        user = self.auth.register("daily_fan", "a secure password")
        session = self.auth.make_session(user)
        self.now += 60 * 60 * 24
        claimed = self.auth.session_user(f"{SESSION_COOKIE}={session}")
        self.assertEqual(claimed["coin"], STARTING_COIN + DAILY_LOGIN_COIN)
        self.assertEqual(self.auth.session_user(f"{SESSION_COOKIE}={session}")["coin"], claimed["coin"])

    def test_invalid_credentials_and_tampered_sessions_are_rejected(self):
        user = self.auth.register("racer-two", "a secure password")
        with self.assertRaises(AuthError):
            self.auth.login("racer-two", "wrong password")
        with self.assertRaises(AuthError):
            self.auth.register("racer-two", "different secure password")
        value = self.auth.make_session(user)
        self.assertIsNone(self.auth.session_user(f"{SESSION_COOKIE}={value}x"))

    def test_session_cookie_is_http_only_and_same_site(self):
        header = self.auth.cookie_header("session", secure=True)
        self.assertIn("HttpOnly", header)
        self.assertIn("SameSite=Lax", header)
        self.assertIn("Secure", header)

    def test_favorite_driver_can_only_change_once_every_24_hours(self):
        user = self.auth.register("fan_driver", "a secure password")
        updated = self.auth.set_favorite_racer(user["id"], 12)
        self.assertEqual(updated["fav_racer"], 12)
        self.assertEqual(self.auth.favorite_change_available_at(user["id"]), self.now + FAVORITE_CHANGE_INTERVAL_SECONDS)
        with self.assertRaises(AuthError):
            self.auth.set_favorite_racer(user["id"], 13)
        self.now += FAVORITE_CHANGE_INTERVAL_SECONDS
        self.assertEqual(self.auth.set_favorite_racer(user["id"], 13)["fav_racer"], 13)

    def test_favorite_counts_only_include_selected_drivers(self):
        first = self.auth.register("fan_count_one", "a secure password")
        second = self.auth.register("fan_count_two", "a secure password")
        self.auth.set_favorite_racer(first["id"], 7)
        self.auth.set_favorite_racer(second["id"], 7)
        self.assertEqual(self.auth.favorite_counts(), {7: 2})

    def test_amendment_vote_locks_and_pit_entries_cost_coin(self):
        user = self.auth.register("election_fan", "a secure password")
        poll = self.auth.vote_final_lap(user["id"], 3, "team-work")
        self.assertEqual(poll["selected"], "team-work")
        self.assertEqual(poll["totals"]["team-work"], 1)
        with self.assertRaisesRegex(AuthError, "already locked"):
            self.auth.vote_final_lap(user["id"], 3, "explosions")

        purchase = self.auth.buy_pit_crew_ticket(user["id"], 3, "haunting", 7)
        self.assertEqual(purchase["user"]["coin"], STARTING_COIN - 10)
        self.auth.buy_pit_crew_ticket(user["id"], 3, "haunting", 7)
        self.auth.buy_pit_crew_ticket(user["id"], 3, "car-swap", 9, 8)
        self.assertEqual(self.auth.pit_crew_ticket_count(3, user["id"]), {"total": 3, "mine": 3})

        result = self.auth.finalize_election(3)
        self.assertEqual(result["amendments"]["team-work"], 1)
        self.assertEqual(len(result["pit_crew"]), 2)
        self.assertEqual(self.auth.finalize_election(3), result)

    def test_pit_entry_requires_distinct_drivers_for_a_swap(self):
        user = self.auth.register("pit_fan", "a secure password")
        with self.assertRaisesRegex(AuthError, "two different"):
            self.auth.buy_pit_crew_ticket(user["id"], 2, "soul-swap", 4, 4)

    def test_tower_items_stack_save_and_sell_for_sixty_percent(self):
        user = self.auth.register("tower_fan", "a secure password")
        with self.auth.db:
            self.auth.db.execute("UPDATE users SET coin = 220 WHERE id = ?", (user["id"],))
        first = self.auth.buy_item(user["id"], "binoculars")
        second = self.auth.buy_item(user["id"], "binoculars")
        self.assertEqual(second["coin"], 20)
        self.assertEqual(len(second["inventory"]), 1)
        self.assertEqual(second["inventory"][0]["quantity"], 2)
        self.assertFalse(second["inventory"][0]["active"])
        stack = {**second["inventory"][0], "active": True}
        saved = self.auth.save_inventory(user["id"], [stack])
        self.assertTrue(saved["inventory"][0]["active"])
        sold = self.auth.sell_item(user["id"], stack["id"])
        self.assertEqual(sold["coin"], 80)
        self.assertEqual(sold["inventory"][0]["quantity"], 1)

    def test_active_item_rewards_are_settled_once_per_race(self):
        user = self.auth.register("reward_fan", "a secure password")
        with self.auth.db:
            self.auth.db.execute("UPDATE users SET coin = 50 WHERE id = ?", (user["id"],))
        purchased = self.auth.buy_item(user["id"], "whistle")
        purchased = self.auth.buy_item(user["id"], "whistle")
        stack = {**purchased["inventory"][0], "active": True}
        self.auth.save_inventory(user["id"], [stack])
        self.auth.set_favorite_racer(user["id"], 7)
        race = {"id": 88, "season": 4, "race_number": 27, "duration": 481, "first_season_win": False, "plans": [],
                "standings": [{"driver_id": 7, "position": 2}, {"driver_id": 8, "position": 1}]}
        self.auth.settle_item_rewards([race])
        self.assertEqual(self.auth.session_user(f"{SESSION_COOKIE}={self.auth.make_session(user)}")["coin"], 10)
        activity = self.auth.activity_for_user(user["id"], 4)
        self.assertEqual([(entry["kind"], entry["item_id"], entry["amount"]) for entry in activity],
                         [("item_payout", "whistle", 10)])
        self.auth.settle_item_rewards([race])
        self.assertEqual(self.auth.session_user(f"{SESSION_COOKIE}={self.auth.make_session(user)}")["coin"], 10)

    def test_bets_charge_immediately_cap_at_ten_and_cannot_be_removed(self):
        user = self.auth.register("betting_fan", "a secure password")
        for _ in range(MAX_BETS_PER_DRIVER):
            updated = self.auth.place_bet(user["id"], 2, 14, 7, 6)
        self.assertEqual(updated["coin"], STARTING_COIN - MAX_BETS_PER_DRIVER * 6)
        bet = self.auth.bets_for_user(user["id"])[0]
        self.assertEqual((bet["quantity"], bet["spent"], bet["settled"]), (10, 60, 0))
        with self.assertRaisesRegex(AuthError, "up to 10"):
            self.auth.place_bet(user["id"], 2, 14, 7, 6)

    def test_vegas_sharks_discount_bets_and_guns_raise_the_cap(self):
        user = self.auth.register("equipped_bettor", "a secure password")
        inventory = [
            {"id": "sharkstack", "item": "vegas-shark", "quantity": 3, "active": True},
            {"id": "gunstack01", "item": "gun", "quantity": 2, "active": True},
        ]
        with self.auth.db:
            self.auth.db.execute("UPDATE users SET coin=1000, inventory=? WHERE id=?", (json.dumps(inventory), user["id"]))
        self.assertEqual(self.auth.betting_terms(user["id"], 17), {"cost": 11, "limit": 14})
        for _ in range(14):
            self.auth.place_bet(user["id"], 2, 14, 7, 11, driver_wins=12)
        with self.assertRaisesRegex(AuthError, "up to 14"):
            self.auth.place_bet(user["id"], 2, 14, 7, 11, driver_wins=12)

    def test_sunglasses_and_lucky_tickets_bonus_a_qualifying_win(self):
        user = self.auth.register("lucky_bettor", "a secure password")
        inventory = [
            {"id": "shades001", "item": "sunglasses", "quantity": 1, "active": True},
            {"id": "tickets01", "item": "lucky-ticket", "quantity": 2, "active": True},
        ]
        with self.auth.db:
            self.auth.db.execute("UPDATE users SET inventory=? WHERE id=?", (json.dumps(inventory), user["id"]))
        self.auth.place_bet(user["id"], 3, 21, 7, 5, driver_wins=0)
        self.auth.settle_bet_rewards([{"season": 3, "race_number": 21, "winner": 7}])
        expected = STARTING_COIN - 5 + BET_PAYOUT + SUNGLASSES_BONUS + 2 * LUCKY_TICKET_BONUS
        actual = self.auth.session_user(f"{SESSION_COOKIE}={self.auth.make_session(user)}")["coin"]
        self.assertEqual(actual, expected)

    def test_existing_bets_are_migrated_for_betting_items(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "legacy.sqlite3"
            with sqlite3.connect(database_path) as database:
                database.execute("""CREATE TABLE bets (
                    user_id INTEGER NOT NULL, season INTEGER NOT NULL, race_number INTEGER NOT NULL,
                    driver_id INTEGER NOT NULL, quantity INTEGER NOT NULL CHECK (quantity BETWEEN 1 AND 10),
                    spent INTEGER NOT NULL DEFAULT 0, settled INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (user_id, season, race_number, driver_id))""")
                database.execute("INSERT INTO bets VALUES (1, 2, 3, 4, 10, 50, 0)")
            migrated = LocalAuth(database_path, environ={"APP_SESSION_SECRET": "test-secret"}, clock=lambda: self.now)
            try:
                columns = {row["name"] for row in migrated.db.execute("PRAGMA table_info(bets)")}
                migrated.db.execute("UPDATE bets SET quantity=11")
                self.assertTrue({"sunglasses", "lucky_tickets"}.issubset(columns))
                self.assertEqual(migrated.db.execute("SELECT quantity FROM bets").fetchone()[0], 11)
            finally:
                migrated.close()

    def test_winning_bets_pay_once_and_losing_bets_expire(self):
        user = self.auth.register("payout_fan", "a secure password")
        self.auth.place_bet(user["id"], 3, 21, 7, 6)
        self.auth.place_bet(user["id"], 3, 21, 7, 6)
        self.auth.place_bet(user["id"], 3, 21, 8, 5)
        race = {"season": 3, "race_number": 21, "winner": 7}
        self.auth.settle_bet_rewards([race])
        expected = STARTING_COIN - 17 + 2 * BET_PAYOUT
        self.assertEqual(self.auth.session_user(f"{SESSION_COOKIE}={self.auth.make_session(user)}")["coin"], expected)
        self.assertTrue(all(bet["settled"] for bet in self.auth.bets_for_user(user["id"])))
        self.auth.settle_bet_rewards([race])
        self.assertEqual(self.auth.session_user(f"{SESSION_COOKIE}={self.auth.make_session(user)}")["coin"], expected)
        activity = self.auth.activity_for_user(user["id"], 3)
        self.assertEqual(len(activity), 5)
        self.assertEqual(sum(entry["amount"] for entry in activity), -17 + 2 * BET_PAYOUT)
        self.assertEqual({entry["kind"] for entry in activity}, {"bet_placed", "bet_payout", "bet_loss"})
