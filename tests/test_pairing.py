from shifan_host_share.pairing import sign_payload, verify_payload

def test_pairing_proof_accepts_correct_code():
    payload={"protocol":2,"action":"start_client","timestamp":1_700_000_000,"nonce":"abc","server_ip":"192.168.1.2","server_port":24861,"client_name":"PEER-A"}; payload["proof"]=sign_payload(payload,"ABCD-EFGH-2345"); assert verify_payload(payload,"abcd efgh 2345",now=1_700_000_010)

def test_pairing_proof_rejects_wrong_code():
    payload={"protocol":2,"action":"stop_client","timestamp":1_700_000_000,"nonce":"abc"}; payload["proof"]=sign_payload(payload,"ABCD-EFGH-2345"); assert not verify_payload(payload,"ABCD-EFGH-9999",now=1_700_000_000)
