"use strict";

const $ = (selector, parent = document) => parent.querySelector(selector);
const $$ = (selector, parent = document) => [...parent.querySelectorAll(selector)];
const escapeHTML = value => String(value).replace(/[&<>"']/g, character => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character]));
const fmtTime = seconds => {
  const value = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(value / 60)).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`;
};
const preciseTime = seconds => `${Math.floor(seconds / 60)}:${(seconds % 60).toFixed(3).padStart(6, "0")}`;
const dateLabel = timestamp => new Date(timestamp * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
const easternStartTime = timestamp => new Date(timestamp * 1000).toLocaleString("en-US", {
  timeZone: "America/New_York",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
  timeZoneName: "short",
});
const normalize = value => value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
const copyInventory = inventory => (inventory || []).map(stack => ({ ...stack }));
let state = null;
let drivers = [];
let driverSeasons = [];
let selectedDriverSeason = "";
let tracks = [];
let page = "live";
let serverOffset = 0;
let historyPage = 1;
let historyRequest = 0;
let dialogRaceId = null;
let dialogRequest = 0;
let completedCount = -1;
let historyTimer;
let currentUser = null;
let favoriteChangeAvailableAt = null;
let authMode = "login";
let inventoryDraft = null;
let draggedStackId = null;
let draggedFanStackId = null;
let fanActivity = [];
let eternals = null;
let eternalsView = "drivers";
let eternalsRequest = 0;

const towerItems = [
  { id: "binoculars", name: "Binoculars", cost: 100, icon: "◉", effect: "Every time your Favorite Racer wins, gain 10 Coin." },
  { id: "beer", name: "Beer", cost: 20, icon: "♨", effect: "Every time your Favorite Racer finishes in the bottom 3, gain 5 Coin." },
  { id: "whistle", name: "Whistle", cost: 25, icon: "⌁", effect: "Every time your Favorite Racer finishes in the top 3, gain 5 Coin." },
  { id: "camera", name: "Camera", cost: 30, icon: "▣", effect: "Every time there is a crash, gain 10 Coin." },
  { id: "old-scroll", name: "Old Scroll", cost: 10, icon: "≋", effect: "Every time someone wins for the first time that season, gain 10 Coin." },
  { id: "watch", name: "Watch", cost: 10, icon: "◷", effect: "Gain 50 Coin when any race takes over 8 minutes." },
  { id: "vegas-shark", name: "Vegas Shark", cost: 50, icon: "♠", effect: "Decrease a racer's win surcharge by 2 Coin per active Shark." },
  { id: "sunglasses", name: "Sunglasses", cost: 50, icon: "▰", effect: "Gain 1,000 bonus Coin per active pair when a zero-win pick wins." },
  { id: "gun", name: "Gun", cost: 100, icon: "⌐", effect: "Increase the number of bets you can place per racer by 1." },
  { id: "lucky-ticket", name: "Lucky Ticket", cost: 1, icon: "✦", effect: "Gain 5 bonus Coin per active ticket when you only back one driver in a race." },
];

const activeItemQuantity = itemId => (currentUser?.inventory || []).filter(stack => stack.active && stack.item === itemId).reduce((total, stack) => total + stack.quantity, 0);

async function api(path) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8000);
  try {
    const response = await fetch(path, { signal: controller.signal, cache: "no-store" });
    if (!response.ok) throw new Error(`Timing tower returned ${response.status}`);
    return await response.json();
  } finally { clearTimeout(timeout); }
}

async function loadAccount() {
  try {
    const data = await api("/api/auth/me");
    currentUser = data.user;
    const login = $("#login");
    const register = $("#register");
    const name = $("#account-name");
    const logout = $("#logout");
    const portalNav = $("#portal-nav");
    if (currentUser) {
      name.textContent = currentUser.username;
      name.hidden = false;
      login.hidden = true;
      register.hidden = true;
      logout.hidden = false;
      portalNav.hidden = false;
    } else {
      inventoryDraft = null;
      name.hidden = true;
      login.hidden = false;
      register.hidden = false;
      logout.hidden = true;
      portalNav.hidden = true;
      if (["fan", "tower", "eternals"].includes(page)) location.hash = "#live";
    }
    favoriteChangeAvailableAt = data.favorite_change_available_at;
    if (state) renderLive();
    if (page === "drivers" && drivers.length) renderDrivers();
    if (page === "fan") renderFanPage();
    if (page === "tower") renderTower();
    if (page === "eternals") renderEternals();
  } catch (_) { /* The normal connection indicator covers unavailable servers. */ }
}

function showAuth(mode) {
  authMode = mode;
  const registering = mode === "register";
  $("#auth-title").textContent = registering ? "Create account" : "Log in";
  $("#auth-submit").textContent = registering ? "Create account" : "Log in";
  $("#auth-password").autocomplete = registering ? "new-password" : "current-password";
  $("#auth-switch").textContent = registering ? "Already registered? Log in ↗" : "Need an account? Register ↗";
  $("#auth-error").hidden = true;
  $("#auth-form").reset();
  const dialog = $("#auth-dialog");
  if (!dialog.open) dialog.showModal();
  setTimeout(() => $("#auth-username").focus(), 0);
}

async function submitAuth(event) {
  event.preventDefault();
  const username = $("#auth-username").value;
  const password = $("#auth-password").value;
  const submit = $("#auth-submit");
  const error = $("#auth-error");
  submit.disabled = true;
  error.hidden = true;
  try {
    const response = await fetch(`/auth/${authMode}`, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username, password }) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Unable to continue");
    currentUser = data.user;
    $("#auth-dialog").close();
    await loadAccount();
  } catch (cause) {
    error.textContent = cause instanceof TypeError ? "Could not reach the account server. Restart python3 server.py, then open http://localhost:8000." : cause.message;
    error.hidden = false;
  } finally { submit.disabled = false; }
}

function carSVG(color, number) {
  return `<svg viewBox="0 0 300 110" role="img" aria-label="Car number ${number}">
    <ellipse cx="151" cy="85" rx="120" ry="8" fill="#000" opacity=".2"/>
    <path d="M22 72 35 56 83 49 111 26 181 26 214 49 265 56 281 71 277 82H22Z" fill="${color}"/>
    <path d="m91 49 25-18h61l25 18Z" fill="#181d17"/><path d="M150 30v20" stroke="${color}" stroke-width="5"/>
    <path d="m31 57 58-3 115-1 63 7M103 55l-6 24m108-24 7 24" fill="none" stroke="#070b18" stroke-width="1.2" opacity=".45"/>
    <path d="M24 74h250v6H24Z" fill="#070b18" opacity=".18"/>
    <path d="M247 45h31v5h-31zm9 5v8h4v-8" fill="${color}"/>
    <path d="M29 63h18v6H25zm237 0h10l4 6h-14" fill="#f4f4dc" opacity=".9"/>
    <circle cx="74" cy="79" r="19" fill="#11140f"/><circle cx="74" cy="79" r="11" fill="#727a65"/><circle cx="74" cy="79" r="6" fill="#23291f"/>
    <circle cx="231" cy="79" r="19" fill="#11140f"/><circle cx="231" cy="79" r="11" fill="#727a65"/><circle cx="231" cy="79" r="6" fill="#23291f"/>
    <path d="M55 78a19 19 0 0 1 38 0m119 0a19 19 0 0 1 38 0" fill="none" stroke="#070b18" stroke-width="4"/>
    <rect x="134" y="55" width="33" height="23" rx="2" fill="#070b18" opacity=".9"/>
    <text x="150" y="71" text-anchor="middle" font-family="monospace" font-size="15" font-weight="bold" fill="${color}">${number}</text>
    <path d="M106 61h16m-16 5h11m68-5h16m-16 5h11" stroke="#070b18" stroke-width="2" opacity=".5"/>
  </svg>`;
}

function isFavorite(driverId) {
  return currentUser && Number(currentUser.fav_racer) === Number(driverId);
}

function favoriteHeart(driverId) {
  return isFavorite(driverId) ? '<span class="favorite-heart" role="img" aria-label="Favorite driver">❤️</span>' : "";
}

function trackMarkup(race, detail = false) {
  return `<div class="track-wrap ${detail ? "detail-track" : ""}">
    <svg class="track-svg" viewBox="0 0 360 180" role="img" aria-label="Live track positions for ${escapeHTML(race.name)}">
      <path class="track-asphalt" d="M100 45H260A45 45 0 0 1 260 135H100A45 45 0 0 1 100 45Z"/>
      <path class="track-edge" d="M100 32H260A58 58 0 0 1 260 148H100A58 58 0 0 1 100 32Z"/>
      <path class="track-edge" d="M100 58H260A32 32 0 0 1 260 122H100A32 32 0 0 1 100 58Z"/>
      <path class="track-center" d="M100 45H260A45 45 0 0 1 260 135H100A45 45 0 0 1 100 45Z"/>
      <path d="M100 33v24" stroke="#e9ecde" stroke-width="5"/>
      <path d="M100 33v24" stroke="#15170f" stroke-width="5" stroke-dasharray="3 3"/>
      <g class="track-markers">${race.standings.map(driver => `<g class="track-marker" data-marker="${driver.driver_id}"><circle class="rank-halo" r="10"/><circle class="car-marker" r="6" fill="${driver.color}"/><text>${driver.number}</text><title>${escapeHTML(driver.name)}</title></g>`).join("")}</g>
    </svg>
    <div class="lap-display"><div class="micro">LEADER LAP</div><div class="lap-value">01 <small>/ 10</small></div></div>
  </div>`;
}

function standingsMarkup(race, detail = false) {
  return `<div class="standings ${detail ? "detail-standings" : ""}"><div class="standings-head"><span>POS</span><span>NUM</span><span>DRIVER</span><span>${detail ? "DIST. KM" : "LAPS"}</span><span>GAP</span></div><ol class="standings-list">${standingsRows(race, detail)}</ol></div>`;
}

function standingsRows(race, detail = false) {
  return race.standings.map(driver => `<li class="standing" style="--driver-color:${driver.color}" aria-label="Position ${driver.position}, ${escapeHTML(driver.name)}, ${driver.laps} laps completed, ${driver.distance} kilometers">
    <span class="position">${String(driver.position).padStart(2, "0")}</span><span class="standing-number">${String(driver.number).padStart(2, "0")}</span><span class="standing-driver"><i class="driver-color"></i><span class="standing-name">${escapeHTML(driver.name)}${favoriteHeart(driver.driver_id)}</span></span>
    <span class="standing-progress">${detail ? driver.distance.toFixed(1) : `${driver.laps}<span class="tiny-progress"><i style="width:${driver.progress * 10}%"></i></span>`}</span>
    <span class="standing-gap">${driver.position === 1 ? (driver.finished ? "WINNER" : "LEADER") : `+${driver.gap.toFixed(1)}`}</span></li>`).join("");
}

function updateTrack(root, race) {
  const path = $(".track-center", root);
  const length = path.getTotalLength();
  for (const driver of race.standings) {
    const marker = $(`[data-marker="${driver.driver_id}"]`, root);
    marker.classList.remove("rank-1", "rank-2", "rank-3");
    if (race.status === "live" && driver.position <= 3) marker.classList.add(`rank-${driver.position}`);
    let x, y;
    if (driver.finished) {
      x = 99 + driver.position * 15;
      y = 165;
    } else {
      const traveled = ((driver.progress % 1) * length - (race.elapsed < 8 ? driver.grid * 2 : 0) + length) % length;
      const point = path.getPointAtLength(traveled);
      const next = path.getPointAtLength((traveled + .5) % length);
      const norm = Math.hypot(next.x - point.x, next.y - point.y) || 1;
      const lane = ((driver.grid - 1) % 3 - 1) * 5;
      x = point.x - (next.y - point.y) / norm * lane;
      y = point.y + (next.x - point.x) / norm * lane;
    }
    marker.style.transform = `translate(${x}px, ${y}px)`;
    $("title", marker).textContent = `P${driver.position} · ${driver.name} · ${driver.laps}/10 laps · ${driver.distance} km`;
  }
  const leader = race.standings[0];
  $(".lap-value", root).innerHTML = `${String(Math.min(10, leader.laps + 1)).padStart(2, "0")} <small>/ 10</small>`;
  $(".lap-display .micro", root).textContent = race.status === "finished" ? "CHECKERED FLAG" : leader.finished ? "LEADER FINISHED" : "LEADER LAP";
}

function raceCard(race) {
  return `<article class="race-card" id="race-${race.id}">
    <div class="race-card-head"><div class="race-meta"><span>RACE ${String(race.race_number).padStart(2, "0")} <span class="divider-dot">/</span> <span class="city-code">${race.city.code}</span></span><span class="race-status"><i></i><span>LIVE</span></span></div>
    <h3>${escapeHTML(race.name)}</h3><div class="city-line"><span class="flag">⌁</span> ${escapeHTML(race.city.circuit)}</div></div>
    ${trackMarkup(race)}<div class="track-caption"><span>${escapeHTML(race.city.circuit).toUpperCase()}</span><span>${race.city.length.toFixed(1)} KM / LAP</span></div>
    ${standingsMarkup(race)}<div class="race-card-foot"><span class="micro race-clock">RACE CLOCK 00:00</span><button class="text-button" data-race="${race.id}">Follow race <span>↗</span></button></div>
    </article>`;
}

function nextRaceCard(race) {
  const betFor = driverId => (state.bets || []).find(bet => bet.season === race.season && bet.race_number === race.race_number && bet.driver_id === driverId);
  return `<article class="next-race-card">
    <div class="next-race-head"><div class="race-meta"><span>RACE ${String(race.race_number).padStart(2, "0")} <span class="divider-dot">/</span> <span class="city-code">${race.city.code}</span></span><span>${dateLabel(race.start)}</span></div>
    <h3>${escapeHTML(race.name)}</h3><div class="city-line"><span class="flag">⌁</span> ${escapeHTML(race.city.circuit)}</div></div>
    <div class="next-racers-head"><span>RACER NO.</span><span>NAME</span><span>WINS</span><span>BET</span></div>
    <ol class="next-racers-list">${race.racers.map(driver => {
      const bet = betFor(driver.driver_id);
      const quantity = bet?.quantity || 0;
      const cost = 5 + Math.max(0, driver.wins - activeItemQuantity("vegas-shark") * 2);
      const limit = 10 + activeItemQuantity("gun");
      const maxed = quantity >= limit;
      const short = currentUser && currentUser.coin < cost;
      const title = maxed ? `Maximum ${limit} bets placed` : `Place one bet for ${cost} Coin. A win pays 100 Coin before item bonuses.`;
      return `<li style="--driver-color:${driver.color}"><span class="next-racer-number">${driver.number}</span><span class="next-racer-name"><i class="driver-color"></i><span>${escapeHTML(driver.name)}${favoriteHeart(driver.driver_id)}${quantity ? '<span class="driver-bet-coin" role="img" aria-label="Bet placed">🪙</span>' : ""}</span></span><span class="next-racer-wins">${String(driver.wins).padStart(2, "0")}</span><button class="bet-button" data-place-bet data-season="${race.season}" data-race-number="${race.race_number}" data-driver-id="${driver.driver_id}" title="${title}" aria-label="${title} ${quantity} of ${limit} bets placed." ${(maxed || short) ? "disabled" : ""}><span aria-hidden="true">🪙</span>${quantity ? `<b>${quantity}</b>` : ""}</button></li>`;
    }).join("")}</ol>
  </article>`;
}

function renderLive() {
  if (!state) return;
  const grid = $("#race-grid");
  const raceSignature = state.races.length ? String(state.wave) : `empty:${state.next_start}`;
  if (grid.dataset.wave !== raceSignature) {
    grid.innerHTML = state.races.length ? state.races.map(raceCard).join("") : emptyState("Waiting for the green light.", "The next season slot opens at the scheduled Eastern start time.");
    grid.dataset.wave = raceSignature;
  }
  const active = state.races.filter(race => race.status === "live");
  $(".nav-dot").classList.toggle("is-live", active.length > 0);
  const liveEyebrow = $("#live-eyebrow");
  if (liveEyebrow) liveEyebrow.textContent = active.length ? "THE CIRCUIT IS ALIVE" : "";
  $("#wave-status").textContent = active.length ? "LIVE NOW" : "WAVE COMPLETE";
  $("#wave-number").textContent = state.wave ? `WAVE ${String(state.wave).padStart(3, "0")}` : `${state.season.name.toUpperCase()} SEASON`;
  const next = state.next_races[0];
  $("#next-wave-number").textContent = `${next ? `WAVE ${String(next.wave).padStart(3, "0")} · ` : ""}STARTS IN ${fmtTime(Math.max(0, Math.ceil(state.next_start - (Date.now() / 1000 + serverOffset))))}`;
  $("#betting-coin-value").textContent = Number(currentUser?.coin || 0).toLocaleString();
  const nextGrid = $("#next-race-grid");
  const nextSignature = `${state.wave}:${state.completed_races}:${state.next_start}:${currentUser?.coin ?? "guest"}:${JSON.stringify(state.bets || [])}`;
  if (nextGrid.dataset.signature !== nextSignature) {
    nextGrid.innerHTML = state.next_races.map(nextRaceCard).join("");
    nextGrid.dataset.signature = nextSignature;
  }
  for (const race of state.races) {
    const card = $(`#race-${race.id}`);
    const leaderId = race.standings[0]?.driver_id;
    const leaderChanged = card.dataset.leader && card.dataset.leader !== String(leaderId);
    card.dataset.leader = String(leaderId || "");
    if (leaderChanged && race.status === "live") {
      card.classList.remove("leader-change");
      void card.offsetWidth;
      card.classList.add("leader-change");
    }
    $(".race-status", card).classList.toggle("finished", race.status === "finished");
    $(".race-status span", card).textContent = race.status === "live" ? "LIVE" : "FINAL";
    $(".standings-list", card).innerHTML = standingsRows(race);
    $(".race-clock", card).textContent = `RACE CLOCK ${fmtTime(race.elapsed)}`;
    const button = $("[data-race]", card);
    if (button.dataset.status !== race.status) {
      button.innerHTML = `${race.status === "live" ? "Follow race" : "Race results"} <span>↗</span>`;
      button.dataset.status = race.status;
    }
    updateTrack(card, race);
  }
  $("#venue-list").innerHTML = state.cities.map(city => `<span class="venue ${active.some(race => race.city.name === city.name) ? "is-active" : ""}"><i></i>${escapeHTML(city.name)}</span>`).join("");
  $("#history-title").textContent = `The ${state.season.name} Season`;
  $("#history-number").innerHTML = `${state.completed_races} / ${state.season.total_races}<span>RACES COMPLETE</span>`;
  updateCountdown();
}

