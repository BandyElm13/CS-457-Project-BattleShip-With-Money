"""
protocal.py - Shared wire protocol for Battleship w/ Money.

Implements the Sprint 1 blueprint (protocal_blueprint.md):

* Transport: TCP stream sockets (AF_INET, SOCK_STREAM).
* Serialization: structured JSON, UTF-8 encoded.
* Framing: every message is prefixed with a 4-byte big-endian unsigned
  length header, followed by exactly that many bytes of JSON:

      00 00 00 2a {"type":"MOVE","x":3,"y":7,"playerId":"p1"}

Because TCP is a byte stream, a single recv() may return half a frame or
several frames glued together.  ``FramedConnection`` keeps a per-socket
receive buffer and only hands complete frames to the caller, so partial
and merged chunks are both handled deterministically.
"""

import json
import socket
import struct
import threading

# ---------------------------------------------------------------------------
# Framing constants
# ---------------------------------------------------------------------------
HEADER = struct.Struct("!I")        # 4-byte big-endian unsigned length
HEADER_SIZE = HEADER.size
MAX_MESSAGE_SIZE = 64 * 1024        # reject absurd lengths (malformed peer)
RECV_CHUNK = 4096

# ---------------------------------------------------------------------------
# Game constants (shared by client and server)
# ---------------------------------------------------------------------------
BOARD_WIDTH = 10
BOARD_HEIGHT = 10
MONEY_PER_HIT = 500
TOTAL_ROUNDS = 3
STARS_TO_WIN = 3

# ---------------------------------------------------------------------------
# Message types (protocal_blueprint.md section 2.2)
# ---------------------------------------------------------------------------
# Client -> Server
JOIN = "JOIN"                # join the lobby with a player name
PICK = "PICK"                # ship placements for the current round
MOVE = "MOVE"                # attack coordinate (x, y)
REJOIN = "REJOIN"            # reconnect with the same name after a drop
DISCONNECT = "DISCONNECT"    # graceful leave (also relayed Server->Client)

# Server -> Client
LOBBY_WAIT = "LOBBY_WAIT"    # joined, waiting for player 2
BOARD_RESET = "BOARD_RESET"  # (new) round: please send PICK
START_ROUND = "START_ROUND"  # both fleets accepted, here is your board
YOUR_TURN = "YOUR_TURN"      # broadcast: whose turn it is (playerId)
HIT = "HIT"
MISS = "MISS"
MONEY = "MONEY"              # attacker's money after a hit
STAR = "STAR"                # round winner's star count
GAME_OVER = "GAME_OVER"      # final result + scoreboard
ERROR = "ERROR"              # invalid move / malformed packet / timeout

CLIENT_TYPES = {JOIN, PICK, MOVE, REJOIN, DISCONNECT}
SERVER_TYPES = {LOBBY_WAIT, BOARD_RESET, START_ROUND, YOUR_TURN, HIT, MISS,
                MONEY, STAR, GAME_OVER, ERROR, DISCONNECT, REJOIN}

# Required fields per client message type (used by validate()).
_REQUIRED_FIELDS = {
    JOIN: {"playerId": str},
    REJOIN: {"playerId": str},
    PICK: {"playerId": str, "data": dict},
    MOVE: {"playerId": str, "x": int, "y": int},
    DISCONNECT: {},
}


class ProtocolError(Exception):
    """Raised when a peer sends a malformed frame or message."""


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------
def make_message(msg_type, **fields):
    """Build a message dict ``{"type": msg_type, **fields}``."""
    message = {"type": msg_type}
    message.update(fields)
    return message


def encode_message(message):
    """Serialize a dict to JSON and prepend the 4-byte length header."""
    payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_MESSAGE_SIZE:
        raise ProtocolError(f"message too large ({len(payload)} bytes)")
    return HEADER.pack(len(payload)) + payload


def decode_payload(payload):
    """Parse a JSON payload (bytes) into a dict with a string 'type'."""
    try:
        message = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"invalid JSON payload: {exc}") from exc
    if not isinstance(message, dict) or not isinstance(message.get("type"), str):
        raise ProtocolError("message must be a JSON object with a 'type' field")
    return message


def validate(message):
    """
    Validate a client->server message against the blueprint schema.

    Returns None when valid, otherwise a human-readable reason string.
    (bool is rejected for int fields because JSON true/false would
    otherwise sneak through isinstance(x, int).)
    """
    msg_type = message.get("type")
    if msg_type not in _REQUIRED_FIELDS:
        return f"unknown message type '{msg_type}'"
    for field, expected in _REQUIRED_FIELDS[msg_type].items():
        value = message.get(field)
        if not isinstance(value, expected) or isinstance(value, bool):
            return f"field '{field}' must be {expected.__name__}"
    return None


# ---------------------------------------------------------------------------
# Framed connection wrapper
# ---------------------------------------------------------------------------
class FramedConnection:
    """
    Wraps a connected TCP socket and exchanges length-prefixed JSON frames.

    * ``recv_message`` buffers raw bytes until a full frame is available,
      so it is correct no matter how TCP splits or merges segments.
    * ``send_message`` is guarded by a lock so several server threads can
      safely write to the same socket (e.g. broadcasts) without
      interleaving bytes of different frames.
    """

    def __init__(self, sock):
        self.sock = sock
        self._buffer = bytearray()
        self._send_lock = threading.Lock()
        self.closed = False

    # -- sending ----------------------------------------------------------
    def send_raw(self, frame):
        """Send an already-encoded frame (used by broadcast: encode once)."""
        with self._send_lock:
            self.sock.sendall(frame)

    def send_message(self, message):
        """Encode and send a single message dict."""
        self.send_raw(encode_message(message))

    def send(self, msg_type, **fields):
        """Convenience: build + send a message."""
        self.send_message(make_message(msg_type, **fields))

    # -- receiving --------------------------------------------------------
    def _extract_frame(self):
        """Return one complete payload from the buffer, or None."""
        if len(self._buffer) < HEADER_SIZE:
            return None
        (length,) = HEADER.unpack_from(self._buffer, 0)
        if length > MAX_MESSAGE_SIZE:
            raise ProtocolError(f"frame length {length} exceeds limit")
        if len(self._buffer) < HEADER_SIZE + length:
            return None
        payload = bytes(self._buffer[HEADER_SIZE:HEADER_SIZE + length])
        del self._buffer[:HEADER_SIZE + length]
        return payload

    def recv_message(self):
        """
        Block until one full message arrives and return it as a dict.

        Returns None when the peer closed the connection cleanly.
        Raises ProtocolError on malformed data and OSError on socket errors.
        """
        while True:
            payload = self._extract_frame()
            if payload is not None:
                return decode_payload(payload)
            chunk = self.sock.recv(RECV_CHUNK)
            if not chunk:
                if self._buffer:
                    raise ProtocolError("connection closed mid-frame")
                return None
            self._buffer.extend(chunk)

    # -- teardown ---------------------------------------------------------
    def close(self):
        """Shut down and close the socket (idempotent)."""
        if self.closed:
            return
        self.closed = True
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()


# ---------------------------------------------------------------------------
# CLI helper shared by client.py and server.py
# ---------------------------------------------------------------------------
def port_type(value):
    """argparse type: an integer TCP port in the range 1024-65535."""
    import argparse
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"invalid port '{value}': must be an integer") from None
    if not 1024 <= port <= 65535:
        raise argparse.ArgumentTypeError(
            f"invalid port {port}: must be between 1024 and 65535")
    return port
