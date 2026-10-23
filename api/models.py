from django.conf import settings
from django.db import models


class Branch(models.Model):
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=20, unique=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.code} — {self.name}"


class BranchCompliancePolicy(models.Model):
    branch = models.OneToOneField(
        Branch,
        on_delete=models.CASCADE,
        related_name="compliance_policy",
    )
    jurisdiction_code = models.CharField(max_length=8, default="UG")
    max_prescription_age_days = models.PositiveIntegerField(null=True, blank=True)
    require_prescriber_registration = models.BooleanField(default=False)
    require_expiry_date_on_prescription = models.BooleanField(default=False)
    controlled_witness_required = models.BooleanField(default=True)
    require_patient_reference = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.branch.code} — {self.jurisdiction_code} policy"


class BranchMembership(models.Model):
    class Role(models.TextChoices):
        PHARMACIST = "pharmacist", "Pharmacist"
        BRANCH_MANAGER = "branch_manager", "Branch manager"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="branch_memberships",
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="memberships",
    )
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.PHARMACIST,
    )
    is_active = models.BooleanField(default=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="memberships_assigned",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["branch__name", "user__username"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "branch"],
                name="unique_user_branch_membership",
            )
        ]

    def __str__(self):
        return f"{self.user} — {self.branch} ({self.get_role_display()})"


class AuditEvent(models.Model):
    class Action(models.TextChoices):
        LOGIN = "login", "Login"
        LOGOUT = "logout", "Logout"
        CREATED = "created", "Created"
        UPDATED = "updated", "Updated"
        DELETED = "deleted", "Deleted"
        STOCK_ADJUSTED = "stock_adjusted", "Stock adjusted"
        SALE_RECORDED = "sale_recorded", "Sale recorded"
        PURCHASE_RECEIVED = "purchase_received", "Purchase received"
        PAYMENT_RECORDED = "payment_recorded", "Payment recorded"
        PERMISSION_CHANGED = "permission_changed", "Permission changed"
        OTHER = "other", "Other"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    action = models.CharField(max_length=24, choices=Action.choices)
    entity_type = models.CharField(max_length=80)
    entity_id = models.CharField(max_length=64, blank=True)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    reason = models.TextField(blank=True)
    reference = models.CharField(max_length=100, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["branch", "created_at"],
                name="audit_branch_time_idx",
            ),
            models.Index(
                fields=["actor", "created_at"],
                name="audit_actor_time_idx",
            ),
        ]

    def __str__(self):
        return f"{self.get_action_display()} — {self.entity_type} — {self.created_at}"


class MedicationProduct(models.Model):
    sku = models.CharField(max_length=40, unique=True)
    barcode = models.CharField(max_length=80, unique=True, null=True, blank=True)
    name = models.CharField(max_length=160)
    category = models.CharField(max_length=100)
    unit = models.CharField(max_length=40, default="unit")
    requires_prescription = models.BooleanField(default=False)
    is_controlled = models.BooleanField(default=False)
    controlled_schedule = models.CharField(max_length=40, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "sku"]

    def __str__(self):
        return f"{self.sku} — {self.name}"


class BarcodeAlias(models.Model):
    product = models.ForeignKey(
        MedicationProduct,
        on_delete=models.PROTECT,
        related_name="barcode_aliases",
    )
    value = models.CharField(max_length=80, unique=True)
    symbology = models.CharField(max_length=32, blank=True)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.value} — {self.product.sku}"


class MedicineBatch(models.Model):
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="medicine_batches",
    )
    product = models.ForeignKey(
        MedicationProduct,
        on_delete=models.PROTECT,
        related_name="batches",
    )
    batch = models.CharField(max_length=80)
    quantity = models.PositiveIntegerField(default=0)
    reorder_level = models.PositiveIntegerField(default=0)
    expiry = models.DateField()
    supplier = models.CharField(max_length=160, blank=True)
    reference = models.CharField(max_length=100, blank=True)
    purchase_cost = models.DecimalField(max_digits=12, decimal_places=2)
    selling_price = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["expiry", "batch"]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "batch"],
                name="unique_branch_batch",
            )
        ]

    def __str__(self):
        return f"{self.product.sku} — {self.batch}"


