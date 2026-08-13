from __future__ import annotations

from shifan_host_share.pairing import PairingClient, PairingService


def test_v06_secondary_initiates_every_connection_to_host():
    authorized = []
    service = PairingService(
        "127.0.0.1",
        0,
        lambda: "ABCD-EFGH-2345",
        lambda: {
            "device_name": "HOST-PC",
            "device_id": "HOST123",
            "version": "0.6.0",
            "host_ready": True,
            "role": "host",
        },
        lambda client_name, direction: (authorized.append((client_name, direction)) is None, "started", 24800),
    )
    service.start()
    try:
        probe = PairingClient.probe("127.0.0.1", service.port)
        assert probe.device_name == "HOST-PC"
        assert probe.host_ready is True
        result = PairingClient.authorize_client(
            "127.0.0.1",
            service.port,
            "ABCD-EFGH-2345",
            "PEER-ABC123",
            "right",
        )
        assert result["ok"] is True
        assert result["server_port"] == 24800
        assert authorized == [("PEER-ABC123", "right")]
    finally:
        service.stop()
