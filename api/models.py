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


class SupplierInvoice(models.Model):
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