function updateCountdown() {
  if (!state) return;
  const remaining = Math.max(0, Math.ceil(state.next_start - (Date.now() / 1000 + serverOffset)));
  const countdown = $("#countdown");
  if (remaining > 60 * 60) {
    countdown.textContent = `${Math.floor(remaining / (60 * 60))} Hours`;
    countdown.title = `Start time: ${easternStartTime(state.next_start)}`;
  } else {
    countdown.innerHTML = fmtTime(remaining).replace(":", "<span>:</span>");
    countdown.removeAttribute("title");
  }
}

async function loadDrivers() {
  try {
    const params = selectedDriverSeason ? `?season=${encodeURIComponent(selectedDriverSeason)}` : "";
    const data = await api(`/api/drivers${params}`);
    drivers = data.drivers;
    driverSeasons = data.seasons || [];
    syncDriverSeasonSelect();
    if (page === "drivers") renderDrivers();
    if (page === "fan") renderFanPage();
  } catch (_) {
    if (page === "drivers" && !drivers.length) $("#driver-grid").innerHTML = emptyState("The paddock is out of range.", "We’ll try the signal again in a moment.");
  }
}

function syncDriverSeasonSelect() {
  const select = $("#driver-season");
  if (!select) return;
  const current = driverSeasons.find(season => season.current) || driverSeasons[0];
  if (!selectedDriverSeason && current) selectedDriverSeason = String(current.number);
  const signature = driverSeasons.map(season => `${season.number}:${season.name}:${season.current}`).join("|");
  if (select.dataset.signature !== signature) {
    select.innerHTML = driverSeasons.map(season => `<option value="${season.number}">${season.current ? `${escapeHTML(season.name)} Season (current)` : `${escapeHTML(season.name)} Season`}</option>`).join("");
    select.dataset.signature = signature;
  }
  if (selectedDriverSeason) select.value = selectedDriverSeason;
}

