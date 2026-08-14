from shifan_host_share.deskflow_engine import classify_deskflow_log


def test_raw_tcp_accept_is_not_treated_as_real_client_connection():
    assert classify_deskflow_log("server", "INFO: accepted client connection") is None


def test_server_requires_protocol_level_client_connected_log():
    event = classify_deskflow_log("server", 'DEBUG: client "PAIR-RIGHT" has connected')
    assert event is not None
    assert event[0] == "connected"


def test_client_protocol_handshake_is_real_connection():
    event = classify_deskflow_log("client", "DEBUG: connected to server")
    assert event is not None
    assert event[0] == "remote_connected"


def test_disconnect_events_restore_waiting_state():
    event = classify_deskflow_log("server", 'INFO: client "PAIR-RIGHT" has disconnected')
    assert event is not None
    assert event[0] == "client_disconnected"
