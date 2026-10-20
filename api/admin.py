from django.contrib import admin

from .models import AuditEvent, Branch, BranchMembership


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