# NPRA recall guideline (source for `app/rules/actions.yaml`)

**Source:** NPRA, *Drug Registration Guidance Document (DRGD) Third Edition, 12th Revision July 2026*, **Appendix 34: Guideline for Product Quality Reporting and Recall Procedures** (17 pages), from the [DRGD e-book page](https://www.npra.gov.my/index.php/en/drug-registration-guidance-documents-drgd-e-book.html).
Fetched 23 Oct 2026. `npra_drgd_appendix34_recall_guideline.txt` is a plain-text extract made with `pypdf` (tables come out one cell per line). Cite rules as `DRGD App. 34 §x.y`.

## Degree of recall (§4.3): how urgent

| Degree | Meaning | Embargo (stop selling) within | Recalling company notifies purchasers within |
|---|---|---|---|
| I | major health risk, may cause serious injury or death | 24 hours | 24 hours of recall start |
| II | minor health risk, or substandard | 72 hours | 48 hours |
| III | other reasons that can cause health risks | 30 days, or as specified | 72 hours |

The notice to purchasers includes the instruction to **immediately cease sale and supply** (§4.3).

## Level of recall (§4.4): how far down the chain

| Level | Recalled from | Applies to a retail pharmacy? | Recall-page wording in `npra_recalls.csv` (`level`) |
|---|---|---|---|
| A: all consumers (end users) | wholesalers, retailers **and consumers who were supplied** | yes, and customers must be reached | `consumer`, `hospital and consumer` |
| B: all points of sale | wholesalers and retailers, incl. retail pharmacies | yes | `sales` |
| C: sub-distributors (wholesalers) | wholesalers, distributors, 3PLs | stock held by the chain's own distribution, not shelf stock | `sub-distributor (wholesaler)`, `distributor` |

All levels: recalled batches are **segregated in a secured area** before follow-up such as destruction (§4.4). Where one batch is affected, consider whether other batches are too (§4.4).

## After the recall (§4.5, §4.6)

- The recalling company runs effectiveness checks that customers received and followed the notice (§4.5).
- The completion report includes a reconciliation: quantity returned, corrected, outstanding (§4.6 iv).
- Proof of destruction is due within **4 months** of recall start (§4.6 i).

## Notes for the rules table

- Most notices on the recall page say "Voluntary recall …" with **no degree**. The guideline has no rule for that case, so the table needs an explicit default (e.g. treat as Degree II urgency) marked as **our assumption**, not NPRA's.
- Severity in RecallGuard combines degree (urgency) with level (whether customers must be contacted): a Level A recall with POS sales after the recall date is the case where the customer-contact line matters.
