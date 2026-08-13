from shifan_host_share.config import normalize_pair_code
def test_pair_code_normalization(): assert normalize_pair_code("abCD-ef12 3456") == "ABCDEF123456"
