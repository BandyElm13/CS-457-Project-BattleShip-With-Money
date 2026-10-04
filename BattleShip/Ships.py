from interface import implements, Interface

class Ships(Interface):

    def get_type(self):
        pass

    def get_size(self):
        pass

    def get_health(self):
        pass

    def get_Appearence(self):
        pass

# Mid-Sized ships
class Ship1(implements(Ships)):
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
class Ship2(implements(Ships)):
    def get_type(self):
        return "Dingy"
    
    def get_size(self):
        return 3

    def get_health(self):
        health = 3
        return self.get_health

    def get_Appearence(self):
            return "2"

#Big ships
class Ship3(implements(Ships)):
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
class Ship4(implements(Ships)):
    health = 1
    def get_type(self):
        return "FleetManager"

    def get_size(self):
        return 1
    
    def get_health(self):
        return self.health

    def get_Appearence(self):
            return "4"