# Pharmacy Inventory Management — Project Wireframe

## Product goal

A branch-aware pharmacy operations system that keeps medicine and skin-care catalogs, lot-level stock, purchasing, sales, payments, and audit history consistent. Inventory changes are server-owned, attributable, and recorded as movements rather than being treated as editable totals.

## Users and access

- **Cashier:** look up branch products and prices, complete ordinary non-prescription/non-controlled sales, and record later payments. Cashiers cannot dispense prescription or controlled products through POS, adjust stock, or access cost and margin data.
- **Pharmacist:** verify prescriptions, authorize and dispense prescription medicines, review legacy pending sales, receive stock, record stock counts, and process permitted sales or non-sale issues for assigned branches. Pharmacists do not see purchase costs or gross profit.
- **Branch manager:** pharmacist workflows plus supplier invoices/payments, branch reports, and staff oversight.
- **Administrator:** manage branches, memberships, product catalog, controlled-medicine settings, and system configuration. Administrators may read analytics for other branches but cannot perform their operations without an active branch membership.

Every operational record belongs to a branch. Operational reads and writes require an active membership in that branch. Only system administrators can select another branch in Reports, where data is read-only analytics; the selector is shown only when more than one active branch exists. An administrator without a branch membership sees administration and analytics, not operational pages.

Routine POS sales are completed in one checkout: the server validates and locks eligible stock, records the cashier as the actor, posts payment and stock movements, and queues the POS event. Prescription and controlled products remain in the prescription workflow, with pharmacist verification and any required witness. Legacy pending sales retain their approval/rejection path.

## Navigation map

```text
Sign in
└── Assigned branch context
    ├── Overview
    ├── Inventory
    │   ├── Product catalog
    │   ├── Lots / batches
    │   ├── Receive stock
    │   ├── Dispense / POS
    │   ├── Stock count and adjustments
    │   └── Expiry and reorder queues
    ├── Prescriptions
    │   ├── Prescription queue
    │   ├── Prescription detail and validation
    │   └── Dispensing history
    ├── Purchasing
    │   ├── Purchase orders
    │   ├── Receiving
    │   ├── Supplier invoices
    │   └── Supplier payments
    ├── Transfers
    │   ├── Request stock
    │   ├── Dispatch from source branch
    │   └── Receive at destination branch
    ├── Reports
    │   ├── Stock valuation and movement
    │   ├── Expiry / wastage / adjustments
    │   ├── Reorder and purchase trends
    │   ├── Sales and payment balances
    │   ├── Controlled-medicine register
    │   └── Administrator-only cross-branch analytics selector (read-only)
    └── Administration
        ├── Products
        ├── Branches and memberships
        ├── Roles and permissions
        └── Audit log
```

## Screen wireframes

### Overview

```text
+--------------------------------------------------------------------------------+
| Wellnest     Branch: Central        Signed in as ... [Theme] [Sign out]        |
| Overview | Inventory | Prescriptions | Purchasing | Transfers | Reports       |
+--------------------------------------------------------------------------------+
| Overview    Today: [date]                                                      |
| [Products] [Low stock] [Expiring soon] [Expired/quarantined] [Today's sales]   |
|                                                                                |
| Reorder queue                         | Expiry / controlled alerts             |
| Product | On hand | Reorder | Action  | Lot | Expiry | Status | Review        |
|                                                                                |
| Recent activity: received, dispensed, adjusted, transferred, payments          |
+--------------------------------------------------------------------------------+
```

### Inventory and receiving

```text
+--------------------------------------------------------------------------------+
| Inventory  [Search name / SKU] [Category ▼] [Status ▼]                     |
| [Receive stock] [New product] [Stock count] [Export]                            |
+--------------------------------------------------------------------------------+
| SKU | Product | Lot | On hand | Reserved | Reorder | Expiry | Price | Status   |
| ...                                                                            |
|                                                                                |
| Receive stock drawer:                                                         |
| Supplier / PO | Product | Lot number | Expiry | Qty | Unit cost | Save        |
| Every receipt creates a lot and a positive stock movement with actor/reference.|
+--------------------------------------------------------------------------------+
```

### Dispensing / prescription

```text
+--------------------------------------------------------------------------------+
| New sale  [Product search] [Quantity] [Amount] [Payment method]                |
| Lot allocation: earliest expiry first; expired/quarantined lots are excluded.  |
| [Complete sale]  (sale reference is assigned automatically)                    |
| Rare stock issues use a separate pharmacist/manager action with a reason.      |
| Prescription and controlled items remain in the verified prescription workflow|
+--------------------------------------------------------------------------------+
```

