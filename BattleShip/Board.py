class Board :

    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.grid = [["[ ]" for _ in range(self.width)] for _ in range(self.height)]

    def draw_board(self):
        for _ in range(self.height):
            print("[ ]" * self.width)