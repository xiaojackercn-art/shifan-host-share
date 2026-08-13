from pathlib import Path

from shifan_host_share.deskflow_engine import _write_settings, build_server_config, reverse_direction


def test_direction_reverse():
    assert reverse_direction("right") == "left"
    assert reverse_direction("up") == "down"


def test_server_config_contains_both_screens():
    text = build_server_config("HOST-1", "PEER-2", "right")
    assert "HOST-1:" in text
    assert "PEER-2:" in text
    assert "right = PEER-2" in text
    assert "left = HOST-1" in text


def test_deskflow_settings_use_official_keys_and_interface(tmp_path: Path):
    settings = tmp_path / "server.ini"
    config = tmp_path / "deskflow.conf"
    config.write_text("section: screens\nend\n", "utf-8")
    _write_settings(
        settings,
        computer_name="HOST-1",
        port=24800,
        server_config=config,
        interface="192.168.1.6",
    )
    text = settings.read_text("utf-8")
    assert "computerName=HOST-1" in text
    assert "port=24800" in text
    assert "processMode=1" in text
    assert "interface=192.168.1.6" in text
    assert "externalConfig=true" in text
    assert "tlsEnabled=false" in text


def test_client_remote_host_matches_official_deskflow_setting(tmp_path: Path):
    settings = tmp_path / "client.ini"
    _write_settings(settings, computer_name="PEER-2", port=24800, remote_host="192.168.1.6")
    text = settings.read_text("utf-8")
    assert "remoteHost=192.168.1.6" in text
    assert "port=24800" in text
