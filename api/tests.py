import json

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import (
    AuditEvent,
    Branch,
    BranchMembership,
    CustomerPayment,
    MedicineBatch,
    MedicationProduct,
    Sale,
    SaleLine,
    StockMovement,
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
