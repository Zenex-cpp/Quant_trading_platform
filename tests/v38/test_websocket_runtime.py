from trading_platform.v37.user_stream_runtime import RecoveryAssessment, SessionState, UserStreamSessionCoordinator
from trading_platform.v38.websocket_runtime import BinanceUserStreamRuntime, SocketState, WebSocketConfig


class FakeSocket:
    def __init__(self):
        self.connected = False
        self.closed = False
        self.connect_calls = []

    def connect(self, url):
        self.connect_calls.append(url)
        self.connected = True

    def send(self, payload):
        pass

    def recv(self, timeout_s):
        return None

    def close(self):
        self.closed = True
        self.connected = False


class FakeControl:
    def __init__(self):
        self.pings = []

    def start(self):
        return "lk"

    def ping(self, listen_key):
        self.pings.append(listen_key)


def test_start_requires_tls_and_opens_socket():
    c = UserStreamSessionCoordinator()
    s = FakeSocket()
    r = BinanceUserStreamRuntime(coordinator=c, transport=s, config=WebSocketConfig(url="wss://test"))
    snap = r.start(listen_key="lk", now_epoch=1.0)
    assert snap.socket_state is SocketState.OPEN
    assert snap.trading_allowed
    assert s.connect_calls == ["wss://test"]


def test_disconnect_and_reconnect_remain_blocked_until_recovery():
    c = UserStreamSessionCoordinator()
    s = BinanceUserStreamRuntime(coordinator=c, transport=FakeSocket())
    s.start(listen_key="lk", now_epoch=1.0)
    s.on_disconnect(now_epoch=2.0)
    assert not s.snapshot(2.0).trading_allowed
    snap = s.reconnect(listen_key="lk2", now_epoch=3.0)
    assert snap.session_state is SessionState.RECOVERING
    assert not snap.trading_allowed
    s.run_recovery(lambda cause: RecoveryAssessment(True, "OK", True, True, True), now_epoch=3.1)
    assert s.snapshot(3.1).trading_allowed


def test_keepalive_is_explicit_and_network_injected():
    c = UserStreamSessionCoordinator()
    r = BinanceUserStreamRuntime(coordinator=c, transport=FakeSocket())
    r.start(listen_key="lk", now_epoch=1.0)
    ctrl = FakeControl()
    snap = r.keepalive(ctrl, now_epoch=2.0)
    assert snap.last_ping_epoch == 2.0
    assert ctrl.pings == ["lk"]


def test_socket_close_blocks_trading():
    c = UserStreamSessionCoordinator()
    sock = FakeSocket()
    r = BinanceUserStreamRuntime(coordinator=c, transport=sock)
    r.start(listen_key="lk", now_epoch=1.0)
    snap = r.close(now_epoch=2.0)
    assert snap.socket_state is SocketState.CLOSED
    assert not snap.trading_allowed
    assert sock.closed
