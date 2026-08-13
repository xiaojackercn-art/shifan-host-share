from shifan_host_share.config import format_pair_code, format_pair_code_input, normalize_pair_code


def test_pair_code_formatting_for_storage():
    assert format_pair_code("abcdEFGH2345") == "ABCD-EFGH-2345"
    assert format_pair_code("abcd-efgh-2345") == "ABCD-EFGH-2345"
    assert normalize_pair_code("ab-cd") == "ABCD"


def test_pair_code_input_adds_separator_after_each_four_characters():
    assert format_pair_code_input("abcd") == "ABCD-"
    assert format_pair_code_input("abcdE") == "ABCD-E"
    assert format_pair_code_input("abcdEFGH") == "ABCD-EFGH-"
    assert format_pair_code_input("abcdEFGH2345") == "ABCD-EFGH-2345"
    assert format_pair_code_input("abcd-efgh-2345-more") == "ABCD-EFGH-2345"
