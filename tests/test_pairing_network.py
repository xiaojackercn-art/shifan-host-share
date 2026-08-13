from __future__ import annotations

from shifan_host_share.pairing import PairingClient, PairingService


def test_pairing_service_real_tcp_roundtrip_on_loopback():
    started = []
    service = PairingService(
        "127.0.0.1",
        0,
        lambda: "ABCD-EFGH-2345",
        lambda: {"device_name": "PEER", "device_id": "ABC123", "version": "0.4.0"},
        lambda host, port, name: (started.append((host, port, name)) is None, "started"),
        lambda: None,
    )
    service.start()
    try:
        probe = PairingClient.probe("127.0.0.1", service.port, source_ip="127.0.0.1")
        assert probe.device_name == "PEER"
        result = PairingClient.start_remote_client(
            "127.0.0.1",
            service.port,
            "ABCD-EFGH-2345",
            "127.0.0.1",
            24861,
            "PEER-ABC123",
            source_ip="127.0.0.1",
        )
        assert result["ok"] is True
        assert started == [("127.0.0.1", 24861, "PEER-ABC123")]
    finally:
        service.stop()
