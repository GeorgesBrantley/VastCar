#!/usr/bin/env python3
"""Run with python3 server.py, then open http://localhost:8000."""

import argparse
import json
import logging
import os
import signal
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from auth import AuthError, LocalAuth
from league import League, TEAM_BY_ID

ROOT = Path(__file__).resolve().parent


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, league, auth, **kwargs):
        self.league = league
        self.auth = auth
        super().__init__(*args, directory=str(ROOT / "public"), **kwargs)

    def do_GET(self):
        url = urlparse(self.path)
        if not url.path.startswith("/api/"):
            return super().do_GET()
        try:
            self.settle_due_elections()
            params = parse_qs(url.query)
            if url.path == "/api/auth/me":
                user = self.auth.session_user(self.headers.get("Cookie"))
                value = {"user": user,
                         "favorite_change_available_at": self.auth.favorite_change_available_at(user["id"]) if user else None,
                         "sponsor_change_available_at": self.auth.sponsor_change_available_at(user["id"]) if user else None}
            elif url.path == "/api/state":
                value = self.league.state()
                self.auth.settle_item_rewards(self.league.completed_item_races())
                self.auth.settle_bet_rewards(self.league.completed_bet_races())
                user = self.auth.session_user(self.headers.get("Cookie"))
                value["bets"] = self.auth.bets_for_user(user["id"], value["next_races"]) if user else []
                value["fan_activity"] = self.auth.activity_for_user(user["id"], value["season"]["number"]) if user else []
            elif url.path == "/api/drivers":
                season = params.get("season", [None])[0]
                selected = int(season) if season else None
                favorite_counts = self.auth.favorite_counts()
                value = {"drivers": [{**driver, "fans": favorite_counts.get(driver["id"], 0)} for driver in self.league.drivers(selected)],
                         "teams": self.league.teams(selected, self.auth.sponsor_counts()),
                         "seasons": self.league.seasons()}
            elif url.path == "/api/history":
                value = self.league.history(int(params.get("page", [1])[0]), params.get("q", [""])[0][:200], params.get("city", [""])[0])
            elif url.path == "/api/tracks":
                value = {"tracks": self.league.tracks()}
            elif url.path == "/api/eternals":
                value = self.league.eternals()
            elif url.path == "/api/final-lap":
                value = self.league.final_lap()
                user = self.auth.session_user(self.headers.get("Cookie"))
                if value["winner"]:
                    value["winner"]["fans"] = self.auth.favorite_counts().get(value["winner"]["id"], 0)
                if value.get("team_champion"):
                    value["team_champion"]["sponsors"] = self.auth.sponsor_counts().get(value["team_champion"]["id"], 0)
                election = value.get("election")
                if election:
                    season = election["season"]
                    if self.league.clock() >= election["closes_at"]:
                        result = self.auth.finalize_election(season)
                        self.league.apply_pit_outcomes(season, result["pit_crew"])
                    election["amendments"] = self.auth.final_lap_poll(season, user["id"] if user else None)
                    election["pit_crew"] = self.auth.pit_crew_ticket_count(season, user["id"] if user else None)
                    election["result"] = self.enrich_election_result(self.auth.final_lap_result(season))
                    election["drivers"] = [
                        {key: driver[key] for key in ("id", "name", "number")}
                        for driver in self.league.roster.values()
                    ]
            elif url.path.startswith("/api/races/"):
                value = self.league.race(int(url.path.rsplit("/", 1)[1]))
                if value is None:
                    return self.send_json({"error": "Race not found"}, 404)
            else:
                return self.send_json({"error": "Endpoint not found"}, 404)
            self.send_json(value)
        except ValueError:
            self.send_json({"error": "Invalid request parameter"}, 400)
        except Exception:
            logging.exception("API request failed")
            self.send_json({"error": "The timing tower is temporarily unavailable"}, 500)

    def do_POST(self):
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            self.settle_due_elections()
        if path == "/auth/logout":
            self.send_response(204)
            self.send_header("Set-Cookie", self.auth.cookie_header("", secure=self.is_secure_request(), max_age=0))
            self.end_headers()
            return
        if path in ("/auth/register", "/auth/login"):
            try:
                payload = self.request_json()
                user = self.auth.register(payload.get("username"), payload.get("password")) if path == "/auth/register" else self.auth.login(payload.get("username"), payload.get("password"))
                self.send_json({"user": user}, 201 if path == "/auth/register" else 200,
                               {"Set-Cookie": self.auth.cookie_header(self.auth.make_session(user), secure=self.is_secure_request())})
            except AuthError as error:
                self.send_json({"error": str(error)}, 400)
            except ValueError:
                self.send_json({"error": "Invalid request"}, 400)
            return
        if path == "/api/fan/favorite":
            try:
                user = self.auth.session_user(self.headers.get("Cookie"))
                if user is None:
                    return self.send_json({"error": "Log in to choose a favorite driver"}, 401)
                payload = self.request_json()
                racer_id = payload.get("driver_id")
                if not isinstance(racer_id, int) or racer_id not in self.league.roster:
                    return self.send_json({"error": "Choose a valid driver"}, 400)
                user = self.auth.set_favorite_racer(user["id"], racer_id)
                self.send_json({"user": user, "favorite_change_available_at": self.auth.favorite_change_available_at(user["id"])})
            except AuthError as error:
                self.send_json({"error": str(error)}, 400)
            except ValueError:
                self.send_json({"error": "Invalid request"}, 400)
            return
        if path == "/api/fan/sponsor":
            try:
                user = self.auth.session_user(self.headers.get("Cookie"))
                if user is None:
                    return self.send_json({"error": "Log in to sponsor a team"}, 401)
                payload = self.request_json()
                team_id = payload.get("team_id")
                if not isinstance(team_id, str) or team_id not in TEAM_BY_ID:
                    return self.send_json({"error": "Choose a valid team"}, 400)
                user = self.auth.set_sponsored_team(user["id"], team_id)
                self.send_json({"user": user, "sponsor_change_available_at": self.auth.sponsor_change_available_at(user["id"])})
            except AuthError as error:
                self.send_json({"error": str(error)}, 400)
            except ValueError:
                self.send_json({"error": "Invalid request"}, 400)
            return
        if path in ("/api/final-lap/vote", "/api/final-lap/amendment"):
            try:
                user = self.auth.session_user(self.headers.get("Cookie"))
                if user is None:
                    return self.send_json({"error": "Log in to cast your vote"}, 401)
                payload = self.request_json()
                feature = self.league.final_lap()
                election = feature.get("election")
                if not election or election["phase"] != "open" or payload.get("season") != election["season"]:
                    return self.send_json({"error": "That amendment vote is closed"}, 400)
                self.send_json({"poll": self.auth.vote_final_lap(user["id"], payload["season"], payload.get("choice"))})
            except AuthError as error:
                self.send_json({"error": str(error)}, 400)
            except ValueError:
                self.send_json({"error": "Invalid request"}, 400)
            return
        if path == "/api/final-lap/pit-crew":
            try:
                user = self.auth.session_user(self.headers.get("Cookie"))
                if user is None:
                    return self.send_json({"error": "Log in to help the pit crew"}, 401)
                payload = self.request_json()
                feature = self.league.final_lap()
                election = feature.get("election")
                if not election or election["phase"] != "open" or payload.get("season") != election["season"]:
                    return self.send_json({"error": "Pit crew entries are closed"}, 400)
                targets = (payload.get("target_a"), payload.get("target_b"))
                if any(target is not None and target not in self.league.roster for target in targets):
                    return self.send_json({"error": "Choose a valid driver"}, 400)
                purchase = self.auth.buy_pit_crew_ticket(
                    user["id"], payload["season"], payload.get("action"), *targets
                )
                purchase["pit_crew"] = self.auth.pit_crew_ticket_count(payload["season"], user["id"])
                self.send_json(purchase)
            except AuthError as error:
                self.send_json({"error": str(error)}, 400)
            except ValueError:
                self.send_json({"error": "Invalid request"}, 400)
            return
        if path in ("/api/items/buy", "/api/items/sell", "/api/items/inventory"):
            try:
                user = self.auth.session_user(self.headers.get("Cookie"))
                if user is None:
                    return self.send_json({"error": "Log in to visit the Tower"}, 401)
                # Settle every completed race before changing which equipment was active.
                self.auth.settle_item_rewards(self.league.completed_item_races())
                payload = self.request_json()
                if path == "/api/items/buy":
                    user = self.auth.buy_item(user["id"], payload.get("item"))
                elif path == "/api/items/sell":
                    user = self.auth.sell_item(user["id"], payload.get("stack_id"))
                else:
                    user = self.auth.save_inventory(user["id"], payload.get("inventory"))
                self.send_json({"user": user})
            except AuthError as error:
                self.send_json({"error": str(error)}, 400)
            except ValueError:
                self.send_json({"error": "Invalid request"}, 400)
            return
        if path == "/api/bets":
            try:
                user = self.auth.session_user(self.headers.get("Cookie"))
                if user is None:
                    return self.send_json({"error": "Log in to place a bet"}, 401)
                payload = self.request_json()
                offer = self.league.bet_offer(payload.get("season"), payload.get("race_number"), payload.get("driver_id"))
                if offer is None:
                    return self.send_json({"error": "Betting for that racer is closed"}, 400)
                terms = self.auth.betting_terms(user["id"], offer["cost"])
                user = self.auth.place_bet(user["id"], offer["season"], offer["race_number"],
                                           offer["driver_id"], terms["cost"], offer["wins"])
                bet = next(entry for entry in self.auth.bets_for_user(user["id"])
                           if entry["season"] == offer["season"] and entry["race_number"] == offer["race_number"]
                           and entry["driver_id"] == offer["driver_id"])
                self.send_json({"user": user, "bet": bet, "cost": terms["cost"]})
            except AuthError as error:
                self.send_json({"error": str(error)}, 400)
            except ValueError:
                self.send_json({"error": "Invalid request"}, 400)
            return
        self.send_json({"error": "Endpoint not found"}, 404)

    def settle_due_elections(self):
        now = self.league.clock()
        for season in self.auth.pending_election_seasons():
            if now >= self.league.election_timing(season)["closes_at"]:
                result = self.auth.finalize_election(season)
                self.league.apply_pit_outcomes(season, result["pit_crew"])

    def enrich_election_result(self, result):
        if result is None:
            return None
        enriched = {**result, "pit_crew": []}
        for outcome in result["pit_crew"]:
            item = dict(outcome)
            item["target_a_name"] = self.league.roster[item["target_a"]]["name"]
            if item["target_b"] is not None:
                item["target_b_name"] = self.league.roster[item["target_b"]]["name"]
            enriched["pit_crew"].append(item)
        return enriched

    def request_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("Invalid request")
        if length <= 0 or length > 4096:
            raise ValueError("Invalid request")
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Invalid request")
        return value

    def is_secure_request(self):
        setting = os.environ.get("AUTH_COOKIE_SECURE", "auto").lower()
        return setting == "true" or (setting == "auto" and self.headers.get("X-Forwarded-Proto", "").lower() == "https")

    def send_json(self, value, status=200, headers=None):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, header_value in (headers or {}).items():
            self.send_header(name, header_value)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, fmt, *args):
        if len(args) > 1 and str(args[1]) not in ("200", "304"):
            super().log_message(fmt, *args)


