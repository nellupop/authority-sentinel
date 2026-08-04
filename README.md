# Authority Sentinel

A ZeroClaw agent that watches a Solana program's upgrade authority (and,
extension point below, a governing Squads multisig's member set) and pings
you on Telegram the moment it changes — silent otherwise.

Built for the ZeroClaw × Solana bounty. Tier 1 (stock release binary, one
skill, one SOP, zero plugins).

## What it does, and who it's for

Anyone who relies on a Solana program's admin key staying where they expect
it — a bug-bounty hunter tracking programs they audit, an LP watching a
protocol's multisig, a team monitoring their own deploy — gets pushed a
Telegram message the moment the on-chain upgrade authority (or, later, the
multisig membership behind it) rotates. No dashboard to remember to check.

This is the automated version of the governance-surface check I do by hand
on every EVM contract I audit (who can call the privileged function, and can
that answer change without me noticing) — same question, Solana-native,
running unattended.

## Custody tier & threat model

**T0 — read-only.** The agent never holds a wallet, never signs, never
submits a transaction. It makes exactly one class of on-chain call
(`getAccountInfo`, read-only) and one off-chain call (Telegram
`sendMessage`). Secrets held: an optional RPC key (config secret, never in
code) and a Telegram bot token (config secret).

**Prompt-injection surface: none applicable.** The bounty's required
injection test applies to agents that *touch funds* — this one structurally
can't be talked into moving anything, because there is nothing in its tool
set capable of moving anything. The one tool with attacker-reachable input
in principle (`authority_diff`) takes **zero arguments** — it reads a local
watchlist file the operator controls, not anything from an inbound message —
so there's no injectable parameter surface to test in the first place. This
is a design property, not a mitigation: the tool's schema has no input
fields for a malicious payload to land in.

**Third-party trust declared:** your RPC provider (public mainnet RPC by
default, bring your own Helius/Triton/QuickNode for anything past a demo)
and Telegram's Bot API. Neither can act on your behalf; both can only see
read requests / receive a text message.

## ZeroClaw features used

- **Skill** (`skills/authority-watch/`) — one narrowly-scoped `shell`-kind
  tool (`authority_diff`), stdlib-only Python, no external dependencies.
- **SOP** (`sops/authority-watch/`) — cron-triggered, two-step deterministic
  pipeline with a `when:`-guarded branch so it only posts on an actual
  change.
- **Channel** — Telegram, hit directly via the Bot API through the stock
  `http_request` tool (see note in `SOP.md` on why).
- **Config secrets** — RPC key and bot token via `zeroclaw config set`,
  never in a file.

## What I had to build

- `authority_diff.py` — the actual authority-fetch-and-diff logic. Parses
  the BPF Loader Upgradeable account layout directly (no SDK dependency):
  reads the `Program` account's 4-byte enum discriminant + 32-byte
  `programdata_address`, then the `ProgramData` account's discriminant +
  `Option<Pubkey>` upgrade-authority field, including the "renounced /
  immutable" case (`Option` tag byte `0`) as a distinct, alert-worthy state
  rather than an error.
- A from-scratch base58 encoder (18 lines, stdlib `int.from_bytes` + repeated
  divmod) — kept dependency-free deliberately, so `python3` alone is enough
  and there's nothing to `pip install` for someone reproducing this.

**Tested, not just written:** the byte-offset parsing and base58 encoding
are checked against real, well-known Solana pubkeys (System Program's
all-zero 32 bytes -> `11111111111111111111111111111111`; Token Program's
address round-tripped through decode->encode) before ever touching a live
RPC endpoint, and the full diff/state-tracking flow (baseline run -> stable
run -> simulated authority rotation) is exercised end-to-end against a mocked
RPC layer. See `tests/test_authority_diff.py`.

## Setup (reproduce this in an evening)

1. Install ZeroClaw (stock release binary -- no source build needed):
   ```sh
   curl -fsSL https://raw.githubusercontent.com/zeroclaw-labs/zeroclaw/master/install.sh | bash
   ```
2. Copy `skills/authority-watch/` to `<install>/shared/skills/security/authority-watch/`
   and `sops/authority-watch/` to `<install>/shared/sops/authority-watch/`.
3. `cp skills/authority-watch/programs.json.example skills/authority-watch/programs.json`
   and fill in the program IDs you actually want watched.
4. Merge `config.toml.snippet` into your config (see that file for exactly
   what to set via masked `zeroclaw config set` vs. plain TOML).
5. Optionally: `export SOLANA_RPC_URL=https://your-rpc-provider/...` in the
   environment ZeroClaw's daemon runs under.
6. `zeroclaw sop validate authority-watch` and `zeroclaw skills audit
   authority-watch` -- **see the two open verification items below before
   trusting this blindly.**
7. `zeroclaw daemon` (or `zeroclaw service install && zeroclaw service
   start` for always-on).

## Two things to verify before first real run (flagged, not guessed past)

I built this against the published docs rather than a live install, and two
spots depend on schema details the docs render dynamically at doc-build time
and I couldn't resolve from raw source:

1. **`SOP.toml`'s cron trigger field name.** I used `schedule = "*/5 * * * *"`
   based on convention; the docs page's field table
   (`docs/book/src/sop/fan-in/cron.md`) is generated from the live
   `CronTrigger` schema via an mdbook macro that didn't render in the raw
   markdown I fetched. `zeroclaw sop validate authority-watch` will say
   immediately if the key name is wrong.
