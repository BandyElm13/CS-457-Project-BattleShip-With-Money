"""
client.py - Console client for Battleship w/ Money.

Usage:
    python3 client.py -i <server hostname or IP> -p <port> [-n NAME] [--auto]

The client is a thin view: the server is the only authority (see
concurrency_design.md 2.2).  It sends JOIN, PICK and MOVE frames and
renders whatever the server broadcasts (YOUR_TURN, HIT/MISS, MONEY,
STAR, BOARD_RESET, GAME_OVER ...).

Coordinates are entered as "x y" (column, row), e.g. "3 7".
"""

import argparse
import random
import socket
import sys

import protocal as P
from Board import Board, render_side_by_side

QUIT_WORDS = {"q", "quit", "exit"}


class QuitGame(Exception):
    """Raised when the local user quits (typed quit, EOF or Ctrl+C)."""


class BattleshipClient:
    """Receives server messages and drives the console UI."""

    def __init__(self, conn, name, auto=False):
        self.conn = conn
        self.name = name
        self.auto = auto
        self.opponent = None
        self.round = 0
        self.total_rounds = P.TOTAL_ROUNDS
        self.width = P.BOARD_WIDTH
        self.height = P.BOARD_HEIGHT
        self.fleet = {}
        self.scores = {}
        self.own = Board(self.width, self.height)
        self.target = Board(self.width, self.height)
        self.echo_input = not sys.stdin.isatty()   # make piped logs readable

    # ------------------------------------------------------------------
    # Input helpers
    # ------------------------------------------------------------------
    def ask(self, prompt):
        """input() wrapper: echoes piped input and maps EOF/quit to QuitGame."""
        try:
            # Print the prompt on its own line and flush, so it shows up even
            # when output is piped through tee / Tee-Object (which hold back
            # text until a newline arrives).
            print(prompt.rstrip(), flush=True)
            value = input()
        except EOFError:
            print()
            raise QuitGame("end of input") from None
        if self.echo_input:
            print(value)
        if value.strip().lower() in QUIT_WORDS:
            raise QuitGame("player quit")
        return value.strip()

    @staticmethod
    def parse_xy(text):
        """Parse 'x y' or 'x,y' into (x, y) ints, or None."""
        parts = text.replace(",", " ").split()
        if len(parts) != 2:
            return None
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------
    def score_line(self):
        """'Round 1/3 | alice: 1 star(s) $500 | bob: ...'"""
        parts = [f"Round {self.round}/{self.total_rounds}"]
        for pid in [self.name, self.opponent]:
            if pid in self.scores:
                s = self.scores[pid]
                label = "You" if pid == self.name else pid
                parts.append(f"{label}: {s['stars']} star(s) ${s['money']}")
        return " | ".join(parts)

    def show_boards(self):
        """Print own board and target view side by side."""
        print()
        print(render_side_by_side(
            self.own.render_lines(f"YOUR FLEET ({self.name})"),
            self.target.render_lines(f"TARGET ({self.opponent})")))
        print("Legend: 1-4 = your ships, X = hit, o = miss")
        print(self.score_line())

    def update_scores(self, scores):
        for entry in scores or []:
            self.scores[entry["playerId"]] = {"stars": entry["stars"],
                                              "money": entry["money"]}

    # ------------------------------------------------------------------
    # Placement (PICK)
    # ------------------------------------------------------------------
    def choose_placements(self):
        """Return a PICK ships payload, random or entered by hand."""
        if self.auto:
            return Board.random_placements(self.width, self.height)
        while True:
            choice = self.ask("Place ships: [r]andom or [m]anual? ").lower()
            if choice in ("r", "random", ""):
                return Board.random_placements(self.width, self.height)
            if choice in ("m", "manual"):
                return self.manual_placements()
            print("  Please type 'r' or 'm' (or 'quit').")

    def manual_placements(self):
        """Prompt for each ship's start cell and direction."""
        used = set()
        placements = {}
        preview = Board(self.width, self.height)
        for key, info in self.fleet.items():
            size = info["size"]
            while True:
                preview.draw_board("Placement preview")
                text = self.ask(f"{info['type']} (size {size}): enter 'x y h|v' "
                                f"(start cell + horizontal/vertical): ")
                parts = text.replace(",", " ").split()
                if len(parts) == 2 and size == 1:
                    parts.append("h")
                if len(parts) != 3 or parts[2].lower() not in ("h", "v"):
                    print("  Format: x y h   (example: 2 4 v)")
                    continue
                try:
                    x, y = int(parts[0]), int(parts[1])
                except ValueError:
                    print("  x and y must be numbers.")
                    continue
                dx, dy = (1, 0) if parts[2].lower() == "h" else (0, 1)
                cells = [(x + i * dx, y + i * dy) for i in range(size)]
                if not all(preview.in_bounds(cx, cy) for cx, cy in cells):
                    print("  That ship would go off the board.")
                    continue
                if used.intersection(cells):
                    print("  That overlaps another ship.")
                    continue
                used.update(cells)
                placements[key] = [list(c) for c in cells]
                for cx, cy in cells:
                    preview.grid[cy][cx] = info["symbol"]
                break
        return placements

    # ------------------------------------------------------------------
    # Moves
    # ------------------------------------------------------------------
    def auto_target(self):
        """Simple hunt/target bot used by --auto (testing)."""
        unshot = [(x, y) for y in range(self.height) for x in range(self.width)
                  if (x, y) not in self.target.shots]
        hits = [c for c, r in self.target.shots.items() if r == "HIT"]
        near = [(x + dx, y + dy) for x, y in hits
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))]
        near = [c for c in near if c in unshot]
        return random.choice(near or unshot)

    def choose_move(self):
        """Prompt until the user enters a fresh, in-bounds coordinate."""
        if self.auto:
            x, y = self.auto_target()
            print(f"Enter target 'x y': {x} {y}  (auto)")
            return x, y
        while True:
            text = self.ask(f"Enter target 'x y' (0-{self.width - 1} 0-{self.height - 1}) "
                            f"or 'quit': ")
            coords = self.parse_xy(text)
            if coords is None:
                print("  Format: x y   (example: 3 7)")
                continue
            if not self.target.in_bounds(*coords):
                print("  That cell is off the board.")
                continue
            if coords in self.target.shots:
                print("  You already fired there.")
                continue
            return coords

    # ------------------------------------------------------------------
    # Message handlers
    # ------------------------------------------------------------------
    def on_lobby_wait(self, msg):
        print(f"[LOBBY] {msg.get('message', 'Waiting for Player 2...')}")

    def on_board_reset(self, msg):
        self.round = msg["round"]
        self.total_rounds = msg["totalRounds"]
        self.opponent = msg.get("opponent")
        self.width, self.height = msg["width"], msg["height"]
        self.fleet = msg["fleet"]
        self.update_scores(msg.get("scores"))
        self.own = Board(self.width, self.height)
        self.target = Board(self.width, self.height)
        print()
        print("=" * 60)
        print(f" ROUND {self.round}/{self.total_rounds}  -  {self.name} vs {self.opponent}")
        print("=" * 60)
        print("Your fleet: " + ", ".join(
            f"{v['type']} ({v['size']}) [{v['symbol']}]" for v in self.fleet.values()))
        ships = self.choose_placements()
        self.conn.send(P.PICK, playerId=self.name, data={"ships": ships})
        print(f"Placements sent. Waiting for {self.opponent} to place ships...")

    def on_start_round(self, msg):
        self.round = msg["round"]
        self.opponent = msg["opponent"]
        self.own.load_view(msg["ownBoard"])
        self.target.load_view(msg["targetBoard"])
        self.update_scores(msg.get("scores"))
        first = "You go" if msg["first"] == self.name else f"{msg['first']} goes"
        print(f"\n*** Round {self.round} begins! {first} first (chosen at random). ***")
        if msg["first"] != self.name:      # YOUR_TURN will show them otherwise
            self.show_boards()

    def on_your_turn(self, msg):
        if msg["playerId"] != self.name:
            print(f"\n... Waiting for {msg['playerId']} (opponent's turn) ...")
            return
        self.show_boards()
        print(">>> Your Turn <<<")
        x, y = self.choose_move()
        self.conn.send(P.MOVE, playerId=self.name, x=x, y=y)

    def on_shot(self, msg):
        hit = msg["type"] == P.HIT
        x, y = msg["x"], msg["y"]
        mine = msg["playerId"] == self.name
        board = self.target if mine else self.own
        board.mark_shot(x, y, hit)
        who = "You" if mine else msg["playerId"]
        result = "HIT!" if hit else "miss."
        line = f"{who} fired at ({x}, {y}): {result}"
        if hit and msg.get("sunk"):
            whose = "their" if mine else "your"
            line += f" Sunk {whose} {msg['ship']}! ({msg['shipsRemaining']} ship(s) left)"
        print(line)

    def on_money(self, msg):
        pid = msg["playerId"]
        self.scores.setdefault(pid, {"stars": 0, "money": 0})["money"] = msg["money"]
        who = "You" if pid == self.name else pid
        print(f"  +${msg['gained']} -> {who} now {'have' if who == 'You' else 'has'} "
              f"${msg['money']}")

    def on_star(self, msg):
        self.update_scores(msg.get("scores"))
        winner = "You" if msg["playerId"] == self.name else msg["playerId"]
        print()
        print("*" * 60)
        print(f" Round {msg['round']} over - {winner} sank the whole fleet! "
              f"(+1 star, total {msg['stars']})")
        print(f" {self.score_line()}")
        print("*" * 60)

    def on_disconnect(self, msg):
        print(f"[NOTICE] {msg.get('message', 'Opponent disconnected.')}")

    def on_rejoin(self, msg):
        if "ownBoard" not in msg:
            print(f"[NOTICE] {msg.get('message')}")
            return
        self.round = msg["round"]
        self.total_rounds = msg["totalRounds"]
        self.opponent = msg["opponent"]
        self.update_scores(msg.get("scores"))
        self.own = Board(self.width, self.height)
        self.target = Board(self.width, self.height)
        self.own.load_view(msg["ownBoard"])
        self.target.load_view(msg["targetBoard"])
        print("[REJOIN] Reconnected - your saved game state was restored.")
        if msg["phase"] == "PLAYING":
            self.show_boards()

    def on_error(self, msg):
        print(f"[SERVER ERROR] {msg.get('reason')}")

    def on_game_over(self, msg):
        self.update_scores(msg.get("scores"))
        winner = msg.get("winner")
        print()
        print("#" * 60)
        print(" GAME OVER")
        if winner is None:
            print(f" Result: DRAW ({msg.get('reason')})")
        elif winner == self.name:
            print(f" Result: YOU WIN! ({msg.get('reason')})")
        else:
            print(f" Result: {winner} wins. ({msg.get('reason')})")
        print(" Final scoreboard:")
        for entry in msg.get("scores", []):
            print(f"   {entry['playerId']:<20} stars: {entry['stars']}   "
                  f"money: ${entry['money']}")
        print("#" * 60)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def run(self):
        """Join, then process server messages until GAME_OVER. Returns exit code."""
        handlers = {
            P.LOBBY_WAIT: self.on_lobby_wait,
            P.BOARD_RESET: self.on_board_reset,
            P.START_ROUND: self.on_start_round,
            P.YOUR_TURN: self.on_your_turn,
            P.HIT: self.on_shot,
            P.MISS: self.on_shot,
            P.MONEY: self.on_money,
            P.STAR: self.on_star,
            P.DISCONNECT: self.on_disconnect,
            P.REJOIN: self.on_rejoin,
            P.ERROR: self.on_error,
            P.GAME_OVER: self.on_game_over,
        }
        self.conn.send(P.JOIN, playerId=self.name)
        while True:
            msg = self.conn.recv_message()
            if msg is None:
                print("[INFO] Server closed the connection.")
                return 1
            handler = handlers.get(msg["type"])
            if handler is None:
                print(f"[WARN] Ignoring unknown message type {msg['type']!r}")
                continue
            handler(msg)
            if msg["type"] == P.GAME_OVER:
                self.conn.send(P.DISCONNECT, playerId=self.name, reason="game over")
                return 0


