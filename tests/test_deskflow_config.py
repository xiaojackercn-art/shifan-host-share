from pathlib import Path

from shifan_host_share.deskflow_engine import _write_settings, build_server_config, reverse_direction
from shifan_host_share.pairing import all_client_screen_names


def test_direction_reverse():
    assert reverse_direction("right") == "left"
    assert reverse_direction("up") == "down"


def test_server_config_contains_all_authorized_screens():
    peers = all_client_screen_names("ABCD-EFGH-2345")
    text = build_server_config("HOST-1", peers)
    assert "HOST-1:" in text
    for direction, name in peers.items():
        assert f"{name}:" in text
        assert f"{direction} = {name}" in text
        assert f"{reverse_direction(direction)} = HOST-1" in text


def test_deskflow_server_settings_use_official_keys_without_pinning_interface(tmp_path: Path):
    settings = tmp_path / "server.ini"
    config = tmp_path / "deskflow.conf"
    config.write_text("section: screens\nend\n", "utf-8")
    _write_settings(
        settings,
        computer_name="HOST-1",
        port=24800,
        server_config=config,
    )
    text = settings.read_text("utf-8")
    assert "computerName=HOST-1" in text
    assert "port=24800" in text
    assert "processMode=1" in text
    assert "interface=" not in text
    assert "externalConfig=true" in text
    assert "tlsEnabled=false" in text


def test_client_remote_host_matches_official_deskflow_setting(tmp_path: Path):
    settings = tmp_path / "client.ini"
    _write_settings(settings, computer_name="PEER-2", port=24800, remote_host="192.168.1.6")
    text = settings.read_text("utf-8")
    assert "remoteHost=192.168.1.6" in text
    assert "port=24800" in text