function renderDrivers() {
  const query = normalize($("#driver-search").value.trim());
  const sort = $("#driver-sort").value;
  const filtered = drivers.filter(driver => normalize(`${driver.name} ${driver.car.name} ${driver.number}`).includes(query));
  filtered.sort((a, b) => sort === "wins" ? b.wins - a.wins || a.id - b.id : sort === "fans" ? (b.fans || 0) - (a.fans || 0) || b.starts - a.starts || a.name.localeCompare(b.name) : sort === "name" ? a.name.localeCompare(b.name) : a.id - b.id);
  $("#driver-count").textContent = `${filtered.length} / 30 DRIVERS`;
  $("#driver-grid").innerHTML = filtered.length ? filtered.map(driver => `<button class="driver-card" data-driver="${driver.id}" style="--driver-color:${driver.color}" aria-label="View ${escapeHTML(driver.name)} and ${escapeHTML(driver.car.name)}, ${driver.wins} wins">
    <div class="driver-card-top"><span class="driver-number">NO. ${driver.number}</span><span class="win-badge"><b>${String(driver.wins).padStart(2, "0")}</b> WINS</span></div><h2>${escapeHTML(driver.name)}${favoriteHeart(driver.id)}</h2><p class="driver-hometown">${driver.fans || 0} Fans <span class="divider-dot">|</span> ${driver.starts} Starts</p>
    <div class="car-art">${carSVG(driver.color, driver.number)}</div><p class="car-name">“${escapeHTML(driver.car.name)}”</p>
    <div class="compact-stats">${driver.attributes.map(attr => `<div class="compact-stat"><span>${escapeHTML(attr.name)}</span><b>${attr.value}</b></div>`).join("")}</div>
    <div class="card-bottom"><span>DRIVER + MACHINE DOSSIER</span><span>OPEN FILE ↗</span></div></button>`).join("") : emptyState("Nobody by that name.", "Try another driver, car name, or racing number.");
}

