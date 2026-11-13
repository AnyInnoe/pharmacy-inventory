import json
import smtplib
import tempfile
from datetime import date, timedelta
from unittest.mock import patch

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import (
    AuditEvent,
    Branch,
    BranchMembership,
    BranchTransfer,
    ControlledDrugRegisterEntry,
    CustomerPayment,
    EmailNotification,
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
            "purchaseCost": "2.00",
            "sellingPrice": "5.00",
        }
        data.update(overrides)
        return self.post_json("/api/batches/", data)

    def create_pending_sale(self, reference):
        product = MedicationProduct.objects.get(sku="MED-001")
        return Sale.objects.create(
            branch=self.branch,
            sku=product.sku,
            name=product.name,
            quantity=1,
            sale_amount="5.00",
            cost_amount="2.00",
            amount_received="0.00",
            balance_due="5.00",
            payment_method="",
            recipient="Customer",
            reference=reference,
            actor=self.user,
            approval_status=Sale.ApprovalStatus.PENDING,
            approval_amount_received="0.00",
            approval_payment_method="Credit",
        )

    def test_receipt_persists_product_lot_and_movement(self):
        response = self.create_batch()

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(MedicationProduct.objects.count(), 1)
        self.assertEqual(MedicineBatch.objects.get().quantity, 10)
        movement = StockMovement.objects.get()
        self.assertEqual(movement.quantity, 10)
        self.assertEqual(movement.type, StockMovement.Type.RECEIVED)
        self.assertEqual(movement.actor, self.user)
        self.assertRegex(movement.reference, r"^RCV-\d{8}-\d{6}$")
        self.assertEqual(MedicineBatch.objects.get().reference, movement.reference)

        data = self.client.get(f"/api/data/?branchId={self.branch.id}").json()
        self.assertEqual(data["inventory"][0]["sku"], "MED-001")
        self.assertEqual(data["stockMovements"][0]["reference"], movement.reference)

    def test_skin_care_product_supports_label_details_and_sale_without_expiry(self):
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        product_response = self.post_json(
            "/api/products/create/",
            {
                "sku": "SKIN-001",
                "name": "Daily Moisturizer",
                "category": "Moisturizer",
                "productType": "skin_care",
                "brand": "Example Brand",
                "skinType": "Dry",
                "skinConcerns": "Dryness",
                "keyIngredients": "Glycerin",
                "usageInstructions": "Use as directed on package.",
                "warnings": "For external use.",
                "periodAfterOpeningMonths": 12,
            },
        )
        self.assertEqual(product_response.status_code, 201, product_response.content)

        prescription_response = self.post_json(
            "/api/prescriptions/create/",
            {
                "branchId": self.branch.id,
                "reference": "SKIN-RX-001",
                "patientReference": "PATIENT-001",
                "prescriberName": "Prescriber",
                "issuedDate": date.today().isoformat(),
                "lines": [{"sku": "SKIN-001", "quantity": 1}],
            },
        )
        self.assertEqual(prescription_response.status_code, 400)

        batch_response = self.create_batch(
            sku="SKIN-001",
            name="Daily Moisturizer",
            category="Moisturizer",
            batch="SKIN-LOT-001",
            expiry="",
        )
        self.assertEqual(batch_response.status_code, 201, batch_response.content)
        batch = MedicineBatch.objects.get()
        self.assertIsNone(batch.expiry)

        catalog_product = MedicationProduct.objects.get(sku="SKIN-001")
        self.assertEqual(catalog_product.brand, "Example Brand")
        self.assertEqual(catalog_product.period_after_opening_months, 12)
        product_data = self.client.get("/api/products/").json()["products"][0]
        self.assertEqual(product_data["productType"], "skin_care")
        self.assertEqual(product_data["keyIngredients"], "Glycerin")
        inventory_data = self.client.get(
            f"/api/data/?branchId={self.branch.id}"
        ).json()["inventory"][0]
        self.assertIsNone(inventory_data["expiry"])

        self.make_manager()
        forecast_response = self.client.get(
            f"/api/reports/replenishment/?branchId={self.branch.id}"
        )
        self.assertEqual(forecast_response.status_code, 200, forecast_response.content)
        recommendation = forecast_response.json()["recommendations"][0]
        self.assertEqual(recommendation["productType"], "skin_care")
        self.assertEqual(recommendation["currentStock"], 10)

        sale_response = self.post_json(
            "/api/dispense/",
            {
                "branchId": self.branch.id,
                "sku": "SKIN-001",
                "transactionType": "Sale",
                "quantity": 1,
                "recipient": "Customer",
                "reference": "SKIN-SALE-001",
                "amountReceived": "5.00",
                "paymentMethod": "Cash",
            },
        )
        self.assertEqual(sale_response.status_code, 201, sale_response.content)
        self.assertEqual(MedicineBatch.objects.get().quantity, 9)

    def test_product_sku_is_generated_when_catalog_form_omits_it(self):
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])

        response = self.post_json(
            "/api/products/create/",
            {"name": "Auto-coded product", "category": "General"},
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertRegex(response.json()["sku"], r"^SKU-[0-9A-F]{12}$")
        self.assertEqual(MedicationProduct.objects.get().sku, response.json()["sku"])

    def test_medicine_batch_still_requires_expiry(self):
        response = self.create_batch(expiry="")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(MedicationProduct.objects.count(), 0)
        self.assertEqual(MedicineBatch.objects.count(), 0)

    def test_skin_care_purchase_order_can_be_received_without_expiry(self):
        product = MedicationProduct.objects.create(
            sku="SKIN-002",
            name="Gentle Cleanser",
            category="Cleanser",
            product_type=MedicationProduct.ProductType.SKIN_CARE,
        )
        supplier = Supplier.objects.create(name="Skin Supplier")
        order = PurchaseOrder.objects.create(
            branch=self.branch,
            supplier=supplier,
            number="PO-SKIN-001",
            status=PurchaseOrder.Status.SUBMITTED,
            created_by=self.user,
        )
        line = PurchaseOrderLine.objects.create(
            purchase_order=order,
            product=product,
            quantity_ordered=6,
            unit_cost="3.00",
        )
        self.make_manager()

        response = self.post_json(
            f"/api/purchase-orders/{order.id}/receive/",
            {
                "branchId": self.branch.id,
                "receipts": [{
                    "lineId": line.id,
                    "quantity": 6,
                    "batch": "SKIN-LOT-002",
                    "expiry": "",
                    "sellingPrice": "5.00",
                }],
            },
        )

        self.assertEqual(response.status_code, 200, response.content)
        batch = MedicineBatch.objects.get()
        self.assertIsNone(batch.expiry)
        self.assertEqual(batch.quantity, 6)

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
                "amountReceived": "4.00",
                "paymentMethod": "Cash",
            },
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertNotIn("grossProfit", response.json()["sale"])
        sale = Sale.objects.get()
        sale_reference = response.json()["sale"]["reference"]
        self.assertRegex(sale_reference, r"^SALE-\d{8}-\d{6}$")
        self.assertEqual(sale.reference, sale_reference)
        self.assertEqual(sale.recipient, "Walk-in customer")
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
        self.assertEqual(sale_movement.reference, sale_reference)
        self.assertRegex(CustomerPayment.objects.get().reference, r"^PAY-\d{8}-\d{6}$")

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
        self.assertRegex(payment_response.json()["reference"], r"^PAY-\d{8}-\d{6}$")
        self.assertNotEqual(payment_response.json()["reference"], "PAY-001")
        sale.refresh_from_db()
        self.assertEqual(sale.balance_due, 0)
        self.assertEqual(CustomerPayment.objects.count(), 2)
        self.assertEqual(
            CustomerPayment.objects.order_by("-id").first().reference,
            payment_response.json()["reference"],
        )
        self.assertEqual(AuditEvent.objects.filter(entity_type="sale").count(), 2)

    def test_cashier_sale_completes_immediately_and_posts_payment_and_stock(self):
        self.create_batch()
        self.make_cashier()
        response = self.post_json(
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

        self.assertEqual(response.status_code, 201, response.content)
        sale = Sale.objects.get()
        self.assertEqual(sale.approval_status, Sale.ApprovalStatus.APPROVED)
        self.assertEqual(sale.actor, self.user)
        self.assertIsNone(sale.approved_by)
        self.assertIsNotNone(sale.approved_at)
        self.assertEqual(sale.approval_amount_received, 4)
        self.assertEqual(sale.amount_received, 4)
        self.assertEqual(sale.balance_due, 6)
        self.assertEqual(MedicineBatch.objects.get().quantity, 8)
        self.assertEqual(
            StockMovement.objects.filter(type=StockMovement.Type.SALE).count(),
            1,
        )
        self.assertEqual(CustomerPayment.objects.count(), 1)
        self.assertNotIn("grossProfit", response.json()["sale"])
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
            {
                "branchId": self.branch.id,
            },
        )
        self.assertEqual(denied.status_code, 403)

        payment = self.post_json(
            f"/api/sales/{sale.pk}/payments/",
            {
                "branchId": self.branch.id,
                "amount": "1.00",
                "method": "Cash",
                "reference": "BALANCE-PAY",
            },
        )
        self.assertEqual(payment.status_code, 201, payment.content)
        sale.refresh_from_db()
        self.assertEqual(sale.approval_status, Sale.ApprovalStatus.APPROVED)
        self.assertEqual(sale.amount_received, 5)
        self.assertEqual(sale.balance_due, 5)
        self.assertEqual(CustomerPayment.objects.count(), 2)
        self.assertEqual(
            CustomerPayment.objects.filter(actor=self.user).count(),
            2,
        )
        movement = StockMovement.objects.get(type=StockMovement.Type.SALE)
        self.assertEqual(movement.actor, self.user)
        self.assertEqual(sale.lines.get().quantity, 2)

    def test_sale_receipt_pdf_and_privacy_safe_email_notification(self):
        self.create_batch()
        self.make_cashier()
        response = self.post_json(
            "/api/dispense/",
            {
                "branchId": self.branch.id,
                "sku": "MED-001",
                "transactionType": "Sale",
                "quantity": 1,
                "amountReceived": "5.00",
                "paymentMethod": "Cash",
                "receiptEmail": "customer@example.com",
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(response.json()["receiptEmailQueued"])
        sale = Sale.objects.get()
        receipt = self.client.get(f"/api/sales/{sale.pk}/receipt.pdf")
        self.assertEqual(receipt.status_code, 200, receipt.content)
        self.assertEqual(receipt["Content-Type"], "application/pdf")
        self.assertTrue(receipt.content.startswith(b"%PDF-"))

        notification = EmailNotification.objects.get()
        self.assertNotIn("Example medicine", notification.body)
        self.assertNotIn("Walk-in customer", notification.body)
        with override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
            mail.outbox = []
            call_command("send_email_notifications")
        notification.refresh_from_db()
        self.assertEqual(notification.status, EmailNotification.Status.SENT)
        self.assertEqual(mail.outbox[0].to, ["customer@example.com"])
        self.assertNotIn("Example medicine", mail.outbox[0].body)

    def test_email_delivery_failure_is_queued_for_retry(self):
        notification = EmailNotification.objects.create(
            event_key="retry-test",
            notification_type=EmailNotification.Type.PURCHASE_ORDER,
            recipient_email="supplier@example.com",
            subject="Purchase order",
            body="Please review the order.",
        )
        with patch(
            "api.management.commands.send_email_notifications.send_mail",
            side_effect=smtplib.SMTPException("Temporary delivery failure"),
        ):
            call_command("send_email_notifications")

        notification.refresh_from_db()
        self.assertEqual(notification.status, EmailNotification.Status.PENDING)
        self.assertEqual(notification.attempts, 1)
        self.assertIn("Temporary delivery failure", notification.last_error)
        self.assertGreater(notification.next_attempt_at, timezone.now())

    def test_supplier_invoice_original_and_reconciliation_pdfs(self):
        self.make_manager()
        supplier = Supplier.objects.create(name="PDF supplier")
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                response = self.client.post(
                    "/api/supplier-invoices/",
                    {
                        "branchId": str(self.branch.id),
                        "supplier": supplier.name,
                        "supplierId": str(supplier.id),
                        "invoiceNumber": "PDF-INV-001",
                        "invoiceAmount": "42.00",
                        "amountPaid": "0.00",
                        "dueDate": "2030-02-01",
                        "method": "Cash",
                        "originalDocument": SimpleUploadedFile(
                            "supplier-invoice.pdf",
                            b"%PDF-1.4\noriginal invoice",
                            content_type="application/pdf",
                        ),
                    },
                )
                self.assertEqual(response.status_code, 201, response.content)
                invoice = SupplierInvoice.objects.get()
                self.assertTrue(response.json()["invoice"]["hasOriginalDocument"])

                reconciliation = self.client.get(
                    f"/api/supplier-invoices/{invoice.pk}/reconciliation.pdf",
                )
                self.assertEqual(reconciliation.status_code, 200, reconciliation.content)
                self.assertTrue(reconciliation.content.startswith(b"%PDF-"))

                original = self.client.get(
                    f"/api/supplier-invoices/{invoice.pk}/original/",
                )
                self.assertEqual(original.status_code, 200)
                self.assertEqual(b"".join(original.streaming_content), b"%PDF-1.4\noriginal invoice")

    def test_cashier_sale_client_request_id_is_idempotent(self):
        self.create_batch()
        self.make_cashier()
        sale_request = {
            "branchId": self.branch.id,
            "sku": "MED-001",
            "transactionType": "Sale",
            "quantity": 2,
            "recipient": "Customer",
            "reference": "SALE-OFFLINE-001",
            "amountReceived": "4.00",
            "paymentMethod": "Cash",
            "clientRequestId": "c44e298a-e315-4c66-9716-2a576f8c3d86",
        }

        first = self.post_json("/api/dispense/", sale_request)
        retry = self.post_json("/api/dispense/", sale_request)

        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(retry.status_code, 200, retry.content)
        self.assertTrue(retry.json()["duplicate"])
        self.assertEqual(Sale.objects.count(), 1)
        self.assertEqual(MedicineBatch.objects.get().quantity, 8)
        self.assertEqual(CustomerPayment.objects.count(), 1)
        self.assertEqual(Sale.objects.get().approval_status, Sale.ApprovalStatus.APPROVED)

        changed_request = {**sale_request, "quantity": 3}
        conflict = self.post_json("/api/dispense/", changed_request)
        self.assertEqual(conflict.status_code, 409)

    def test_only_branch_managers_and_administrators_can_view_cost_and_profit(self):
        self.create_batch(reorderLevel=20)
        self.make_manager()
        sale_response = self.post_json(
            "/api/dispense/",
            {
                "branchId": self.branch.id,
                "sku": "MED-001",
                "transactionType": "Sale",
                "quantity": 1,
                "recipient": "Customer",
                "reference": "SALE-MARGIN-TEST",
                "amountReceived": "5.00",
                "paymentMethod": "Cash",
            },
        )
        self.assertEqual(sale_response.status_code, 201, sale_response.content)
        product = MedicationProduct.objects.get(sku="MED-001")
        supplier = Supplier.objects.create(name="Margin test supplier")
        SupplierProduct.objects.create(
            supplier=supplier,
            product=product,
            unit_cost="3.00",
            lead_time_days=5,
            is_preferred=True,
        )
        order = PurchaseOrder.objects.create(
            branch=self.branch,
            supplier=supplier,
            number="PO-MARGIN-TEST",
            created_by=self.user,
        )
        PurchaseOrderLine.objects.create(
            purchase_order=order,
            product=product,
            quantity_ordered=2,
            unit_cost="3.00",
        )
        membership = BranchMembership.objects.get(
            user=self.user,
            branch=self.branch,
        )
        membership.role = BranchMembership.Role.PHARMACIST
        membership.save(update_fields=["role"])
        data = self.client.get(f"/api/data/?branchId={self.branch.id}").json()
        self.assertNotIn("purchaseCost", data["inventory"][0])
        self.assertNotIn("grossProfit", data["sales"][0])
        suggestions = self.client.get(
            f"/api/reorder-suggestions/?branchId={self.branch.id}"
        ).json()["suggestions"]
        purchase_orders = self.client.get(
            f"/api/purchase-orders/?branchId={self.branch.id}"
        ).json()["purchaseOrders"]
        self.assertNotIn("unitCost", suggestions[0])
        self.assertNotIn("unitCost", purchase_orders[0]["lines"][0])

        membership.role = BranchMembership.Role.BRANCH_MANAGER
        membership.save(update_fields=["role"])
        data = self.client.get(f"/api/data/?branchId={self.branch.id}").json()
        self.assertIn("purchaseCost", data["inventory"][0])
        self.assertIn("grossProfit", data["sales"][0])
        suggestions = self.client.get(
            f"/api/reorder-suggestions/?branchId={self.branch.id}"
        ).json()["suggestions"]
        purchase_orders = self.client.get(
            f"/api/purchase-orders/?branchId={self.branch.id}"
        ).json()["purchaseOrders"]
        self.assertEqual(suggestions[0]["unitCost"], 3)
        self.assertEqual(purchase_orders[0]["lines"][0]["unitCost"], 3)

    def test_manager_analytics_summarizes_approved_sales_and_stock_decisions(self):
        self.create_batch()
        self.make_manager()
        approved = self.post_json(
            "/api/dispense/",
            {
                "branchId": self.branch.id,
                "sku": "MED-001",
                "transactionType": "Sale",
                "quantity": 2,
                "recipient": "Customer",
                "reference": "SALE-APPROVED",
                "amountReceived": "5.00",
                "paymentMethod": "Cash",
            },
        )
        self.assertEqual(approved.status_code, 201, approved.content)

        self.make_cashier()
        direct_sale = self.post_json(
            "/api/dispense/",
            {
                "branchId": self.branch.id,
                "sku": "MED-001",
                "transactionType": "Sale",
                "quantity": 1,
                "recipient": "Customer",
                "reference": "SALE-PENDING",
                "amountReceived": "0.00",
                "paymentMethod": "Cash",
            },
        )
        self.assertEqual(direct_sale.status_code, 201, direct_sale.content)
        self.make_manager()

        today = date.today().isoformat()
        report = self.client.get(
            f"/api/reports/analytics/?branchId={self.branch.id}&start={today}&end={today}"
        )

        self.assertEqual(report.status_code, 200, report.content)
        data = report.json()
        self.assertEqual(data["summary"]["salesCount"], 2)
        self.assertEqual(data["summary"]["salesAmount"], 15)
        self.assertEqual(data["summary"]["grossProfit"], 9)
        self.assertEqual(data["summary"]["outstandingBalance"], 10)
        self.assertEqual(data["summary"]["pendingApprovalCount"], 0)
        self.assertIsNone(data["summary"]["salesChangePercent"])
        self.assertEqual(data["topProducts"][0]["sku"], "MED-001")
        self.assertEqual(data["topProducts"][0]["unitsSold"], 3)
        self.assertEqual(len(data["salesTrend"]), 1)
        self.assertEqual(data["salesTrend"][0]["salesAmount"], 15)

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

    def test_stock_count_generates_an_adjustment_reference(self):
        self.make_manager()
        self.create_batch()

        response = self.post_json(
            "/api/stock-count/",
            {
                "branchId": self.branch.id,
                "batch": "LOT-001",
                "quantity": 9,
                "reason": "Counting correction",
            },
        )

        self.assertEqual(response.status_code, 200, response.content)
        reference = response.json()["reference"]
        self.assertRegex(reference, r"^ADJ-\d{8}-\d{6}$")
        movement = StockMovement.objects.get(type=StockMovement.Type.STOCK_COUNT)
        self.assertEqual(movement.reference, reference)

    def test_non_sale_issue_generates_a_reference(self):
        self.create_batch()

        response = self.post_json(
            "/api/dispense/",
            {
                "branchId": self.branch.id,
                "sku": "MED-001",
                "transactionType": "Non-sale issue",
                "quantity": 1,
                "recipient": "Damaged stock",
            },
        )

        self.assertEqual(response.status_code, 201, response.content)
        reference = response.json()["reference"]
        self.assertRegex(reference, r"^ISS-\d{8}-\d{6}$")
        movement = StockMovement.objects.get(type=StockMovement.Type.NON_SALE_ISSUE)
        self.assertEqual(movement.reference, reference)
        self.assertEqual(movement.recipient, "Damaged stock")

    def test_supplier_reference_is_generated(self):
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])

        response = self.post_json(
            "/api/suppliers/create/",
            {"name": "Supplier A"},
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["reference"], "SUP-000001")
        self.assertEqual(
            self.client.get("/api/suppliers/").json()["suppliers"][0]["reference"],
            "SUP-000001",
        )

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

    def test_administrator_can_read_cross_branch_analytics_but_not_operations(self):
        self.create_batch()
        other_branch = Branch.objects.create(name="North", code="NORTH")
        other_membership = BranchMembership.objects.create(
            user=self.user,
            branch=other_branch,
            role=BranchMembership.Role.PHARMACIST,
        )
        other_batch = self.create_batch(
            branchId=other_branch.id,
            sku="MED-002",
            name="Other medicine",
            batch="NORTH-LOT",
            reference="NORTH-RECEIPT",
        )
        self.assertEqual(other_batch.status_code, 201, other_batch.content)
        other_membership.role = BranchMembership.Role.BRANCH_MANAGER
        other_membership.save(update_fields=["role"])
        other_sale = self.post_json(
            "/api/dispense/",
            {
                "branchId": other_branch.id,
                "sku": "MED-002",
                "transactionType": "Sale",
                "quantity": 1,
                "recipient": "Customer",
                "reference": "NORTH-SALE",
                "amountReceived": "5.00",
                "paymentMethod": "Cash",
            },
        )
        self.assertEqual(other_sale.status_code, 201, other_sale.content)
        administrator = get_user_model().objects.create_superuser(
            username="analytics-administrator",
            password="test-password",
        )
        self.client.force_login(administrator)

        today = date.today().isoformat()
        report = self.client.get(
            f"/api/reports/analytics/?branchId={other_branch.id}&start={today}&end={today}"
        )
        export = self.client.get(
            f"/api/reports/movements.csv?branchId={other_branch.id}&start={today}&end={today}"
        )
        operational_data = self.client.get(f"/api/data/?branchId={other_branch.id}")
        stock_adjustment = self.post_json(
            "/api/stock-count/",
            {
                "branchId": other_branch.id,
                "batch": "NORTH-LOT",
                "quantity": 9,
                "reason": "Count",
                "reference": "NORTH-COUNT",
            },
        )

        self.assertEqual(report.status_code, 200, report.content)
        self.assertEqual(report.json()["summary"]["unitsReceived"], 10)
        self.assertEqual(report.json()["summary"]["salesAmount"], 5)
        self.assertEqual(report.json()["summary"]["grossProfit"], 3)
        self.assertEqual(export.status_code, 200)
        self.assertEqual(operational_data.status_code, 403)
        self.assertEqual(stock_adjustment.status_code, 403)
        self.assertEqual(
            MedicineBatch.objects.get(branch=other_branch).quantity,
            9,
        )

    def test_sale_approval_rejects_price_changes_since_cashier_checkout(self):
        self.create_batch()
        self.make_cashier()
        sale = self.create_pending_sale("SALE-PRICE-CHANGE")
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

        self.assertEqual(approval.status_code, 409)
        sale.refresh_from_db()
        self.assertEqual(sale.approval_status, Sale.ApprovalStatus.PENDING)
        self.assertEqual(MedicineBatch.objects.get().quantity, 10)
        self.assertEqual(CustomerPayment.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_pharmacist_can_approve_legacy_pending_sale_without_margin_data(self):
        self.create_batch()
        self.make_cashier()
        sale = self.create_pending_sale("SALE-LEGACY-PENDING")
        pharmacist = get_user_model().objects.create_user(
            username="legacy-sale-pharmacist",
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
        self.assertNotIn("grossProfit", approved.json()["sale"])
        self.assertEqual(MedicineBatch.objects.get().quantity, 9)

    def test_rejecting_cashier_sale_leaves_stock_and_payments_unchanged(self):
        self.create_batch()
        self.make_cashier()
        sale = self.create_pending_sale("SALE-REJECT")
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

        self.assertEqual(rejected.status_code, 200, rejected.content)
        self.assertNotIn("grossProfit", rejected.json()["sale"])
        sale.refresh_from_db()
        self.assertEqual(sale.approval_status, Sale.ApprovalStatus.REJECTED)
        self.assertEqual(sale.rejected_by, pharmacist)
        self.assertEqual(sale.rejection_reason, "Verify item and quantity.")
        self.assertEqual(MedicineBatch.objects.get().quantity, 10)
        self.assertEqual(CustomerPayment.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_supplier_invoice_and_payment_are_persisted(self):
        self.make_manager()
        supplier = Supplier.objects.create(name="Supplier A")
        response = self.post_json(
            "/api/supplier-invoices/",
            {
                "branchId": self.branch.id,
                "supplier": "Supplier A",
                "supplierId": supplier.id,
                "invoiceNumber": "INV-001",
                "invoiceAmount": "100.00",
                "amountPaid": "20.00",
                "dueDate": "2030-02-01",
                "method": "Cash",
            },
        )

        self.assertEqual(response.status_code, 201, response.content)
        invoice = SupplierInvoice.objects.get()
        self.assertEqual(invoice.supplier_record, supplier)
        self.assertEqual(invoice.amount_paid, 20)
        self.assertEqual(SupplierPayment.objects.get().amount, 20)
        self.assertEqual(response.json()["invoice"]["invoiceNumber"], "INV-001")
        self.assertRegex(response.json()["invoice"]["reference"], r"^INV-\d{6}$")
        self.assertRegex(SupplierPayment.objects.get().reference, r"^SPAY-\d{8}-\d{6}$")

        payment_response = self.post_json(
            f"/api/supplier-invoices/{invoice.id}/payments/",
            {
                "branchId": self.branch.id,
                "amount": "80.00",
                "method": "Bank transfer",
            },
        )
        self.assertEqual(payment_response.status_code, 201, payment_response.content)
        self.assertRegex(payment_response.json()["reference"], r"^SPAY-\d{8}-\d{6}$")
        invoice.refresh_from_db()
        self.assertEqual(invoice.amount_paid, 100)
        self.assertEqual(SupplierPayment.objects.count(), 2)
        supplier_payments = self.client.get(
            f"/api/data/?branchId={self.branch.id}"
        ).json()["supplierPayments"]
        self.assertEqual(
            supplier_payments[0]["invoiceReference"],
            response.json()["invoice"]["reference"],
        )

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
        self.make_cashier()
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

    def test_prescription_product_cannot_use_cashier_pos(self):
        self.create_batch()
        product = MedicationProduct.objects.get(sku="MED-001")
        product.requires_prescription = True
        product.save(update_fields=["requires_prescription"])
        self.make_cashier()

        response = self.post_json(
            "/api/dispense/",
            {
                "branchId": self.branch.id,
                "sku": "MED-001",
                "transactionType": "Sale",
                "quantity": 1,
                "recipient": "Customer",
                "reference": "SALE-RX-BLOCKED",
                "amountReceived": "5.00",
                "paymentMethod": "Cash",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "prescription_required")
        self.assertEqual(MedicineBatch.objects.get().quantity, 10)
        self.assertEqual(Sale.objects.count(), 0)

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
                "witnessId": witness.id,
            },
        )
        self.assertEqual(dispense.status_code, 201, dispense.content)
        self.assertNotIn("grossProfit", dispense.json()["sale"])
        self.assertRegex(
            dispense.json()["sale"]["reference"],
            r"^SALE-\d{8}-\d{6}$",
        )
        self.assertEqual(Sale.objects.get().recipient, "PAT-001")
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
                "lines": [{"sku": product.sku, "quantity": 4, "unitCost": "2.50"}],
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertRegex(response.json()["number"], r"^PO-\d{8}-\d{6}$")
        self.assertNotEqual(response.json()["number"], "PO-001")
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
                "lines": [{"sku": "MED-001", "quantity": 3}],
            },
        )
        self.assertEqual(create.status_code, 201, create.content)
        self.assertRegex(create.json()["reference"], r"^TRF-\d{8}-\d{6}$")
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

    def test_idempotent_integration_events(self):
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

    def test_manager_replenishment_forecast_uses_sales_lead_time_and_reorder_floor(self):
        self.create_batch(quantity=2, reorderLevel=2)
        denied = self.client.get(
            f"/api/reports/replenishment/?branchId={self.branch.id}"
        )
        self.assertEqual(denied.status_code, 403)

        self.make_manager()
        product = MedicationProduct.objects.get(sku="MED-001")
        supplier = Supplier.objects.create(name="Forecast supplier")
        SupplierProduct.objects.create(
            supplier=supplier,
            product=product,
            unit_cost="2.50",
            lead_time_days=3,
            is_preferred=True,
        )

        cold_start = self.client.get(
            f"/api/reports/replenishment/?branchId={self.branch.id}"
        )
        self.assertEqual(cold_start.status_code, 200, cold_start.content)
        cold_start_item = cold_start.json()["recommendations"][0]
        self.assertEqual(cold_start_item["confidence"], "low")
        self.assertEqual(cold_start_item["suggestedOrderQuantity"], 2)

        for days_ago in range(1, 9):
            recent_sale = Sale.objects.create(
                branch=self.branch,
                sku=product.sku,
                name=product.name,
                quantity=4,
                sale_amount="20.00",
                cost_amount="8.00",
                amount_received="20.00",
                balance_due="0.00",
                payment_method="Cash",
                recipient="Customer",
                reference=f"FORECAST-RECENT-{days_ago}",
                actor=self.user,
                approval_status=Sale.ApprovalStatus.APPROVED,
                approved_by=self.user,
                approved_at=timezone.now(),
            )
            Sale.objects.filter(pk=recent_sale.pk).update(
                recorded_at=timezone.now() - timedelta(days=days_ago)
            )
        for days_ago in range(29, 37):
            previous_sale = Sale.objects.create(
                branch=self.branch,
                sku=product.sku,
                name=product.name,
                quantity=2,
                sale_amount="10.00",
                cost_amount="4.00",
                amount_received="10.00",
                balance_due="0.00",
                payment_method="Cash",
                recipient="Customer",
                reference=f"FORECAST-PREVIOUS-{days_ago}",
                actor=self.user,
                approval_status=Sale.ApprovalStatus.APPROVED,
                approved_by=self.user,
                approved_at=timezone.now(),
            )
            Sale.objects.filter(pk=previous_sale.pk).update(
                recorded_at=timezone.now() - timedelta(days=days_ago)
            )

        response = self.client.get(
            f"/api/reports/replenishment/?branchId={self.branch.id}"
        )

        self.assertEqual(response.status_code, 200, response.content)
        item = response.json()["recommendations"][0]
        self.assertEqual(item["confidence"], "medium")
        self.assertEqual(item["salesDays"], 16)
        self.assertEqual(item["leadTimeDays"], 3)
        self.assertEqual(item["forecastHorizonDays"], 17)
        self.assertEqual(item["expectedDemand"], 17)
        self.assertEqual(item["currentStock"], 2)
        self.assertEqual(item["expectedDeliveryDate"], (timezone.localdate() + timedelta(days=3)).isoformat())
        self.assertEqual(item["targetStock"], 17)
        self.assertEqual(item["suggestedOrderQuantity"], 15)
        self.assertEqual(item["supplierId"], supplier.id)
        self.assertEqual(item["modelVersion"], "weighted-moving-average-v1")

        MedicineBatch.objects.create(
            branch=self.branch,
            product=product,
            batch="LOT-EXPIRING",
            quantity=50,
            reorder_level=2,
            expiry=timezone.localdate() + timedelta(days=30),
            purchase_cost="2.00",
            selling_price="5.00",
        )
        expiry_report = self.client.get(
            f"/api/reports/replenishment/?branchId={self.branch.id}"
        )
        self.assertEqual(expiry_report.status_code, 200, expiry_report.content)
        expiry_item = expiry_report.json()["recommendations"][0]
        self.assertEqual(expiry_item["expiringWithin30Days"], 50)
        self.assertEqual(expiry_item["estimatedExpiryRisk"], 20)
        self.assertEqual(expiry_item["suggestedOrderQuantity"], 0)

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