### Purchasing and transfers

```text
+--------------------------------------+-----------------------------------------+
| Purchase order                       | Branch transfer                         |
| Supplier | Expected date | Status    | Source branch | Destination | Status   |
| Lines: product, quantity, cost        | Lines: product, quantity, lot            |
| [Submit] [Receive against PO]         | [Request] [Dispatch] [Confirm receipt]   |
+--------------------------------------+-----------------------------------------+
| Supplier invoice and payment history; shipment and receipt movements are linked|
+--------------------------------------------------------------------------------+
```

### Reports and compliance

```text
+--------------------------------------------------------------------------------+
| Reports [Report ▼] [Date range] [Branch ▼] [Export CSV]                         |
| Stock movement | Usage | Shrinkage | Expiry/waste | Reorder | Sales / payments |
| Controlled register: product | schedule | lot | quantity in/out | witness      |
| Each row links back to the immutable movement and audit event.                 |
+--------------------------------------------------------------------------------+
```

## Target domain model

```text
Branch 1---* BranchMembership *---1 User
Branch 1---* StockLot *---1 MedicationProduct
StockLot 1---* StockMovement
Supplier 1---* PurchaseOrder 1---* PurchaseOrderLine
PurchaseOrderLine *---0..1 StockLot (created when received)
SupplierInvoice 1---* SupplierPayment
Prescription 1---* PrescriptionLine *---1 MedicationProduct
PrescriptionLine 1---* DispenseLine *---1 StockLot
Sale 1---* SaleLine *---1 StockLot
Sale 1---* CustomerPayment
Transfer 1---* TransferLine *---1 MedicationProduct
TransferLine 0..* StockMovement (dispatch and receipt)
ControlledDrugRegisterEntry *---1 StockMovement
AuditEvent *---0..1 Branch; *---0..1 User
```

### Data rules

- `MedicationProduct` is the shared catalog identity (automatically generated SKU, product type, name, category, unit, and medicine-only prescription/controlled flags). Skin-care products can also store brand, skin type and concerns, key ingredients, package usage and warning text, and period-after-opening months.
- SKU is the unique internal product identifier used to connect stock, sales, purchasing, and reports. It is generated by the server when a product is created; products can be found by SKU or name. Barcode support is intentionally omitted.
- `StockLot` is branch-specific and carries lot number, optional expiry, quantity, reorder policy, and cost/price snapshots. Medicines require expiry dates; skin-care lots may omit a date only when none is printed on the package. Period-after-opening is separate from lot expiry. The unique lot key is `(branch, product, lot_number)`.
- `StockMovement` is the source of truth for every receipt, dispense, count correction, waste event, and transfer leg. Corrections are new signed movements, never silent edits to history.
- Sales, payment allocations, prescription dispense lines, purchase-order lines, and transfers retain references to their source records and the user who performed the operation.
- Internal references for sales, supplier records/payments, receipts, adjustments, purchase orders, and transfers are generated by the server. Supplier invoice numbers and prescription references remain the original external document identifiers for reconciliation and clinical traceability.
- A prescription-required or controlled product cannot be dispensed through an ordinary sale path. Controlled products require a dedicated, permission-gated workflow and jurisdiction-specific policy.
- POS, insurer, and patient-system connectivity are integration boundaries. Do not claim an integration until its external contract, privacy requirements, and reconciliation behavior are defined.

## Delivery status