2. **How step 2's `http_request` body pulls step 1's piped output.** The
   docs confirm "each step's output pipes to the next" but I didn't find
   the exact interpolation syntax for referencing `$.steps.1.summary` inside
   a tool call's own arguments (as opposed to a `when:` guard, which *is*
   documented). Worth a `zeroclaw sop show authority-watch` and a dry run
   with a throwaway Telegram chat before pointing it at anything that
   matters.

Everything else here -- the skill/SOP directory layout, the `when`/`next`
routing, the `SKILL.toml` shape, the config sections -- matches what's
documented in the current `master` branch as of this build.

## Extension point: Squads multisig membership

The BPF-Loader-Upgradeable authority is often itself a Squads v4 multisig,
not an EOA -- rotating a *member* of that multisig doesn't change the
upgrade-authority pubkey the script above tracks. Watching the multisig's
own member/threshold account is the natural next layer, left out of this
first cut deliberately: it means parsing an Anchor-discriminated account
(8-byte sighash + borsh-encoded fields) rather than the fixed, hand-documented
BPF loader layout, and I'd rather ship the smaller, fully-verified thing than
a guessed Anchor layout I couldn't test against a real deployed multisig.

## Watchlist: five categories

`skills/authority-watch/programs.json` ships with real, verified addresses
across five categories. Two need your attention before you trust them —
flagged below, not silently guessed past:

| Category | Entries | Kind |
|---|---|---|
| `infrastructure` | Meteora DLMM | `program` |
| `infrastructure` | **Helius — placeholder, see note** | — |
| `memes` | PNUT, CHILLGUY, **ANSEM — unverified, see note** | `mint` |
| `dex-aggregation` | Jupiter Aggregator v6 | `program` |
| `lending` | Kamino Lending | `program` |
| `oracles` | Switchboard On-Demand | `program` |

**On Helius:** I couldn't find one canonical "Helius program" to watch —
they're primarily an off-chain RPC/API/indexer provider, not a single
on-chain protocol the way Meteora is. There's no honest program ID to put
here. Options: swap it for **Squads Protocol** (multisig infra — genuinely
fitting, since "the agent proposes, a Squads multisig disposes" is the
exact pattern the bounty brief calls out as the strongest custody design),
or tell me what on-chain surface you actually meant by "Helius" and I'll
find the right address.

**On ANSEM:** multiple sources explicitly warn this is "a cluster of Solana
memecoins using the influencer's name, not one official coin," with active
imitators. I found one candidate (`9cRCn9rG...TGpump`, referred to as "The
Black Bull") from a single corroborating source. **Confirm this on Solscan
yourself against the ticker/socials you actually trust before shipping it**
— this is exactly the kind of address where being wrong is a real, visible
mistake, not just a rebuild.

**Kind matters:** `program` entries check BPF-Loader-Upgradeable upgrade
authority. `mint` entries check the SPL Token mint's own mint + freeze
authority — a meme coin isn't a separate "program" the way Meteora or
Jupiter are (they're accounts under Solana's shared Token program), so
watching the same field for both would either error out or silently check
the wrong thing. The script dispatches on each entry's `"kind"` field.

## Dashboard

Every run also writes `skills/authority-watch/index.html` — a self-contained
static page (inline CSS, zero JS, zero dependencies) grouped by category,
with a stable/changed/error badge per entry and a Solscan link on every
address. Screenshot-worthy for the X thread, and exactly what a "clean
website" for this should look like without standing up a server.

**Ship it free, on GitHub Pages, using the repo you're already pushing:**

```sh
# after your first real `zeroclaw daemon` run has generated a real index.html
cd authority-sentinel
git add skills/authority-watch/index.html
git commit -m "dashboard snapshot"
git push
```

Then on GitHub: **Settings → Pages → Deploy from a branch → `main` → `/skills/authority-watch`** (or move `index.html` to the repo root if GitHub Pages
on your account only offers root/`docs` as options — check what your repo
settings actually show). Free, no server, URL is `https://<you>.github.io/authority-sentinel/`.

The page is a static snapshot from the *last* poll, not live — good enough
for "here's proof this is really running" in your write-up; if you want it
live-live later, that's a GitHub Action on a schedule re-running the poll
and re-publishing, which is a real next step but not needed for the bounty.

## Linux setup (Dell Precision 3480 / any x86_64 Linux)

```sh
# 1. Install
curl -fsSL https://raw.githubusercontent.com/zeroclaw-labs/zeroclaw/master/install.sh | bash

# 2. Confirm it installed and find the install root
zeroclaw --version
ls ~/.zeroclaw    # this is almost certainly <install> below; adjust if the
                   # installer printed something different

# 3. Unpack this project (wherever you downloaded authority-sentinel.tar.gz)
tar -xzf authority-sentinel.tar.gz
cd authority-sentinel

# 4. Place the skill and SOP
mkdir -p ~/.zeroclaw/shared/skills/security ~/.zeroclaw/shared/sops
cp -r skills/authority-watch ~/.zeroclaw/shared/skills/security/authority-watch
cp -r sops/authority-watch   ~/.zeroclaw/shared/sops/authority-watch

# 5. programs.json is already filled in (skills/authority-watch/programs.json)
#    — fix the two flagged entries above before going further

# 6. Merge config.toml.snippet into ~/.zeroclaw/config.toml, run the masked
#    secret prompts it calls out (bot_token, api_key)

# 7. THE VALIDATION STEP — run this and paste me the output:
zeroclaw sop validate authority-watch
zeroclaw skills audit authority-watch

# 8. Once both are clean:
zeroclaw daemon
```

Paste me the output of step 7 verbatim, including any error — that's what
resolves the two open syntax questions flagged earlier in this README.
