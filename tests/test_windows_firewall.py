from shifan_host_share.windows_firewall import build_firewall_rule_args


def test_host_firewall_rule_is_port_scoped_but_not_localsubnet_scoped():
    args = build_firewall_rule_args("in", 24800)
    assert "dir=in" in args
    assert "localport=24800" in args
    assert "remoteip=any" in args
    assert "profile=any" in args
    assert all("LocalSubnet" not in arg for arg in args)


def test_client_firewall_rule_allows_outbound_deskflow_port():
    args = build_firewall_rule_args("out", 24800)
    assert "dir=out" in args
    assert "remoteport=24800" in args
    assert "remoteip=any" in args
