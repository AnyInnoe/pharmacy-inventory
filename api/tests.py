import json
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import (
    AuditEvent,
    Branch,
    BranchMembership,
    BranchTransfer,
    ControlledDrugRegisterEntry,
    CustomerPayment,
    ExternalIntegrationEvent,
    MedicineBatch,
    MedicationProduct,
    PurchaseOrder,
    PurchaseOrderLine,
    Prescription,
    Sale,
    SaleLine,
    StockMovement,
    Supplier,
    SupplierProduct,
    SupplierInvoice,
    SupplierPayment,
)


class InventoryApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="pharmacist",
            password="test-password",
        )
        self.branch = Branch.objects.create(name="Central", code="CENTRAL")
        BranchMembership.objects.create(user=self.user, branch=self.branch)
        self.client.force_login(self.user)

    def post_json(self, path, data):
        return self.client.post(
            path,
            data=json.dumps(data),
            content_type="application/json",
        )

    def make_manager(self, branch=None):
        membership = BranchMembership.objects.get(
            user=self.user,
            branch=branch or self.branch,
        )
        membership.role = BranchMembership.Role.BRANCH_MANAGER
        membership.save(update_fields=["role"])

    def make_cashier(self, branch=None):
        membership = BranchMembership.objects.get(
            user=self.user,
            branch=branch or self.branch,
        )
        membership.role = BranchMembership.Role.CASHIER
        membership.save(update_fields=["role"])

    def create_batch(self, **overrides):
        data = {
            "branchId": self.branch.id,
            "sku": "MED-001",
            "name": "Example medicine",
            "category": "General",
            "batch": "LOT-001",
            "quantity": 10,
            "reorderLevel": 2,
            "expiry": "2030-01-01",
            "supplier": "Supplier A",
            "reference": "RECEIPT-001",
            "purchaseCost": "2.00",
            "sellingPrice": "5.00",
        }
        data.update(overrides)
        return self.post_json("/api/batches/", data)

    def test_receipt_persists_product_lot_and_movement(self):
        response = self.create_batch()

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(MedicationProduct.objects.count(), 1)
        self.assertEqual(MedicineBatch.objects.get().quantity, 10)
        movement = StockMovement.objects.get()
        self.assertEqual(movement.quantity, 10)
        self.assertEqual(movement.type, StockMovement.Type.RECEIVED)
        self.assertEqual(movement.actor, self.user)

        data = self.client.get(f"/api/data/?branchId={self.branch.id}").json()
        self.assertEqual(data["inventory"][0]["sku"], "MED-001")
        self.assertEqual(data["stockMovements"][0]["reference"], "RECEIPT-001")

    def test_dispense_rejects_overpayment_without_changing_stock(self):
        self.create_batch()
        response = self.post_json(
            "/api/dispense/",
            {
                "branchId": self.branch.id,
                "sku": "MED-001",
                "transactionType": "Sale",
                "quantity": 2,
                "recipient": "Customer",
                "reference": "SALE-001",
                "amountReceived": "11.00",
                "paymentMethod": "Cash",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(MedicineBatch.objects.get().quantity, 10)
        self.assertEqual(Sale.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_batch_rejects_fractional_quantity(self):
        response = self.create_batch(quantity=1.5)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(MedicineBatch.objects.count(), 0)
        self.assertEqual(MedicationProduct.objects.count(), 0)

    def test_sale_and_customer_payment_are_persisted(self):
        self.create_batch()
        response = self.post_json(
            "/api/dispense/",
            {
                "branchId": self.branch.id,
                "sku": "MED-001",
                "transactionType": "Sale",
                "quantity": 2,
                "recipient": "Customer",
                "reference": "SALE-001",
                "amountReceived": "4.00",
                "paymentMethod": "Cash",
            },
        )

        self.assertEqual(response.status_code, 201, response.content)
        sale = Sale.objects.get()
        self.assertEqual(sale.sale_amount, 10)
        self.assertEqual(sale.cost_amount, 4)
        self.assertEqual(sale.balance_due, 6)
        self.assertEqual(MedicineBatch.objects.get().quantity, 8)
        self.assertEqual(CustomerPayment.objects.get().amount, 4)
        sale_line = SaleLine.objects.get(sale=sale)
        self.assertEqual(sale_line.batch.batch, "LOT-001")
        self.assertEqual(sale_line.quantity, 2)
        sale_movement = StockMovement.objects.get(sale=sale)
        self.assertEqual(sale_movement.quantity, -2)

        payment_response = self.post_json(
            f"/api/sales/{sale.id}/payments/",
            {
                "branchId": self.branch.id,
                "amount": "6.00",
                "method": "Mobile money",
                "reference": "PAY-001",
            },
        )
        self.assertEqual(payment_response.status_code, 201, payment_response.content)
        sale.refresh_from_db()
        self.assertEqual(sale.balance_due, 0)
        self.assertEqual(CustomerPayment.objects.count(), 2)
        self.assertEqual(AuditEvent.objects.filter(entity_type="sale").count(), 2)

    def test_cashier_sale_requires_distinct_pharmacist_approval(self):
        self.create_batch()
        self.make_cashier()
        pending = self.post_json(
            "/api/dispense/",
            {
                "branchId": self.branch.id,
                "sku": "MED-001",
                "transactionType": "Sale",
                "quantity": 2,
                "recipient": "Customer",
                "reference": "SALE-PENDING",
                "amountReceived": "4.00",
                "paymentMethod": "Cash",
            },
        )

        self.assertEqual(pending.status_code, 202, pending.content)
        sale = Sale.objects.get()
        self.assertEqual(sale.approval_status, Sale.ApprovalStatus.PENDING)
        self.assertEqual(sale.actor, self.user)
        self.assertIsNone(sale.approved_by)
        self.assertEqual(sale.approval_amount_received, 4)
        self.assertEqual(sale.amount_received, 0)
        self.assertEqual(MedicineBatch.objects.get().quantity, 10)
        self.assertEqual(StockMovement.objects.count(), 1)
        self.assertEqual(CustomerPayment.objects.count(), 0)

        payment = self.post_json(
            f"/api/sales/{sale.pk}/payments/",
            {
                "branchId": self.branch.id,
                "amount": "1.00",
                "method": "Cash",
                "reference": "EARLY-PAY",
            },
        )
        self.assertEqual(payment.status_code, 409)

        self.assertNotIn(
            "purchaseCost",
            self.client.get(f"/api/data/?branchId={self.branch.id}").json()["inventory"][0],
        )
        self.assertNotIn(
            "grossProfit",
            self.client.get(f"/api/data/?branchId={self.branch.id}").json()["sales"][0],
        )

        denied = self.post_json(
            f"/api/sales/{sale.pk}/approve/",
            {"branchId": self.branch.id},
        )
        self.assertEqual(denied.status_code, 403)

        pharmacist = get_user_model().objects.create_user(
            username="approving-pharmacist",
            password="test-password",
        )
        BranchMembership.objects.create(
            user=pharmacist,
            branch=self.branch,
            role=BranchMembership.Role.PHARMACIST,
        )
        self.client.force_login(pharmacist)
        approved = self.post_json(
            f"/api/sales/{sale.pk}/approve/",
            {"branchId": self.branch.id},
        )
        self.assertEqual(approved.status_code, 200, approved.content)
        sale.refresh_from_db()
        self.assertEqual(sale.approval_status, Sale.ApprovalStatus.APPROVED)
        self.assertEqual(sale.approved_by, pharmacist)
        self.assertEqual(sale.amount_received, 4)
        self.assertEqual(sale.balance_due, 6)
        self.assertEqual(MedicineBatch.objects.get().quantity, 8)
        self.assertEqual(CustomerPayment.objects.get().actor, self.user)
        movement = StockMovement.objects.get(type=StockMovement.Type.SALE)
        self.assertEqual(movement.actor, pharmacist)
        self.assertEqual(sale.lines.get().quantity, 2)

    def test_cashier_cannot_adjust_stock_or_access_prescriptions(self):
        self.create_batch()
        self.make_cashier()
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        stock_count = self.post_json(
            "/api/stock-count/",
            {
                "branchId": self.branch.id,
                "batch": "LOT-001",
                "quantity": 9,
                "reason": "Counting correction",
                "reference": "COUNT-DENIED",
            },
        )
        non_sale_issue = self.post_json(
            "/api/dispense/",
            {
                "branchId": self.branch.id,
                "sku": "MED-001",
                "transactionType": "Non-sale issue",
                "quantity": 1,
                "recipient": "Waste",
                "reference": "ISSUE-DENIED",
            },
        )
        prescriptions = self.client.get(f"/api/prescriptions/?branchId={self.branch.id}")
        catalog_update = self.post_json(
            "/api/products/create/",
            {"sku": "MED-002", "name": "Other", "category": "General"},
        )

        self.assertEqual(stock_count.status_code, 403)
        self.assertEqual(non_sale_issue.status_code, 403)
        self.assertEqual(prescriptions.status_code, 403)
        self.assertEqual(catalog_update.status_code, 403)
        self.assertEqual(MedicineBatch.objects.get().quantity, 10)

    def test_administrator_without_branch_role_cannot_finalize_sales(self):
        self.create_batch()
        administrator = get_user_model().objects.create_superuser(
            username="global-administrator",
            password="test-password",
        )
        self.client.force_login(administrator)
        response = self.post_json(
            "/api/dispense/",
            {
                "branchId": self.branch.id,
                "sku": "MED-001",
                "transactionType": "Sale",
                "quantity": 1,
                "recipient": "Customer",
                "reference": "SALE-NO-ROLE",
                "amountReceived": "0.00",
                "paymentMethod": "Credit",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Sale.objects.count(), 0)
        self.assertEqual(MedicineBatch.objects.get().quantity, 10)

    def test_sale_approval_rejects_price_changes_since_cashier_checkout(self):
        self.create_batch()
        self.make_cashier()
        pending = self.post_json(
            "/api/dispense/",
            {
                "branchId": self.branch.id,
                "sku": "MED-001",
                "transactionType": "Sale",
                "quantity": 1,
                "recipient": "Customer",
                "reference": "SALE-PRICE-CHANGE",
                "amountReceived": "0.00",
                "paymentMethod": "Credit",
            },
        )
        sale = Sale.objects.get()
        pharmacist = get_user_model().objects.create_user(
            username="price-approving-pharmacist",
            password="test-password",
        )
        BranchMembership.objects.create(
            user=pharmacist,
            branch=self.branch,
            role=BranchMembership.Role.PHARMACIST,
        )
        batch = MedicineBatch.objects.get()
        batch.selling_price = 6
        batch.save(update_fields=["selling_price"])
        self.client.force_login(pharmacist)
        approval = self.post_json(
            f"/api/sales/{sale.pk}/approve/",
            {"branchId": self.branch.id},
        )

        self.assertEqual(pending.status_code, 202)
        self.assertEqual(approval.status_code, 409)
        sale.refresh_from_db()
        self.assertEqual(sale.approval_status, Sale.ApprovalStatus.PENDING)
        self.assertEqual(MedicineBatch.objects.get().quantity, 10)
        self.assertEqual(CustomerPayment.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_rejecting_cashier_sale_leaves_stock_and_payments_unchanged(self):
        self.create_batch()
        self.make_cashier()
        pending = self.post_json(
            "/api/dispense/",
            {
                "branchId": self.branch.id,
                "sku": "MED-001",
                "transactionType": "Sale",
                "quantity": 1,
                "recipient": "Customer",
                "reference": "SALE-REJECT",
                "amountReceived": "0.00",
                "paymentMethod": "Credit",
            },
        )
        sale = Sale.objects.get()
        pharmacist = get_user_model().objects.create_user(
            username="rejecting-pharmacist",
            password="test-password",
        )
        BranchMembership.objects.create(
            user=pharmacist,
            branch=self.branch,
            role=BranchMembership.Role.PHARMACIST,
        )
        self.client.force_login(pharmacist)
        rejected = self.post_json(
            f"/api/sales/{sale.pk}/reject/",
            {"branchId": self.branch.id, "reason": "Verify item and quantity."},
        )

        self.assertEqual(pending.status_code, 202)
        self.assertEqual(rejected.status_code, 200, rejected.content)
        sale.refresh_from_db()
        self.assertEqual(sale.approval_status, Sale.ApprovalStatus.REJECTED)
        self.assertEqual(sale.rejected_by, pharmacist)
        self.assertEqual(sale.rejection_reason, "Verify item and quantity.")
        self.assertEqual(MedicineBatch.objects.get().quantity, 10)
        self.assertEqual(CustomerPayment.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_supplier_invoice_and_payment_are_persisted(self):
        self.make_manager()
        response = self.post_json(
            "/api/supplier-invoices/",
            {
                "branchId": self.branch.id,
                "supplier": "Supplier A",
                "invoiceNumber": "INV-001",
                "invoiceAmount": "100.00",
                "amountPaid": "20.00",
                "dueDate": "2030-02-01",
                "method": "Cash",
            },
        )

        self.assertEqual(response.status_code, 201, response.content)
        invoice = SupplierInvoice.objects.get()
        self.assertEqual(invoice.amount_paid, 20)
        self.assertEqual(SupplierPayment.objects.get().amount, 20)

        payment_response = self.post_json(
            f"/api/supplier-invoices/{invoice.id}/payments/",
            {
                "branchId": self.branch.id,
                "amount": "80.00",
                "method": "Bank transfer",
                "reference": "PAY-INV-001",
            },
        )
        self.assertEqual(payment_response.status_code, 201, payment_response.content)
        invoice.refresh_from_db()
        self.assertEqual(invoice.amount_paid, 100)
        self.assertEqual(SupplierPayment.objects.count(), 2)

    def test_linked_supplier_invoice_reconciliation_requires_complete_receipt(self):
        self.make_manager()
        self.create_batch()
        product = MedicationProduct.objects.get(sku="MED-001")
        supplier = Supplier.objects.create(name="Reconciliation supplier")
        order = PurchaseOrder.objects.create(
            branch=self.branch,
            supplier=supplier,
            number="PO-RECON",
            status=PurchaseOrder.Status.SUBMITTED,
            created_by=self.user,
        )
        PurchaseOrderLine.objects.create(
            purchase_order=order,
            product=product,
            quantity_ordered=3,
            quantity_received=3,
            unit_cost="2.50",
        )
        invoice = SupplierInvoice.objects.create(
            branch=self.branch,
            supplier_record=supplier,
            purchase_order=order,
            supplier=supplier.name,
            invoice_number="INV-RECON",
            invoice_amount="7.50",
            due_date=date(2030, 1, 1),
            actor=self.user,
        )
        pending = self.post_json(
            f"/api/supplier-invoices/{invoice.id}/reconcile/",
            {"branchId": self.branch.id},
        )
        self.assertEqual(pending.status_code, 409)

        order.status = PurchaseOrder.Status.RECEIVED
        order.save(update_fields=["status"])
        matched = self.post_json(
            f"/api/supplier-invoices/{invoice.id}/reconcile/",
            {"branchId": self.branch.id},
        )
        self.assertEqual(matched.status_code, 200, matched.content)
        self.assertEqual(matched.json()["invoice"]["reconciliationStatus"], "matched")
        self.assertEqual(matched.json()["invoice"]["reconciledExpectedAmount"], 7.5)

        invoice.invoice_amount = "8.00"
        invoice.save(update_fields=["invoice_amount"])
        variance = self.post_json(
            f"/api/supplier-invoices/{invoice.id}/reconcile/",
            {"branchId": self.branch.id},
        )
        self.assertEqual(variance.status_code, 200, variance.content)
        self.assertEqual(variance.json()["invoice"]["reconciliationStatus"], "variance")
        self.assertEqual(variance.json()["invoice"]["reconciliationVariance"], 0.5)

    def test_controlled_product_cannot_use_regular_dispense_flow(self):
        self.create_batch()
        product = MedicationProduct.objects.get(sku="MED-001")
        product.is_controlled = True
        product.save(update_fields=["is_controlled"])

        response = self.post_json(
            "/api/dispense/",
            {
                "branchId": self.branch.id,
                "sku": "MED-001",
                "transactionType": "Sale",
                "quantity": 1,
                "recipient": "Customer",
                "reference": "SALE-CONTROLLED",
                "amountReceived": "5.00",
                "paymentMethod": "Cash",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "prescription_required")
        self.assertIn("Prescriptions workflow", response.json()["detail"])
        self.assertEqual(MedicineBatch.objects.get().quantity, 10)
        self.assertEqual(Sale.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_branch_membership_is_required(self):
        other_branch = Branch.objects.create(name="North", code="NORTH")
        response = self.client.get(f"/api/data/?branchId={other_branch.id}")
        self.assertEqual(response.status_code, 403)

    def test_inventory_api_requires_authentication(self):
        self.client.logout()
        response = self.client.get(f"/api/data/?branchId={self.branch.id}")
        self.assertEqual(response.status_code, 401)

    def test_prescription_controlled_dispense_records_witness_and_lot(self):
        self.create_batch()
        product = MedicationProduct.objects.get(sku="MED-001")
        product.is_controlled = True
        product.requires_prescription = True
        product.save(update_fields=["is_controlled", "requires_prescription"])
        witness = get_user_model().objects.create_user(
            username="witness",
            password="test-password",
        )
        BranchMembership.objects.create(
            user=witness,
            branch=self.branch,
            role=BranchMembership.Role.PHARMACIST,
        )
        today = date.today().isoformat()
        response = self.post_json(
            "/api/prescriptions/create/",
            {
                "branchId": self.branch.id,
                "reference": "RX-001",
                "patientReference": "PAT-001",
                "prescriberName": "Dr Example",
                "issuedDate": today,
                "lines": [{"sku": "MED-001", "quantity": 3, "directions": "As directed"}],
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        prescription = Prescription.objects.get()
        verify = self.post_json(
            f"/api/prescriptions/{prescription.id}/verify/",
            {"branchId": self.branch.id},
        )
        self.assertEqual(verify.status_code, 200, verify.content)
        line = prescription.lines.get()

        dispense = self.post_json(
            f"/api/prescriptions/{prescription.id}/dispense/",
            {
                "branchId": self.branch.id,
                "lineId": line.id,
                "quantity": 2,
                "amountReceived": "10.00",
                "paymentMethod": "Cash",
                "reference": "DISP-001",
                "patientReference": "PAT-001",
                "witnessId": witness.id,
            },
        )
        self.assertEqual(dispense.status_code, 201, dispense.content)
        self.assertEqual(ControlledDrugRegisterEntry.objects.get().witness, witness)
        self.assertEqual(ControlledDrugRegisterEntry.objects.get().balance_after, 8)
        line.refresh_from_db()
        self.assertEqual(line.quantity_dispensed, 2)
        self.assertEqual(MedicineBatch.objects.get().quantity, 8)

    def test_prescription_dispense_rejects_same_user_as_witness(self):
        self.create_batch()
        product = MedicationProduct.objects.get(sku="MED-001")
        product.is_controlled = True
        product.save(update_fields=["is_controlled"])
        today = date.today().isoformat()
        response = self.post_json(
            "/api/prescriptions/create/",
            {
                "branchId": self.branch.id,
                "reference": "RX-SELF",
                "patientReference": "PAT-SELF",
                "prescriberName": "Dr Example",
                "issuedDate": today,
                "lines": [{"sku": "MED-001", "quantity": 1}],
            },
        )
        prescription_id = response.json()["prescription"]["id"]
        self.post_json(f"/api/prescriptions/{prescription_id}/verify/", {"branchId": self.branch.id})
        line = Prescription.objects.get(pk=prescription_id).lines.get()
        dispense = self.post_json(
            f"/api/prescriptions/{prescription_id}/dispense/",
            {
                "branchId": self.branch.id,
                "lineId": line.id,
                "quantity": 1,
                "amountReceived": 0,
                "paymentMethod": "Credit",
                "reference": "DISP-SELF",
                "patientReference": "PAT-SELF",
                "witnessId": self.user.id,
            },
        )
        self.assertEqual(dispense.status_code, 400)
        self.assertEqual(MedicineBatch.objects.get().quantity, 10)

    def test_purchase_order_receipt_creates_batch_and_movement(self):
        self.make_manager()
        self.create_batch()
        product = MedicationProduct.objects.get(sku="MED-001")
        supplier = Supplier.objects.create(name="Purchase supplier")
        response = self.post_json(
            "/api/purchase-orders/create/",
            {
                "branchId": self.branch.id,
                "supplierId": supplier.id,
                "number": "PO-001",
                "lines": [{"sku": product.sku, "quantity": 4, "unitCost": "2.50"}],
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        order_id = response.json()["id"]
        from .models import PurchaseOrderLine

        line = PurchaseOrderLine.objects.get()
        receive = self.post_json(
            f"/api/purchase-orders/{order_id}/receive/",
            {
                "branchId": self.branch.id,
                "receipts": [{
                    "lineId": line.id,
                    "quantity": 4,
                    "batch": "LOT-PO-1",
                    "expiry": "2030-05-01",
                    "sellingPrice": "6.00",
                }],
            },
        )
        self.assertEqual(receive.status_code, 200, receive.content)
        self.assertEqual(MedicineBatch.objects.filter(branch=self.branch).count(), 2)
        self.assertEqual(StockMovement.objects.filter(type=StockMovement.Type.RECEIVED).count(), 2)

    def test_branch_transfer_dispatch_and_receipt_are_persisted(self):
        self.make_manager()
        self.create_batch()
        destination = Branch.objects.create(name="North", code="NORTH")
        BranchMembership.objects.create(
            user=self.user,
            branch=destination,
            role=BranchMembership.Role.BRANCH_MANAGER,
        )
        create = self.post_json(
            "/api/transfers/create/",
            {
                "sourceBranchId": self.branch.id,
                "destinationBranchId": destination.id,
                "reference": "TR-001",
                "lines": [{"sku": "MED-001", "quantity": 3}],
            },
        )
        self.assertEqual(create.status_code, 201, create.content)
        transfer_id = create.json()["id"]
        dispatch = self.post_json(
            f"/api/transfers/{transfer_id}/dispatch/",
            {"branchId": self.branch.id},
        )
        self.assertEqual(dispatch.status_code, 200, dispatch.content)
        self.assertEqual(MedicineBatch.objects.get(branch=self.branch).quantity, 7)
        receive = self.post_json(
            f"/api/transfers/{transfer_id}/receive/",
            {"branchId": destination.id},
        )
        self.assertEqual(receive.status_code, 200, receive.content)
        self.assertEqual(MedicineBatch.objects.get(branch=destination).quantity, 3)
        self.assertEqual(BranchTransfer.objects.get().status, BranchTransfer.Status.RECEIVED)
        self.assertEqual(
            StockMovement.objects.filter(type=StockMovement.Type.TRANSFER_IN).get().quantity,
            3,
        )

    def test_branch_transfer_allocates_multiple_lots_and_allows_partial_receipt(self):
        self.make_manager()
        self.create_batch(quantity=5, batch="LOT-FIRST", expiry="2030-01-01")
        product = MedicationProduct.objects.get(sku="MED-001")
        later_lot = MedicineBatch.objects.create(
            branch=self.branch,
            product=product,
            batch="LOT-SECOND",
            quantity=5,
            reorder_level=0,
            expiry=date(2030, 2, 1),
            supplier="Supplier A",
            reference="RECEIPT-SECOND",
            purchase_cost="2.00",
            selling_price="5.00",
        )
        destination = Branch.objects.create(name="South", code="SOUTH")
        BranchMembership.objects.create(
            user=self.user,
            branch=destination,
            role=BranchMembership.Role.BRANCH_MANAGER,
        )
        create = self.post_json(
            "/api/transfers/create/",
            {
                "sourceBranchId": self.branch.id,
                "destinationBranchId": destination.id,
                "reference": "TR-SPLIT",
                "lines": [{"sku": "MED-001", "quantity": 8}],
            },
        )
        self.assertEqual(create.status_code, 201, create.content)
        transfer = BranchTransfer.objects.get()
        lines = list(transfer.lines.order_by("source_batch__expiry"))
        self.assertEqual(len(lines), 2)
        self.assertEqual([line.quantity_dispatched for line in lines], [5, 3])
        self.assertEqual(lines[0].source_batch.batch, "LOT-FIRST")
        self.assertEqual(lines[1].source_batch_id, later_lot.id)

        dispatch = self.post_json(
            f"/api/transfers/{transfer.id}/dispatch/",
            {"branchId": self.branch.id},
        )
        self.assertEqual(dispatch.status_code, 200, dispatch.content)
        first_receipt = self.post_json(
            f"/api/transfers/{transfer.id}/receive/",
            {
                "branchId": destination.id,
                "quantities": {str(lines[0].id): 2, str(lines[1].id): 0},
            },
        )
        self.assertEqual(first_receipt.status_code, 200, first_receipt.content)
        self.assertEqual(first_receipt.json()["status"], BranchTransfer.Status.PARTIALLY_RECEIVED)
        lines[0].refresh_from_db()
        self.assertEqual(lines[0].quantity_received, 2)
        self.assertEqual(MedicineBatch.objects.get(pk=lines[0].destination_batch_id).quantity, 2)

        final_receipt = self.post_json(
            f"/api/transfers/{transfer.id}/receive/",
            {"branchId": destination.id},
        )
        self.assertEqual(final_receipt.status_code, 200, final_receipt.content)
        self.assertEqual(final_receipt.json()["status"], BranchTransfer.Status.RECEIVED)
        transfer.refresh_from_db()
        self.assertEqual(transfer.lines.get(pk=lines[0].id).quantity_received, 5)
        self.assertEqual(transfer.lines.get(pk=lines[1].id).quantity_received, 3)
        self.assertEqual(
            StockMovement.objects.filter(branch=destination, type=StockMovement.Type.TRANSFER_IN).count(),
            3,
        )

    def test_barcode_lookup_alias_and_idempotent_integration_events(self):
        self.create_batch()
        alias = self.post_json(
            "/api/barcode/aliases/",
            {"sku": "MED-001", "value": "0001234567890", "symbology": "EAN-13"},
        )
        self.assertEqual(alias.status_code, 403)
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        alias = self.post_json(
            "/api/barcode/aliases/",
            {"sku": "MED-001", "value": "0001234567890", "symbology": "EAN-13"},
        )
        self.assertEqual(alias.status_code, 201, alias.content)
        lookup = self.client.get("/api/barcode/lookup/?value=0001234567890")
        self.assertEqual(lookup.status_code, 200)
        self.assertEqual(lookup.json()["product"]["sku"], "MED-001")

        event_data = {
            "provider": "test-pos",
            "externalId": "sale-123",
            "eventType": "pos.sale",
            "payload": {"reference": "POS-123"},
        }
        first = self.post_json("/api/integrations/events/", event_data)
        duplicate = self.post_json("/api/integrations/events/", event_data)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(duplicate.status_code, 200)
        self.assertTrue(duplicate.json()["duplicate"])
        self.assertEqual(ExternalIntegrationEvent.objects.count(), 1)

    def test_purchase_order_creation_requires_manager_role(self):
        self.create_batch()
        supplier = Supplier.objects.create(name="Supplier role")
        response = self.post_json(
            "/api/purchase-orders/create/",
            {
                "branchId": self.branch.id,
                "supplierId": supplier.id,
                "number": "PO-DENIED",
                "lines": [{"sku": "MED-001", "quantity": 1, "unitCost": "1.00"}],
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_reorder_recommendation_creates_and_submits_draft_order(self):
        self.make_manager()
        self.create_batch(reorderLevel=12)
        product = MedicationProduct.objects.get(sku="MED-001")
        supplier = Supplier.objects.create(name="Preferred supplier")
        SupplierProduct.objects.create(
            supplier=supplier,
            product=product,
            unit_cost="2.50",
            lead_time_days=3,
            is_preferred=True,
        )

        suggestions = self.client.get(
            f"/api/reorder-suggestions/?branchId={self.branch.id}"
        )
        self.assertEqual(suggestions.status_code, 200)
        self.assertEqual(suggestions.json()["suggestions"][0]["suggestedQuantity"], 14)
        self.assertEqual(suggestions.json()["suggestions"][0]["supplierId"], supplier.id)

        draft = self.post_json(
            "/api/purchase-orders/reorder-draft/",
            {"branchId": self.branch.id, "sku": product.sku},
        )
        self.assertEqual(draft.status_code, 201, draft.content)
        order_id = draft.json()["id"]
        self.assertEqual(draft.json()["status"], "draft")

        submitted = self.post_json(
            f"/api/purchase-orders/{order_id}/submit/",
            {"branchId": self.branch.id},
        )
        self.assertEqual(submitted.status_code, 200, submitted.content)
        self.assertEqual(submitted.json()["status"], "submitted")

    def test_supplier_product_mapping_requires_administrator(self):
        self.create_batch()
        supplier = Supplier.objects.create(name="Mapped supplier")
        data = {
            "sku": "MED-001",
            "supplierId": supplier.id,
            "unitCost": "2.25",
            "leadTimeDays": 4,
            "isPreferred": True,
        }
        denied = self.post_json("/api/supplier-products/", data)
        self.assertEqual(denied.status_code, 403)

        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        saved = self.post_json("/api/supplier-products/", data)
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertTrue(
            SupplierProduct.objects.get(product__sku="MED-001").is_preferred
        )