function trackCard(track) {
  const curveBias = track.curve_bias ?? 50;
  return `<button class="track-card" data-track="${escapeHTML(track.name)}" aria-label="Open ${escapeHTML(track.name)} track history">
    <div class="track-card-top"><span class="driver-number">${escapeHTML(track.code)}</span></div>
    <div class="track-art" aria-hidden="true"><svg viewBox="0 0 300 150"><path d="M72 35h156a40 40 0 0 1 0 80H72a40 40 0 0 1 0-80Z"/><path d="M72 50h156a25 25 0 0 1 0 50H72a25 25 0 0 1 0-50Z"/><path d="M72 35v24" class="track-start"/></svg><span class="track-art-mark">ϟ</span></div>
    <h2>${escapeHTML(track.name)}</h2><p>${escapeHTML(track.circuit)} <span class="divider-dot">/</span> ${escapeHTML(track.country)}</p>
    <div class="track-card-stats"><span>LENGTH</span><b>${track.length.toFixed(1)} KM / LAP</b></div>
    <div class="track-bias" style="--curve-bias:${curveBias}%"><div><span>STRAIGHTAWAYS</span><span>CURVES</span></div><i></i></div>
    <div class="card-bottom"><span>CIRCUIT ARCHIVE</span><span>OPEN FILE ↗</span></div>
  </button>`;
}

async function loadTracks() {
  try {
    tracks = (await api("/api/tracks")).tracks;
    if (page === "tracks") renderTracks();
  } catch (_) {
    if (page === "tracks") $("#track-grid").innerHTML = emptyState("The map is out of range.", "We’ll try the signal again in a moment.");
  }
}

function renderTracks() {
  const query = normalize($("#track-search").value.trim());
  const sort = $("#track-sort").value;
  const filtered = tracks.filter(track => normalize(`${track.name} ${track.circuit} ${track.country} ${track.code}`).includes(query));
  filtered.sort((a, b) => sort === "length-asc" ? a.length - b.length || a.name.localeCompare(b.name) : sort === "length-desc" ? b.length - a.length || a.name.localeCompare(b.name) : a.name.localeCompare(b.name));
  $("#track-count").textContent = `${filtered.length} / ${tracks.length} TRACKS`;
  $("#track-grid").innerHTML = filtered.length ? filtered.map(trackCard).join("") : emptyState("No tracks by that name.", "Try another track, circuit, country, or code.");
}

function openTrack(name) {
  const track = tracks.find(item => item.name === name);
  if (!track) return;
  dialogRaceId = null;
  dialogRequest++;
  $("#dialog-eyebrow").textContent = "CIRCUIT ARCHIVE / TRACK HISTORY";
  const curveBias = track.curve_bias ?? 50;
  $("#dialog-content").innerHTML = `<h2 id="dialog-title" class="dialog-title">${escapeHTML(track.name)}</h2><p class="dialog-subtitle">${escapeHTML(track.circuit)}, ${escapeHTML(track.country)} · ${track.length.toFixed(1)} km per lap · Last 10 completed races</p>
    <div class="track-bias detail-bias" style="--curve-bias:${curveBias}%"><div><span>STRAIGHTAWAYS</span><span>CURVES</span></div><i></i></div>
    <div class="track-history"><div class="track-history-head"><span>RACE</span><span>DATE</span><span>PODIUM</span><span>FILE</span></div>${track.races.length ? track.races.map(race => `<div class="track-history-row"><div><b>${escapeHTML(race.name)}</b><small>WAVE ${String(race.wave).padStart(3, "0")}</small></div><span class="history-sub">${escapeHTML(dateLabel(race.start))}</span><div class="podium-list">${race.standings.slice(0, 3).map(driver => `<span class="history-winner" style="--driver-color:${driver.color}"><i class="driver-color"></i>${driver.position}. ${escapeHTML(driver.name)}</span>`).join("")}</div><button data-race="${race.id}" aria-label="View results for ${escapeHTML(race.name)}">↗</button></div>`).join("") : emptyState("No completed races yet.", "This track’s first podium is still out there.")}</div>`;
  showDialog();
}

function attributeMarkup(groups) {
  return groups.map(group => `<div class="attribute-group"><div class="attribute-heading"><span>${escapeHTML(group.name)}</span><b>${group.value}<span class="muted"> / 100</span></b></div>${group.stats.map(stat => ["Eyes", "Wheels"].includes(stat.name)
    ? `<div class="stat-row raw-stat"><span>${escapeHTML(stat.name)}</span><span>${stat.value}</span></div>`
    : `<div class="stat-row"><span>${escapeHTML(stat.name)}</span><span class="stat-bar"><i style="width:${stat.value}%"></i></span><span>${stat.value}</span></div>`).join("")}</div>`).join("");
}

function openDriver(id) {
  const driver = drivers.find(item => item.id === id);
  if (!driver) return;
  const selectedSeason = driverSeasons.find(season => String(season.number) === selectedDriverSeason);
  dialogRaceId = null;
  dialogRequest++;
  $("#dialog-eyebrow").textContent = "DRIVER DOSSIER";
  $("#dialog-content").innerHTML = `<div style="--driver-color:${driver.color}">
    <div class="profile-header"><div><h2 id="dialog-title" class="dialog-title">${escapeHTML(driver.name)}</h2><p class="dialog-subtitle">${escapeHTML(selectedSeason?.name || "Current")} season <span class="divider-dot">/</span> ${driver.wins} wins <span class="divider-dot">/</span> ${driver.starts} starts</p></div><span class="profile-number">${driver.number}</span></div>
    <div class="profile-car">${carSVG(driver.color, driver.number)}<div><div class="eyebrow">THE MACHINE</div><h3>${escapeHTML(driver.car.name)}</h3></div></div>
    <div class="stat-sections"><section class="stat-column"><h3>01 / DRIVER ATTRIBUTES</h3>${attributeMarkup(driver.attributes)}</section><section class="stat-column"><h3>02 / CAR ATTRIBUTES</h3>${attributeMarkup(driver.car.attributes)}</section></div></div>`;
  showDialog();
}

function emptyState(title, description) {
  return `<div class="empty-state"><div class="empty-icon">⌁</div><h2>${title}</h2><p>${description}</p></div>`;
}

function favoriteChangeLabel() {
  if (!favoriteChangeAvailableAt || favoriteChangeAvailableAt * 1000 <= Date.now()) return "Choose or change your favorite driver";
  return `Available again ${dateLabel(favoriteChangeAvailableAt)}`;
}

