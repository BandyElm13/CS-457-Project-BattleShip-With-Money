"""
server.py - Multithreaded TCP game server for Battleship w/ Money.

Usage:
    python3 server.py -p <port> [--rounds N] [--turn-timeout S] [--rejoin-timeout S]

Design (see concurrency_design.md / fsm_specification.md):

* One accept loop (main thread) plus one handler thread per client.  Each
  handler blocks on recv_message() for its own socket only, so one client
  can never freeze the other.
* Clients are paired into isolated GameSession objects (2 players each).
  All state of a session sits behind a single threading.RLock; every
  JOIN/PICK/MOVE/disconnect is processed while holding it.
* The server is the only authority: it validates every PICK and MOVE,
  checks self.turn, and broadcasts HIT/MISS, MONEY, STAR, YOUR_TURN and
  GAME_OVER to both players (encoded once, same bytes to both).
* Session FSM:
      WAITING_FOR_PLAYERS -> PLACING -> PLAYING -> (round over)
        -> PLACING (next round) ... -> GAME_OVER -> CLEANUP
  with a "paused" flag while a dropped player may REJOIN.
"""

import argparse
import random
import signal
import socket
import sys
import threading
import time

import protocal as P
from player import Player
from Ships import FLEET

# FSM phases
WAITING_FOR_PLAYERS = "WAITING_FOR_PLAYERS"
PLACING = "PLACING"
PLAYING = "PLAYING"
GAME_OVER = "GAME_OVER"
CLEANUP = "CLEANUP"

JOIN_TIMEOUT = 60.0      # seconds a new socket has to send JOIN
MAX_NAME_LEN = 20

_print_lock = threading.Lock()


def log(message):
    """Thread-safe timestamped server log line."""
    with _print_lock:
        print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


