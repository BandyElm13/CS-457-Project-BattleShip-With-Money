"""
Ships.py - Ship classes for Battleship w/ Money.

Each concrete ship has a type name, a size (number of grid cells), a
health value (hits remaining) and a one-character appearance used when
drawing the owner's board.  The fleet keys ("ship1".."ship4") match the
PICK payload in protocal_blueprint.md.
"""

from abc import ABC, abstractmethod


class Ships(ABC):
    """Abstract base ship. Health starts at size and drops on each hit."""

    def __init__(self):
        # Per-instance health (the original class attribute would be shared
        # between every ship of the same class across both players).
        self.health = self.get_size()
        self.positions = []          # list of (x, y) cells this ship occupies

    @abstractmethod
    def get_type(self):
        """Human readable ship type."""

    @abstractmethod
    def get_size(self):
        """Number of cells the ship occupies."""

    @abstractmethod
    def get_health(self):
        """Hits remaining before the ship sinks."""

    @abstractmethod
    def get_Appearence(self):
        """Single character drawn on the owner's board."""
        return ""

    def take_damage(self):
        """Register one hit. Returns True if the ship is now destroyed."""
        if self.health > 0:
            self.health -= 1
        return self.ship_distroyed()

    def ship_distroyed(self):
        """True once every cell of the ship has been hit."""
        return self.health <= 0

    def get_full_ship(self):
        """Summary string, e.g. 'Dingy, Size: 3, Health: 2'."""
        return f"{self.get_type()}, Size: {self.get_size()}, Health: {self.get_health()}"


# Mid-Sized ships
class Ship1(Ships):
    """Cargoship - 5 cells."""

    def get_type(self):
        return "Cargoship"

    def get_size(self):
        return 5

    def get_health(self):
        return self.health

    def get_Appearence(self):
        return "1"


# Small ships
class Ship2(Ships):
    """Dingy - 3 cells."""

    def get_type(self):
        return "Dingy"

    def get_size(self):
        return 3

    def get_health(self):
        return self.health

    def get_Appearence(self):
        return "2"


# Big ships
class Ship3(Ships):
    """Aircraftcarrier - 8 cells."""

    def get_type(self):
        return "Aircraftcarrier"

    def get_size(self):
        return 8

    def get_health(self):
        return self.health

    def get_Appearence(self):
        return "3"


# FleetManager, smallest ship
class Ship4(Ships):
    """FleetManager - 1 cell."""

    def get_type(self):
        return "FleetManager"

    def get_size(self):
        return 1

    def get_health(self):
        return self.health

    def get_Appearence(self):
        return "4"


# Fleet definition: PICK payload key -> ship class.
FLEET = {
    "ship1": Ship1,
    "ship2": Ship2,
    "ship3": Ship3,
    "ship4": Ship4,
}


def ship_sizes():
    """Return {fleet_key: size} for every ship in the fleet."""
    return {key: cls().get_size() for key, cls in FLEET.items()}


if __name__ == "__main__":
    for key, cls in FLEET.items():
        print(key, "->", cls().get_full_ship())