function renderFanPage() {
  if (!currentUser) return;
  $("#fan-title").textContent = currentUser.username;
  $("#fan-coin-value").textContent = Number(currentUser.coin || 0).toLocaleString();
  const favorite = drivers.find(driver => isFavorite(driver.id));
  const favoriteMarkup = favorite ? `<button class="fan-driver-card" data-open-favorite style="--driver-color:${favorite.color}" aria-label="Change favorite driver, currently ${escapeHTML(favorite.name)}">
      <div><span class="eyebrow">FAVORITE DRIVER</span><div class="fan-card-title">${escapeHTML(favorite.name)} ${favoriteHeart(favorite.id)}</div><p>“${escapeHTML(favorite.car.name)}”</p><small>${favoriteChangeLabel()}</small></div><div class="fan-car-art">${carSVG(favorite.color, favorite.number)}</div><span class="fan-change">CHANGE ↗</span>
    </button>` : `<button class="fan-driver-card fan-driver-empty" data-open-favorite><div><span class="eyebrow">FAVORITE DRIVER</span><div class="fan-card-title">No favorite yet</div><p>Choose a driver and their machine.</p></div><span class="fan-change">CHOOSE ↗</span></button>`;
  const inventory = currentUser.inventory || [];
  const slots = (active, limit) => Array.from({ length: limit }, (_, index) => {
    const stack = inventory.filter(entry => entry.active === active)[index];
    if (!stack) return `<div class="fan-slot ${active ? "" : "inactive"}" data-fan-drop-area="${active ? "active" : "stash"}" data-fan-drop-index="${index}"><span>${String(index + 1).padStart(2, "0")}</span><i>EMPTY</i></div>`;
    const item = towerItems.find(entry => entry.id === stack.item);
    const destination = active ? "stash" : "active";
    const description = active ? "" : `<p class="fan-item-description">${escapeHTML(item.effect)}</p>`;
    return `<div class="fan-slot fan-item-slot ${active ? "" : "inactive"}" draggable="true" data-fan-stack-id="${stack.id}" data-fan-drop-area="${active ? "active" : "stash"}" data-fan-drop-index="${index}"><span>${String(index + 1).padStart(2, "0")}</span><b>${item.icon} ${escapeHTML(item.name)}</b><i>×${stack.quantity} / 10</i>${description}<button data-fan-move="${stack.id}" data-fan-target="${destination}">Move to ${destination}</button></div>`;
  }).join("");
  const driverName = driverId => drivers.find(driver => driver.id === Number(driverId))?.name || `Driver ${driverId}`;
  const activityLabel = entry => {
    if (entry.kind === "bet_placed") return `Bet placed on ${escapeHTML(driverName(entry.driver_id))}`;
    if (entry.kind === "bet_payout") return `Winning bet on ${escapeHTML(driverName(entry.driver_id))}`;
    if (entry.kind === "bet_loss") return `Bet settled on ${escapeHTML(driverName(entry.driver_id))}`;
    const item = towerItems.find(candidate => candidate.id === entry.item_id);
    return `${item?.icon || "◇"} ${escapeHTML(item?.name || entry.item_id)} payout`;
  };
  const activityRows = fanActivity.map(entry => `<li class="fan-activity-row"><span class="fan-activity-kind ${entry.kind}">${entry.kind.startsWith("bet_") ? "BET" : "ITEM"}</span><span class="fan-activity-detail"><b>${activityLabel(entry)}</b><small>Race ${entry.race_number}${entry.quantity > 1 ? ` · ×${entry.quantity}` : ""} · ${dateLabel(entry.created_at)}</small></span><strong class="${entry.amount > 0 ? "positive" : entry.amount < 0 ? "negative" : "neutral"}">${entry.amount > 0 ? "+" : entry.amount < 0 ? "−" : ""}${Math.abs(entry.amount)} <small>COIN</small></strong></li>`).join("");
  const activityMarkup = `<section class="fan-activity"><div class="fan-activity-head"><div><span class="eyebrow">CURRENT SEASON</span><h2>Betting & payouts</h2></div><span>${fanActivity.length} ${fanActivity.length === 1 ? "ENTRY" : "ENTRIES"}</span></div>${activityRows ? `<ol class="fan-activity-list">${activityRows}</ol>` : `<div class="fan-activity-empty">Your bets and item payouts will be saved here for the current season.</div>`}</section>`;
  $("#fan-content").innerHTML = `<div class="fan-layout"><section>${favoriteMarkup}</section><section class="fan-inventory"><div class="fan-inventory-head"><div class="fan-section-title">Active Inventory</div><span>${inventory.filter(entry => entry.active).length} / 3 SLOTS</span></div><div class="fan-slots">${slots(true, 3)}</div><p id="fan-inventory-message" class="fan-inventory-message" role="status">Only active items earn Coin. Use Move, or drag a stack onto another to swap.</p><a class="inventory-link" href="#tower">Buy equipment at The Tower ↗</a></section><section class="fan-inventory fan-stash"><div class="fan-inventory-head"><div class="fan-section-title">Stash</div><span>${inventory.filter(entry => !entry.active).length} / 5 SLOTS</span></div><div class="fan-slots">${slots(false, 5)}</div></section>${activityMarkup}</div>`;
}

function showFanInventoryMessage(message) {
  const status = $("#fan-inventory-message");
  if (status) status.textContent = message;
}

async function moveFanInventoryStack(stackId, destination) {
  const inventory = copyInventory(currentUser?.inventory);
  const stack = inventory.find(entry => entry.id === stackId);
  const active = destination === "active";
  if (!stack || stack.active === active) return;
  const limit = active ? 3 : 5;
  if (inventory.filter(entry => entry.active === active).length >= limit) {
    showFanInventoryMessage(`${active ? "Active inventory" : "Stash"} is full. Move an item out first.`);
    return;
  }
  stack.active = active;
  showFanInventoryMessage("Saving equipment…");
  try {
    const response = await fetch("/api/items/inventory", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ inventory }) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not update your equipment");
    currentUser = data.user;
    inventoryDraft = copyInventory(currentUser.inventory);
    renderFanPage();
    const item = towerItems.find(candidate => candidate.id === stack.item);
    showFanInventoryMessage(`Moved ${item.name} to ${destination}.`);
  } catch (cause) {
    showFanInventoryMessage(cause instanceof TypeError ? "Could not reach the Tower." : cause.message);
  }
}

async function swapFanInventoryStack(stackId, destination, index) {
  const inventory = copyInventory(currentUser?.inventory);
  const source = inventory.find(entry => entry.id === stackId);
  const active = destination === "active";
  if (!source || source.active === active) return;
  const target = inventory.filter(entry => entry.active === active)[index];
  if (target && target.id !== source.id) target.active = source.active;
  source.active = active;
  showFanInventoryMessage("Saving equipment…");
  try {
    const response = await fetch("/api/items/inventory", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ inventory }) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not update your equipment");
    currentUser = data.user;
    inventoryDraft = copyInventory(currentUser.inventory);
    renderFanPage();
    showFanInventoryMessage("Active equipment updated.");
  } catch (cause) {
    showFanInventoryMessage(cause instanceof TypeError ? "Could not reach the Tower." : cause.message);
  }
}

function towerSlotMarkup(active, limit) {
  const stacks = (inventoryDraft || []).filter(stack => stack.active === active);
  return Array.from({ length: limit }, (_, index) => {
    const stack = stacks[index];
    if (!stack) return `<div class="tower-slot empty" data-drop-area="${active ? "active" : "stash"}" data-drop-index="${index}"><span>${String(index + 1).padStart(2, "0")}</span><i>EMPTY</i></div>`;
    const item = towerItems.find(entry => entry.id === stack.item);
    return `<div class="tower-slot" draggable="true" data-stack-id="${stack.id}" data-drop-area="${active ? "active" : "stash"}" data-drop-index="${index}"><span>${String(index + 1).padStart(2, "0")}</span><b>${item.icon} ${escapeHTML(item.name)}</b><i>×${stack.quantity} / 10</i><button data-sell-stack="${stack.id}" aria-label="Sell one ${escapeHTML(item.name)}">Sell +${Math.floor(item.cost * .6)}</button></div>`;
  }).join("");
}

