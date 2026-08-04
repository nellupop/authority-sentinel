#!/usr/bin/env python3
"""
authority_diff.py — poll Solana BPF-Loader-Upgradeable program authorities,
diff against last-known state, print a compact JSON result to stdout.

Stdlib only (urllib, base64, json, struct) — no pip install needed.
RPC endpoint: $SOLANA_RPC_URL env var, falls back to a public mainnet RPC
(fine for occasional 5-minute polling of a handful of accounts; bring your
own Helius/Triton/QuickNode URL for anything beyond a demo).

Watchlist: programs.json next to this script.
State:     state.json next to this script (created on first run).

Exit code is always 0 on a completed poll (even individual RPC failures are
captured per-program in the output, not raised) — a transient RPC hiccup on
one program should not fail the whole SOP step.
"""
import base64
import json
import os
import struct
import urllib.request
import urllib.error
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
PROGRAMS_FILE = SKILL_DIR / "programs.json"
STATE_FILE = SKILL_DIR / "state.json"
RPC_URL = os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")

BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode(b: bytes) -> str:
    n = int.from_bytes(b, "big")
    out = ""
    while n > 0:
        n, rem = divmod(n, 58)
        out = BASE58_ALPHABET[rem] + out
    pad = len(b) - len(b.lstrip(b"\x00"))
    return "1" * pad + out


