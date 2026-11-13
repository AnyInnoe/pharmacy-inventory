# Pharmacy Inventory System — Stakeholder Requirements Baseline

## Document purpose and status

This document reconstructs the requirements that could have guided the project from discovery through rollout. It is based on the needs and decisions expressed during project discussions and the capabilities documented in the current system. It is **not a record of completed stakeholder interviews or regulatory approval**. Pharmacy owners, pharmacists, cashiers, branch managers, administrators, and local compliance advisers should validate it before production use.

The document distinguishes implemented capabilities from deployment responsibilities and future opportunities. “Must” describes a business-critical requirement; it does not by itself establish legal or clinical compliance.

## 1. Business context

The system is intended for a pharmacy business with one or more branches. It brings catalog, lot-level inventory, dispensing, purchasing, supplier invoices, payments, reporting, and audit history into one branch-aware application. It must keep routine sales fast while protecting prescription and controlled-medicine workflows.

Development uses SQLite by default. PostgreSQL is available as a deployment option, but moving existing SQLite data to PostgreSQL requires a separately planned and verified migration.

## 2. Stakeholders and needs

| Stakeholder | Primary needs |
|---|---|
| Owner / business administrator | Understand performance across branches, manage access and configuration, and protect confidential business data. |
| Branch manager | See branch sales, stock risks, purchasing needs, supplier balances, and staff activity; reconcile supplier invoices. |
| Pharmacist | Verify prescriptions, dispense safely, trace stock to its lot, and review controlled-medicine activity. |
| Cashier | Find products quickly, complete ordinary sales with few steps, take payment, and continue recording eligible sales during a brief outage. |
| Inventory / purchasing staff | Receive stock accurately, track supplier terms and purchase orders, monitor expiry, and transfer stock between branches. |
| Customer | Receive accurate service without avoidable checkout delays and, when requested, a sale receipt. |
| IT / operations support | Deploy, back up, monitor, and recover the application; configure email and maintain secure access. |

## 3. Business problems and intended outcomes

| Problem to address | Business impact | System response |
|---|---|---|
| Stock records are kept in separate books, spreadsheets, or branch-specific tools. | Staff cannot reliably tell what is available; discrepancies and duplicate work increase. | Keep one shared product catalog with branch-specific lots, quantities, movements, and transfers. |
| Staff have limited visibility into expiring, low, or out-of-stock products. | Lost sales, avoidable expiry, emergency purchases, and tied-up cash. | Show stock-risk and expiry information, reorder suggestions, and lot-level quantities. |
| Sales, receiving, and adjustments are not consistently linked to who performed them. | Difficult investigations, weak reconciliation, and unreliable reports. | Record attributable, referenced stock movements and audit events for operational changes. |
| Routine dispensing includes unnecessary fields, approvals, or navigation. | Longer queues and more opportunities for entry errors. | Provide a short ordinary-sale checkout; require additional steps only for exceptional, prescription, or controlled workflows. |
| Prescription and controlled items need more oversight than ordinary products. | Risk of unauthorized dispensing or incomplete accountability. | Separate prescription verification and controlled workflows from routine POS, with role and witness controls where configured. |
| Staff manually create references and product identifiers. | Inconsistent references make follow-up and reconciliation harder. | Generate internal references and product SKUs on the server; retain supplier invoice and prescription references where they originate externally. |
| Managers cannot compare branches or understand margins and sales trends. | Purchasing and staffing decisions rely on incomplete or delayed information. | Provide date-range reports for approved sales, gross profit, products sold, outstanding balances, stock risk, movements, and controlled-register activity. Cross-branch analytics are read-only and administrator-only. |
| Supplier orders, receiving, invoices, and payments are disconnected. | Quantity and invoice discrepancies can be missed; payment follow-up is difficult. | Link purchase orders, receiving, supplier invoices, reconciliation, and supplier payments. Retain the supplier’s original invoice when uploaded. |
| An internet interruption can stop all work. | Sales may be delayed during a short outage. | Cache the application shell and active-branch catalog in the browser and queue eligible ordinary-sale drafts for later server validation. |
| Useful sales history is not translated into purchasing guidance. | Replenishment decisions are reactive or based only on intuition. | Offer a transparent statistical demand forecast that managers review; do not place orders automatically. |
| Staff may send sensitive sale or clinical details over email. | Customer and clinical privacy exposure. | Keep sale notices generic and do not email prescription, patient, or product details or attach detailed receipt PDFs. |

