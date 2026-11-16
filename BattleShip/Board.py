"""
Board.py - Grid model for Battleship w/ Money.

The same class is used in two ways:

* On the server it is the authoritative board for one player: it holds
  the Ship objects, validates PICK placements and resolves incoming shots.
* On the client it is a display model (own board / target view) that is
  updated from the server's HIT and MISS broadcasts.

Coordinates are (x, y) = (column, row), both zero-based.
"""

import random

from Ships import FLEET

EMPTY = " "
HIT_MARK = "X"
MISS_MARK = "o"


class Board:
    """A width x height grid with optional ships."""

    def __init__(self, width, height):
        self.width = width
        self.height = height
        # grid[y][x] holds a single display character (EMPTY, ship char,
        # HIT_MARK or MISS_MARK).
        self.grid = [[EMPTY for _ in range(self.width)] for _ in range(self.height)]
        self.ships = {}            # fleet key -> Ship object
        self._cell_to_ship = {}    # (x, y) -> fleet key
        self.shots = {}            # (x, y) -> "HIT" | "MISS"

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------
    def in_bounds(self, x, y):
        """True if (x, y) lies on the grid."""
        return 0 <= x < self.width and 0 <= y < self.height

    # ------------------------------------------------------------------
    # Placement (server side)
    # ------------------------------------------------------------------
    def validate_placements(self, placements):
        """
        Check a PICK payload: {"ship1": [[x, y], ...], ...}.

        Rules: every fleet ship present exactly once, correct length,
        integer in-bounds cells, a straight contiguous horizontal or
        vertical line, and no overlap with another ship.
        Returns None when valid, otherwise an error reason string.
        """
        if not isinstance(placements, dict):
            return "ships must be an object of shipN -> [[x, y], ...]"
        if set(placements) != set(FLEET):
            return f"expected exactly these ships: {', '.join(sorted(FLEET))}"
        used = set()
        for key, cls in FLEET.items():
            ship = cls()
            cells = placements[key]
            if not isinstance(cells, list) or len(cells) != ship.get_size():
                return (f"{key} ({ship.get_type()}) needs exactly "
                        f"{ship.get_size()} cells")
            coords = []
            for cell in cells:
                if (not isinstance(cell, (list, tuple)) or len(cell) != 2
                        or not all(isinstance(v, int) and not isinstance(v, bool)
                                   for v in cell)):
                    return f"{key}: each cell must be [x, y] integers"
                x, y = cell
                if not self.in_bounds(x, y):
                    return f"{key}: cell ({x}, {y}) is out of bounds"
                if (x, y) in used:
                    return f"{key}: cell ({x}, {y}) overlaps another ship"
                coords.append((x, y))
            if len(set(coords)) != len(coords):
                return f"{key}: duplicate cells"
            xs = sorted(c[0] for c in coords)
            ys = sorted(c[1] for c in coords)
            horizontal = len(set(ys)) == 1 and xs == list(range(xs[0], xs[0] + len(xs)))
            vertical = len(set(xs)) == 1 and ys == list(range(ys[0], ys[0] + len(ys)))
            if not (horizontal or vertical):
                return f"{key}: cells must form a straight, contiguous line"
            used.update(coords)
        return None

    def place_fleet(self, placements):
        """Validate then place every ship. Returns None or an error string."""
        error = self.validate_placements(placements)
        if error:
            return error
        for key, cls in FLEET.items():
            ship = cls()
            ship.positions = [tuple(c) for c in placements[key]]
            self.ships[key] = ship
            for x, y in ship.positions:
                self._cell_to_ship[(x, y)] = key
                self.grid[y][x] = ship.get_Appearence()
        return None

    @staticmethod
    def random_placements(width, height, rng=random):
        """Generate a valid random PICK payload for the whole fleet."""
        used = set()
        placements = {}
        # Place largest ships first so they always fit.
        order = sorted(FLEET, key=lambda k: -FLEET[k]().get_size())
        for key in order:
            size = FLEET[key]().get_size()
            while True:
                horizontal = rng.random() < 0.5
                if horizontal:
                    x0, y0 = rng.randrange(width - size + 1), rng.randrange(height)
                    cells = [(x0 + i, y0) for i in range(size)]
                else:
                    x0, y0 = rng.randrange(width), rng.randrange(height - size + 1)
                    cells = [(x0, y0 + i) for i in range(size)]
                if not used.intersection(cells):
                    used.update(cells)
                    placements[key] = [list(c) for c in cells]
                    break
        return {key: placements[key] for key in FLEET}

    # ------------------------------------------------------------------
    # Shots
    # ------------------------------------------------------------------
    def receive_shot(self, x, y):
        """
        Resolve an attack on (x, y).

        Returns (hit: bool, sunk_ship or None).
        Raises ValueError if the cell is out of bounds or already shot.
        """
        if not self.in_bounds(x, y):
            raise ValueError(f"invalid move: ({x}, {y}) is out of bounds "
                             f"(0-{self.width - 1}, 0-{self.height - 1})")
        if (x, y) in self.shots:
            raise ValueError(f"invalid move: ({x}, {y}) was already shot")
        key = self._cell_to_ship.get((x, y))
        if key is None:
            self.shots[(x, y)] = "MISS"
            self.grid[y][x] = MISS_MARK
            return False, None
        self.shots[(x, y)] = "HIT"
        self.grid[y][x] = HIT_MARK
        ship = self.ships[key]
        sunk = ship.take_damage()
        return True, (ship if sunk else None)

    def mark_shot(self, x, y, hit):
        """Client-side: record a shot result reported by the server."""
        if self.in_bounds(x, y):
            self.shots[(x, y)] = "HIT" if hit else "MISS"
            self.grid[y][x] = HIT_MARK if hit else MISS_MARK

    def all_sunk(self):
        """True when every ship on the board has been destroyed."""
        return bool(self.ships) and all(s.ship_distroyed() for s in self.ships.values())

    def ships_remaining(self):
        """Number of ships still afloat."""
        return sum(1 for s in self.ships.values() if not s.ship_distroyed())

    # ------------------------------------------------------------------
    # Views / serialization
    # ------------------------------------------------------------------
    def own_view(self):
        """Rows of characters showing ships, hits and misses (owner only)."""
        return ["".join(row) for row in self.grid]

    def target_view(self):
        """Rows showing only hits/misses - what the opponent may see."""
        rows = []
        for y in range(self.height):
            row = ""
            for x in range(self.width):
                result = self.shots.get((x, y))
                row += HIT_MARK if result == "HIT" else MISS_MARK if result == "MISS" else EMPTY
            rows.append(row)
        return rows

    def load_view(self, rows):
        """Client-side: replace the grid with rows received from the server."""
        self.shots = {}
        for y, row in enumerate(rows[:self.height]):
            for x, ch in enumerate(row[:self.width]):
                self.grid[y][x] = ch
                if ch == HIT_MARK:
                    self.shots[(x, y)] = "HIT"
                elif ch == MISS_MARK:
                    self.shots[(x, y)] = "MISS"

    def render_lines(self, title):
        """Return the board as printable lines with x/y axis labels."""
        lines = [title, "    " + "".join(f" {x} " for x in range(self.width))]
        for y in range(self.height):
            lines.append(f" {y:>2} " + "".join(f"[{c}]" for c in self.grid[y]))
        return lines

    def draw_board(self, title="Board"):
        """Print the board to the console."""
        print("\n".join(self.render_lines(title)))


def render_side_by_side(left, right, gap=6):
    """Combine two Board.render_lines() outputs into one string."""
    width = max(len(line) for line in left)
    return "\n".join(f"{a:<{width}}{' ' * gap}{b}" for a, b in zip(left, right))