function renderTower() {
  if (!currentUser) return;
  if (!inventoryDraft) inventoryDraft = copyInventory(currentUser.inventory);
  $("#tower-coin-value").textContent = Number(currentUser.coin || 0).toLocaleString();
  const itemCards = towerItems.map(item => `<article class="tower-item"><div class="tower-item-icon">${item.icon}</div><div><div class="tower-item-head"><h2>${item.name}</h2><span>${item.cost} COIN</span></div><p>${item.effect}</p><button class="tower-buy" data-buy-item="${item.id}" ${currentUser.coin < item.cost ? "disabled" : ""}>Buy one ↗</button></div></article>`).join("");
  $("#tower-content").innerHTML = `<div class="tower-layout"><section class="tower-stock"><div class="tower-section-heading"><span class="eyebrow">THE COUNTER</span><h2>Useful objects</h2><p>Items stack up to 10 per slot. Sell one item at a time for 60% of its price.</p></div><div class="tower-item-grid">${itemCards}</div></section><aside class="tower-inventory"><div class="tower-section-heading"><span class="eyebrow">YOUR EQUIPMENT</span><h2>Set your kit</h2><p>Drag stacks between active inventory and stash, then save. Only active items pay out after a race.</p></div><div class="tower-area"><div><span class="micro">ACTIVE / 03</span><div class="tower-slots">${towerSlotMarkup(true, 3)}</div></div><div><span class="micro">STASH / 05</span><div class="tower-slots tower-stash-slots">${towerSlotMarkup(false, 5)}</div></div></div><p class="tower-message" id="tower-message" role="status"></p><button class="tower-save" data-save-inventory>Save equipment ↗</button></aside></div>`;
}

async function loadEternals() {
  const request = ++eternalsRequest;
  try {
    const data = await api("/api/eternals");
    if (request !== eternalsRequest) return;
    eternals = data;
    renderEternals();
  } catch (_) {
    if (request === eternalsRequest) $("#eternals-content").innerHTML = emptyState("The record is sealed.", "The eternal archive is temporarily out of reach.");
  }
}

function renderEternals() {
  if (!eternals) return;
  $$('[data-eternals-view]').forEach(button => {
    const active = button.dataset.eternalsView === eternalsView;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
  if (eternalsView === "seasons") {
    $("#eternals-content").innerHTML = eternals.seasons.length ? `<div class="eternals-table-wrap"><div class="eternals-table-note">UPCOMING SEASON, THEN NEWEST COMPLETED FIRST</div><table class="eternals-table seasons-record"><thead><tr><th>SEASON</th><th>START DATE</th><th>WINNER</th><th>SECOND</th><th>THIRD</th></tr></thead><tbody>${eternals.seasons.map(season => `<tr class="${season.winner ? "" : "upcoming-season"}"><td><strong>The ${escapeHTML(season.name)} Season</strong><span>${season.winner ? `SEASON ${String(season.number).padStart(2, "0")}` : "UP NEXT"}</span></td><td>${new Date(`${season.start_date}T00:00:00`).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })}</td>${[season.winner, season.second, season.third].map((driver, index) => driver ? `<td><span class="eternal-driver" style="--driver-color:${driver.color}"><i></i><b>${["🏆", "🥈", "🥉"][index]} ${escapeHTML(driver.name)}</b><small>№ ${driver.number}</small></span></td>` : '<td class="eternal-tbd">—</td>').join("")}</tr>`).join("")}</tbody></table></div>` : emptyState("No names in the book—yet.", "Completed seasons will appear here after the championship race.");
    return;
  }
  $("#eternals-content").innerHTML = eternals.drivers.length ? `<div class="eternals-table-wrap"><div class="eternals-table-note">SCORE = PODIUM 7 / 5 / 3 · CHAMPIONSHIP FINISH 2 · FINALIST FINISH 1</div><table class="eternals-table drivers-record"><thead><tr><th>DRIVER NAME</th><th>NUMBER</th><th>CHAMPIONSHIP WINS</th><th>CHAMPIONSHIP APPEARANCES</th><th>FINALIST APPEARANCES</th><th>ETERNAL SCORE</th></tr></thead><tbody>${eternals.drivers.map((driver, index) => `<tr><td><span class="eternal-driver" style="--driver-color:${driver.color}"><i></i><b>${index < 3 ? `${["🏆", "🥈", "🥉"][index]} ` : ""}${escapeHTML(driver.name)}</b></span></td><td>№ ${driver.number}</td><td>${driver.championship_wins}</td><td>${driver.championship_appearances}</td><td>${driver.finalist_appearances}</td><td class="eternal-score">${driver.eternal_score}</td></tr>`).join("")}</tbody></table></div>` : emptyState("No immortals—yet.", "A driver appears here after earning their first Eternal Score point.");
}

function moveTowerStack(stackId, area, index) {
  if (!inventoryDraft) return;
  const source = inventoryDraft.find(stack => stack.id === stackId);
  if (!source) return;
  const destination = inventoryDraft.filter(stack => stack.active === (area === "active"))[index];
  const targetActive = area === "active";
  if (destination && destination.id !== source.id) destination.active = source.active;
  source.active = targetActive;
  renderTower();
}

async function towerRequest(path, payload, message) {
  const status = $("#tower-message");
  if (status) status.textContent = "Contacting the Tower…";
  try {
    const response = await fetch(path, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "The Tower is closed for the moment");
    currentUser = data.user;
    inventoryDraft = copyInventory(currentUser.inventory);
    renderTower();
    const updatedStatus = $("#tower-message");
    if (updatedStatus) updatedStatus.textContent = message;
    if (page === "fan") renderFanPage();
  } catch (cause) {
    if (status) status.textContent = cause instanceof TypeError ? "Could not reach the Tower." : cause.message;
  }
}

async function openFavoritePicker() {
  if (!currentUser) return;
  if (!drivers.length) await loadDrivers();
  const list = $("#favorite-driver-list");
  list.innerHTML = drivers.length ? [...drivers].sort((a, b) => a.name.localeCompare(b.name)).map(driver => `<button class="favorite-choice ${isFavorite(driver.id) ? "selected" : ""}" data-favorite-driver="${driver.id}" style="--driver-color:${driver.color}" ${isFavorite(driver.id) ? "disabled" : ""}><span class="favorite-choice-number">${driver.number}</span><span><b>${escapeHTML(driver.name)}${favoriteHeart(driver.id)}</b><small>“${escapeHTML(driver.car.name)}”</small></span><i></i></button>`).join("") : '<div class="loading-state">Opening the paddock…</div>';
  $("#fan-error").hidden = true;
  const dialog = $("#fan-dialog");
  if (!dialog.open) dialog.showModal();
}

async function setFavoriteDriver(driverId, button) {
  const error = $("#fan-error");
  error.hidden = true;
  button.disabled = true;
  try {
    const response = await fetch("/api/fan/favorite", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ driver_id: driverId }) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Unable to save your favorite driver");
    currentUser = data.user;
    favoriteChangeAvailableAt = data.favorite_change_available_at;
    $("#fan-dialog").close();
    renderFanPage();
    if (drivers.length) renderDrivers();
    if (state) {
      $("#next-race-grid").dataset.signature = "";
      renderLive();
    }
  } catch (cause) {
    error.textContent = cause instanceof TypeError ? "Could not reach the account server." : cause.message;
    error.hidden = false;
    button.disabled = false;
  }
}

