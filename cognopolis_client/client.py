"""Sync client over the Cognopolis REST API.

Each action returns the server's ``{result, cooldown, character}`` dict and remembers the
cooldown so ``wait_cooldown()`` can block the right amount. Rule violations from the server
(``{"error": {"code", "message"}}``) are raised as :class:`GameError` with a stable ``.code``.
"""
import time

import httpx


class GameError(Exception):
    """A server-side rule violation (or transport problem). Carries the canon error code."""

    def __init__(self, code: str, message: str, status_code: int):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status_code = status_code


class Client:
    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        token: str | None = None,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self._http = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)
        self.token = token
        self.last_cooldown: float = 0.0

    # ---- lifecycle ----
    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    # ---- account / auth ----
    # Anonymous minting was removed (D-042). In lessons/notebooks you normally pass a game-token
    # you copied from your resident (M6/D-052: one под-токен = one resident): Client(token="...").
    # register()/login() are here for scripts that want to create or sign into an account
    # programmatically; they also keep the session cookie, which hire()/rotate need.
    def register(self, username: str, password: str) -> dict:
        """Create an account (username + password) + starter resident; store the first resident's
        под-токен and return the payload. Returns {user, characters: [{…, token}]}."""
        data = self._request("POST", "/auth/register", json={"username": username, "password": password})
        self.token = data["characters"][0]["token"]
        return data

    def login(self, username: str, password: str) -> dict:
        """Log into an existing account; store the FIRST resident's под-токен (switch residents by
        assigning `client.token` yourself). Returns {user, characters: [{…, token}]}."""
        data = self._request("POST", "/auth/login", json={"username": username, "password": password})
        self.token = data["characters"][0]["token"]
        return data

    # ---- roster / hire (M6 срез B, D-052) ----
    def get_roster(self) -> dict:
        """Read the settlement roster: {characters: […]} — every resident of your account with
        abilities (skills, tools) and its current поручение. No tokens here."""
        return self._request("GET", "/account/characters", auth=True)

    def hire(self, name: str | None = None, reason: str | None = None) -> dict:
        """Нанять жителя (player meta-action; needs a browser-style SESSION — call login() first).
        The roster cap is the town hall level; the cost is spent from the shared склад.
        Returns {character: {…, token}} — the new resident with its под-токен."""
        return self._session_request("POST", "/account/characters",
                                     json={"name": name, "reason": reason})

    def rotate_character_token(self, character_id: str) -> dict:
        """Mint a new под-токен for MY resident (session-auth; call login() first). Returns {token}.
        The old token stops working immediately — update `client.token` if you rotated your own."""
        return self._session_request("POST", f"/characters/{character_id}/rotate-token")

    def appoint_elder(self, character_id: str | None) -> dict:
        """Назначить старосту (player meta-action, session-auth — call login() first; срез C/D-053).
        The staроста's под-токен may write EVERY roster member's поручение (set_assignment on
        siblings). Pass None to unset; appointing another resident replaces the previous one.
        Returns {elder: character_id | None}."""
        return self._session_request("PUT", "/account/elder", json={"character_id": character_id})

    def set_elder_managed(self, character_id: str, managed: bool) -> dict:
        """Тумблер «управляется старостой» (player meta-action, session-auth — call login() first;
        срез D/D-054). managed=False takes MY resident away from the staроста's cross-roster
        поручение writes (the elder gets `elder_managed_off`); True hands it back (default).
        Self-writes by the resident's own token are never blocked. Returns {elder_managed: bool}."""
        return self._session_request("PUT", f"/characters/{character_id}/elder-managed",
                                     json={"managed": managed})

    def get_character(self) -> dict:
        return self._request("GET", "/character", auth=True)

    def get_map(self) -> dict:
        return self._request("GET", "/map")

    # ---- discovery catalogs (M4 — LLM tool-use, D-055; public, no token) ----
    def get_recipes(self) -> dict:
        """Discover every craftable recipe (the recipe book): {recipes: [{recipe, name_ru, inputs,
        building, building_level_req, skill, xp}]}. Static reference — no token needed."""
        return self._request("GET", "/recipes")

    def get_buildings(self) -> dict:
        """Discover the building CATALOG / tech tree: {buildings: [{kind, name_ru, buildable, implicit,
        build_cost, upgrade_base, max_level, town_hall_req, capacity_per_level}]}. This is what CAN be
        built — NOT your owned buildings (those are in get_character()['buildings']). No token needed."""
        return self._request("GET", "/buildings")

    def get_items(self) -> dict:
        """Discover the item CATALOG: {items: [{item, name_ru, category, source}]}. No token needed."""
        return self._request("GET", "/items")

    def get_enemies(self) -> dict:
        """Discover the enemy CATALOG / бестиарий (С1): {enemies: [{kind, name_ru, max_hp, atk_min,
        atk_max, armor, xp, loot, bounty_gross, bounty_net, respawn_s, danger_at_base, target_build}],
        resolve}. `danger_at_base` is the verdict for a base-stat resident — "safe" (goblin) |
        "gear_required" (wolf → target_build names the gear) | "wall" (ogre — unbeatable in MVP);
        `resolve` carries the exact hit formulas (armor cuts every hit to max(1, roll − armor)) so an
        agent re-derives the verdict from its own stats. No token needed (static reference)."""
        return self._request("GET", "/enemies")

    def get_bounty(self) -> dict:
        """Discover the Торговец's trophy buy-prices (M5): {trophies: [{item, name_ru, unit_price}],
        burn_pct}. `unit_price` is GROSS gold/unit; net = gross − round-half-up(gross×burn_pct/100).
        Only trophies are buyable. No token needed (static reference)."""
        return self._request("GET", "/bounty")

    def get_treasury(self) -> dict:
        """Read your settlement's shared казна (M5): {gold}. Account-scoped (every resident reads the
        same one); also mirrored on get_character()['gold']."""
        return self._request("GET", "/account/treasury", auth=True)

    def get_shop(self) -> dict:
        """Discover the Торговец-Лавка's sell board (M5 Срез 2a): {items: [{item, name_ru, unit_price}]}
        — the finished tools it sells for gold. Buy them with buy_from_shop(). No token (static reference)."""
        return self._request("GET", "/shop")

    def get_stats(self) -> dict:
        """Discover the боевой лист catalog (D-070, prices retired at С7): {stats: [{key, name_ru,
        effect, formula, saturation}], base, progression, death, gear}. Machine-readable stat
        effect formulas — compute atk/max_hp/cooldown locally from your columns. Stats are NOT
        purchasable (С7): the only way they grow is `progression` (С6), the AUTO channel — the
        xp→level curve (level = min(6, 1 + isqrt(xp // 50)), a precomputed thresholds table,
        cap L6) and the fixed payout pattern (even level → strength, odd → vitality: +1 column
        point per level-up, automatic); your live values are get_character()'s
        `level`/`xp_next`/`stats`. С4 adds `death` (machine-readable death rules per carry zone)
        and `gear` (gear catalog + wear/repair/upkeep math — wear_per_fight, death_penalty_pct,
        repair_full, upkeep_per_fight). No token needed (static reference)."""
        return self._request("GET", "/stats")

    def get_temple(self) -> dict:
        """Discover the Храм's heal rate (M5 Срез 2a): {heal_rate} gold per hp. Heal to full with
        heal_at_temple() — cost = (max_hp − hp) × heal_rate. No token (static reference)."""
        return self._request("GET", "/temple")

    # ---- actions ----
    # 8 compass directions the resident can step (D-069) — matches the server's directional endpoints.
    DIRECTIONS = ("north", "south", "east", "west",
                  "northeast", "northwest", "southeast", "southwest")

    def move_dir(self, direction: str, reason: str | None = None) -> dict:
        """Step ONE tile in a fixed `direction` (D-069): one of DIRECTIONS (north/south/east/west or a
        diagonal). No coordinates — the server steps you one tile that way, so an agent can't send an
        invalid target. Stepping off the map edge raises GameError `at_map_edge`. Landing on home (0,0)
        auto-banks the рюкзак (result carries `banked`)."""
        return self._action(f"/actions/move/{direction}", json={"reason": reason})

    def move(self, x: int, y: int, reason: str | None = None) -> dict:
        """DEPRECATED (D-069): coordinate move — kept so older lessons keep running. Prefer move_dir()."""
        return self._action("/actions/move", json={"x": x, "y": y, "reason": reason})

    def gather(self, resource: str | None = None, reason: str | None = None) -> dict:
        return self._action("/actions/gather", json={"resource": resource, "reason": reason})

    def fight(self, reason: str | None = None) -> dict:
        return self._action("/actions/fight", json={"reason": reason})

    def fight_preview(self) -> dict:
        """Dry-run of your NEXT fight on this tile (С2) — a pure read: no cooldown, zero side
        effects, the fight seed does not advance, so ``result["combat_log"]`` is round-for-round
        what the next real ``fight()`` here returns (until your hp/stats/gear or the enemy
        change). Result carries ``{"preview": True, "combat_log": {...}}`` in fight's exact shape
        plus the С4 projections: ``projected_durability`` (weapon durability after this fight;
        None = no weapon) and ``on_death`` ``{weapon_dur_after, backpack_lost}`` — the price of a
        death here, computed without writing. Errors: ``no_enemy_here`` (404) /
        ``rate_limited`` (429)."""
        return self._action("/actions/fight/preview")

    # rest() lived here (M0) and was removed at С8 ([[Регенерация hp]]): healing is PASSIVE now —
    # the server tick regenerates hp automatically (+hp_per_event every 9s in the field, every 3s
    # on the home tile; see get_stats()['regen'] and character['regen'] incl. seconds_to_full_here),
    # and heal_at_temple() heals instantly for gold. The old endpoint answers 410 Gone (error code
    # rest_gone) for scripts that still call it.

    def build(self, structure: str, reason: str | None = None) -> dict:
        """Build a new building on your per-account base (M3). `structure`: "sawmill" | "forge".
        Cost is spent from your stored bank (склад). Returns {result, cooldown, character}."""
        return self._action("/actions/build", json={"structure": structure, "reason": reason})

    def upgrade(self, structure: str, reason: str | None = None) -> dict:
        """Raise an existing building's level by 1 (M3), cost from your stored bank."""
        return self._action("/actions/upgrade", json={"structure": structure, "reason": reason})

    def craft(self, recipe: str, reason: str | None = None) -> dict:
        """Craft a recipe at its station (M3): "axe_handle" | "axe" | "pickaxe". Inputs spent from your
        stored bank; owning an axe/pickaxe boosts wood/stone gather. Returns {result, cooldown, character}."""
        return self._action("/actions/craft", json={"recipe": recipe, "reason": reason})

    def train(self, reason: str | None = None) -> dict:
        """Обучиться — raise your resident's tier by 1 (срез D/D-054; a BASE action, like craft).
        Needs the university at level ≥ the target tier (`training_locked` otherwise); costs
        15 wood + 15 stone × the target tier from the stored bank. The tier (0..4, батрак →
        вольный мастер) is a game stat the engine does not interpret. Returns
        {result: {trained_to}, cooldown, character}."""
        return self._action("/actions/train", json={"reason": reason})

    # train_stat() lived here (D-070) and was removed at С7 («Уровни и статы» §Миграция):
    # stats grow with the character level automatically (get_stats()['progression']); the old
    # endpoint answers 410 Gone (error code train_stat_gone) for scripts that still call it.

    def equip(self, item: str, reason: str | None = None) -> dict:
        """Экипировать вещь в её слот (С3): `item` — gear key (MVP: "spear"/копьё, +2/+3 atk while
        active). Consumes one from the рюкзак first, else from the shared склад; durability starts
        full. Occupied slot auto-swaps the old item into the рюкзак — only at FULL durability
        (GameError `gear_worn` otherwise). Equipment survives death (the рюкзак does not) and is
        never auto-banked. Returns {result: {equipped, slot, durability, durability_max, source,
        swapped_out}, cooldown, character} — see character['combat'] for the boosted card."""
        return self._action("/actions/equip", json={"item": item, "reason": reason})

    def unequip(self, slot: str = "weapon", reason: str | None = None) -> dict:
        """Снять вещь из слота в рюкзак (С3) — только при полной прочности (`gear_worn` иначе —
        почини сначала: repair()). Careful: an unequipped item rides in the рюкзак and burns on
        death. Returns {result: {unequipped, slot}, cooldown, character}."""
        return self._action("/actions/unequip", json={"slot": slot, "reason": reason})

    def repair(self, slot: str = "weapon", reason: str | None = None) -> dict:
        """Починить вещь в слоте до полной прочности (С4) — BASE action, needs the forge (кузница)
        ≥ 1 on your base. Price: ceil(missing × 4 / durability_max) wood + the same stone from the
        shared склад, all-or-nothing (spear after one death: 2 wood + 2 stone). The weapon wears
        −1/fight (+25% of max on death); at 0 it stays equipped but inert (active=false). Returns
        {result: {repaired, slot, durability, restored, cost}, cooldown, character}. Errors:
        `unknown_slot`/`slot_empty`/`nothing_to_repair`/`not_at_station`/`not_enough_resources`."""
        return self._action("/actions/repair", json={"slot": slot, "reason": reason})

    def sell_trophy(self, kind: str, qty: int = 1, reason: str | None = None) -> dict:
        """Sell trophies to the Торговец for gold (M5 faucet — D-061). `kind`: "goblin_ear" | "wolf_pelt" | "ogre_tusk"
        (see get_bounty()); `qty`: how many. Trophies are spent from the shared склад, the net gold
        (gross − 20% burn) lands in the shared казна. Only trophies are buyable (`not_a_trophy`
        otherwise). Returns {result: {sold, qty, unit_price, gross, burned, net, gold}, cooldown,
        character}."""
        return self._action("/actions/sell_trophy",
                            json={"kind": kind, "qty": qty, "reason": reason})

    def buy_from_shop(self, item: str, qty: int = 1, reason: str | None = None) -> dict:
        """Buy a tool from the Торговец-Лавка for gold (M5 Срез 2a). `item`: "axe_handle" | "axe" |
        "pickaxe" (see get_shop()). Gold is spent from the shared казна, the tool banks to the shared
        склад (serves every resident). Only SHOP_STOCK tools (`not_in_shop` otherwise). Returns
        {result: {bought, qty, unit_price, cost, gold}, cooldown, character}."""
        return self._action("/actions/buy_from_shop",
                            json={"item": item, "qty": qty, "reason": reason})

    def heal_at_temple(self, reason: str | None = None) -> dict:
        """Heal your resident to full hp at the Храм for gold (M5 Срез 2a): cost = (max_hp − hp) ×
        heal_rate from the shared казна. Instant, unlike the free-but-slow passive regen (С8 —
        see character['regen']). Returns {result: {healed, cost, hp, gold}, cooldown, character}."""
        return self._action("/actions/heal_at_temple", json={"reason": reason})

    def get_market(self, item: str) -> dict:
        """Public price signal for `item` on the Базар (M5 Срез 2b): best_bid/best_ask/spread/last_trade +
        recent_trades. No fair value — reason over these. No token needed."""
        return self._request("GET", f"/market?item={item}")

    def get_account_orders(self) -> dict:
        """Your market orders (M5 Срез 2b): open + recent, with remaining_qty/status."""
        return self._request("GET", "/account/orders", auth=True)

    def post_order(self, side: str, item: str, qty: int, unit_price: int, reason: str | None = None) -> dict:
        """Post a buy/sell limit order to the Базар (M5 Срез 2b). Escrows gold (buy) or items (sell); the
        tick matcher fills it at the maker price (5% tax burned). Only tradeable items (raw materials/tools).
        Returns {result: {order_id, side, item, qty, unit_price, remaining_qty, status, escrowed}, ...}."""
        return self._action("/actions/post_order",
                            json={"side": side, "item": item, "qty": qty, "unit_price": unit_price, "reason": reason})

    def cancel_order(self, order_id: str, reason: str | None = None) -> dict:
        """Cancel your open order (M5 Срез 2b) — refunds remaining escrow."""
        return self._action("/actions/cancel_order", json={"order_id": order_id, "reason": reason})

    def get_events(self, limit: int = 50) -> list:
        return self._request("GET", f"/events?limit={limit}", auth=True)

    def observe(self, events: int = 0) -> dict:
        """ONE aggregated snapshot for the decide-loop (хвост D-039; the granular reads remain
        the teaching surface — this replaces four GETs per loop on advanced tiers): {character,
        map, goals, assignment, events}. Every sub-object is identical to its granular read
        (get_character / get_map / get_settlement_goals / get_assignment / get_events), so
        existing parsing code keeps working. `events` is opt-in (0..200, newest first;
        default 0 → []). Pure read — no cooldown."""
        return self._request("GET", f"/observe?events={events}", auth=True)

    # ---- settlement goals (player -> agent bridge; read by agents, set in Town Hall) ----
    def get_settlement_goals(self) -> dict:
        """Read the settlement goal board: {goals, version}."""
        return self._request("GET", "/settlement/goals", auth=True)

    def set_settlement_goals(self, goals: list) -> dict:
        """Replace the whole goal board. Returns the new {goals, version}.
        Срез C (D-053): WRITING the board needs town hall level ≥ 3 (`town_hall_locked`
        otherwise — upgrade the town hall first); reading stays open at any level."""
        return self._request("PUT", "/settlement/goals", json={"goals": goals}, auth=True)

    # ---- character assignment (поручение — personal task for ONE resident; D-051) ----
    def get_assignment(self) -> dict:
        """Read your character's personal поручение: {assignment, version}. `assignment` is
        None (the resident is free) or one goal-shaped task + assigned_at/assigned_by."""
        return self._request("GET", "/assignment", auth=True)

    def set_assignment(self, character_id: str, spec: dict) -> dict:
        """Assign (replace) the character's single поручение slot. `spec` has the same shape
        as a goal: {"type": "gather"|"defeat"|"build", ...typed fields, "flavor"?}.
        Writer rule (D-052/D-053): `character_id` must be the resident this client's под-токен
        belongs to (self-write), OR the token must belong to the settlement's staроста
        (appoint_elder) — the elder may write EVERY roster slot. Anyone else gets 404.
        Returns {assignment}."""
        return self._request("PUT", f"/characters/{character_id}/assignment", json=spec, auth=True)

    def clear_assignment(self, character_id: str) -> dict:
        """Снять поручение — free the slot (idempotent; self or staроста, see set_assignment).
        Returns {assignment: None}."""
        return self._request("DELETE", f"/characters/{character_id}/assignment", auth=True)

    def wait_cooldown(self) -> None:
        """Block until the last action's cooldown elapses (observe→decide→act→**wait**)."""
        if self.last_cooldown > 0:
            time.sleep(self.last_cooldown)
        self.last_cooldown = 0.0

    # ---- internals ----
    def _action(self, path: str, json: dict | None = None) -> dict:
        data = self._request("POST", path, json=json, auth=True)
        self.last_cooldown = float(data.get("cooldown", 0.0))
        return data

    def _session_request(self, method: str, path: str, json: dict | None = None) -> dict:
        """A browser-style call: session cookie (kept by httpx after register()/login()) + the
        double-submit CSRF header (D-042). Used by the player meta-surface (hire, token rotation)."""
        csrf = self._http.cookies.get("cognopolis_csrf")
        if not csrf:
            raise GameError(
                "no_session",
                "No session — call register()/login() first (hire/rotate are player actions).", 0)
        try:
            r = self._http.request(method, path, json=json, headers={"X-CSRF-Token": csrf})
        except httpx.HTTPError as e:
            raise GameError("transport_error", str(e), 0) from e
        if r.status_code >= 400:
            try:
                err = r.json().get("error", {})
            except Exception:
                err = {}
            raise GameError(err.get("code", "http_error"), err.get("message", r.text), r.status_code)
        return r.json()

    def _request(self, method: str, path: str, json: dict | None = None, auth: bool = False) -> dict:
        headers = {}
        if auth:
            if not self.token:
                raise GameError(
                    "no_token",
                    "No game-token — pass Client(token=...) with your account's token, "
                    "or call register()/login() first.", 0)
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            r = self._http.request(method, path, json=json, headers=headers)
        except httpx.HTTPError as e:
            raise GameError("transport_error", str(e), 0) from e
        if r.status_code >= 400:
            try:
                err = r.json().get("error", {})
            except Exception:
                err = {}
            raise GameError(err.get("code", "http_error"), err.get("message", r.text), r.status_code)
        return r.json()