def parse_args(argv=None):
    """Command line options for the client."""
    parser = argparse.ArgumentParser(
        description="Battleship w/ Money console client.",
        epilog="Example: python3 client.py -i server.harvey.edu -p 5000")
    parser.add_argument("-i", "--ip", dest="hostname", required=True,
                        help="server hostname or IP address (resolved via DNS)")
    parser.add_argument("-p", "--port", type=P.port_type, required=True,
                        help="server TCP port (1024-65535)")
    parser.add_argument("-n", "--name", help="player name (prompted if omitted)")
    parser.add_argument("--auto", action="store_true",
                        help="bot mode for testing: random placement and automatic shots")
    return parser.parse_args(argv)


def connect(hostname, port):
    """Resolve the hostname via DNS and open a TCP connection."""
    try:
        if not hostname.strip():
            raise socket.gaierror("empty hostname")
        server_ip = socket.gethostbyname(hostname)
    except (socket.gaierror, UnicodeError):   # UnicodeError: e.g. 'a..b'
        print(f"[ERROR] Unable to resolve DNS hostname '{hostname}'.")
        print("Please check your Cisco router DNS configuration "
              "('ip dns server' / 'ip host') or verify domain spelling.")
        sys.exit(1)
    print(f"[INFO] Resolved {hostname} -> {server_ip}")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    try:
        sock.connect((server_ip, port))
    except ConnectionRefusedError:
        print(f"[ERROR] Connection refused by {hostname} ({server_ip}:{port}). "
              "Is the server running on that port?")
        sys.exit(1)
    except socket.timeout:
        print(f"[ERROR] Timed out connecting to {hostname} ({server_ip}:{port}).")
        sys.exit(1)
    except OSError as exc:
        print(f"[ERROR] Could not connect to {hostname} ({server_ip}:{port}): "
              f"{exc.strerror or exc}")
        sys.exit(1)
    sock.settimeout(None)
    print(f"[INFO] Connected to {server_ip}:{port}")
    return P.FramedConnection(sock)


def main():
    """Entry point."""
    args = parse_args()
    conn = connect(args.hostname, args.port)
    client = None
    exit_code = 1
    try:
        name = args.name
        while not name:
            name = input("Enter your player name: ").strip()
            if not sys.stdin.isatty():
                print(name)
        client = BattleshipClient(conn, name[:20], auto=args.auto)
        exit_code = client.run()
    except (QuitGame, KeyboardInterrupt, EOFError) as exc:
        print(f"\n[INFO] Leaving the game ({exc or 'interrupted'}).")
        try:
            conn.send(P.DISCONNECT, playerId=client.name if client else "",
                      reason="player quit")
        except OSError:
            pass
        exit_code = 0
    except P.ProtocolError as exc:
        print(f"[ERROR] Protocol error from server: {exc}")
    except OSError as exc:
        print(f"[ERROR] Connection lost: {exc.strerror or exc}")
    finally:
        conn.close()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