class GameSession:
    """One isolated 2-player game: boards, money, stars, turn and FSM."""

    def __init__(self, game_id, rounds, turn_timeout, rejoin_timeout, on_finished):
        self.game_id = game_id
        self.rounds = rounds
        self.turn_timeout = turn_timeout
        self.rejoin_timeout = rejoin_timeout
        self._on_finished = on_finished
        self.lock = threading.RLock()
        self.players = []
        self.phase = WAITING_FOR_PLAYERS
        self.round = 0
        self.turn = None
        self.paused = False
        self._turn_timer = None
        self._turn_token = 0
        self._rejoin_timers = {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def tag(self):
        """Prefix for log lines."""
        return f"[game {self.game_id}]"

    def opponent(self, player):
        """The other player in this session (or None)."""
        for other in self.players:
            if other is not player:
                return other
        return None

    def get_player(self, name):
        """Look up a player by name."""
        for player in self.players:
            if player.name == name:
                return player
        return None

    def scores(self):
        """Scoreboard list for both players."""
        return [p.score() for p in self.players]

    def is_full(self):
        """True once two players have joined."""
        return len(self.players) >= 2

    def send_to(self, player, msg_type, **fields):
        """Send a message to one player (ignored if they are offline)."""
        if player.conn is None:
            return
        try:
            player.conn.send(msg_type, **fields)
        except OSError as exc:
            log(f"{self.tag()} send to {player.name} failed: {exc}")

    def broadcast(self, msg_type, **fields):
        """Encode once and send the same bytes to every connected player."""
        frame = P.encode_message(P.make_message(msg_type, **fields))
        for player in self.players:
            if player.conn is None:
                continue
            try:
                player.conn.send_raw(frame)
            except OSError as exc:
                log(f"{self.tag()} broadcast to {player.name} failed: {exc}")

    # ------------------------------------------------------------------
    # Lobby
    # ------------------------------------------------------------------
    def add_player(self, player):
        """Add a player; start round 1 once both have joined."""
        with self.lock:
            self.players.append(player)
            log(f"{self.tag()} {player.name} joined ({len(self.players)}/2)")
            if not self.is_full():
                self.send_to(player, P.LOBBY_WAIT, playerId=player.name,
                             message="Joined lobby. Waiting for Player 2...")
                return
            log(f"{self.tag()} both players ready: "
                f"{self.players[0].name} vs {self.players[1].name}")
            self.round = 1
            self._start_placement()

    # ------------------------------------------------------------------
    # Rounds / placement
    # ------------------------------------------------------------------
    def _start_placement(self):
        """Reset boards and prompt both clients to PICK (BOARD_RESET)."""
        self.phase = PLACING
        self.turn = None
        self._cancel_turn_timer()
        for player in self.players:
            player.reset_board()
        log(f"{self.tag()} round {self.round}/{self.rounds}: waiting for placements")
        for player in self.players:
            self._send_board_reset(player)

    def _send_board_reset(self, player):
        """Prompt one player for ship placements."""
        fleet = {key: {"type": cls().get_type(), "size": cls().get_size(),
                       "symbol": cls().get_Appearence()}
                 for key, cls in FLEET.items()}
        opp = self.opponent(player)
        self.send_to(player, P.BOARD_RESET, round=self.round, totalRounds=self.rounds,
                     playerId=player.name, opponent=opp.name if opp else None,
                     width=P.BOARD_WIDTH, height=P.BOARD_HEIGHT, fleet=fleet,
                     scores=self.scores())

    def _on_pick(self, player, msg):
        if self.phase != PLACING:
            self.send_to(player, P.ERROR, reason="not accepting placements right now")
            return
        if player.picked:
            self.send_to(player, P.ERROR, reason="placements already accepted for this round")
            return
        ships = msg["data"].get("ships")
        error = player.board.place_fleet(ships)
        if error:
            # Discard request and ask the client again (sender only).
            log(f"{self.tag()} rejected PICK from {player.name}: {error}")
            player.reset_board()
            self.send_to(player, P.ERROR, reason=f"invalid placement: {error}")
            self._send_board_reset(player)
            return
        player.picked = True
        log(f"{self.tag()} PICK accepted from {player.name}")
        if all(p.picked for p in self.players) and not self.paused:
            self._start_play()

    def _start_play(self):
        """Both fleets placed: send each player their half, pick first turn."""
        self.phase = PLAYING
        self.turn = random.choice(self.players).name
        log(f"{self.tag()} round {self.round} started, {self.turn} goes first")
        for player in self.players:
            opp = self.opponent(player)
            self.send_to(player, P.START_ROUND, round=self.round, totalRounds=self.rounds,
                         playerId=player.name, opponent=opp.name,
                         ownBoard=player.board.own_view(),
                         targetBoard=opp.board.target_view(),
                         first=self.turn, scores=self.scores())
        self._announce_turn()

    def _announce_turn(self):
        """Broadcast YOUR_TURN naming the active player; arm the timer."""
        self.broadcast(P.YOUR_TURN, playerId=self.turn, round=self.round)
        self._arm_turn_timer()

    def _send_turn_to(self, player):
        """Re-send YOUR_TURN to one player only (after an invalid move)."""
        self.send_to(player, P.YOUR_TURN, playerId=self.turn, round=self.round)

    # ------------------------------------------------------------------
    # Moves
    # ------------------------------------------------------------------
    def _on_move(self, player, msg):
        x, y = msg["x"], msg["y"]
        if self.phase != PLAYING:
            self.send_to(player, P.ERROR, reason="no round in progress")
            return
        if self.paused:
            self.send_to(player, P.ERROR,
                         reason="game paused: waiting for opponent to rejoin")
            return
        if player.name != self.turn:
            self.send_to(player, P.ERROR, reason=f"not your turn (it is {self.turn}'s turn)")
            return
        opp = self.opponent(player)
        try:
            hit, sunk_ship = opp.board.receive_shot(x, y)
        except ValueError as exc:
            # Sender only; state unchanged, still their turn.
            self.send_to(player, P.ERROR, reason=str(exc))
            self._send_turn_to(player)
            return

        self._cancel_turn_timer()
        if not hit:
            log(f"{self.tag()} {player.name} -> ({x},{y}) MISS")
            self.broadcast(P.MISS, playerId=player.name, x=x, y=y)
            self.turn = opp.name
            self._announce_turn()
            return

        sunk_type = sunk_ship.get_type() if sunk_ship else None
        log(f"{self.tag()} {player.name} -> ({x},{y}) HIT"
            + (f", sunk {sunk_type}" if sunk_type else ""))
        self.broadcast(P.HIT, playerId=player.name, x=x, y=y,
                       sunk=sunk_ship is not None, ship=sunk_type,
                       shipsRemaining=opp.board.ships_remaining())
        player.money += P.MONEY_PER_HIT
        self.broadcast(P.MONEY, playerId=player.name, money=player.money,
                       gained=P.MONEY_PER_HIT)
        if opp.board.all_sunk():
            self._end_round(player)
        else:
            self._announce_turn()   # a hit earns another shot

    def _end_round(self, winner):
        """Award a star, then either reset boards or finish the game."""
        winner.stars += 1
        log(f"{self.tag()} round {self.round} won by {winner.name} "
            f"(stars={winner.stars}, money={winner.money})")
        self.broadcast(P.STAR, playerId=winner.name, stars=winner.stars,
                       round=self.round, scores=self.scores())
        if self.round >= self.rounds or winner.stars >= P.STARS_TO_WIN:
            self._finish_game()
        else:
            self.round += 1
            self._start_placement()

    def _finish_game(self, winner=None, reason=None):
        """Decide the winner (stars, then money) and broadcast GAME_OVER."""
        if winner is None and reason is None:
            a, b = self.players
            if a.stars != b.stars:
                winner = a if a.stars > b.stars else b
                reason = "most stars"
            elif a.money != b.money:
                winner = a if a.money > b.money else b
                reason = "stars tied - decided by money"
            else:
                reason = "draw - stars and money tied"
        self.phase = GAME_OVER
        self._cancel_turn_timer()
        for timer in self._rejoin_timers.values():
            timer.cancel()
        self._rejoin_timers.clear()
        log(f"{self.tag()} GAME OVER: winner={winner.name if winner else 'none'} "
            f"({reason}) scores={self.scores()}")
        self.broadcast(P.GAME_OVER, winner=winner.name if winner else None,
                       reason=reason, scores=self.scores())
        # Give clients a moment to read GAME_OVER and send DISCONNECT, then
        # close whatever is left and purge the session.
        threading.Timer(2.0, self._cleanup).start()

    def _cleanup(self):
        """Close remaining sockets and drop the session (CLEANUP state)."""
        with self.lock:
            self.phase = CLEANUP
            for player in self.players:
                if player.conn is not None:
                    player.conn.close()
                    player.conn = None
        log(f"{self.tag()} session cleaned up")
        self._on_finished(self)

    # ------------------------------------------------------------------
    # Timers
    # ------------------------------------------------------------------
    def _arm_turn_timer(self):
        self._cancel_turn_timer()
        if self.turn_timeout <= 0:
            return
        self._turn_token += 1
        token = self._turn_token
        self._turn_timer = threading.Timer(self.turn_timeout, self._turn_expired, args=(token,))
        self._turn_timer.daemon = True
        self._turn_timer.start()

    def _cancel_turn_timer(self):
        if self._turn_timer is not None:
            self._turn_timer.cancel()
            self._turn_timer = None

    def _turn_expired(self, token):
        with self.lock:
            if token != self._turn_token or self.phase != PLAYING or self.paused:
                return
            idle = self.get_player(self.turn)
            log(f"{self.tag()} {idle.name} timed out")
            self.send_to(idle, P.ERROR, reason="TimedOut: you were inactive too long")
            self._finish_game(winner=self.opponent(idle),
                              reason=f"{idle.name} timed out")

    # ------------------------------------------------------------------
    # Disconnect / rejoin (fsm_specification.md 2.4)
    # ------------------------------------------------------------------
    def on_disconnect(self, player, conn):
        """Called by the handler thread when a player's socket goes away."""
        with self.lock:
            if player.conn is not conn:
                return                         # stale socket (already rejoined)
            player.conn = None
            player.connected = False
            if self.phase == WAITING_FOR_PLAYERS:
                self.players.remove(player)
                log(f"{self.tag()} {player.name} left the lobby")
                return
            if self.phase in (GAME_OVER, CLEANUP):
                return
            log(f"{self.tag()} {player.name} disconnected; holding data for "
                f"{self.rejoin_timeout:.0f}s")
            if not any(p.connected for p in self.players):
                log(f"{self.tag()} both players gone; ending session")
                self._finish_game(winner=None, reason="both players disconnected")
                return
            self.paused = True
            self._cancel_turn_timer()
            self.broadcast(P.DISCONNECT, playerId=player.name,
                           rejoinTimeout=self.rejoin_timeout,
                           message=f"{player.name} disconnected. Game paused; "
                                   f"waiting up to {self.rejoin_timeout:.0f}s for them to rejoin.")
            timer = threading.Timer(self.rejoin_timeout, self._rejoin_expired, args=(player,))
            timer.daemon = True
            self._rejoin_timers[player.name] = timer
            timer.start()

    def _rejoin_expired(self, player):
        with self.lock:
            if player.connected or self.phase in (GAME_OVER, CLEANUP):
                return
            log(f"{self.tag()} {player.name} did not rejoin in time")
            self._finish_game(winner=self.opponent(player),
                              reason=f"{player.name} disconnected and did not rejoin")

    def rejoin(self, player, conn):
        """Re-attach a reconnecting client and resend its state."""
        with self.lock:
            timer = self._rejoin_timers.pop(player.name, None)
            if timer:
                timer.cancel()
            player.conn = conn
            player.connected = True
            self.paused = not all(p.connected for p in self.players)
            opp = self.opponent(player)
            log(f"{self.tag()} {player.name} rejoined")
            self.send_to(player, P.REJOIN, playerId=player.name, opponent=opp.name,
                         round=self.round, totalRounds=self.rounds, phase=self.phase,
                         ownBoard=player.board.own_view(),
                         targetBoard=opp.board.target_view(), scores=self.scores())
            self.send_to(opp, P.REJOIN, playerId=player.name,
                         message=f"{player.name} rejoined the game.")
            if self.paused:
                return
            if self.phase == PLACING:
                for p in self.players:
                    if not p.picked:
                        self._send_board_reset(p)
                if all(p.picked for p in self.players):
                    self._start_play()
            elif self.phase == PLAYING:
                self._announce_turn()

    # ------------------------------------------------------------------
    # Dispatcher
    # ------------------------------------------------------------------
    def handle(self, player, msg):
        """Process one validated client message under the game lock."""
        with self.lock:
            if msg.get("playerId") not in (None, player.name):
                self.send_to(player, P.ERROR, reason="playerId does not match this connection")
                return
            if msg["type"] == P.PICK:
                self._on_pick(player, msg)
            elif msg["type"] == P.MOVE:
                self._on_move(player, msg)
            else:
                self.send_to(player, P.ERROR,
                             reason=f"unexpected message '{msg['type']}' during game")


class Lobby:
    """Pairs incoming clients into isolated GameSessions."""

    def __init__(self, rounds, turn_timeout, rejoin_timeout):
        self.rounds = rounds
        self.turn_timeout = turn_timeout
        self.rejoin_timeout = rejoin_timeout
        self.lock = threading.Lock()
        self.games = []
        self._next_id = 1

    def _remove_game(self, game):
        with self.lock:
            if game in self.games:
                self.games.remove(game)

    def assign(self, name, conn):
        """
        Place a JOIN/REJOIN'd client into a session.

        Returns (game, player) or raises ValueError with a reason.
        """
        with self.lock:
            # Rejoin: same name as a disconnected player in a running game.
            for game in self.games:
                player = game.get_player(name)
                if player is None:
                    continue
                if not player.connected and game.phase in (PLACING, PLAYING):
                    game.rejoin(player, conn)
                    return game, player
                raise ValueError(f"name '{name}' is already in use")
            # Otherwise join the open lobby (or open a new one).
            game = next((g for g in self.games
                         if g.phase == WAITING_FOR_PLAYERS and not g.is_full()), None)
            if game is None:
                game = GameSession(self._next_id, self.rounds, self.turn_timeout,
                                   self.rejoin_timeout, self._remove_game)
                self._next_id += 1
                self.games.append(game)
            player = Player(name, conn)
            # Lock order is always Lobby.lock -> GameSession.lock.
            game.add_player(player)
            return game, player


def handle_client(sock, addr, lobby):
    """Per-connection worker thread: JOIN, then recv loop until disconnect."""
    conn = P.FramedConnection(sock)
    peer = f"{addr[0]}:{addr[1]}"
    game = player = None
    log(f"connection from {peer}")
    try:
        sock.settimeout(JOIN_TIMEOUT)
        first = conn.recv_message()
        sock.settimeout(None)
        if first is None:
            return
        if first.get("type") not in (P.JOIN, P.REJOIN) or P.validate(first):
            conn.send(P.ERROR, reason="first message must be JOIN with a playerId")
            return
        name = first["playerId"].strip()[:MAX_NAME_LEN]
        if not name:
            conn.send(P.ERROR, reason="player name cannot be empty")
            return
        try:
            game, player = lobby.assign(name, conn)
        except ValueError as exc:
            conn.send(P.ERROR, reason=str(exc))
            return

        while True:
            msg = conn.recv_message()
            if msg is None:
                break
            error = P.validate(msg)
            if error:
                conn.send(P.ERROR, reason=f"malformed message: {error}")
                continue
            if msg["type"] == P.DISCONNECT:
                log(f"{player.name} sent DISCONNECT")
                break
            game.handle(player, msg)
    except socket.timeout:
        log(f"{peer} never sent JOIN; closing")
    except P.ProtocolError as exc:
        log(f"protocol error from {peer}: {exc}")
        try:
            conn.send(P.ERROR, reason=f"protocol error: {exc}")
        except OSError:
            pass
    except OSError as exc:
        log(f"socket error from {peer}: {exc}")
    finally:
        if game is not None:
            game.on_disconnect(player, conn)
        conn.close()
        log(f"connection {peer} closed")


def parse_args(argv=None):
    """Command line options for the server."""
    parser = argparse.ArgumentParser(
        description="Battleship w/ Money game server (TCP, multithreaded).",
        epilog="Example: python3 server.py -p 5000")
    parser.add_argument("-p", "--port", type=P.port_type, required=True,
                        help="TCP port to listen on (1024-65535)")
    parser.add_argument("--host", default="0.0.0.0",
                        help="interface to bind (default: 0.0.0.0, all interfaces)")
    parser.add_argument("--rounds", type=int, default=P.TOTAL_ROUNDS,
                        help=f"rounds per game (default: {P.TOTAL_ROUNDS})")
    parser.add_argument("--turn-timeout", type=float, default=300.0,
                        help="seconds a player may idle on their turn before "
                             "forfeiting (0 = off, default: 300)")
    parser.add_argument("--rejoin-timeout", type=float, default=30.0,
                        help="seconds to hold a dropped player's data for REJOIN "
                             "(default: 30)")
    args = parser.parse_args(argv)
    if args.rounds < 1:
        parser.error("--rounds must be at least 1")
    return args


def main():
    """Bind, listen and spawn a worker thread per client."""
    args = parse_args()

    def _on_sigterm(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, _on_sigterm)   # `kill` shuts down cleanly too
    lobby = Lobby(args.rounds, args.turn_timeout, args.rejoin_timeout)
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_sock.bind((args.host, args.port))
    except OSError as exc:
        print(f"[ERROR] Could not bind {args.host}:{args.port}: {exc.strerror or exc}")
        sys.exit(1)
    server_sock.listen()
    server_sock.settimeout(1.0)   # wake up periodically so Ctrl+C works
    log(f"Battleship w/ Money server listening on {args.host}:{args.port} "
        f"(rounds={args.rounds})")
    try:
        while True:
            try:
                client_sock, addr = server_sock.accept()
            except socket.timeout:
                continue
            client_sock.settimeout(None)
            threading.Thread(target=handle_client, args=(client_sock, addr, lobby),
                             daemon=True).start()
    except KeyboardInterrupt:
        log("shutting down")
    finally:
        server_sock.close()


if __name__ == "__main__":
    main()