## 4. Scope

### Included in the current system

- Branches, memberships, role-based access, and branch-scoped operations.
- Shared medicine and skin-care catalog with automatically generated SKUs.
- Branch-specific stock lots, receiving, stock counts, adjustments, expiry tracking, and FEFO allocation.
- Ordinary sales and payments; prescription intake, verification, and dispensing; configured controlled-medicine controls.
- Suppliers, supplier-product terms, purchase orders, receiving, supplier invoices, reconciliation, payments, and branch transfers.
- Operational reports, CSV movement export, management analytics, and the replenishment forecast.
- Offline application-shell/catalog access and queued ordinary-sale drafts, with server-side validation after reconnection.
- PDF sale receipts, internal supplier-invoice reconciliation PDFs, protected storage/access for uploaded original invoices, and queued email notices.
- Light/dark theme preference.

### Explicitly not included or not yet connected

- Barcode fields, barcode aliases, or scanner workflows.
- A live external POS, insurance, billing, or patient-management integration.
- Automatic offline stock reservation, offline payment confirmation, offline prescription or controlled dispensing, or offline approvals.
- Automatic purchase submission or autonomous AI decisions.
- A statutory accounting ledger, tax invoice certification, or guarantee of regulatory compliance.
- Automatic scheduling of the email worker; deployment operations must schedule `python manage.py send_email_notifications`.
- A completed migration of existing SQLite data to PostgreSQL.

## 5. Functional requirements

### Access, branches, and roles

**FR-01 — Authenticated, role-appropriate access (Must).** Users must sign in and receive only the navigation and operations permitted by their assigned role and active branch membership.

**Acceptance:** A cashier can complete permitted ordinary sales but cannot access cost/margin data or controlled workflows. A pharmacist can use assigned clinical workflows. A branch manager can use purchasing and branch reports. An administrator can manage configuration and view read-only cross-branch analytics, but cannot conduct branch operations without membership.

**FR-02 — Branch isolation and analytics (Must).** Every operational record must belong to a branch. Ordinary reads and writes must be confined to branches where the user has an active membership. The administrator’s cross-branch selector must appear only when more than one active branch exists and must not enable cross-branch writes.

**Acceptance:** A request to view or change another branch’s operational records is denied without membership. With multiple active branches, the administrator can compare analytics but cannot receive stock or record a sale in another branch unless separately assigned.

### Catalog and inventory

**FR-03 — Product catalog (Must).** Staff with catalog permissions can create and maintain medicine and skin-care products. The server assigns a unique SKU; users do not need to enter one. The catalog must not depend on barcode support.

**FR-04 — Skin-care attributes (Should).** Skin-care products may capture brand, skin type, concerns, ingredients, label instructions/warnings, and period-after-opening information without forcing medicine-only prescription fields on them.

**FR-05 — Lot-level stock (Must).** Stock must be recorded by branch, product, lot, expiry where applicable, quantity, reorder level, cost, and selling price. Medicines require expiry dates; skin-care expiry may be omitted only when no date is printed.

**Acceptance:** Receiving creates a traceable lot and positive movement. Expired or otherwise ineligible lots are excluded from sale allocation. Eligible lots are allocated earliest-expiry-first. A correction creates a new movement instead of silently rewriting stock history.

**FR-06 — Transfers and stock reconciliation (Should).** Authorized staff must be able to request, dispatch, and receive branch transfers with quantities and lot references; partial receipts must remain traceable.

### Dispensing and purchasing

