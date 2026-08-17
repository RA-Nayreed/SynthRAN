from __future__ import annotations

import json
from pathlib import Path
import socket
import tempfile
import time
import unittest

from synthran.ingress import (
    CountedTcpIngress,
    IngressError,
    IngressSnapshot,
    main,
)


class IngressSnapshotTests(unittest.TestCase):
    def test_snapshot_to_dict_and_from_dict(self) -> None:
        snap = IngressSnapshot(accepted_connections=10, upstream_bytes=500, downstream_bytes=200)
        data = snap.to_dict()
        self.assertEqual(
            data,
            {
                "accepted_connections": 10,
                "upstream_bytes": 500,
                "downstream_bytes": 200,
            },
        )
        loaded = IngressSnapshot.from_dict(data)
        self.assertEqual(loaded, snap)

    def test_snapshot_from_dict_rejects_malformed(self) -> None:
        with self.assertRaises(IngressError):
            IngressSnapshot.from_dict("not-a-dict")  # type: ignore[arg-type]
        with self.assertRaises(IngressError):
            IngressSnapshot.from_dict({"accepted_connections": -1, "upstream_bytes": 0, "downstream_bytes": 0})
        with self.assertRaises(IngressError):
            IngressSnapshot.from_dict({"accepted_connections": 1, "upstream_bytes": "abc", "downstream_bytes": 0})


class CountedTcpIngressTests(unittest.TestCase):
    def test_port_validation(self) -> None:
        with self.assertRaisesRegex(IngressError, "ingress ports must be between 1 and 65535"):
            CountedTcpIngress(listen_port=0)
        with self.assertRaisesRegex(IngressError, "ingress ports must be between 1 and 65535"):
            CountedTcpIngress(target_port=70000)
        with self.assertRaisesRegex(IngressError, "ingress connect timeout must be positive"):
            CountedTcpIngress(connect_timeout=0)

    def test_write_snapshot_file_creates_atomic_json_without_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            snap_path = Path(temp_dir) / "snapshot.json"
            ingress = CountedTcpIngress(
                listen_host="127.0.0.1",
                listen_port=18881,
                target_host="127.0.0.1",
                target_port=18882,
            )
            ingress._accepted_connections = 5
            ingress._upstream_bytes = 1024
            ingress._downstream_bytes = 512
            ingress.write_snapshot_file(snap_path)

            self.assertTrue(snap_path.is_file())
            content = json.loads(snap_path.read_text(encoding="utf-8"))
            self.assertEqual(content["accepted_connections"], 5)
            self.assertEqual(content["upstream_bytes"], 1024)
            self.assertEqual(content["downstream_bytes"], 512)
            # Ensure no payload content is saved
            self.assertNotIn("payload", content)
            self.assertNotIn("data", content)

    def test_end_to_end_local_forwarding(self) -> None:
        # Create a mock upstream TCP server on loopback
        upstream_srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        upstream_srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        upstream_srv.bind(("127.0.0.1", 0))
        upstream_srv.listen(5)
        _, target_port = upstream_srv.getsockname()

        # Find a free port for ingress
        temp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        temp_sock.bind(("127.0.0.1", 0))
        _, listen_port = temp_sock.getsockname()
        temp_sock.close()

        ingress = CountedTcpIngress(
            listen_host="127.0.0.1",
            listen_port=listen_port,
            target_host="127.0.0.1",
            target_port=target_port,
        )
        ingress.start()

        def _upstream_echo() -> None:
            try:
                upstream_srv.settimeout(2.0)
                conn, _ = upstream_srv.accept()
                data = conn.recv(1024)
                if data:
                    conn.sendall(b"ECHO:" + data)
                conn.close()
            except OSError:
                pass
            finally:
                upstream_srv.close()

        import threading
        srv_thread = threading.Thread(target=_upstream_echo, daemon=True)
        srv_thread.start()

        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.connect(("127.0.0.1", listen_port))
            client.sendall(b"Hello SynthRAN")
            client.settimeout(2.0)
            response = client.recv(1024)
            client.close()

            self.assertEqual(response, b"ECHO:Hello SynthRAN")
            srv_thread.join(timeout=2.0)

            # Check snapshot counters
            time.sleep(0.2)
            snap = ingress.snapshot()
            self.assertEqual(snap.accepted_connections, 1)
            self.assertEqual(snap.upstream_bytes, len(b"Hello SynthRAN"))
            self.assertEqual(snap.downstream_bytes, len(b"ECHO:Hello SynthRAN"))
        finally:
            ingress.stop()


class IngressCliTests(unittest.TestCase):
    def test_cli_missing_snapshot_path_fails(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            main(["--listen-port", "1883"])
        self.assertNotEqual(ctx.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
