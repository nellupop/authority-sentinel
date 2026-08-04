"""
Offline tests for authority_diff.py — no live network needed. Run with:
    python3 tests/test_authority_diff.py
"""
import base64
import importlib
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "authority-watch"))
import authority_diff as m  # noqa: E402


def test_base58_known_vectors():
    importlib.reload(m)
    assert m.b58encode(b"\x00" * 32) == "11111111111111111111111111111111"

    def b58decode(s):
        n = 0
        for ch in s:
            n = n * 58 + m.BASE58_ALPHABET.index(ch)
        return n.to_bytes(32, "big")

    known = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
    assert m.b58encode(b58decode(known)) == known
    print("test_base58_known_vectors: PASS")


def test_full_diff_flow_against_mocked_rpc(tmp_dir: Path):
    importlib.reload(m)

    fake_program_bytes = struct.pack("<I", 2) + bytes([1] * 32)
    programdata_addr = m.b58encode(fake_program_bytes[4:36])
    fake_pd_v1 = struct.pack("<I", 3) + struct.pack("<Q", 100) + bytes([1]) + bytes([2] * 32)
    fake_pd_v2 = struct.pack("<I", 3) + struct.pack("<Q", 200) + bytes([1]) + bytes([9] * 32)

    account_table = {"PROGRAM_ID_1": fake_program_bytes, programdata_addr: fake_pd_v1}

    def fake_rpc(method, params):
        pubkey = params[0]
        raw = account_table.get(pubkey)
        if raw is None:
            return {"result": {"value": None}}
        return {"result": {"value": {"data": [base64.b64encode(raw).decode(), "base64"]}}}

    m.rpc = fake_rpc
    m.PROGRAMS_FILE = tmp_dir / "programs.json"
    m.STATE_FILE = tmp_dir / "state.json"
    m.PROGRAMS_FILE.write_text(json.dumps([{"name": "test-program", "program_id": "PROGRAM_ID_1"}]))

    baseline, _ = _capture_stdout(m.main)
    assert json.loads(baseline)["changed_count"] == 0, "first-run baseline must not alert"

    stable, _ = _capture_stdout(m.main)
    assert json.loads(stable)["changed_count"] == 0, "unchanged authority must not alert"

    account_table[programdata_addr] = fake_pd_v2
    rotated, _ = _capture_stdout(m.main)
    result = json.loads(rotated)
    assert result["changed_count"] == 1, "rotated authority must alert exactly once"
    assert result["changed"][0]["name"] == "test-program"
    print("test_full_diff_flow_against_mocked_rpc: PASS")


def _capture_stdout(fn):
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn()
    return buf.getvalue().strip(), None


if __name__ == "__main__":
    import tempfile

    test_base58_known_vectors()
    with tempfile.TemporaryDirectory() as td:
        test_full_diff_flow_against_mocked_rpc(Path(td))
    print("ALL TESTS PASSED")
