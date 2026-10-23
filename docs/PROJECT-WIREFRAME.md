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

## Delivery slices

1. **Foundation (in progress):** branch-scoped catalog/lots, receiving, FEFO stock dispensing, stock counts, supplier invoices/payments, sales/payments, audit trail, persistence, and tests.
2. **Operations:** purchase orders/receiving reconciliation, richer product administration, barcode aliases and scan UX, transfer request/dispatch/receipt.
3. **Prescription and compliance:** prescription validation/dispensing, controlled-medicine register and witness workflow, configurable policies and retention.
4. **Integrations and analytics:** POS/claims/patient integration after contracts and privacy review; operational reports and exports.

## Current implementation boundary

The first delivery slice is being wired into the Django API and React dashboard. Prescription integration, controlled-substance operations, scanning hardware, purchase orders, transfers, and external POS/claims/patient integrations are design targets, not implemented or certified capabilities yet. Compliance requirements vary by jurisdiction and must be reviewed before production use.
