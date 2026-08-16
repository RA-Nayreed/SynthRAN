"""Counted TCP ingress joining the Cooja IPv6 edge to the UE-side broker."""

from __future__ import annotations

from dataclasses import dataclass
import selectors
import socket
import threading


class IngressError(RuntimeError):
    """Raised when the experiment ingress proxy cannot operate safely."""


@dataclass(frozen=True)
class IngressSnapshot:
    accepted_connections: int
    upstream_bytes: int
    downstream_bytes: int


class CountedTcpIngress:
    """Forward one IPv6 listener to one IPv4 loopback target and count bytes."""

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
            raise IngressError("ingress ports must be between 1 and 65535")
        if connect_timeout <= 0:
            raise IngressError("ingress connect timeout must be positive")
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
            raise IngressError("ingress is already running")
        try:
            listener = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((self.listen_host, self.listen_port))
            listener.listen(128)
            listener.settimeout(0.5)
            self._listener = listener
        except OSError as exc:
            raise IngressError(
                f"unable to bind ingress on [{self.listen_host}]:{self.listen_port}"
            ) from exc

        thread = threading.Thread(target=self._run, daemon=True)
        self._thread = thread
        thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        if self._error is not None:
            raise IngressError("ingress failed during execution") from self._error

    def snapshot(self) -> IngressSnapshot:
        with self._lock:
            return IngressSnapshot(
                accepted_connections=self._accepted_connections,
                upstream_bytes=self._upstream_bytes,
                downstream_bytes=self._downstream_bytes,
            )

    def _run(self) -> None:
        assert self._listener is not None
        try:
            while not self._stop.is_set():
                try:
                    client, _ = self._listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                with self._lock:
                    self._accepted_connections += 1
                threading.Thread(
                    target=self._forward_connection,
                    args=(client,),
                    daemon=True,
                ).start()
        except BaseException as exc:
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
