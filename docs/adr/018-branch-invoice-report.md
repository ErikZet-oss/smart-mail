# ADR-018: Print report of an issued invoice per branch (by the invoice's centre)

Status: accepted (Erik, #174, 2026-10-31)

## Context
Each branch uses its own print report for issued invoices in Money. Smart Mail attaches the original Money PDF
(`GET /v2.0/IssuedInvoice/{id}/Report/{reportId}`, confirmed by the probe on TEST). Until now the report id came only
from the company settings 13b (per language).

## Decision
- `branches.money_report_ids` JSON `{"invoice": "...", "proforma": "..."}` (migration 0019), SK only, edited in 11e.
- The bridge reads `Stredisko_ID` of issued invoices (GraphQL, validated against the schema).
- The branch of an invoice = the branch whose `money_centre_id` equals the invoice's `Stredisko_ID`. Rules:
  SK / empty language → branch report, else company SK. EN/DE → company report of that language, else the branch
  report, else company SK. No centre, or a centre without a branch → 13b. Nothing → blocking `report_not_configured`.
- The selection runs at evaluation, again at approval (draft creation) and for reminders.
- 11e saves the centre only from Money's centre codebook (never a typed GUID).

## Consequences
Read-only (PDF only); no Money writes. The other 11e fields (price list, warehouse, series, template note) come with
Phase 4.