async function loadHistory() {
  const request = ++historyRequest;
  const params = new URLSearchParams({ page: historyPage, q: $("#history-search").value.trim(), city: $("#history-city").value });
  try {
    const data = await api(`/api/history?${params}`);
    if (request !== historyRequest) return;
    historyPage = data.page;
    const filtered = params.get("q") || params.get("city");
    $("#history-list").innerHTML = data.races.length ? `<table class="history-table"><thead><tr><th>RACE / START TIME</th><th>LOCATION</th><th>WINNER / MACHINE</th><th>WINNING TIME</th><th><span class="micro">FILE</span></th></tr></thead><tbody>${data.races.map(race => {
      const winner = race.standings[0];
      return `<tr><td><span class="history-name">${escapeHTML(race.name)}</span><span class="history-sub">${escapeHTML(dateLabel(race.start))} · WAVE ${String(race.wave).padStart(3, "0")}</span></td><td>${escapeHTML(race.city.name)}<span class="history-sub">${(race.city.length * 10).toFixed(1)} KM / 10 LAPS</span></td><td><span class="history-winner" style="--driver-color:${winner.color}"><i class="driver-color"></i>${escapeHTML(winner.name)}</span><span class="history-sub">${escapeHTML(winner.car)}</span></td><td class="history-time">${preciseTime(winner.finish_time)}</td><td><button data-race="${race.id}" aria-label="View results for ${escapeHTML(race.name)}">↗</button></td></tr>`;
    }).join("")}</tbody></table>` : emptyState(filtered ? "No races on this frequency." : "The ink is still dry.", filtered ? "Try another race name or location." : 'The first results will arrive when all ten drivers finish. Until then, <a href="#live">meet us at the circuit ↗</a>');
    $("#pagination").innerHTML = data.total ? `<button data-history-page="${data.page - 1}" ${data.page === 1 ? "disabled" : ""}>← Previous</button><span>${data.page} / ${data.pages} · ${data.total} RACES</span><button data-history-page="${data.page + 1}" ${data.page === data.pages ? "disabled" : ""}>Next →</button>` : "";
  } catch (_) {
    if (request === historyRequest) {
      $("#history-list").innerHTML = emptyState("The archives are out of range.", 'The timing tower is unavailable. <button class="text-button" data-retry-history>Try again ↗</button>');
      $("#pagination").innerHTML = "";
    }
  }
}

async function openRace(id) {
  const request = ++dialogRequest;
  dialogRaceId = id;
  $("#dialog-eyebrow").textContent = "RACE CONTROL / TIMING & TELEMETRY";
  $("#dialog-content").innerHTML = '<h2 id="dialog-title" class="dialog-title">Tuning in…</h2>';
  showDialog();
  try {
    const race = state?.races.find(item => item.id === id) || await api(`/api/races/${id}`);
    if (request !== dialogRequest) return;
    renderRaceDetail(race);
  } catch (_) {
    if (request === dialogRequest) $("#dialog-content").innerHTML = '<h2 id="dialog-title" class="dialog-title">Signal lost.</h2><p class="dialog-subtitle">Close this file and try again when the timing tower reconnects.</p>';
  }
}

function renderRaceDetail(race) {
  $("#dialog-content").innerHTML = `<h2 id="dialog-title" class="dialog-title">${escapeHTML(race.name)}</h2><p class="dialog-subtitle">${escapeHTML(race.city.name)}, ${escapeHTML(race.city.country)} · ${escapeHTML(race.city.circuit)} · Wave ${race.wave}</p>
    <div class="race-detail-grid"><div>${trackMarkup(race, true)}${standingsMarkup(race, true)}<div class="detail-weather"></div></div><section class="event-log"><h3>↳ FROM THE TIMING TOWER</h3><div class="event-log-body"></div></section></div>`;
  updateRaceDetail(race);
}

function updateRaceDetail(race) {
  const root = $("#dialog-content");
  if (!$(".track-svg", root)) return;
  updateTrack(root, race);
  $(".standings-list", root).innerHTML = standingsRows(race, true);
  const log = $(".event-log-body", root);
  const signature = JSON.stringify(race.events);
  if (log.dataset.signature !== signature) {
    log.innerHTML = race.events.map(event => `<div class="event ${event.type}"><time>${fmtTime(event.at)}</time><p>${escapeHTML(event.text)}</p></div>`).join("");
    log.dataset.signature = signature;
  }
  $(".detail-weather", root).textContent = `${race.status === "live" ? "LIVE" : "FINAL"} / ${fmtTime(race.elapsed)} ELAPSED · ${race.weather} · ${race.city.length * 10} km total. Gaps in seconds.`;
}

function showDialog() {
  const dialog = $("#detail-dialog");
  if (!dialog.open) dialog.showModal();
  document.body.style.overflow = "hidden";
}

