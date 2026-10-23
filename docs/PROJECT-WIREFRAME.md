# Pharmacy Inventory Management — Project Wireframe

## Product goal

A branch-aware pharmacy operations system that keeps medication catalog, lot-level stock, purchasing, dispensing, payments, and audit history consistent. Inventory changes are server-owned, attributable, and recorded as movements rather than being treated as editable totals.

## Users and access

- **Pharmacist:** look up products, receive stock, dispense sales or non-sale issues, and record stock counts for assigned branches.
- **Branch manager:** pharmacist workflows plus supplier invoices/payments, branch reports, and staff oversight.
- **Administrator:** manage branches, memberships, product catalog, controlled-medicine settings, and system configuration.

Every operational record belongs to a branch. Users may only read or change records in branches where they have an active membership; administrators can select any active branch.

## Navigation map

```text
Sign in
└── Select active branch
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
    │   └── Controlled-medicine register
    └── Administration
        ├── Products and barcode aliases
        ├── Branches and memberships
        ├── Roles and permissions
        └── Audit log
```

## Screen wireframes

### Overview

```text
+--------------------------------------------------------------------------------+
| Wellnest     [Branch: Central ▼]                  Signed in as ... [Sign out]  |
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
| Inventory  [Search name / SKU / barcode] [Category ▼] [Status ▼] [Scan barcode]|
| [Receive stock] [New product] [Stock count] [Export]                            |
+--------------------------------------------------------------------------------+
| SKU | Product | Lot | On hand | Reserved | Reorder | Expiry | Price | Status   |
| ...                                                                            |
|                                                                                |
| Receive stock drawer:                                                         |
| Supplier / PO | Product [scan] | Lot number | Expiry | Qty | Unit cost | Save  |
| Every receipt creates a lot and a positive stock movement with actor/reference.|
+--------------------------------------------------------------------------------+
```

### Dispensing / prescription

```text
+--------------------------------------------------------------------------------+
| Dispense  [Scan product/barcode] [Search product]                              |
| Prescription: [ID / patient reference] [Validate]   Type: [Prescription ▼]     |
| Items: Product | Requested | Available eligible lots | Dispense quantity        |
| Lot allocation: earliest expiry first; expired/quarantined lots are excluded.  |
| Patient/customer reference | Payment method | Amount received | [Confirm]       |
| Warnings: prescription required / controlled-drug witness / insufficient stock |
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
MedicationProduct 1---* BarcodeAlias
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

- `MedicationProduct` is the shared catalog identity (SKU, name, category, unit, barcode, prescription and controlled flags).
- `StockLot` is branch-specific and carries lot number, expiry, quantity, reorder policy, and cost/price snapshots. The unique lot key is `(branch, product, lot_number)`.
- `StockMovement` is the source of truth for every receipt, dispense, count correction, waste event, and transfer leg. Corrections are new signed movements, never silent edits to history.
- Sales, payment allocations, prescription dispense lines, purchase-order lines, and transfers retain references to their source records and the user who performed the operation.
- A prescription-required or controlled product cannot be dispensed through an ordinary sale path. Controlled products require a dedicated, permission-gated workflow and jurisdiction-specific policy.
- Barcode aliases resolve to a product; scanning never substitutes for lot/expiry verification.
- POS, insurer, and patient-system connectivity are integration boundaries. Do not claim an integration until its external contract, privacy requirements, and reconciliation behavior are defined.

## Delivery status

- **Foundation:** implemented in the Django API and React dashboard: branch-scoped catalog and lots, stock receiving and dispensing, stock counts, sales and payments, supplier invoices and payments, audit events, and role-based branch access.
- **Operations:** internal workflows implemented for purchase orders, reorder suggestions and drafts, supplier/product terms, receiving, barcode lookup and aliases, and branch transfer request/dispatch/partial receipt. Transfers allocate eligible stock across FEFO-ordered lots.
- **Invoice reconciliation:** linked invoices can be reconciled after full purchase-order receipt against received quantities at the purchase-order unit cost. Differences are flagged with the expected amount and variance; freight, tax, and other invoice adjustments require review.
- **Prescriptions and compliance controls:** internal prescription intake, verification and dispensing; configurable per-branch policies; controlled-medicine register and witness controls. The default jurisdiction code is `UG`, but the software does not establish regulatory compliance.
- **Analytics:** operational summaries and movement CSV export are available. These are not statutory reports.
- **External integrations:** provider-neutral event records and internal boundaries exist. No POS, insurer, billing, or patient-system provider has been selected or connected, so there is no live external integration.

## Implementation boundaries and release checklist

- Configure a branch policy only after review by qualified Uganda pharmacy/regulatory stakeholders. Requirements, retention periods, and controlled-medicine rules must be verified independently before production use.
- External POS, insurance, billing, and patient-system integrations require a named provider, API contract, credentials, privacy/security review, event delivery/retry, and reconciliation behavior.
- Barcode lookup accepts scanner keyboard input; hardware-specific device integrations are not included.
- External system connectivity remains provider-neutral until the pharmacy chooses a provider and agrees its API and privacy requirements.
- This invoice reconciliation compares merchandise amounts only; it is not a tax, freight, or accounting ledger.
- Run migrations, tests, and production configuration checks before deployment; development defaults are not production-ready.
