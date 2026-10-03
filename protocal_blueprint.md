**BattleShip w Money(Blue Print)**
    2.1 Transport Layer and Packet Framing mechanism
        -Transport Layer: TCP
        -Serialialize Format: Structured Json
        -Framing Rule 4 byte big endian length
        00 00 00 2a {"type":"MOVE","x":3,"y":7,"playerId":"p1"}
        00 00 00 00 {"type": "PICK","playerId": "player1","data": {"Ships": {"ship1"}: [[],[],[],[]], "ship2": [[],[],[],[]], etc}}
    
    2.2(Application Message Types)
    Clients
        Type, Direction, Purpose
        JOIN, Client-Server, A client joins the lobby
        PICK, Client-Server, Client adds there ships to there haft of the board
        MOVE, Client-Server, Client chooses an idex to attack
        REJOIN, Client to Server, client disconnected, timmer server hold player data for a timmer length, if cl;ient rejoins and the name is the same to the servers held id, connection is reatbliched otehr is ERROR ois triggered
        DISCONECT, Client-Server, client connection is serveres and triggers Rejoin on the server side

    Server
        PICK-ACCEPTED, Server-Client, Server accepets teh clients placment
        PICK-INVALID, Server-Client, Server found an issues with client input(out of bounds index, type error(dopuble instead of an integer))
        START-ROUND, Server-Client, Loads board with bothe Clients data for ship placments
        YOUR-TURN, Server-client, prompts the current clienmt to make a move 
        HIT/MISS. Server-Client, server verifies if client hit the others a ship on teh other feild or not
        MONEY, Server-Client, If HIT/MISS comes back as true for the server the server updates the clients money by 500
        STAR, Server-Client, At the end of a round the winning clients stars is upgraded by + 1
        BOARD_RESET: Server-Client, Board Resets and pronts PICK to resend
        GAME_OVER, SERVER-CLIENT, when a Client winns has 3 stars, or who every has more stars or money.\
        ERROR, Client to server, invalid move, typeError, TimedOut

    ![ULM](/Images/STATES.jpg)