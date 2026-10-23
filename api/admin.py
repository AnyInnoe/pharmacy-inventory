from django.contrib import admin

from .models import (
    AuditEvent,
    BarcodeAlias,
    Branch,
    BranchCompliancePolicy,
    BranchMembership,
    BranchTransfer,
    ControlledDrugRegisterEntry,
    ExternalIntegrationEvent,
    MedicineBatch,
    MedicationProduct,
    Prescription,
    PurchaseOrder,
    Supplier,
    SupplierProduct,
)


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "phone", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name", "address")


@admin.register(BranchMembership)
class BranchMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "branch", "role", "is_active", "assigned_by")
    list_filter = ("role", "is_active", "branch")
    search_fields = ("user__username", "user__first_name", "user__last_name")
    autocomplete_fields = ("user", "branch", "assigned_by")


@admin.register(BranchCompliancePolicy)
class BranchCompliancePolicyAdmin(admin.ModelAdmin):
    list_display = ("branch", "jurisdiction_code", "controlled_witness_required", "updated_at")
    list_filter = ("jurisdiction_code", "controlled_witness_required")


@admin.register(MedicationProduct)
class MedicationProductAdmin(admin.ModelAdmin):
    list_display = (
        "sku",
        "name",
        "category",
        "barcode",
        "requires_prescription",
        "is_controlled",
        "is_active",
    )
    list_filter = ("category", "requires_prescription", "is_controlled", "is_active")
    search_fields = ("sku", "name", "barcode")


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "contact_name", "phone", "email", "is_active")
    search_fields = ("name", "contact_name", "phone", "email")
    list_filter = ("is_active",)


@admin.register(SupplierProduct)
class SupplierProductAdmin(admin.ModelAdmin):
    list_display = ("supplier", "product", "supplier_sku", "unit_cost", "lead_time_days", "is_preferred")
    list_filter = ("supplier", "is_preferred")
    search_fields = ("supplier__name", "product__sku", "product__name", "supplier_sku")


@admin.register(MedicineBatch)
class MedicineBatchAdmin(admin.ModelAdmin):
    list_display = ("batch", "product", "branch", "quantity", "expiry")
    search_fields = ("batch", "product__sku", "product__name")
    list_filter = ("branch", "expiry")
    readonly_fields = ("quantity", "created_at", "updated_at")


@admin.register(BarcodeAlias)
class BarcodeAliasAdmin(admin.ModelAdmin):
    list_display = ("value", "product", "symbology", "is_primary")
    search_fields = ("value", "product__sku", "product__name")


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ("number", "branch", "supplier", "status", "created_at")
    list_filter = ("branch", "status", "supplier")
    search_fields = ("number", "supplier__name")
    readonly_fields = ("created_at", "submitted_at")


@admin.register(Prescription)
class PrescriptionAdmin(admin.ModelAdmin):
    list_display = ("reference", "branch", "patient_reference", "status", "issued_date")
    list_filter = ("branch", "status", "issued_date")
    search_fields = ("reference", "patient_reference", "prescriber_name")
    readonly_fields = ("received_by", "verified_by", "created_at", "verified_at")


@admin.register(BranchTransfer)
class BranchTransferAdmin(admin.ModelAdmin):
    list_display = ("reference", "source_branch", "destination_branch", "status", "created_at")
    list_filter = ("status", "source_branch", "destination_branch")
    search_fields = ("reference",)
    readonly_fields = ("requested_by", "dispatched_by", "received_by", "created_at", "dispatched_at", "received_at")


@admin.register(ControlledDrugRegisterEntry)
class ControlledDrugRegisterEntryAdmin(admin.ModelAdmin):
    list_display = ("recorded_at", "movement", "witness", "balance_after")
    list_filter = ("recorded_at",)
    search_fields = ("movement__reference", "patient_reference", "prescriber_reference")
    readonly_fields = tuple(field.name for field in ControlledDrugRegisterEntry._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "actor",
        "branch",
        "action",
        "entity_type",
        "entity_id",
    )
    list_filter = ("action", "branch", "created_at")
    search_fields = ("actor__username", "entity_type", "entity_id", "reference")
    readonly_fields = (
        "actor",
        "branch",
        "action",
        "entity_type",
        "entity_id",
        "before",
        "after",
        "reason",
        "reference",
        "ip_address",
        "created_at",
    )
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False