from shifan_host_share.pairing import all_client_screen_names, client_screen_name, pairing_token


def test_pairing_token_is_deterministic_and_code_sensitive():
    assert pairing_token("ABCD-EFGH-2345") == pairing_token("abcd efgh 2345")
    assert pairing_token("ABCD-EFGH-2345") != pairing_token("ABCD-EFGH-2346")


def test_client_name_encodes_direction_without_exposing_code():
    name = client_screen_name("ABCD-EFGH-2345", "right")
    assert name.startswith("SF-R-")
    assert "ABCD" not in name
    names = all_client_screen_names("ABCD-EFGH-2345")
    assert set(names) == {"left", "right", "up", "down"}
    assert len(set(names.values())) == 4