**FR-07 — Fast ordinary checkout (Must).** An ordinary non-prescription, non-controlled sale must be completable in a short checkout without unnecessary recipient, transaction-type, or approval steps. Product, quantity, payment method, and amount received must be sufficient when the sale is valid.

**Acceptance:** The server validates available stock and records the sale, payment, stock movements, actor, and internal reference together. The sale cannot be recorded twice because of an eligible retried request.

**FR-08 — Prescription and controlled dispensing (Must).** Prescription-required and controlled products must not be dispensed through ordinary POS. They must follow the configured verification, authorization, witness, and recordkeeping workflow.

**FR-09 — Purchasing and suppliers (Must).** Authorized staff must be able to manage supplier details and product terms, prepare and submit purchase orders, receive stock against orders, and record supplier invoices and payments. Internal references must be generated automatically; the supplier’s own invoice number must be retained for reconciliation.

**FR-10 — Invoice documents and email (Should).** A user may retain an uploaded supplier-original PDF. The system must distinguish it from an internal reconciliation PDF. Sale and purchase-order email notices must be queued and retried after temporary delivery failures.

**Acceptance:** Only authorized managers can retrieve supplier invoice documents. Sale notices must exclude patient, prescription, and product details; detailed receipts are not attached. Delivery status and attempts are auditable.

### Reporting, resilience, and decision support

**FR-11 — Operational and management reports (Must).** Authorized users must be able to review branch-appropriate inventory, movement, expiry, sales, payment, and purchasing information. Financial values must be hidden from roles not authorized to view them.

**FR-12 — Offline continuity (Should).** After a successful online sign-in, the browser may cache the application shell and active-branch catalog. During a network outage, a cashier may queue eligible ordinary-sale drafts locally.

**Acceptance:** A queued draft is clearly not a completed sale, does not reserve stock or confirm payment, and is revalidated by the server after reconnection. Duplicate replay must not create duplicate sales. Rejected drafts remain available for review. Offline mode must not permit prescription or controlled dispensing, stock adjustments, or approvals.

**FR-13 — Replenishment guidance (Should).** The application may estimate demand from approved sales history and show a confidence level, assumptions, expiry considerations, and a suggested quantity. A manager must review the recommendation and submit any order manually.

**FR-14 — Auditability (Must).** Material operational changes must retain actor, branch, reference, timestamp, and relevant movement or audit record so that staff can investigate stock and transaction history.

## 6. Non-functional requirements

- **Security:** Enforce authorization on the server, not only by hiding UI controls. Use protected sessions, secure deployment configuration, least-privilege memberships, and private storage for original supplier invoices.
- **Privacy:** Do not email patient identifiers, prescriptions, or clinical notes. Treat offline browser data as sensitive; use access-controlled devices and clear local data when devices are shared, retired, or permissions change.
- **Data integrity:** Keep stock changes transactional and attributable; use idempotency for sale replay; preserve original external invoice and prescription references.
- **Usability:** Keep routine checkout concise, use readable forms and responsive layouts, and surface errors rather than silently accepting invalid data.
- **Availability and recovery:** The deployment must have tested backups and restore procedures. Offline draft replay reduces some outage impact but does not replace backups or guarantee uninterrupted operations.
- **Performance:** Agree response-time and checkout-duration targets with staff during a representative pilot. The current project has not established a measured production service-level objective.
- **Maintainability:** Run migrations and tests during releases, monitor email delivery, and keep dependencies and deployment configuration maintained.
- **Compatibility:** SQLite is the development default. Production database choice, migration, backups, host configuration, HTTPS, and email relay must be explicitly tested before rollout.
- **Compliance:** Branch policies, prescription controls, retention periods, and controlled-medicine procedures require review by qualified local stakeholders. The application does not itself certify compliance.

## 7. End-to-end delivery and acceptance plan

