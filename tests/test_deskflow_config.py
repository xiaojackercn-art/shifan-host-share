import pytest
from shifan_host_share.deskflow_engine import build_server_config, safe_screen_name
@pytest.mark.parametrize("direction,opposite",[("right","left"),("left","right"),("up","down"),("down","up")])
def test_config_links_both_directions(direction,opposite):
    text=build_server_config("HOST-A","PEER-B",direction); assert f"{direction} = PEER-B" in text; assert f"{opposite} = HOST-A" in text
def test_screen_names_are_ascii_safe(): assert safe_screen_name("HOST","你好 12-AB") == "HOST-12-AB"
