import concurrent.futures
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest

from league import (
    CAR_ATTRIBUTES, CHAMPIONSHIP_FINAL_SLOT, CHAMPIONSHIP_R1_SLOT,
    CHAMPIONSHIP_R2_SLOT, CITIES, DRIVER_ATTRIBUTES, EASTERN, INTERVAL,
    League, RACES_PER_SEASON, ROSTER_VERSION, SLOTS_PER_SEASON,
    slot_start_timestamp, stat_map,
)


class LeagueTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database = Path(self.directory.name) / "test.sqlite3"
        self.now = datetime(2026, 9, 14, 9, 0, 0, 0, EASTERN).timestamp()
        self.league = League(self.database, clock=lambda: self.now)

    def tearDown(self):
        self.league.close()
        self.directory.cleanup()

    def advance(self, seconds):
        self.now += seconds
        self.league.tick()

    def test_first_wave_has_three_distinct_cities_and_every_driver_once(self):
        state = self.league.state()
        self.assertEqual(len(state["races"]), 3)
        self.assertEqual(len({r["city"]["name"] for r in state["races"]}), 3)
        entrants = [s["driver_id"] for race in state["races"] for s in race["standings"]]
        self.assertEqual(sorted(entrants), list(range(1, 31)))
        self.assertEqual([race["race_number"] for race in state["races"]], [1, 2, 3])
        for race in state["races"]:
            self.assertEqual(len(race["standings"]), 10)
            self.assertEqual(race["laps"], 10)
            self.assertEqual(race["name"], f'{race["city"]["name"]}, Race {race["race_number"]}')
            self.assertEqual(race["status"], "live")
        self.assertEqual(len(state["next_races"]), 3)
        self.assertEqual([race["race_number"] for race in state["next_races"]], [4, 5, 6])
        self.assertEqual(len({r["city"]["name"] for r in state["next_races"]}), 3)
        next_entrants = [d["driver_id"] for race in state["next_races"] for d in race["racers"]]
        self.assertEqual(sorted(next_entrants), list(range(1, 31)))
        self.assertTrue(all(d["wins"] == 0 for race in state["next_races"] for d in race["racers"]))

    def test_bet_offer_uses_the_next_grid_price_and_locks_at_start(self):
        preview = self.league.state()["next_races"][0]
        racer = preview["racers"][0]
        offer = self.league.bet_offer(preview["season"], preview["race_number"], racer["driver_id"])
        self.assertEqual(offer["cost"], 5 + racer["wins"])
        self.assertIsNone(self.league.bet_offer(preview["season"], preview["race_number"], 999))
        self.now = preview["start"]
        self.assertIsNone(self.league.bet_offer(preview["season"], preview["race_number"], racer["driver_id"]))

    def test_exact_attribute_counts_and_named_cars(self):
        drivers = self.league.drivers()
        self.assertEqual(len(drivers), 30)
        self.assertEqual(len({d["car"]["name"] for d in drivers}), 30)
        for driver in drivers:
            self.assertEqual([a["name"] for a in driver["attributes"]], list(DRIVER_ATTRIBUTES))
            self.assertEqual([a["name"] for a in driver["car"]["attributes"]], list(CAR_ATTRIBUTES))
            self.assertEqual(sum(len(a["stats"]) for a in driver["attributes"] + driver["car"]["attributes"]), 19)
            for attrs, count in ((driver["attributes"], 3), (driver["car"]["attributes"], 2)):
                for attribute in attrs:
                    self.assertEqual(len(attribute["stats"]), count)
                    self.assertTrue(all(0 <= stat["value"] <= 100 for stat in attribute["stats"]))
            stats = stat_map(driver)
            self.assertLessEqual(stats["Eyes"], 8)
            self.assertGreaterEqual(stats["Wheels"], 1)
            self.assertLessEqual(stats["Wheels"], 10)
            self.assertFalse(stats["Horsepower"] >= 90 and stats["Ghostpower"] >= 90)
        self.assertGreaterEqual(sum(stat_map(driver)["Eyes"] == 2 for driver in drivers), 15)
        self.assertGreaterEqual(sum(stat_map(driver)["Wheels"] == 4 for driver in drivers), 12)
        force_outliers = [
            driver for driver in drivers
            if any(not 40 <= stat_map(driver)[name] <= 60 for name in ("Horsepower", "Ghostpower"))
        ]
        self.assertEqual(len(force_outliers), 5)

    def test_stat_driven_events_have_signed_effects_and_weather_is_not_an_event(self):
        with self.league.db:
            self.league.db.execute("DELETE FROM races")
        self.league.seed = 123456
        self.now += INTERVAL * 30
        self.league.tick()
        events = [event for row in self.league.db.execute("SELECT data FROM races")
                  for plan in json.loads(row["data"])["plans"] for event in plan["events"]]
        by_type = {kind: [event for event in events if event["type"] == kind]
                   for kind in ("boost", "draft", "crash", "major-crash", "slip", "paranormal", "mistake")}
        self.assertEqual({event["type"] for event in events}, set(by_type))
        self.assertTrue(all(by_type.values()))
        self.assertTrue(all(event["delta"] < 0 for kind in ("boost", "draft") for event in by_type[kind]))
        self.assertTrue(all(event["delta"] > 0 for kind in ("crash", "major-crash", "slip", "mistake") for event in by_type[kind]))
        self.assertTrue(any(event["delta"] < 0 for event in by_type["paranormal"]))
        self.assertTrue(any(event["delta"] > 0 for event in by_type["paranormal"]))

    def test_old_roster_is_migrated_without_losing_schedule(self):
        driver = json.loads(self.league.db.execute("SELECT data FROM drivers WHERE id=1").fetchone()[0])
        old_pride = stat_map(driver)["Pride"]
        for group in driver["attributes"]:
            for stat in group["stats"]:
                stat["name"] = {"Pride": "Racecraft", "Eyes": "Gravitational charm"}.get(stat["name"], stat["name"])
                if stat["name"] == "Gravitational charm":
                    stat["value"] = 77
        old_car = []
        for group in driver["car"]["attributes"]:
            if group["name"] == "Engine":
                continue
            group["name"] = {"Force": "Power", "Frame": "Integrity"}.get(group["name"], group["name"])
            for stat in group["stats"]:
                stat["name"] = {"Hauntings": "Corner memory", "Rust": "Existential stability",
                                "Veil": "Slipstream", "Wheels": "Hauntodynamics"}.get(stat["name"], stat["name"])
                if stat["name"] in ("Horsepower", "Ghostpower"):
                    stat["value"] = 98
                if stat["name"] == "Hauntodynamics":
                    stat["value"] = 77
            old_car.append(group)
        driver["car"]["attributes"] = old_car
        anchor = self.league.anchor
        race_count = self.league.db.execute("SELECT COUNT(*) FROM races").fetchone()[0]
        with self.league.db:
            self.league.db.execute("UPDATE drivers SET data=? WHERE id=1", (json.dumps(driver),))
            self.league.db.execute("DELETE FROM meta WHERE key='roster_version'")
        self.league.close()
        self.league = League(self.database, clock=lambda: self.now)
        upgraded = self.league.roster[1]
        self.assertEqual(int(self.league.db.execute("SELECT value FROM meta WHERE key='roster_version'").fetchone()[0]), ROSTER_VERSION)
        self.assertEqual(self.league.anchor, anchor)
        self.assertEqual(self.league.db.execute("SELECT COUNT(*) FROM races").fetchone()[0], race_count)
        self.assertEqual(stat_map(upgraded)["Pride"], old_pride)
        self.assertLessEqual(stat_map(upgraded)["Horsepower"], 60)
        self.assertLessEqual(stat_map(upgraded)["Ghostpower"], 60)
        self.assertLessEqual(stat_map(upgraded)["Eyes"], 8)
        self.assertLessEqual(stat_map(upgraded)["Wheels"], 10)
        self.assertEqual([group["name"] for group in upgraded["car"]["attributes"]], list(CAR_ATTRIBUTES))

    def test_progress_tracks_laps_distance_and_position(self):
        self.advance(160)
        for race in self.league.state()["races"]:
            progress = [s["progress"] for s in race["standings"]]
            self.assertEqual(progress, sorted(progress, reverse=True))
            for driver in race["standings"]:
                self.assertGreater(driver["progress"], 0)
                self.assertLess(driver["progress"], 10)
                self.assertEqual(driver["laps"], int(driver["progress"]))
                self.assertAlmostEqual(driver["distance"], driver["progress"] * race["city"]["length"], delta=.011)

    def test_no_future_results_or_events_are_exposed(self):
        self.advance(60)
        for race in self.league.state()["races"]:
            self.assertIsNone(race["end"])
            self.assertNotIn("winner", race)
            self.assertNotIn("plans", race)
            self.assertTrue(all(s["finish_time"] is None for s in race["standings"]))
            self.assertTrue(all(event["at"] <= race["elapsed"] for event in race["events"]))
        self.assertEqual(self.league.history()["total"], 0)

    def test_every_race_finishes_between_five_and_ten_minutes(self):
        self.now = slot_start_timestamp(self.league.season_zero_date, 1, SLOTS_PER_SEASON - 1) + 600
        self.league.tick()
        rows = self.league.db.execute("SELECT start,end,data FROM races").fetchall()
        self.assertEqual(len(rows), RACES_PER_SEASON)
        for row in rows:
            self.assertGreaterEqual(row["end"] - row["start"], 300)
            self.assertLessEqual(row["end"] - row["start"], 600)
            for plan in json.loads(row["data"])["plans"]:
                self.assertEqual(len(plan["splits"]), 10)
                self.assertGreaterEqual(plan["splits"][-1], 300)
                self.assertLessEqual(plan["splits"][-1], 600)

    def test_completion_records_all_finishers_and_exactly_one_win(self):
        self.advance(600)
        state = self.league.state()
        self.assertEqual(state["completed_races"], 3)
        self.assertEqual(sum(d["wins"] for d in self.league.drivers()), 3)
        for race in state["races"]:
            self.assertEqual(race["status"], "finished")
            self.assertTrue(all(d["laps"] == 10 for d in race["standings"]))
            times = [d["finish_time"] for d in race["standings"]]
            self.assertEqual(times, sorted(times))
            self.assertEqual(race["standings"][0]["gap"], 0)
        self.league.tick()
        self.assertEqual(sum(d["wins"] for d in self.league.drivers()), 3)

    def test_exact_finish_boundary_has_no_phantom_unfinished_driver(self):
        self.now = self.league.db.execute("SELECT MAX(end) FROM races").fetchone()[0]
        self.league.tick()
        for race in self.league.state()["races"]:
            self.assertEqual(race["status"], "finished")
            self.assertTrue(all(s["finished"] for s in race["standings"]))

    def test_twenty_minute_boundary_starts_next_wave_once(self):
        self.advance(INTERVAL - .001)
        preview = self.league.state()["next_races"]
        self.assertEqual(self.league.state()["wave"], 1)
        self.advance(.001)
        state = self.league.state()
        self.assertEqual(state["wave"], 2)
        self.assertEqual(state["next_start"], self.league.anchor + INTERVAL * 2)
        self.assertTrue(all(r["status"] == "live" for r in state["races"]))
        self.assertEqual([r["race_number"] for r in state["races"]], [4, 5, 6])
        self.assertEqual([r["name"] for r in state["races"]], [r["name"] for r in preview])
        self.assertEqual([r["city"] for r in state["races"]], [r["city"] for r in preview])
        for _ in range(3):
            self.league.tick()
        self.assertEqual(self.league.db.execute("SELECT COUNT(*) FROM races").fetchone()[0], 6)

    def test_season_race_numbers_end_at_three_hundred(self):
        self.now = slot_start_timestamp(self.league.season_zero_date, 1, SLOTS_PER_SEASON - 1)
        self.league.tick()
        races = self.league.state()["races"]
        self.assertEqual([race["race_number"] for race in races], [300])
        self.assertTrue(races[0]["name"].startswith("🏆 Eclipse Season Championship at "))

    def test_restart_recovers_schedule_results_and_current_progress(self):
        before = self.league.state()
        self.league.close()
        self.now += INTERVAL * 3 + 140
        self.league = League(self.database, clock=lambda: self.now)
        after = self.league.state()
        self.assertEqual(after["wave"], 4)
        self.assertEqual(after["completed_races"], 9)
        self.assertEqual(after["races"][0]["elapsed"], 140)
        self.assertEqual(self.league.race(before["races"][0]["id"])["name"], before["races"][0]["name"])
        self.assertEqual(sum(d["wins"] for d in self.league.drivers()), 9)

    def test_restart_migrates_old_fictional_race_names(self):
        with self.league.db:
            self.league.db.execute("UPDATE races SET name='The Impossible Omen'")
        self.league.close()
        self.league = League(self.database, clock=lambda: self.now)
        races = self.league.state()["races"]
        self.assertEqual([race["name"] for race in races], [
            f'{race["city"]["name"]}, Race {race["race_number"]}' for race in races
        ])

    def test_scheduler_advances_without_state_requests(self):
        self.advance(INTERVAL * 2 + 600)
        self.assertEqual(self.league.db.execute("SELECT COUNT(*) FROM races WHERE completed=1").fetchone()[0], 9)

    def test_monday_starts_new_season_and_driver_dropdown_lists_only_current_and_past(self):
        self.now = datetime(2026, 9, 21, 0, 1, 0, 0, EASTERN).timestamp()
        self.league.tick()
        state = self.league.state()
        self.assertEqual(state["season"], {"number": 2, "name": "Petals", "total_races": RACES_PER_SEASON})
        self.assertEqual(state["wave"], 0)
        self.assertEqual([race["race_number"] for race in state["next_races"]], [1, 2, 3])
        self.assertEqual(sum(driver["wins"] for driver in self.league.drivers()), 0)
        self.assertEqual(sum(driver["wins"] for driver in self.league.drivers(1)), RACES_PER_SEASON)
        self.assertEqual(self.league.seasons(), [
            {"number": 2, "name": "Petals", "current": True},
            {"number": 1, "name": "Eclipse", "current": False},
        ])

    def test_final_day_uses_championship_bracket(self):
        self.now = slot_start_timestamp(self.league.season_zero_date, 1, CHAMPIONSHIP_R1_SLOT)
        r1 = self.league.state()["races"]
        self.assertEqual([race["race_number"] for race in r1], [295, 296, 297])
        self.assertTrue(all(race["name"].startswith("🏆 Qualifiers Series at ") for race in r1))
        self.assertTrue(all(len(race["standings"]) == 10 for race in r1))

        self.now = slot_start_timestamp(self.league.season_zero_date, 1, CHAMPIONSHIP_R2_SLOT)
        r2 = self.league.state()["races"]
        r1_top_five = {
            standing["driver_id"]
            for race in r1
            for standing in self.league.race(race["id"])["standings"][:5]
        }
        r2_entrants = {standing["driver_id"] for race in r2 for standing in race["standings"]}
        self.assertEqual([race["race_number"] for race in r2], [298, 299])
        self.assertTrue(all(race["name"].startswith("🏆 Finalist Series at ") for race in r2))
        self.assertEqual([len(race["standings"]) for race in r2], [8, 8])
        self.assertTrue(r1_top_five.issubset(r2_entrants))
        self.assertEqual(len(r2_entrants - r1_top_five), 1)

        self.now = slot_start_timestamp(self.league.season_zero_date, 1, CHAMPIONSHIP_FINAL_SLOT)
        final = self.league.state()["races"]
        r2_top_four = {
            standing["driver_id"]
            for race in r2
            for standing in self.league.race(race["id"])["standings"][:4]
        }
        final_entrants = {standing["driver_id"] for standing in final[0]["standings"]}
        self.assertEqual([race["race_number"] for race in final], [300])
        self.assertTrue(final[0]["name"].startswith("🏆 Eclipse Season Championship at "))
        self.assertEqual(len(final[0]["standings"]), 8)
        self.assertEqual(final_entrants, r2_top_four)

    def test_history_filters_pagination_and_results(self):
        self.advance(INTERVAL * 8 + 600)
        history = self.league.history()
        self.assertEqual(history["total"], 27)
        self.assertEqual(len(history["races"]), 12)
        self.assertEqual(history["pages"], 3)
        self.assertEqual(len(self.league.history(page=3)["races"]), 3)
        self.assertEqual(self.league.history(page=999)["page"], 3)
        race = history["races"][0]
        matches = self.league.history(query=race["name"].lower())["races"]
        self.assertTrue(matches)
        self.assertTrue(all(r["name"] == race["name"] for r in matches))
        city = self.league.history(city="Tokyo")["races"]
        self.assertTrue(all(r["city"]["name"] == "Tokyo" for r in city))
        self.assertEqual(self.league.history(query="%_' OR 1=1 --")["total"], 0)
        self.assertEqual(len(self.league.race(race["id"])["standings"]), 10)
        self.assertIsNone(self.league.race(999999))

    def test_tracks_include_all_circuits_and_recent_podiums(self):
        self.advance(INTERVAL * 8 + 600)
        tracks = self.league.tracks()
        self.assertEqual([track["name"] for track in tracks], [city["name"] for city in CITIES])
        self.assertTrue(all(track["length"] > 0 for track in tracks))
        self.assertTrue(all(0 <= track["curve_bias"] <= 100 for track in tracks))
        self.assertTrue(all(len(track["races"]) <= 10 for track in tracks))
        self.assertTrue(all(len(race["standings"]) == 3 for track in tracks for race in track["races"]))

    def test_concurrent_reads_and_ticks_do_not_duplicate_waves(self):
        self.now += INTERVAL * 2
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            states = list(executor.map(lambda _: self.league.state(), range(20)))
        self.assertTrue(all(s["wave"] == 3 for s in states))
        self.assertEqual(self.league.db.execute("SELECT COUNT(*) FROM races").fetchone()[0], 9)


if __name__ == "__main__":
    unittest.main()
