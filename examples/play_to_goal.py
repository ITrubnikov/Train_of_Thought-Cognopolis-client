"""M0 scripted resident: the canonical observe → decide → act → wait loop.

Goal (DoD): gather >= GOAL_WOOD AND defeat the goblin without dying.
Run a server first (e.g. `./run.sh` or the SQLite toggle), then:

    uv run python client/examples/play_to_goal.py            # localhost:8000
    uv run python client/examples/play_to_goal.py http://host:8000
"""
import pathlib
import sys
import time

# Make the in-repo client importable when running this file directly (no install needed).
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from cognopolis_client import Client  # noqa: E402

GOAL_WOOD = 5
LOW_HP = 6   # wait for passive regen below this before fighting (С8: rest is gone)
SAFE_HP = 12  # regen back up to this before re-engaging


def _tile(world: dict, content: str) -> tuple[int, int]:
    t = next(t for t in world["tiles"] if t["content"] == content)
    return t["x"], t["y"]


def _wait_regen(c: Client, until_hp: int) -> None:
    """Wait out the passive regen (С8, [[Регенерация hp]]): hp restores automatically on the
    server tick — no action needed. character['regen'] carries the exact cadence (hp_per_event +
    the period for the CURRENT tile, ×3 faster at home), so the agent sleeps precisely instead of
    hammering the API. (The Храм — c.heal_at_temple() — is the instant paid alternative.)"""
    while True:
        ch = c.get_character()
        target = min(until_hp, ch["max_hp"])
        if ch["hp"] >= target:
            return
        rg = ch["regen"]
        period = rg["village_period_s"] if rg["in_village"] else rg["field_period_s"]
        events = -(-(target - ch["hp"]) // rg["hp_per_event"])   # ceil
        time.sleep(events * period + 1.0)   # +1s absorbs the tick phase; the loop re-checks


def _step_toward(c: Client, char: dict, tx: int, ty: int) -> None:
    """One orthogonal step toward (tx, ty) on the obstacle-free 5x5 grid."""
    x, y = char["x"], char["y"]
    if x != tx:
        c.move(x + (1 if tx > x else -1), y)
    elif y != ty:
        c.move(x, y + (1 if ty > y else -1))


def play(base_url: str) -> None:
    import uuid
    with Client(base_url) as c:
        c.register(f"demo-{uuid.uuid4().hex[:10]}", "demo-password")  # throwaway account for the demo
        world = c.get_map()
        tree = _tile(world, "tree")
        goblin = _tile(world, "goblin")  # the wolf at (6,5) is tougher — dying loses your backpack; left as an M2 exercise

        # --- gather phase: stock up safely ---
        while c.get_character()["inventory"].get("wood", 0) < GOAL_WOOD:
            ch = c.get_character()
            if (ch["x"], ch["y"]) == tree:
                c.gather()
            else:
                _step_toward(c, ch, *tree)
            c.wait_cooldown()
        print(f"gathered {GOAL_WOOD} wood ✓")

        # --- fight phase: risk/reward, regen-before-fight (M2: dying loses the backpack + sends you home) ---
        while any(e["kind"] == "goblin" and e["alive"] for e in c.get_map()["enemies"]):
            ch = c.get_character()
            if ch["hp"] <= LOW_HP:
                _wait_regen(c, SAFE_HP)   # С8: healing is passive — wait it out (no rest action)
            elif (ch["x"], ch["y"]) == goblin:
                log = c.fight()["result"]["combat_log"]
                print(f"  fight: {log['outcome']} in {len(log['rounds'])} round(s)")
            else:
                _step_toward(c, ch, *goblin)
            c.wait_cooldown()

        ch = c.get_character()
        print(f"goblin defeated ✓  hp={ch['hp']} xp={ch['xp']} "
              f"wood={ch['inventory'].get('wood', 0)} loot={ch['inventory'].get('goblin_ear', 0)}")
        print("GOAL REACHED ✓")


if __name__ == "__main__":
    play(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000")