def main():
    parser = argparse.ArgumentParser(description="An unattended racing league. The engines remember.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "league.sqlite3")
    args = parser.parse_args()
    args.db.parent.mkdir(parents=True, exist_ok=True)
    league = League(args.db)
    auth = LocalAuth(args.db)
    if not os.environ.get("APP_SESSION_SECRET"):
        logging.warning("APP_SESSION_SECRET is not set; sign-in sessions will end when this server restarts")
    try:
        server = ThreadingHTTPServer((args.host, args.port), partial(Handler, league=league, auth=auth))
    except OSError:
        league.close()
        raise
    stopped = threading.Event()

    def scheduler():
        while not stopped.wait(1):
            try:
                league.tick()
            except Exception:
                logging.exception("Scheduler tick failed; retrying in one second")

    thread = threading.Thread(target=scheduler, name="race-clock", daemon=True)
    thread.start()

    def stop(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    print(f"\n  STRANGE CIRCUIT\n  Live at http://{args.host}:{server.server_port}\n  Three races every 20 minutes Mon-Thu, then Friday's six-race championship. Ctrl+C to stop.\n", flush=True)
    try:
        server.serve_forever(poll_interval=.5)
    except KeyboardInterrupt:
        pass
    finally:
        stopped.set()
        thread.join()
        server.server_close()
        league.close()
        auth.close()


if __name__ == "__main__":
    main()
