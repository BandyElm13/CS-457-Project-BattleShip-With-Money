from abc import ABC, abstractmethod

class Ships(ABC):

    @abstractmethod
    def get_type(self):
        pass

    @abstractmethod
    def get_size(self):
        pass

    @abstractmethod
    def get_health(self):
        pass

    @abstractmethod
    def get_Appearence(self):
        return ""

    def take_damage(self):
        if self.health > 0:
            self.health -= 1
        return self.ship_distroyed()

    def ship_distroyed(self):
        return self.health <= 0

    def get_full_ship(self):
        return f"{self.get_type()}, Size: {self.get_size()}, Health: {self.get_health()}"


# Mid-Sized ships
class Ship1(Ships):
    health = 5
    def get_type(self):
        return "Cargoship"
    
    def get_size(self):
        return 5

    def get_health(self):
        return self.health

    def get_Appearence(self):
        return "1"

#Small ships
class Ship2(Ships):
    health = 3
    def get_type(self):
        return "Dingy"
    
    def get_size(self):
        return 3

    def get_health(self):
        return self.health

    def get_Appearence(self):
            return "2"

#Big ships
class Ship3(Ships):
    health = 8
    def get_type(self):
        return "Aircraftcarrier"

    def get_size(self):
        return 8

    def get_health(self):
        return self.health

    def get_Appearence(self):
            return "3"

#FleetManage, smallest ship
class Ship4(Ships):
    health = 1

    def get_type(self):
        return "FleetManager"

    def get_size(self):
        return 1
    
    def get_health(self):
        return self.health

    def get_Appearence(self):
            return "4"

ship1 = Ship1()

print(ship1.get_full_ship())