def rpc(method: str, params: list):
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    ).encode()
    req = urllib.request.Request(
        RPC_URL, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def get_account_bytes(pubkey: str):
    res = rpc("getAccountInfo", [pubkey, {"encoding": "base64"}])
    value = res.get("result", {}).get("value")
    if value is None:
        return None
    data_b64 = value["data"][0]
    return base64.b64decode(data_b64)


def upgrade_authority_for(program_id: str):
    """BPF-Loader-Upgradeable programs. Returns (authority_or_'immutable', error)."""
    try:
        prog_data = get_account_bytes(program_id)
        if prog_data is None:
            return None, "program account not found"
        discriminant = struct.unpack_from("<I", prog_data, 0)[0]
        if discriminant != 2:
            return None, f"unexpected discriminant {discriminant} (not an upgradeable Program account)"
        programdata_pubkey = b58encode(prog_data[4:36])

        pd_data = get_account_bytes(programdata_pubkey)
        if pd_data is None:
            return None, "programdata account not found"
        pd_discriminant = struct.unpack_from("<I", pd_data, 0)[0]
        if pd_discriminant != 3:
            return None, f"unexpected discriminant {pd_discriminant} (not a ProgramData account)"
        option_tag = pd_data[12]
        if option_tag == 0:
            return "immutable", None  # upgrade authority renounced
        authority = b58encode(pd_data[13:45])
        return authority, None
    except (urllib.error.URLError, OSError, KeyError, IndexError, struct.error) as e:
        return None, str(e)


def mint_authority_for(mint_id: str):
    """
    SPL Token classic Mint account (82 bytes, fixed layout, unchanged since
    the Token program's original spec):
      0..4   mint_authority COption tag (u32 LE: 0 absent, 1 present)
      4..36  mint_authority pubkey (meaningful only if tag == 1)
      36..44 supply (u64 LE)
      44     decimals (u8)
      45     is_initialized (bool)
      46..50 freeze_authority COption tag (u32 LE)
      50..82 freeze_authority pubkey (meaningful only if tag == 1)

    Returns (authority_str_or_'renounced', error) for BOTH mint and freeze
    authority, combined into one comparable string so a change in EITHER
    one triggers an alert: "mint=<X> freeze=<Y>".

    NOTE: Token-2022 (Token Extensions) mints carry additional TLV-encoded
    extension data past byte 82 (transfer fees, permanent delegate, etc.)
    that this does not parse -- the base authorities below still decode
    correctly since extensions are strictly appended, but an extension-only
    authority change (e.g. a permanent delegate) would not be caught. Not
    built here for the same reason the Squads multisig case isn't: I'd
    rather ship the verified fixed-layout case than a guessed TLV parser.
    """
    try:
        data = get_account_bytes(mint_id)
        if data is None:
            return None, "mint account not found"
        if len(data) < 82:
            return None, f"account too short ({len(data)} bytes) to be a Token Mint"

        mint_tag = struct.unpack_from("<I", data, 0)[0]
        mint_auth = b58encode(data[4:36]) if mint_tag == 1 else "renounced"

        freeze_tag = struct.unpack_from("<I", data, 46)[0]
        freeze_auth = b58encode(data[50:82]) if freeze_tag == 1 else "renounced"

        return f"mint={mint_auth} freeze={freeze_auth}", None
    except (urllib.error.URLError, OSError, KeyError, IndexError, struct.error) as e:
        return None, str(e)


DASHBOARD_FILE = SKILL_DIR / "index.html"


def render_dashboard(programs, results, last_run_iso):
    """Self-contained static HTML — no build step, safe to serve as-is from
    GitHub Pages or open locally. Grouped by category."""
    by_category = {}
    for entry in programs:
        by_category.setdefault(entry.get("category", "other"), []).append(entry)

    def row(entry):
        r = results.get(entry["program_id"], {})
        status = r.get("authority", "?")
        changed = r.get("changed", False)
        err = r.get("error")
        badge = (
            f'<span class="badge err">error</span>' if err else
            f'<span class="badge changed">changed</span>' if changed else
            f'<span class="badge ok">stable</span>'
        )
        status_line = err if err else status
        return f"""
        <tr>
          <td class="name">{entry['name']}</td>
          <td class="id"><a href="https://solscan.io/account/{entry['program_id']}" target="_blank" rel="noopener">{entry['program_id'][:8]}…{entry['program_id'][-6:]}</a></td>
          <td class="kind">{entry.get('kind', 'program')}</td>
          <td class="status">{status_line}</td>
          <td>{badge}</td>
        </tr>"""

    sections = ""
    for category, entries in sorted(by_category.items()):
        rows = "\n".join(row(e) for e in entries)
        sections += f"""
        <section>
          <h2>{category}</h2>
          <table>
            <thead><tr><th>Name</th><th>Address</th><th>Kind</th><th>Authority state</th><th></th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </section>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Authority Sentinel</title>
<style>
  :root {{
    --bg: #0b0d10; --panel: #14171c; --border: #232830;
    --text: #e6e9ef; --dim: #8a92a0; --accent: #6ee7b7;
    --warn: #f5b942; --err: #f2685c;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--text);
    font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    padding: 48px 24px 80px;
  }}
  .wrap {{ max-width: 880px; margin: 0 auto; }}
  h1 {{ font-size: 22px; font-weight: 600; margin: 0 0 4px; letter-spacing: -0.01em; }}
  .sub {{ color: var(--dim); font-size: 13px; margin: 0 0 40px; }}
  h2 {{
    font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--dim); font-weight: 600; margin: 0 0 10px;
  }}
  section {{ margin-bottom: 32px; }}
  table {{
    width: 100%; border-collapse: collapse; background: var(--panel);
    border: 1px solid var(--border); border-radius: 10px; overflow: hidden;
  }}
  th {{
    text-align: left; font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.05em; color: var(--dim); font-weight: 500;
    padding: 10px 14px; border-bottom: 1px solid var(--border);
  }}
  td {{ padding: 12px 14px; border-bottom: 1px solid var(--border); font-size: 13.5px; }}
  tr:last-child td {{ border-bottom: none; }}
  td.name {{ font-weight: 500; }}
  td.id a {{ color: var(--dim); text-decoration: none; font-family: ui-monospace, monospace; font-size: 12px; }}
  td.id a:hover {{ color: var(--text); }}
  td.kind {{ color: var(--dim); font-size: 12px; }}
  td.status {{ font-family: ui-monospace, monospace; font-size: 12px; color: var(--dim); }}
  .badge {{
    display: inline-block; padding: 2px 8px; border-radius: 20px;
    font-size: 11px; font-weight: 600;
  }}
  .badge.ok {{ background: rgba(110,231,183,0.12); color: var(--accent); }}
  .badge.changed {{ background: rgba(245,185,66,0.15); color: var(--warn); }}
  .badge.err {{ background: rgba(242,104,92,0.15); color: var(--err); }}
  footer {{ color: var(--dim); font-size: 12px; margin-top: 40px; }}
  footer a {{ color: var(--dim); }}
</style>
</head>
<body>
  <div class="wrap">
    <h1>Authority Sentinel</h1>
    <p class="sub">Last checked {last_run_iso} UTC · read-only · T0 · <a href="https://github.com/zeroclaw-labs/zeroclaw" style="color:var(--dim)">ZeroClaw</a></p>
    {sections}
    <footer>Static snapshot regenerated each poll. Source: authority_diff.py.</footer>
  </div>
</body>
</html>"""


def main():
    if not PROGRAMS_FILE.exists():
        print(json.dumps({"error": f"missing {PROGRAMS_FILE}", "changed_count": 0}))
        return

    programs = json.loads(PROGRAMS_FILE.read_text())
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}

    changed = []
    errors = []
    results = {}  # program_id -> {authority, changed, error} for the dashboard
    for entry in programs:
        name = entry["name"]
        program_id = entry["program_id"]
        kind = entry.get("kind", "program")
        fetch = mint_authority_for if kind == "mint" else upgrade_authority_for
        authority, err = fetch(program_id)

        if err:
            errors.append({"name": name, "program_id": program_id, "error": err})
            results[program_id] = {"authority": None, "changed": False, "error": err}
            continue

        last = state.get(program_id)
        did_change = last is not None and last != authority
        if did_change:
            changed.append(
                {
                    "name": name,
                    "program_id": program_id,
                    "previous_authority": last,
                    "new_authority": authority,
                }
            )
        state[program_id] = authority
        results[program_id] = {"authority": authority, "changed": did_change, "error": None}

    STATE_FILE.write_text(json.dumps(state, indent=2))

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    DASHBOARD_FILE.write_text(render_dashboard(programs, results, now))

    summary_lines = [
        f"{c['name']}: {c['previous_authority']} -> {c['new_authority']}" for c in changed
    ]
    print(
        json.dumps(
            {
                "changed_count": len(changed),
                "changed": changed,
                "errors": errors,
                "summary": "; ".join(summary_lines) if summary_lines else "no change",
            }
        )
    )


if __name__ == "__main__":
    main()
