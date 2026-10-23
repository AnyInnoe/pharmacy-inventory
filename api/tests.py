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
