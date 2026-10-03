**FSM DESIGN**
![BattleSAHip w Monney](/Images/Battleship%20ULM%20diagram.png)

**2.4 Connection Termination & Socket Life Cycle**
    - If a client leaves on accicent/ purposful, they trigger a Disconect State to the server, ther server will then start REJOIn which holds that clients player data. If the client rejoins with the SAME name as whats the server holds, the server first sends an emty board then overwrite it with there data, If the host doesnt respawn, the client remaining wins and the server clears its data and closes.
    -If a client leaves on there turn, oopopn rejoining the server resends YOUR TURN, and the fgame continues
    -If client quicks on the enemys turn, the game is paused untill the client leaves if they dont come back. the client thats left wins.
    -socket.close() normally should exit after a client has 3 stars or has more stars, or has more money, beacsues thats when the game ends
    -socket echange for socket.close(), 1, end, 2, end-ack, 3.ack
    -socket infinite loop., the server during each input has a another timer for each client, but if that timer expires the game ends, sockets gets closed and data is purged/cleared. Ths is only yo be used when the client goes inactive for too long
