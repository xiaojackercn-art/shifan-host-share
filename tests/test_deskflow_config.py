import configparser

import pytest

from shifan_host_share.deskflow_engine import build_server_config, safe_screen_name, _write_settings


@pytest.mark.parametrize("direction,opposite", [("right", "left"), ("left", "right"), ("up", "down"), ("down", "up")])
def test_config_links_both_directions(direction, opposite):
    text = build_server_config("HOST-A", "PEER-B", direction)
    assert f"{direction} = PEER-B" in text
    assert f"{opposite} = HOST-A" in text


def test_screen_names_are_ascii_safe():
    assert safe_screen_name("HOST", "你好 12-AB") == "HOST-12-AB"


def test_server_settings_match_deskflow_126_keys(tmp_path):
    server_config = tmp_path / "server.conf"
    server_config.write_text("section: screens\nend\n", "utf-8")
    settings = tmp_path / "server.ini"
    _write_settings(settings, computer_name="HOST-ABC", port=24861, server_config=server_config)
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read(settings, encoding="utf-8")
    assert cfg["core"]["computerName"] == "HOST-ABC"
    assert cfg["core"]["port"] == "24861"
    assert cfg["security"].getboolean("tlsEnabled") is False
    assert cfg["server"].getboolean("externalConfig") is True
    assert cfg["server"]["externalConfigFile"] == str(server_config)


def test_client_settings_match_deskflow_126_keys(tmp_path):
    settings = tmp_path / "client.ini"
    _write_settings(settings, computer_name="PEER-ABC", port=24861, remote_host="192.168.1.10")
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read(settings, encoding="utf-8")
    assert cfg["core"]["computerName"] == "PEER-ABC"
    assert cfg["client"]["remoteHost"] == "192.168.1.10"
    assert cfg["security"].getboolean("checkPeerFingerprints") is False
