# Supplier API: negotiate with Tiwala from your own system

A supplier can answer a Tiwala buyer with its own software (an AI agent, an ERP rule, a script) instead of a
person. Tiwala sends offers; your system accepts, counters or rejects. Tiwala's buyer side replies within the
buyer's private limits, and an agreement still needs the buyer's own confirmation before any money moves.

A working example is [`scripts/supplier_agent_example.py`](../scripts/supplier_agent_example.py) (standard library
only). Try it against the local demo (`./scripts/local-demo.sh` prints the exact command).

## Access

1. The buyer saves you as a payee (your payout address) and issues your token:
   `cd agent && ../.venv/bin/python -m console.supplier_token "<your name as saved>"`.
2. Every request sends `Authorization: Bearer <token>` and `?supplier=<your address>`.

| Property | Behaviour |
| --- | --- |
| Scope | One supplier: read your own negotiations, answer offers, set your mandate. You never see the buyer's limits, other suppliers, the wallet, or the owner console |
| Format | HMAC-SHA256 of your address under a key kept in the buyer's data directory (owner-only file); 128 bits |
| Lifetime | Survives restarts; the buyer revokes all tokens by deleting `agent/data/supplier_token_secret` |
| Transport | Header only for API clients; never put it in a URL. Use HTTPS whenever the buyer exposes the endpoint beyond their machine |
| Errors | `403 supplier token required` (missing or wrong token), `403 not your negotiation`, `400` with a plain reason (for example `stale: the latest offer is v5, you answered v3`, or invalid terms) |

When your system first calls the API, the buyer's console shows you as connected, and the buyer can choose
"Supplier's own system (API)" when starting a negotiation with you.

## Endpoints

### `GET /api/supplier?supplier=<address>`

Your name, mandate and up to 10 recent negotiations. Poll it every few seconds. For each negotiation:

| Field | Meaning |
| --- | --- |
| `id`, `product`, `state` | `awaiting_acceptance` or `awaiting_clarification` means it is your turn |
| `mode` | `api` for negotiations your system answers |
| `proposals[]` | Every offer, newest last: `id`, `version`, `by` (`buyer`/`supplier`), `status` (`open`, `superseded`, `accepted`, ...), `terms`, `terms_hash`, `note`, `expires` |
| `terms` | `quantity`, `unit_price` (centavos), `deposit_bps` (basis points), `deliver_by` (unix seconds), `total`, `deposit` |
| `messages[]`, `agreement` | The conversation and, once both sides accept, the agreed terms |

### `POST /api/supplier/negotiations/<id>/move?supplier=<address>`

Answer the open buyer offer. Always send the `version`, `id` and `terms_hash` of the offer you are answering:
if the buyer has moved on, the move is refused as stale (`400`, reason starts with `stale:`) and you answer the
newer offer instead.

```json
{"type": "accept", "base_version": 3, "proposal_id": "…", "terms_hash": "…"}
{"type": "counter", "base_version": 3, "proposal_id": "…", "terms_hash": "…",
 "terms": {"quantity": 450, "unit_price_php": 111, "deposit_pct": 15, "deliver_by": "1792800000",
           "note": "Best we can do this month."}}
{"type": "reject", "base_version": 3, "proposal_id": "…", "terms_hash": "…", "reason": "Out of stock."}
```

`deliver_by` takes unix seconds (recommended: copy the buyer's) or `YYYY-MM-DD` (end of that day in the buyer's
time zone). The response is the updated negotiation, including Tiwala's reply if it countered.

### `PUT /api/supplier/mandate?supplier=<address>`

Optional. Stores your private limits for the simulated supplier agent that can answer for you on the buyer's
server. Not needed when your own system answers.

## What Tiwala guarantees your side

- Acceptance binds to one exact version and terms hash; a counter supersedes all earlier offers.
- Your text and notes are treated as data, never as instructions to the buyer's agent.
- A negotiation never moves money. The agreed terms become an on-chain escrow only after the buyer confirms;
  the deposit and balance are then paid to your saved payout address by the escrow contract.