class StockMovement(models.Model):
    class Type(models.TextChoices):
        RECEIVED = "Received", "Received"
        SALE = "Sale", "Sale"
        NON_SALE_ISSUE = "Non-sale issue", "Non-sale issue"
        STOCK_COUNT = "Stock count adjustment", "Stock count adjustment"
        WASTE = "Waste", "Waste"
        TRANSFER_OUT = "Transfer out", "Transfer out"
        TRANSFER_IN = "Transfer in", "Transfer in"

    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="stock_movements")
    batch = models.ForeignKey(
        MedicineBatch,
        on_delete=models.PROTECT,
        related_name="movements",
    )
    type = models.CharField(max_length=32, choices=Type.choices)
    quantity = models.IntegerField()
    supplier = models.CharField(max_length=160, blank=True)
    recipient = models.CharField(max_length=160, blank=True)
    reference = models.CharField(max_length=100)
    reason = models.CharField(max_length=120, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="stock_movements",
    )
    sale = models.ForeignKey(
        "Sale",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="stock_movements",
    )
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-recorded_at", "-id"]


class Sale(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="sales")
    sku = models.CharField(max_length=40)
    name = models.CharField(max_length=160)
    quantity = models.PositiveIntegerField()
    sale_amount = models.DecimalField(max_digits=12, decimal_places=2)
    cost_amount = models.DecimalField(max_digits=12, decimal_places=2)
    amount_received = models.DecimalField(max_digits=12, decimal_places=2)
    balance_due = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(max_length=40)
    recipient = models.CharField(max_length=160)
    reference = models.CharField(max_length=100)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="recorded_sales",
    )
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-recorded_at", "-id"]


class SaleLine(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="lines")
    batch = models.ForeignKey(
        MedicineBatch,
        on_delete=models.PROTECT,
        related_name="sale_lines",
    )
    quantity = models.PositiveIntegerField()
    purchase_cost = models.DecimalField(max_digits=12, decimal_places=2)
    selling_price = models.DecimalField(max_digits=12, decimal_places=2)


class Supplier(models.Model):
    name = models.CharField(max_length=160)
    contact_name = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    address = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["name"], name="unique_supplier_name")
        ]

    def __str__(self):
        return self.name


class SupplierProduct(models.Model):
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="catalog_items")
    product = models.ForeignKey(MedicationProduct, on_delete=models.PROTECT, related_name="supplier_options")
    supplier_sku = models.CharField(max_length=80, blank=True)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)
    lead_time_days = models.PositiveIntegerField(default=0)
    is_preferred = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["supplier", "product"],
                name="unique_supplier_product",
            )
        ]


class PurchaseOrder(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        PARTIALLY_RECEIVED = "partially_received", "Partially received"
        RECEIVED = "received", "Received"
        CANCELLED = "cancelled", "Cancelled"

    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="purchase_orders")
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchase_orders")
    number = models.CharField(max_length=40)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DRAFT)
    expected_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_purchase_orders",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["branch", "number"], name="unique_branch_po_number")
        ]


class PurchaseOrderLine(models.Model):
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name="lines")
    product = models.ForeignKey(MedicationProduct, on_delete=models.PROTECT, related_name="purchase_order_lines")
    quantity_ordered = models.PositiveIntegerField()
    quantity_received = models.PositiveIntegerField(default=0)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["purchase_order", "product"],
                name="unique_product_per_purchase_order",
            )
        ]


class SupplierInvoice(models.Model):
    class ReconciliationStatus(models.TextChoices):
        NOT_LINKED = "not_linked", "Not linked"
        PENDING = "pending", "Pending"
        MATCHED = "matched", "Matched"
        VARIANCE = "variance", "Variance"

    supplier_record = models.ForeignKey(
        Supplier,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="invoices",
    )
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="invoices",
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="supplier_invoices",
    )
    supplier = models.CharField(max_length=160)
    invoice_number = models.CharField(max_length=100)
    invoice_amount = models.DecimalField(max_digits=12, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    due_date = models.DateField()
    reconciliation_status = models.CharField(
        max_length=16,
        choices=ReconciliationStatus.choices,
        default=ReconciliationStatus.NOT_LINKED,
    )
    reconciled_expected_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    reconciliation_variance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    reconciled_at = models.DateTimeField(null=True, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="recorded_supplier_invoices",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "invoice_number"],
                name="unique_branch_supplier_invoice",
            )
        ]


class SupplierPayment(models.Model):
    invoice = models.ForeignKey(
        SupplierInvoice,
        on_delete=models.PROTECT,
        related_name="payments",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=40)
    reference = models.CharField(max_length=100)
    recorded_at = models.DateTimeField(auto_now_add=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="recorded_supplier_payments",
    )


