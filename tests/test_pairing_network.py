from shifan_host_share.deskflow_engine import DEFAULT_PORT, build_server_config
from shifan_host_share.pairing import all_client_screen_names


def test_single_channel_server_config_pre_authorizes_all_screen_directions():
    peers = all_client_screen_names("ABCD-EFGH-2345")
    text = build_server_config("HOST-ABC", peers)
    assert DEFAULT_PORT == 24800
    assert "35999" not in text
    for direction, name in peers.items():
        assert name in text
        assert f"{direction} = {name}" in text