function changePage() {
  const requested = location.hash.slice(1) || "live";
  page = ["live", "drivers", "tracks", "history", "fan", "tower", "eternals"].includes(requested) && (!["fan", "tower", "eternals"].includes(requested) || currentUser) ? requested : "live";
  $$(".page").forEach(section => { section.hidden = section.id !== `page-${page}`; });
  $$("nav [data-page]").forEach(link => {
    const active = link.dataset.page === page;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  $$(".nav-menu").forEach(menu => menu.classList.toggle("active", !!$("[data-page].active", menu)));
  document.title = `${{ live: "Races", drivers: "Drivers", tracks: "Tracks", history: "Current Season", fan: "You", tower: "The Tower", eternals: "The Eternals" }[page]} — VASTCAR RACING`;
  if (page === "drivers") {
    if (drivers.length) renderDrivers();
    else $("#driver-grid").innerHTML = '<div class="loading-state">Opening the paddock…</div>';
    loadDrivers();
  }
  if (page === "history") loadHistory();
  if (page === "tracks") {
    if (tracks.length) renderTracks();
    else $("#track-grid").innerHTML = '<div class="loading-state">Mapping the circuit…</div>';
    loadTracks();
  }
  if (page === "fan") {
    renderFanPage();
    loadDrivers();
  }
  if (page === "tower") renderTower();
  if (page === "eternals") {
    if (eternals) renderEternals();
    else $("#eternals-content").innerHTML = '<div class="loading-state">Opening the eternal record…</div>';
    loadEternals();
  }
  window.scrollTo({ top: 0, behavior: "instant" });
}

async function poll() {
  try {
    const previous = state;
    state = await api("/api/state");
    const nextFanActivity = state.fan_activity || [];
    const activityChanged = JSON.stringify(nextFanActivity) !== JSON.stringify(fanActivity);
    fanActivity = nextFanActivity;
    serverOffset = state.now - Date.now() / 1000;
    $("#connection").hidden = true;
    $("#server-status").innerHTML = '<i class="status-dot"></i> CIRCUIT ONLINE';
    renderLive();
    if (activityChanged && page === "fan") renderFanPage();
    if (dialogRaceId !== null && $("#detail-dialog").open) {
      const race = state.races.find(item => item.id === dialogRaceId);
      if (race) updateRaceDetail(race);
      else if (previous?.races.some(item => item.id === dialogRaceId && item.status === "live")) {
        const id = dialogRaceId;
        const result = await api(`/api/races/${id}`);
        if (dialogRaceId === id) updateRaceDetail(result);
      }
    }
    if (completedCount !== state.completed_races || !drivers.length) {
      completedCount = state.completed_races;
      await loadDrivers();
      if (currentUser) await loadAccount();
      if (page === "history") loadHistory();
      if (page === "eternals") loadEternals();
    }
  } catch (_) {
    $("#connection").hidden = false;
    $("#server-status").textContent = "SIGNAL LOST / RETRYING";
    if (!state) $("#race-grid").innerHTML = emptyState("Waiting for the green light.", "Connecting to the server. The circuit will appear here as soon as the signal returns.");
  } finally { setTimeout(poll, 1000); }
}

async function placeBet(button) {
  if (!currentUser) {
    showAuth("login");
    return;
  }
  const status = $("#betting-status");
  button.disabled = true;
  status.textContent = "Placing bet…";
  try {
    const response = await fetch("/api/bets", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ season: Number(button.dataset.season), race_number: Number(button.dataset.raceNumber), driver_id: Number(button.dataset.driverId) }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Unable to place that bet");
    currentUser = data.user;
    state.bets = [...(state.bets || []).filter(bet => !(bet.season === data.bet.season && bet.race_number === data.bet.race_number && bet.driver_id === data.bet.driver_id)), data.bet];
    $("#next-race-grid").dataset.signature = "";
    renderLive();
    if (page === "fan") renderFanPage();
    if (page === "tower") renderTower();
    status.textContent = `Bet placed for ${data.cost} Coin. Bets cannot be withdrawn.`;
  } catch (cause) {
    status.textContent = cause instanceof TypeError ? "Could not reach the betting window." : cause.message;
    button.disabled = false;
  }
}

document.addEventListener("click", event => {
  const favorite = event.target.closest("[data-favorite-driver]");
  const openFavorite = event.target.closest("[data-open-favorite]");
  const driver = event.target.closest("[data-driver]");
  const race = event.target.closest("[data-race]");
  const track = event.target.closest("[data-track]");
  const pagination = event.target.closest("[data-history-page]");
  const buy = event.target.closest("[data-buy-item]");
  const sell = event.target.closest("[data-sell-stack]");
  const saveInventory = event.target.closest("[data-save-inventory]");
  const fanMove = event.target.closest("[data-fan-move]");
  const bet = event.target.closest("[data-place-bet]");
  const eternalsTab = event.target.closest("[data-eternals-view]");
  if (eternalsTab) {
    eternalsView = eternalsTab.dataset.eternalsView;
    renderEternals();
  }
  if (bet && !bet.disabled) placeBet(bet);
  if (driver) openDriver(Number(driver.dataset.driver));
  if (openFavorite) openFavoritePicker();
  if (favorite && !favorite.disabled) setFavoriteDriver(Number(favorite.dataset.favoriteDriver), favorite);
  if (race) openRace(Number(race.dataset.race));
  else if (track) openTrack(track.dataset.track);
  if (pagination && !pagination.disabled) { historyPage = Number(pagination.dataset.historyPage); loadHistory(); }
  if (buy && !buy.disabled) towerRequest("/api/items/buy", { item: buy.dataset.buyItem }, "Item added to your kit.");
  if (sell && !sell.disabled) towerRequest("/api/items/sell", { stack_id: sell.dataset.sellStack }, "One item sold for 60% value.");
  if (saveInventory) towerRequest("/api/items/inventory", { inventory: inventoryDraft }, "Equipment saved.");
  if (fanMove) moveFanInventoryStack(fanMove.dataset.fanMove, fanMove.dataset.fanTarget);
  if (event.target.closest("[data-retry-history]")) loadHistory();
});
$$('.nav-menu').forEach(menu => {
  menu.addEventListener('pointerleave', () => {
    menu.removeAttribute('open');
  });
});
document.addEventListener("dragstart", event => {
  const fanStack = event.target.closest("[data-fan-stack-id]");
  if (fanStack) {
    draggedFanStackId = fanStack.dataset.fanStackId;
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", draggedFanStackId);
    fanStack.classList.add("dragging");
    return;
  }
  const stack = event.target.closest("[data-stack-id]");
  if (!stack) return;
  draggedStackId = stack.dataset.stackId;
  event.dataTransfer.effectAllowed = "move";
  event.dataTransfer.setData("text/plain", draggedStackId);
  stack.classList.add("dragging");
});
document.addEventListener("dragend", event => {
  const fanStack = event.target.closest("[data-fan-stack-id]");
  if (fanStack) {
    fanStack.classList.remove("dragging");
    draggedFanStackId = null;
    return;
  }
  const stack = event.target.closest("[data-stack-id]");
  if (stack) stack.classList.remove("dragging");
  draggedStackId = null;
});
document.addEventListener("dragover", event => {
  if (event.target.closest("[data-fan-drop-area]") && draggedFanStackId) {
    event.preventDefault();
    return;
  }
  if (event.target.closest("[data-drop-area]") && draggedStackId) event.preventDefault();
});
document.addEventListener("drop", event => {
  const fanTarget = event.target.closest("[data-fan-drop-area]");
  if (fanTarget && draggedFanStackId) {
    event.preventDefault();
    swapFanInventoryStack(draggedFanStackId, fanTarget.dataset.fanDropArea, Number(fanTarget.dataset.fanDropIndex));
    draggedFanStackId = null;
    return;
  }
  const target = event.target.closest("[data-drop-area]");
  if (!target || !draggedStackId) return;
  event.preventDefault();
  moveTowerStack(draggedStackId, target.dataset.dropArea, Number(target.dataset.dropIndex));
  draggedStackId = null;
});
$(".close-button").addEventListener("click", () => $("#detail-dialog").close());
$("#detail-dialog").addEventListener("click", event => {
  if (event.target === event.currentTarget) {
    const bounds = event.currentTarget.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) event.currentTarget.close();
  }
});
$("#detail-dialog").addEventListener("close", () => {
  document.body.style.overflow = "";
  dialogRaceId = null;
  dialogRequest++;
});
$("#driver-search").addEventListener("input", renderDrivers);
$("#driver-sort").addEventListener("change", renderDrivers);
$("#driver-season").addEventListener("change", event => { selectedDriverSeason = event.target.value; loadDrivers(); });
$("#track-search").addEventListener("input", renderTracks);
$("#track-sort").addEventListener("change", renderTracks);
$("#history-search").addEventListener("input", () => {
  historyPage = 1;
  historyRequest++;
  clearTimeout(historyTimer);
  historyTimer = setTimeout(loadHistory, 200);
});
$("#history-city").addEventListener("change", () => { historyPage = 1; loadHistory(); });
$("#login").addEventListener("click", () => showAuth("login"));
$("#register").addEventListener("click", () => showAuth("register"));
$("#auth-close").addEventListener("click", () => $("#auth-dialog").close());
$("#auth-switch").addEventListener("click", () => showAuth(authMode === "login" ? "register" : "login"));
$("#auth-form").addEventListener("submit", submitAuth);
$("#fan-close").addEventListener("click", () => $("#fan-dialog").close());
$("#logout").addEventListener("click", async () => {
  await fetch("/auth/logout", { method: "POST", credentials: "same-origin" });
  currentUser = null;
  await loadAccount();
});
window.addEventListener("hashchange", changePage);
changePage();
loadAccount();
poll();
setInterval(updateCountdown, 250);