1. **Discovery:** Confirm branch count, user roles, current stock records, dispensing steps, supplier processes, reports, internet reliability, and applicable local rules. Record baseline queue times, stock discrepancies, expired stock, and reporting effort.
2. **Requirements validation:** Review the problem list, role matrix, data fields, privacy rules, offline limits, and acceptance tests with the owner, managers, pharmacists, and cashiers.
3. **Workflow and data design:** Prototype product setup, receiving, ordinary checkout, prescription flow, purchasing, reports, and cross-branch access. Confirm which fields are mandatory and which are generated automatically.
4. **Build and integration:** Implement catalog, branch access, lot movements, dispensing, purchasing, reporting, offline replay, documents, and the outbox in increments. Keep external integrations explicitly out of scope until a provider and contract are approved.
5. **Verification:** Test role restrictions, branch isolation, expiry/FEFO behavior, transaction consistency, duplicate replay, offline rejection handling, document permissions, email privacy/retries, and forecast calculations. Run migrations against a copy of representative data.
6. **User acceptance and pilot:** Train each role. Enter a small, clearly labeled demo dataset, run ordinary and prescription scenarios, compare reports with known totals, and gather queue-time and inventory feedback.
7. **Production readiness:** Configure database, secrets, allowed hosts, HTTPS, backups, restore drills, monitoring, email relay, and the scheduled email worker. Do not expose Django’s development server publicly.
8. **Support and improvement:** Review errors, stock discrepancies, expiry outcomes, forecast accuracy, and user feedback. Prioritize improvements with stakeholders; keep AI recommendations reviewable and non-autonomous.

## 8. Proposed user-acceptance checks

- A cashier with one branch membership can complete an eligible sale and cannot view cost or gross profit.
- A pharmacist can receive stock and complete configured prescription workflows; an ordinary cashier cannot dispense a prescription-required item.
- An administrator with two active branches can compare read-only analytics, but cannot write operational data to an unassigned branch.
- An eligible sale reduces the correct branch lot, records payment and actor, and is not duplicated on retry.
- Offline drafts are visibly pending until server acceptance; a rejected draft can be reviewed and is not reported as a completed sale.
- Expired stock is not allocated, and eligible stock follows FEFO.
- A manager can reconcile a linked supplier invoice after qualifying receipt, view the internal PDF, and retrieve an uploaded original without making it public.
- A completed sale can produce a PDF receipt. Email delivery can be retried, and the sale notice contains no clinical or product details.
- Reports reconcile against known test sales and movements for each branch. The forecast shows its assumptions and requires human review.

## 9. Assumptions, risks, and decisions to validate

- The branch model, staff roles, and approval responsibilities reflect the actual organization; validate them before rollout.
- Each branch has reliable procedures for initial stock counts, lot/expiry entry, supplier reconciliation, and user account management.
- Offline browser storage is used only on appropriately secured devices. Cached stock can be stale and may persist until reconnection or local cleanup.
- A scheduled worker and monitored SMTP relay are required for queued email. A queued email is not proof of delivery.
- Forecasts are limited by the quality and duration of sales history and do not currently correct for historical stockout periods.
- The reconciliation PDF is an internal operational document, not a supplier original, tax invoice, or accounting ledger.
- The PostgreSQL deployment path is configuration support, not an automatic migration of existing SQLite records.
- Stakeholders must decide production retention periods, backups, support ownership, service-level objectives, and any required external integrations.
- Regulatory requirements, especially prescription and controlled-medicine rules, must be independently reviewed for the operating jurisdiction.

## 10. Outcome measures to establish during the pilot

Capture a baseline and review these measures after pilot use; do not treat the application alone as proof of improvement:

- Median time to complete an ordinary sale and observed queue length at peak periods.
- Difference between system stock and physical counts; number and value of adjustments.
- Expired/wasted stock and stockout frequency by branch.
- Time required to prepare a purchase order and reconcile a supplier invoice.
- Accuracy and timeliness of branch sales, margin, and balance reports.
- Number of offline drafts accepted, rejected, or awaiting review after reconnection.
- Replenishment forecast error compared with later approved sales and manager overrides.
- Training and support issues by role, branch, and workflow.
