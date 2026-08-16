"""Small counted TCP proxy used to join the Cooja IPv6 edge to the UE-side broker."""

from __future__ import annotations

from dataclasses import dataclass
import selectors
import socket
import threading
from typing import Callable


class ProxyError(RuntimeError):
    """Raised when the Phase 3 ingress proxy cannot operate safely."""


@dataclass(frozen=True)
class ProxySnapshot:
    accepted_connections: int
    upstream_bytes: int
    downstream_bytes: int


class CountedTcpProxy:
    """Forward one IPv6 listener to one IPv4 loopback target and count bytes.

    The proxy intentionally understands no MQTT.  It preserves the MQTT byte
    stream while providing deterministic ingress evidence at the Cooja/tun0
    boundary.  A separate MQTT bridge inside the srsUE network namespace is
    responsible for the actual 5G-bound connection.
    """

    def __init__(
        self,
        *,
        listen_host: str = "fd00::1",
        listen_port: int = 1883,
        target_host: str = "127.0.0.1",
        target_port: int = 18883,
        connect_timeout: float = 10.0,
    ) -> None:
        if not 1 <= listen_port <= 65535 or not 1 <= target_port <= 65535:
            raise ProxyError("proxy ports must be between 1 and 65535")
        if connect_timeout <= 0:
            raise ProxyError("proxy connect timeout must be positive")
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.target_host = target_host
        self.target_port = target_port
        self.connect_timeout = connect_timeout
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._listener: socket.socket | None = None
        self._lock = threading.Lock()
        self._accepted_connections = 0
        self._upstream_bytes = 0
        self._downstream_bytes = 0
        self._error: BaseException | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise ProxyError("proxy is already started")
        listener = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind((self.listen_host, self.listen_port))
            listener.listen(32)
            listener.settimeout(0.5)
        except OSError as exc:
            listener.close()
            raise ProxyError("unable to bind the Phase 3 IPv6 ingress listener") from exc
        self._listener = listener
        self._thread = threading.Thread(target=self._serve, name="synthran-phase3-proxy", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        listener = self._listener
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass
        thread = self._thread
        if thread is not None:
            thread.join(timeout=3.0)
        if self._error is not None:
            raise ProxyError("Phase 3 ingress proxy failed") from self._error

    def snapshot(self) -> ProxySnapshot:
        with self._lock:
            return ProxySnapshot(
                self._accepted_connections,
                self._upstream_bytes,
                self._downstream_bytes,
            )

    def _serve(self) -> None:
        assert self._listener is not None
        try:
            while not self._stop.is_set():
                try:
                    client, _ = self._listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    if self._stop.is_set():
                        return
                    raise
                with self._lock:
                    self._accepted_connections += 1
                worker = threading.Thread(
                    target=self._forward_connection,
                    args=(client,),
                    daemon=True,
                )
                worker.start()
        except BaseException as exc:  # stored and surfaced synchronously by stop()
            self._error = exc
            self._stop.set()

    def _forward_connection(self, client: socket.socket) -> None:
        upstream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            upstream.settimeout(self.connect_timeout)
            upstream.connect((self.target_host, self.target_port))
            upstream.setblocking(False)
            client.setblocking(False)
            selector = selectors.DefaultSelector()
            selector.register(client, selectors.EVENT_READ, (upstream, self._count_upstream))
            selector.register(upstream, selectors.EVENT_READ, (client, self._count_downstream))
            try:
                while not self._stop.is_set():
                    events = selector.select(timeout=0.5)
                    if not events:
                        continue
                    for key, _ in events:
                        destination, counter = key.data
                        try:
                            chunk = key.fileobj.recv(65536)
                        except BlockingIOError:
                            continue
                        if not chunk:
                            return
                        destination.sendall(chunk)
                        counter(len(chunk))
            finally:
                selector.close()
        except OSError:
            return
        finally:
            for connection in (client, upstream):
                try:
                    connection.close()
                except OSError:
                    pass

    def _count_upstream(self, count: int) -> None:
        with self._lock:
            self._upstream_bytes += count

    def _count_downstream(self, count: int) -> None:
        with self._lock:
            self._downstream_bytes += count
