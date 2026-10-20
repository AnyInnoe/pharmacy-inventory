from django.db import models

# Create your models here.
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