- **Foundation:** implemented in the Django API and React dashboard: branch-scoped medicine and skin-care catalog and lots, stock receiving and dispensing, stock counts, sales and payments, supplier invoices and payments, audit events, and role-based branch access.
- **Operations:** internal workflows implemented for purchase orders, reorder suggestions and drafts, supplier/product terms, receiving, and branch transfer request/dispatch/partial receipt. Transfers allocate eligible stock across FEFO-ordered lots.
- **Documents and email:** approved sales can be opened as printable PDF receipts. Managers can access an internal supplier-invoice reconciliation PDF and the privately stored original supplier PDF. Optional sale notices and purchase-order emails are queued in a database outbox; run `python manage.py send_email_notifications` periodically to deliver queued messages and retry temporary failures. Sale email notices intentionally contain no product, prescription, or patient details and do not attach the receipt PDF.
- **Invoice reconciliation:** linked invoices can be reconciled after full purchase-order receipt against received quantities at the purchase-order unit cost. Differences are flagged with the expected amount and variance; freight, tax, and other invoice adjustments require review.
- **Prescriptions and compliance controls:** internal prescription intake, verification and dispensing; configurable per-branch policies; controlled-medicine register and witness controls. The default jurisdiction code is `UG`, but the software does not establish regulatory compliance.
- **Manager analytics:** approved sales and gross-profit trends, comparison with the previous date range, leading products, outstanding approved balances, pending approvals, and stock-risk/reorder signals are available in Reports alongside movement and controlled-register reports. Administration is reserved for catalog and supplier setup; charts are not duplicated there. These are operational summaries, not statutory reports.
- **Dashboard preferences:** signed-in users can switch between light and dark themes; the preference is saved in browser storage when available.
- **Offline operation:** the production frontend caches its application shell and the active user's branch inventory/catalog in the current browser session. Cashiers can queue ordinary POS sale drafts on-device; after reconnection, the server validates and records each draft using an idempotency key. Drafts that the server cannot accept remain available for review. Offline drafts do not reserve stock, record payments, or support stock adjustment, prescription dispensing, controlled medicines, or approvals. A prior online sign-in is required; cached stock can be stale.
- **External integrations:** provider-neutral event records and internal boundaries exist. No POS, insurer, billing, or patient-system provider has been selected or connected, so there is no live external integration.

## AI roadmap

The first **demand-forecasting and replenishment assistant is implemented** in Purchasing. Its transparent, local weighted-moving-average model uses 56 calendar days of approved sales, weighting the latest 28 days at 70% and the preceding 28 days at 30%. The planning horizon is supplier lead time plus a 14-day review buffer. The target is at least the greater of forecast demand over that horizon and twice the configured reorder level. Expiring stock is reported, and estimated surplus expiring within 30 days is discounted when sales history is sufficient. Low-confidence results fall back to the configured reorder point.

Confidence is based on the number of days with approved sales in the lookback window: high at 20 or more, medium at 8–19, and low below 8. The manager sees the calculation and can prefill the purchase-order form, but must review supplier, quantity, cost, and delivery date before submitting. The forecast does not adjust for historical stockout days, so sparse or stockout-affected data requires extra review. This is a lightweight statistical forecasting assistant, not a generative AI model; it makes no external AI calls and does not create or submit orders automatically.

Useful follow-on features include:

- **Operational anomaly alerts:** flag unusual sales spikes, repeated stock adjustments, unexplained shrinkage, or abrupt supplier-price changes for human investigation.
- **Expiry and overstock reduction:** identify slow-moving lots likely to expire and suggest transfer, promotion, or supplier-return review where policy permits.
- **Supplier and cash-flow insights:** summarize lead-time reliability, price trends, and expected near-term purchasing needs.

Continue to measure forecast error against actual demand and refine the model only when sufficient branch history is available. Do not send patient identifiers, prescriptions, or clinical notes to a general-purpose AI service. Do not allow AI to diagnose, prescribe, approve dispensing, alter stock, or submit purchases autonomously. AI features must be optional, auditable, privacy-reviewed, and clearly separated from regulatory reporting. The manager report's comparison and stock-risk signals are deterministic analytics, not AI.

## Implementation boundaries and release checklist

- Treat offline cached data as sensitive: deploy only on access-controlled pharmacy devices with individual operating-system accounts, screen locks, and a process for clearing browser data on shared or retired devices. Cached branch data may outlive a permission change until the device reconnects.
- Reconcile queued POS drafts after an outage and review any server-rejected draft; do not treat a locally queued draft as a completed sale or proof of payment.
- Configure a branch policy only after review by qualified Uganda pharmacy/regulatory stakeholders. Requirements, retention periods, and controlled-medicine rules must be verified independently before production use.
- External POS, insurance, billing, and patient-system integrations require a named provider, API contract, credentials, privacy/security review, event delivery/retry, and reconciliation behavior.
- Product barcodes and scanner workflows are not implemented; product search uses name or the automatically generated SKU.
- External system connectivity remains provider-neutral until the pharmacy chooses a provider and agrees its API and privacy requirements.
- This invoice reconciliation compares merchandise amounts only; it is not a tax, freight, or accounting ledger.
- Run migrations, tests, and production configuration checks before deployment; development defaults are not production-ready.
