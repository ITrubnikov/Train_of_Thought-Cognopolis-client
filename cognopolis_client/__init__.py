"""Cognopolis official Python client (M0).

The ergonomic connection contract for driving a Resident over the REST API — the same
surface an agent/script uses. Sync on purpose: teaching notebooks stay simple (no async).

    from cognopolis_client import Client

    # In a lesson/notebook you pass the game-token you copied from your account:
    with Client("http://localhost:8000", token=MY_GAME_TOKEN) as c:
        c.move_dir("south"); c.wait_cooldown()   # step one tile; onto a tree/rock to gather (D-069)
        c.gather();          c.wait_cooldown()

    # Scripts can also create/sign into an account programmatically:
    #   with Client("http://localhost:8000") as c:
    #       c.register("my-name", "my-password")  # or c.login(...)
"""
from .client import Client, GameError

__all__ = ["Client", "GameError"]
__version__ = "0.0.1"
