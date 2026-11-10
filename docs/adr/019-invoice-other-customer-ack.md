# ADR-019: Another company's invoice — offered only with a red warning and a person's explicit confirmation

Status: accepted (Erik, #215, 2026-11-10)

## Context
CLAUDE.md §11 requires a recipient ↔ document-owner check on every Money document: an issued invoice is attached
and sent only to its own customer. In the pilot, a customer asked for the invoice of an e-shop order. The order
number found the invoice (#210), but Money had issued it to a **different company**: with e-shop orders the
person who orders and the customer on the invoice are often different (an employee, an intermediary). The owner
check dropped the invoice, so no card was shown at all, and someone had to look it up by hand.

## Decision (a deliberate exception to §11)
- When the mail itself identified the invoice — a written invoice number / VS, or the order number in the invoice
  „Popis“ (#210) — and none of the found invoices belongs to the sender, the invoices of **one** other company are
  offered on the card with a check `invoice_other_customer` of the new level **`requires_ack`**:
  „Faktúra je vystavená na {odberateľ}, žiada {žiadateľ}“. Only here may the card name the other company; the amount
  stays on the invoice line. „Odosielateľ nie je potvrdený“ is merged into the same single tick.
- Never for „the last invoice“ (#182 stays limited to a sender strongly matched to its own company), never when
  the sender has an invoice of its own in the same mail (that path is unchanged), never for several owners.
- The primary action stays disabled until the person ticks „Overil som, že odosielateľ smie dostať túto faktúru“.
- `POST /api/suggestions/{id}/approve` must carry `acknowledged_checks: ["invoice_other_customer"]`, else **409
  `ack_required`**. Approve re-checks live in Money that the invoice still exists and its customer is unchanged,
  else 409. The ack (person, account, time) is stored in `ai_suggestions.final_payload.ack` — no new column — and
  audited as `money.invoice_other_customer_ack` (person, account, suggestion, invoice numbers, owner, requester
  e-mail; no mail content).
- Such a suggestion is always `batch_safe = false` (batch approve never takes it); autonomy 3–4 stays impossible for
  external sends.
- The PDF marker `compose/<draft>/money-invoice/<company>` names the **invoice's customer**. The send guard accepts
  recipients outside that company only when an approved suggestion with this ack exists for **exactly this draft**
  and this company — and then only for **the one address the person saw on the card** (`final_payload.ack.email`),
  plus internal addresses and addresses of the invoice's own company. Any other external address in To / Cc / Bcc,
  or the confirmed address replaced by another one, is blocked (`recipient_not_document_owner`). Another company's
  invoice attached by hand, or an ack of another draft, stays blocked.

## Consequences
- A person always decides; the AI never sends another company's invoice on its own and never in a batch.
- The other company's name is visible to the person deciding — necessary for the decision, never in logs.
- Read-only towards Money; no data-model change.
