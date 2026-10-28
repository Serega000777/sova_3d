# Sova 3D — proposed subscriptions and credit packs (29.10.2026)

**Status:** product proposal exposed by the read-only pricing API; purchases, grants, debits,
refunds and renewals are not enabled. All money is stored in minor units (kopeks/cents).

## Product ladder

| Plan | Included credits / month | Seats | Russia | International |
|---|---:|---:|---:|---:|
| Free | 100 | 1 | ₽0 | $0 |
| Maker | 350 | 1 | ₽490 | $7.99 |
| Pro | 1,500 | 1 | ₽1,490 | $19.99 |
| Studio | 5,000 | 1 | ₽3,990 | $49.99 |
| Team | 15,000 | 5 | ₽9,990 | $129 |

Extra credits are permanent product credits in the proposed model:

| Pack | Russia | International |
|---:|---:|---:|
| 250 credits | ₽390 | $4.99 |
| 1,000 credits | ₽1,290 | $14.99 |
| 5,000 credits | ₽4,990 | $49.99 |

The Free tier is enough to prove capture, editing and export without a card. Maker is for
occasional object/print work. Pro is the individual working tier. Studio covers repeated AI,
scan and render workflows. Team includes five seats and a shared allowance. Feature access
must remain a separate entitlement decision: credits measure variable compute, not permission
to use basic offline editing tools.

## Benchmark and rationale

- [Polycam pricing](https://poly.cam/pricing) separates free discovery, an individual Basic
  plan and higher Business/Enterprise tiers; its paid value includes more capture, export,
  measurement and team capabilities.
- [Planner 5D pricing](https://planner5d.com/pricing) combines free planning, paid catalogue
  and professional workflows with included AI credits.
- [Meshy credit rules](https://help.meshy.ai/en/articles/9991981-how-do-meshy-credits-work)
  distinguish subscription credits from separately purchased permanent credits. Sova follows
  that user-friendly distinction in this proposal.
- [Meshy task costs](https://help.meshy.ai/en/articles/16815622-how-many-credits-does-each-meshy-api-task-cost)
  show why a visible per-operation catalogue is preferable to an opaque balance.

The RU ladder is intentionally not a converted USD price: it is a lower local-market proposal.
The international ladder sits near current individual AI/3D subscriptions while reserving a
team tier. These values still need margin validation against measured GPU/provider costs,
VAT/sales tax, store commissions, chargebacks and payment-provider fees before launch.

## Safety rules before real billing

1. Never debit in `shadow` mode. A quote is not a charge.
2. Grant and spend through an append-only, idempotent ledger; derive the balance from entries.
3. Charge only successful work; failed or cancelled work costs zero or receives an automatic,
   traceable reversal if a provider requires pre-authorization.
4. Show the price and balance before submission; record the pricing version with every entry.
5. Spend expiring subscription credits before permanent top-up credits.
6. Require explicit confirmation for a paid top-up, show taxes and renewal terms, and provide
   receipts plus a support-visible audit trail.
7. Launch enforcement per operation only after shadow measurements prove the quote covers cost
   without surprising users.

The canonical machine-readable proposal is `GET /api/v1/pricing`; action prices, plan prices
and pack prices are versioned together as `2026-10-29.v2` (`v1` remains the immutable first
action-only publication).
