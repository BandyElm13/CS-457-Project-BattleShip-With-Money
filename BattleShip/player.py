"""
player.py - Server-side Player record (concurrency_design.md 2.3).

Each connected client has one Player object in server memory holding
its name, money, stars, current Board and its network connection.
"""

from Board import Board
from protocal import BOARD_HEIGHT, BOARD_WIDTH


class Player:
    """A player's persistent game data (survives a disconnect/rejoin)."""

    def __init__(self, name, conn):
        self.name = name           # also used as playerId on the wire
        self.conn = conn           # protocal.FramedConnection or None
        self.money = 0
        self.stars = 0
        self.board = Board(BOARD_WIDTH, BOARD_HEIGHT)
        self.picked = False        # PICK accepted for the current round
        self.connected = conn is not None

    def reset_board(self):
        """Fresh empty board for a new round (money and stars persist)."""
        self.board = Board(BOARD_WIDTH, BOARD_HEIGHT)
        self.picked = False

    def score(self):
        """Scoreboard entry used in STAR / GAME_OVER messages."""
        return {"playerId": self.name, "stars": self.stars, "money": self.money}