class CustomerPayment(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=40)
    reference = models.CharField(max_length=100)
    recorded_at = models.DateTimeField(auto_now_add=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="recorded_customer_payments",
    )


class Prescription(models.Model):
    class Status(models.TextChoices):
        RECEIVED = "received", "Received"
        VERIFIED = "verified", "Verified"
        PARTIALLY_DISPENSED = "partially_dispensed", "Partially dispensed"
        DISPENSED = "dispensed", "Dispensed"
        REJECTED = "rejected", "Rejected"

    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="prescriptions")
    reference = models.CharField(max_length=100)
    patient_reference = models.CharField(max_length=100)
    prescriber_name = models.CharField(max_length=160)
    prescriber_registration = models.CharField(max_length=100, blank=True)
    issued_date = models.DateField()
    expires_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.RECEIVED)
    notes = models.TextField(blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="received_prescriptions",
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="verified_prescriptions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "reference"],
                name="unique_branch_prescription_reference",
            )
        ]


class PrescriptionLine(models.Model):
    prescription = models.ForeignKey(Prescription, on_delete=models.PROTECT, related_name="lines")
    product = models.ForeignKey(MedicationProduct, on_delete=models.PROTECT, related_name="prescription_lines")
    directions = models.CharField(max_length=240, blank=True)
    quantity_prescribed = models.PositiveIntegerField()
    quantity_dispensed = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["prescription", "product"],
                name="unique_product_per_prescription",
            )
        ]


class DispenseLine(models.Model):
    prescription_line = models.ForeignKey(
        PrescriptionLine,
        on_delete=models.PROTECT,
        related_name="dispenses",
    )
    sale_line = models.ForeignKey(
        SaleLine,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="prescription_dispenses",
    )
    batch = models.ForeignKey(MedicineBatch, on_delete=models.PROTECT, related_name="prescription_dispenses")
    quantity = models.PositiveIntegerField()
    dispensed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="prescription_dispenses",
    )
    dispensed_at = models.DateTimeField(auto_now_add=True)


class ControlledDrugRegisterEntry(models.Model):
    movement = models.OneToOneField(
        StockMovement,
        on_delete=models.PROTECT,
        related_name="controlled_register_entry",
    )
    witness = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="witnessed_controlled_movements",
    )
    patient_reference = models.CharField(max_length=100, blank=True)
    prescriber_reference = models.CharField(max_length=100, blank=True)
    balance_after = models.PositiveIntegerField()
    notes = models.TextField(blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True)


class BranchTransfer(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        DISPATCHED = "dispatched", "Dispatched"
        PARTIALLY_RECEIVED = "partially_received", "Partially received"
        RECEIVED = "received", "Received"
        CANCELLED = "cancelled", "Cancelled"

    source_branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="outgoing_transfers")
    destination_branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name="incoming_transfers")
    reference = models.CharField(max_length=100)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.REQUESTED)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="requested_transfers",
    )
    dispatched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="dispatched_transfers",
    )
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="received_transfers",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["source_branch", "reference"],
                name="unique_transfer_reference_per_source",
            )
        ]


class BranchTransferLine(models.Model):
    transfer = models.ForeignKey(BranchTransfer, on_delete=models.PROTECT, related_name="lines")
    product = models.ForeignKey(MedicationProduct, on_delete=models.PROTECT, related_name="transfer_lines")
    source_batch = models.ForeignKey(
        MedicineBatch,
        on_delete=models.PROTECT,
        related_name="transfer_out_lines",
    )
    destination_batch = models.ForeignKey(
        MedicineBatch,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="transfer_in_lines",
    )
    quantity_dispatched = models.PositiveIntegerField()
    quantity_received = models.PositiveIntegerField(default=0)


class ExternalIntegrationEvent(models.Model):
    class Direction(models.TextChoices):
        INBOUND = "inbound", "Inbound"
        OUTBOUND = "outbound", "Outbound"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSED = "processed", "Processed"
        FAILED = "failed", "Failed"

    provider = models.CharField(max_length=80)
    external_id = models.CharField(max_length=120)
    direction = models.CharField(max_length=12, choices=Direction.choices)
    event_type = models.CharField(max_length=80)
    payload = models.JSONField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "external_id", "direction"],
                name="unique_external_integration_event",
            )
        ]