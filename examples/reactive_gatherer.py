"""M1 reactive resident: gather several resources, carry a full рюкзак home to auto-bank.

The point of M1 is a *reactive* agent — one action per tick, decided from current state
(observe -> decide -> act -> wait):
  * if the рюкзак is full  -> head HOME (0,0); the server auto-banks the рюкзак the moment the
    resident steps onto its home tile (no manual deposit — the `move` result carries `banked`);
  * otherwise target the resource it owns LESS of (balances wood vs stone) and head to the
    nearest node of that type. Wanting the scarcer resource is what makes the agent actually
    choose a route between different nodes — the behaviour M1 teaches.
Each tick it takes a single directional step toward its target, and gathers only while standing
ON a node tile (D-069 — no adjacency; move onto the tree/rock first). Diagonal steps are allowed,
so the route can cut corners. There is no storehouse tile anymore: coming home *is* the deposit.

Run a server first, then:

    uv run python client/examples/reactive_gatherer.py            # localhost:8000
    uv run python client/examples/reactive_gatherer.py http://host:8000

Tip: to watch the full рюкзак->дом cycle quickly, start the server with a small cap and
no cooldown, e.g.  INVENTORY_CAP=6 COOLDOWN_SECONDS=0 uvicorn server.app:app
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from cognopolis_client import Client, GameError  # noqa: E402

ROUNDS = 40
HOME = (0, 0)  # the resident's home tile — stepping onto it auto-banks the рюкзак
RESOURCE_NODE = {"wood": "tree", "stone": "rock"}  # resource -> the tile that yields it


def _nearest(ch, tiles, content):
    here = (ch["x"], ch["y"])
    nodes = [t for t in tiles if t["content"] == content]
    return min(nodes, key=lambda t: abs(t["x"] - here[0]) + abs(t["y"] - here[1]))


def _scarcer_resource(ch: dict) -> str:
    """The resource the resident owns less of (carried + banked) — its next target."""
    owned = {r: ch["inventory"].get(r, 0) + ch["stored"].get(r, 0) for r in RESOURCE_NODE}
    return min(RESOURCE_NODE, key=lambda r: owned[r])


# (dx, dy) with each in {-1,0,1} -> the compass direction to send (D-069). (0,0) has no step.
_STEP_DIR = {
    (0, -1): "north", (0, 1): "south", (1, 0): "east", (-1, 0): "west",
    (1, -1): "northeast", (-1, -1): "northwest", (1, 1): "southeast", (-1, 1): "southwest",
}


def _on_tile(ch, tx, ty) -> bool:
    return ch["x"] == tx and ch["y"] == ty


def _dir_toward(ch, tx, ty) -> str:
    """One directional step toward (tx, ty) — diagonals let it approach on both axes at once."""
    sx = (tx > ch["x"]) - (tx < ch["x"])
    sy = (ty > ch["y"]) - (ty < ch["y"])
    return _STEP_DIR[(sx, sy)]


def play(base_url: str) -> None:
    import uuid
    with Client(base_url) as c:
        c.register(f"demo-{uuid.uuid4().hex[:10]}", "demo-password")  # throwaway account for the demo
        world = c.get_map()
        for _ in range(ROUNDS):
            ch = c.get_character()
            full = sum(ch["inventory"].values()) >= ch["inventory_cap"]

            if full:                                  # decide: target = дом (0,0)
                want = None
                tx, ty, reason = HOME[0], HOME[1], "рюкзак полон — иду домой разгрузиться"
            else:                                     # decide: target = scarcer resource's node
                want = _scarcer_resource(ch)
                node = _nearest(ch, world["tiles"], RESOURCE_NODE[want])
                tx, ty, reason = node["x"], node["y"], f"{want} в дефиците — иду к {node['content']}"

            if not _on_tile(ch, tx, ty):              # act: one directional step toward the target
                result = c.move_dir(_dir_toward(ch, tx, ty), reason=reason)["result"]
                if result.get("banked"):              # a step home lands on (0,0) and auto-banks
                    print(f"  дом: авто-разгрузка {result['banked']}")
            elif want is not None:                    # act: standing ON the node -> добыча (D-069)
                try:
                    got = c.gather(resource=want, reason=f"добываю {want}")["result"]["gathered"]
                    print(f"  +{got}  (рюкзак {sum(ch['inventory'].values()) + 1}/{ch['inventory_cap']})")
                except GameError as e:
                    print("  gather blocked:", e.code)
            else:                                     # home but склад full — idle a tick, don't spin
                c.rest(reason="дома, склад полон — жду")
            c.wait_cooldown()

        ch = c.get_character()
        print("skills:", {k: v["level"] for k, v in ch["skills"].items()},
              "| carried:", ch["inventory"], "| stored:", ch["stored"])
        print("DONE")


if __name__ == "__main__":
    play(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000")
