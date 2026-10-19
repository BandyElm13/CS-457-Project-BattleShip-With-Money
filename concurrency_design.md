**2.1 Server Concurrency Model Selection**

    1. Battleship with money will use Multi Threading to make sure one oponant cant send data to the sregver while its the
    other persons turn

    2. Each thred blocks the recv_message() for its own socket so one client neever freezes the other

    3. All shared game state regardless of whos turn it is will sit behind a  a single game lock threading.Rlock

    4. The server will check every move against self.turn. If its not that playuers turn the moive is rejected or the client you made the inavlid reqaueest gest an error. The goaL here is to fully prevent/lock out the the opther player untiull its there turn;



**2.2 Client State & Turn Synchronization Scheme**
![Turn Based Protocal](/Images/BattleShipImage.png)

    1. The server is the only authority, clients just display what the server will tell them

    2. The server sends YOUR_TURN to both clients so each one knopws whos turn it is.

    3. Only the player named in YOUR_TURN is prohibbited to make a move

    4. After a Valid move has been made the srever will broadcast HIT or MISS  and Money to both clients before a new your_turn is sent

    5. All invalid moves will be sent to coreesbonding client that made the error and NOT both.


**2.3 Score & Leaderboard Synchronization Design**

    1. *How scores will be stored in memmory*

        a. Each player has a Player object in the servers memmory holding name money stars, and their Board

        b.Money goes up by 500 for every hit, Money per hit

        c. The Player with 3 stars will win the game Stars per player

        d.Scores are the only changes while holding the game lock so extra infomation doesnt have to bve processed
        during the clients turn. This is because if the game fully locked the thread on the client after there move was sent to the sever
        the server cant respond back to that said client untill there next round after the other guy. This would hold a lot of infomation
        and prevent updating scores which could have unforseen issues such as overflow errors as not only the server sends the go ahead for the client to make there move, but also the notification that there previouse shot was a hit/mis and to give money according. AKA sending both bits of infomatioon at once might not be the best choice, which is wky scores will not ne locked and the server will tell the client ZHOt miss and give money accordingly.


    2. *Broadcast logic on round completion*

        a. When a fleet is fully sunk, the server still holdiong the lock updates the winner stars.

        b. It broadcast a star message with the updataedstar count to both clients

        c. if someone has three star server will broaadcast Game_Over with the winner and final scores in a ScoadBoard stroiing object broadcasted to both clients, before sending the cleints back to lobby. and teh data from that game is clear and (MAYBY in a fiuture realease there is permant scores associated with cleints, but iof i did do this, then i would bneed a database mand accually have to implient hashing algorithms, for proper data security)

        d. broadcast() encodes each message once and sends the same bytes to both clients back to back so they alwasy show identical scores
