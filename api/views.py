import csv
import json
import math
import uuid
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib.auth import authenticate, login, logout
from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator
from django.db import models, transaction
from django.http import FileResponse, HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .documents import (
    invoice_reconciliation_pdf,
    sale_receipt_pdf as render_sale_receipt_pdf,
)
from .models import (
    AuditEvent,
    Branch,
    BranchCompliancePolicy,
    BranchTransfer,
    BranchTransferLine,
    BranchMembership,
    ControlledDrugRegisterEntry,
    CustomerPayment,
    DispenseLine,
    EmailNotification,
    ExternalIntegrationEvent,
    MedicineBatch,
    MedicationProduct,
    Prescription,
    PrescriptionLine,
    PurchaseOrder,
    PurchaseOrderLine,
    Sale,
    SaleLine,
    StockMovement,
    Supplier,
    SupplierProduct,
    SupplierInvoice,
    SupplierPayment,
)


def _user_data(user):
    memberships = (
        BranchMembership.objects.filter(
            user=user,
            is_active=True,
            branch__is_active=True,
        )
        .select_related("branch")
        .order_by("branch__name")
    )

    return {
        "id": user.id,
        "username": user.username,
        "firstName": user.first_name,
        "lastName": user.last_name,
        "isSuperuser": user.is_superuser,
        "isStaff": user.is_staff,
        "memberships": [
            {
                "branchId": membership.branch_id,
                "branchName": membership.branch.name,
                "branchCode": membership.branch.code,
                "role": membership.role,
            }
            for membership in memberships
        ],
    }


def _record_auth_event(request, user, action):
    AuditEvent.objects.create(
        actor=user,
        action=action,
        entity_type="user",
        entity_id=str(user.pk),
        ip_address=request.META.get("REMOTE_ADDR"),
    )


def _json_body(request):
    try:
        data = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, JsonResponse({"detail": "Request must contain valid JSON."}, status=400)

    if not isinstance(data, dict):
        return None, JsonResponse({"detail": "Request must contain a JSON object."}, status=400)
    return data, None


def _generated_reference(prefix, record_id):
    record_part = f"{record_id:06d}" if isinstance(record_id, int) else str(record_id)
    return f"{prefix}-{timezone.localdate():%Y%m%d}-{record_part}"


def _create_payment(payment_model, prefix, **values):
    payment = payment_model.objects.create(reference="", **values)
    payment.reference = _generated_reference(prefix, payment.pk)
    payment.save(update_fields=["reference"])
    return payment


def _branch_for_user(request, branch_id, allow_admin_cross_branch=False):
    if not request.user.is_authenticated:
        return None, JsonResponse({"detail": "Authentication required."}, status=401)
    try:
        branch = Branch.objects.get(pk=branch_id, is_active=True)
    except (Branch.DoesNotExist, ValueError, TypeError):
        return None, JsonResponse({"detail": "Select a valid active branch."}, status=400)

    has_membership = BranchMembership.objects.filter(
        user=request.user,
        branch=branch,
        is_active=True,
    ).exists()
    if not has_membership and not (
        request.user.is_superuser and allow_admin_cross_branch
    ):
        return None, JsonResponse({"detail": "You do not have access to this branch."}, status=403)
    return branch, None


def _branch_role(request, branch):
    membership = BranchMembership.objects.filter(
        user=request.user,
        branch=branch,
        is_active=True,
    ).first()
    return membership.role if membership else None


def _require_roles(request, branch, roles):
    role = _branch_role(request, branch)
    if role not in roles:
        return JsonResponse({"detail": "You do not have permission for this action."}, status=403)
    return None


def _require_pharmacist(request, branch):
    role = BranchMembership.objects.filter(
        user=request.user,
        branch=branch,
        is_active=True,
    ).values_list("role", flat=True).first()
    if role not in {
        BranchMembership.Role.PHARMACIST,
        BranchMembership.Role.BRANCH_MANAGER,
    }:
        return JsonResponse(
            {"detail": "An active pharmacist or branch-manager membership is required."},
            status=403,
        )
    return None


def _branch_role_for_user(request, branch):
    return BranchMembership.objects.filter(
        user=request.user,
        branch=branch,
        is_active=True,
    ).values_list("role", flat=True).first()


def _can_view_financials(request, branch):
    return (
        request.user.is_superuser
        or _branch_role_for_user(request, branch)
        == BranchMembership.Role.BRANCH_MANAGER
    )


def _require_catalog_admin(request):
    has_cashier_membership = BranchMembership.objects.filter(
        user=request.user,
        is_active=True,
        role=BranchMembership.Role.CASHIER,
    ).exists()
    if not request.user.is_superuser and (
        not request.user.is_staff or has_cashier_membership
    ):
        return JsonResponse(
            {"detail": "Administrator access is required."},
            status=403,
        )
    return None


def _branch_policy(branch):
    return BranchCompliancePolicy.objects.filter(branch=branch).first()


def _controlled_witness(request, branch, witness_id):
    if not witness_id:
        return None, JsonResponse(
            {"detail": "A second active branch member must witness this controlled-medicine movement."},
            status=400,
        )
    try:
        witness_id = int(witness_id)
    except (TypeError, ValueError):
        return None, JsonResponse({"detail": "Select a valid controlled-medicine witness."}, status=400)
    if witness_id == request.user.id:
        return None, JsonResponse({"detail": "The witness must be a different user."}, status=400)
    membership = BranchMembership.objects.filter(
        user_id=witness_id,
        branch=branch,
        is_active=True,
        user__is_active=True,
    ).select_related("user").first()
    if membership is None:
        return None, JsonResponse(
            {"detail": "The witness must be an active member of this branch."},
            status=400,
        )
    return membership.user, None


def _branch_id(request, data=None):
    return (data or {}).get("branchId") or request.GET.get("branchId")


def _money(value, field):
    try:
        amount = Decimal(str(value))
        amount = amount.quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} must be a valid amount.")
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"{field} must be a non-negative amount.")
    return amount


def _whole_number(value, field):
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a whole number.")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdecimal():
        return int(value.strip())
    raise ValueError(f"{field} must be a whole number.")


def _batch_expiry(value, product_type):
    expiry_value = str(value or "").strip()
    if not expiry_value:
        if product_type == MedicationProduct.ProductType.SKIN_CARE:
            return None
        raise ValueError("Expiry date is required for medicines.")
    return date.fromisoformat(expiry_value)


def _eligible_batch_expiry(as_of=None):
    as_of = as_of or date.today()
    return models.Q(expiry__gte=as_of) | models.Q(
        product__product_type=MedicationProduct.ProductType.SKIN_CARE,
        expiry__isnull=True,
    )


def _record_audit(request, branch, action, entity_type, entity_id, after=None, reference=""):
    AuditEvent.objects.create(
        actor=request.user,
        branch=branch,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        after=after,
        reference=reference,
        ip_address=request.META.get("REMOTE_ADDR"),
    )


def _queue_pos_event(sale):
    ExternalIntegrationEvent.objects.get_or_create(
        provider="internal-outbox",
        external_id=f"sale-{sale.pk}",
        direction=ExternalIntegrationEvent.Direction.OUTBOUND,
        defaults={
            "event_type": "pos.sale",
            "payload": {
                "saleId": sale.pk,
                "branchId": sale.branch_id,
                "reference": sale.reference,
                "sku": sale.sku,
                "quantity": sale.quantity,
                "total": str(sale.sale_amount),
                "amountReceived": str(sale.amount_received),
                "balanceDue": str(sale.balance_due),
            },
            "status": ExternalIntegrationEvent.Status.PENDING,
        },
    )


def _queue_email_notification(event_key, notification_type, recipient, subject, body):
    return EmailNotification.objects.get_or_create(
        event_key=event_key,
        defaults={
            "notification_type": notification_type,
            "recipient_email": recipient,
            "subject": subject,
            "body": body,
        },
    )


def _batch_data(batch, include_cost=True):
    data = {
        "id": batch.id,
        "sku": batch.product.sku,
        "name": batch.product.name,
        "category": batch.product.category,
        "productType": batch.product.product_type,
        "brand": batch.product.brand,
        "skinType": batch.product.skin_type,
        "skinConcerns": batch.product.skin_concerns,
        "keyIngredients": batch.product.key_ingredients,
        "usageInstructions": batch.product.usage_instructions,
        "warnings": batch.product.warnings,
        "periodAfterOpeningMonths": batch.product.period_after_opening_months,
        "batch": batch.batch,
        "quantity": batch.quantity,
        "reorderLevel": batch.reorder_level,
        "expiry": batch.expiry.isoformat() if batch.expiry else None,
        "supplier": batch.supplier,
        "reference": batch.reference,
        "sellingPrice": float(batch.selling_price),
        "requiresPrescription": batch.product.requires_prescription,
        "isControlled": batch.product.is_controlled,
        "controlledSchedule": batch.product.controlled_schedule,
    }
    if include_cost:
        data["purchaseCost"] = float(batch.purchase_cost)
    return data


def _sale_data(sale, include_cost=True):
    data = {
        "id": str(sale.pk),
        "sku": sale.sku,
        "name": sale.name,
        "quantity": sale.quantity,
        "saleAmount": float(sale.sale_amount),
        "amountReceived": float(sale.amount_received),
        "balanceDue": float(sale.balance_due),
        "paymentMethod": sale.payment_method,
        "recipient": sale.recipient,
        "reference": sale.reference,
        "recordedAt": sale.recorded_at.isoformat(),
        "approvalStatus": sale.approval_status,
        "proposedAmountReceived": float(sale.approval_amount_received),
        "proposedPaymentMethod": sale.approval_payment_method,
        "submittedBy": sale.actor.get_username() if sale.actor else "",
        "approvedBy": sale.approved_by.get_username() if sale.approved_by else "",
        "approvedAt": sale.approved_at.isoformat() if sale.approved_at else None,
        "rejectionReason": sale.rejection_reason,
    }
    if include_cost:
        data["costAmount"] = float(sale.cost_amount)
        data["grossProfit"] = float(sale.sale_amount - sale.cost_amount)
    return data


def _invoice_data(invoice):
    return {
        "id": str(invoice.pk),
        "reference": f"INV-{invoice.pk:06d}",
        "supplier": invoice.supplier,
        "invoiceNumber": invoice.invoice_number,
        "invoiceAmount": float(invoice.invoice_amount),
        "amountPaid": float(invoice.amount_paid),
        "dueDate": invoice.due_date.isoformat(),
        "createdAt": invoice.created_at.isoformat(),
        "purchaseOrderId": invoice.purchase_order_id,
        "reconciliationStatus": invoice.reconciliation_status,
        "reconciledExpectedAmount": (
            float(invoice.reconciled_expected_amount)
            if invoice.reconciled_expected_amount is not None
            else None
        ),
        "reconciliationVariance": (
            float(invoice.reconciliation_variance)
            if invoice.reconciliation_variance is not None
            else None
        ),
        "reconciledAt": invoice.reconciled_at.isoformat() if invoice.reconciled_at else None,
        "hasOriginalDocument": bool(invoice.original_document),
    }


@require_GET
def branches_view(request):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required."}, status=401)
    branches = Branch.objects.filter(is_active=True)
    if not request.user.is_superuser:
        branches = branches.filter(
            memberships__user=request.user,
            memberships__is_active=True,
        )
    return JsonResponse({
        "branches": [
            {"id": branch.id, "name": branch.name, "code": branch.code}
            for branch in branches.distinct().order_by("name")
        ]
    })


@require_GET
def branch_staff_view(request):
    branch, error = _branch_for_user(request, _branch_id(request))
    if error:
        return error
    error = _require_roles(request, branch, {"branch_manager"})
    if error:
        return error
    members = BranchMembership.objects.filter(
        branch=branch,
        is_active=True,
        user__is_active=True,
    ).select_related("user").order_by("user__username")
    return JsonResponse({
        "members": [
            {
                "id": membership.user_id,
                "username": membership.user.get_username(),
                "name": membership.user.get_full_name() or membership.user.get_username(),
                "role": membership.role,
            }
            for membership in members
        ]
    })


@require_GET
def products_view(request):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required."}, status=401)
    products = MedicationProduct.objects.filter(is_active=True)
    return JsonResponse({
        "products": [
            {
                "sku": product.sku,
                "name": product.name,
                "category": product.category,
                "productType": product.product_type,
                "unit": product.unit,
                "brand": product.brand,
                "skinType": product.skin_type,
                "skinConcerns": product.skin_concerns,
                "keyIngredients": product.key_ingredients,
                "usageInstructions": product.usage_instructions,
                "warnings": product.warnings,
                "periodAfterOpeningMonths": product.period_after_opening_months,
                "requiresPrescription": product.requires_prescription,
                "isControlled": product.is_controlled,
                "controlledSchedule": product.controlled_schedule,
            }
            for product in products
        ]
    })


@require_POST
def create_product(request):
    data, error = _json_body(request)
    if error:
        return error
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required."}, status=401)
    error = _require_catalog_admin(request)
    if error:
        return error
    sku = str(data.get("sku", "")).strip()
    name = str(data.get("name", "")).strip()
    category = str(data.get("category", "")).strip()
    product_type = str(
        data.get("productType", MedicationProduct.ProductType.MEDICINE)
    ).strip()
    if not name or not category:
        return JsonResponse({"detail": "Product name and category are required."}, status=400)
    if product_type not in MedicationProduct.ProductType.values:
        return JsonResponse({"detail": "Select a valid product type."}, status=400)
    if sku and MedicationProduct.objects.filter(sku__iexact=sku).exists():
        return JsonResponse({"detail": "SKU is already in use."}, status=409)
    if not isinstance(data.get("requiresPrescription", False), bool) or not isinstance(
        data.get("isControlled", False), bool
    ):
        return JsonResponse({"detail": "Prescription and controlled flags must be booleans."}, status=400)
    if product_type == MedicationProduct.ProductType.SKIN_CARE and (
        data.get("requiresPrescription") or data.get("isControlled")
    ):
        return JsonResponse(
            {"detail": "Skin-care products cannot be marked as prescription or controlled medicines."},
            status=400,
        )
    try:
        pao_value = data.get("periodAfterOpeningMonths")
        period_after_opening_months = (
            _whole_number(pao_value, "Period after opening")
            if pao_value not in (None, "")
            else None
        )
    except ValueError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    if period_after_opening_months is not None and period_after_opening_months <= 0:
        return JsonResponse(
            {"detail": "Period after opening must be a positive number of months."},
            status=400,
        )
    if product_type != MedicationProduct.ProductType.SKIN_CARE and (
        period_after_opening_months is not None
        or any(
            str(data.get(field, "")).strip()
            for field in (
                "brand",
                "skinType",
                "skinConcerns",
                "keyIngredients",
                "usageInstructions",
                "warnings",
            )
        )
    ):
        return JsonResponse(
            {"detail": "Skin-care details can only be set for skin-care products."},
            status=400,
        )
    product_fields = {
        "name": name,
        "category": category,
        "product_type": product_type,
        "unit": str(data.get("unit", "unit")).strip() or "unit",
        "brand": str(data.get("brand", "")).strip(),
        "skin_type": str(data.get("skinType", "")).strip(),
        "skin_concerns": str(data.get("skinConcerns", "")).strip(),
        "key_ingredients": str(data.get("keyIngredients", "")).strip(),
        "usage_instructions": str(data.get("usageInstructions", "")).strip(),
        "warnings": str(data.get("warnings", "")).strip(),
        "period_after_opening_months": period_after_opening_months,
        "requires_prescription": bool(data.get("requiresPrescription")),
        "is_controlled": bool(data.get("isControlled")),
        "controlled_schedule": str(data.get("controlledSchedule", "")).strip(),
    }
    if sku:
        product_fields["sku"] = sku
    product = MedicationProduct.objects.create(**product_fields)
    return JsonResponse({"sku": product.sku}, status=201)


@require_GET
def suppliers_view(request):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required."}, status=401)
    return JsonResponse({
        "suppliers": [
            {
                "id": supplier.id,
                "reference": f"SUP-{supplier.pk:06d}",
                "name": supplier.name,
                "phone": supplier.phone,
                "email": supplier.email,
            }
            for supplier in Supplier.objects.filter(is_active=True)
        ]
    })


@require_POST
def create_supplier(request):
    data, error = _json_body(request)
    if error:
        return error
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required."}, status=401)
    error = _require_catalog_admin(request)
    if error:
        return error
    name = str(data.get("name", "")).strip()
    if not name:
        return JsonResponse({"detail": "Supplier name is required."}, status=400)
    supplier, created = Supplier.objects.get_or_create(
        name=name,
        defaults={
            "contact_name": str(data.get("contactName", "")).strip(),
            "email": str(data.get("email", "")).strip(),
            "phone": str(data.get("phone", "")).strip(),
            "address": str(data.get("address", "")).strip(),
        },
    )
    if not created:
        return JsonResponse({"detail": "Supplier already exists."}, status=409)
    return JsonResponse(
        {
            "id": supplier.id,
            "reference": f"SUP-{supplier.pk:06d}",
            "name": supplier.name,
        },
        status=201,
    )


@require_POST
def set_supplier_product(request):
    data, error = _json_body(request)
    if error:
        return error
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required."}, status=401)
    error = _require_catalog_admin(request)
    if error:
        return error
    try:
        supplier = Supplier.objects.get(pk=int(data.get("supplierId")), is_active=True)
        product = MedicationProduct.objects.get(sku=str(data.get("sku", "")).strip(), is_active=True)
        unit_cost = _money(data.get("unitCost"), "Unit cost")
        lead_time = _whole_number(data.get("leadTimeDays", 0), "Lead time")
    except (Supplier.DoesNotExist, MedicationProduct.DoesNotExist, ValueError, TypeError):
        return JsonResponse({"detail": "Select a valid supplier, product, cost, and lead time."}, status=400)
    if lead_time < 0:
        return JsonResponse({"detail": "Lead time cannot be negative."}, status=400)
    is_preferred = data.get("isPreferred", False)
    if not isinstance(is_preferred, bool):
        return JsonResponse({"detail": "Preferred supplier flag must be a boolean."}, status=400)
    with transaction.atomic():
        if is_preferred:
            SupplierProduct.objects.filter(product=product).update(is_preferred=False)
        mapping, _ = SupplierProduct.objects.update_or_create(
            supplier=supplier,
            product=product,
            defaults={
                "supplier_sku": str(data.get("supplierSku", "")).strip(),
                "unit_cost": unit_cost,
                "lead_time_days": lead_time,
                "is_preferred": is_preferred,
            },
        )
    return JsonResponse({"id": mapping.id, "supplier": supplier.name, "sku": product.sku})


@require_GET
def dashboard_data(request):
    branch, error = _branch_for_user(request, _branch_id(request))
    if error:
        return error

    role = _branch_role_for_user(request, branch)
    can_manage_branch = role == BranchMembership.Role.BRANCH_MANAGER
    can_view_cost = _can_view_financials(request, branch)
    batches = MedicineBatch.objects.filter(branch=branch)
    movements = StockMovement.objects.filter(branch=branch).select_related("batch")
    sales = Sale.objects.filter(branch=branch)
    invoices = SupplierInvoice.objects.filter(branch=branch)
    supplier_payments = SupplierPayment.objects.filter(invoice__branch=branch).select_related("invoice")
    customer_payments = CustomerPayment.objects.filter(sale__branch=branch).select_related("sale")
    return JsonResponse({
        "inventory": [_batch_data(batch, include_cost=can_view_cost) for batch in batches],
        "stockMovements": [
            {
                "id": movement.id,
                "type": movement.type,
                "name": movement.batch.product.name,
                "sku": movement.batch.product.sku,
                "batch": movement.batch.batch,
                "quantity": movement.quantity,
                "supplier": movement.supplier,
                "recipient": movement.recipient or movement.reason,
                "reference": movement.reference,
                "recordedAt": movement.recorded_at.isoformat(),
            }
            for movement in movements
        ],
        "sales": [_sale_data(sale, include_cost=can_view_cost) for sale in sales],
        "supplierInvoices": (
            [_invoice_data(invoice) for invoice in invoices]
            if can_manage_branch
            else []
        ),
        "supplierPayments": [
            {
                "id": payment.id,
                "invoiceId": str(payment.invoice_id),
                "invoiceReference": f"INV-{payment.invoice_id:06d}",
                "supplier": payment.invoice.supplier,
                "invoiceNumber": payment.invoice.invoice_number,
                "amount": float(payment.amount),
                "method": payment.method,
                "reference": payment.reference,
                "recordedAt": payment.recorded_at.isoformat(),
            }
            for payment in supplier_payments
        ] if can_manage_branch else [],
        "customerPayments": [
            {
                "id": payment.id,
                "saleId": str(payment.sale_id),
                "saleReference": payment.sale.reference,
                "customer": payment.sale.recipient,
                "amount": float(payment.amount),
                "method": payment.method,
                "reference": payment.reference,
                "recordedAt": payment.recorded_at.isoformat(),
            }
            for payment in customer_payments
        ],
    })


@require_POST
def create_batch(request):
    data, error = _json_body(request)
    if error:
        return error
    branch, error = _branch_for_user(request, _branch_id(request, data))
    if error:
        return error
    error = _require_roles(request, branch, {"pharmacist", "branch_manager"})
    if error:
        return error
    try:
        quantity = _whole_number(data.get("quantity"), "Quantity")
        reorder_level = _whole_number(data.get("reorderLevel"), "Reorder level")
        purchase_cost = _money(data.get("purchaseCost"), "Purchase cost")
        selling_price = _money(data.get("sellingPrice"), "Selling price")
    except (ValueError, TypeError) as exc:
        return JsonResponse({"detail": str(exc) or "Enter valid batch values."}, status=400)

    sku = str(data.get("sku", "")).strip()
    name = str(data.get("name", "")).strip()
    category = str(data.get("category", "")).strip()
    batch_number = str(data.get("batch", "")).strip()
    supplier = str(data.get("supplier", "")).strip()
    if not all([sku, name, category, batch_number, supplier]):
        return JsonResponse({"detail": "Complete all required batch fields."}, status=400)
    if quantity < 0 or reorder_level < 0:
        return JsonResponse({"detail": "Quantity and reorder level cannot be negative."}, status=400)
    requested_product_type = data.get("productType")
    if requested_product_type is not None and requested_product_type not in MedicationProduct.ProductType.values:
        return JsonResponse({"detail": "Select a valid product type."}, status=400)
    existing_product = MedicationProduct.objects.filter(sku=sku).first()
    if (
        existing_product
        and requested_product_type is not None
        and requested_product_type != existing_product.product_type
    ):
        return JsonResponse({"detail": "The SKU already belongs to a different product type."}, status=400)
    product_type = (
        existing_product.product_type
        if existing_product
        else requested_product_type or MedicationProduct.ProductType.MEDICINE
    )
    try:
        expiry = _batch_expiry(data.get("expiry"), product_type)
    except (ValueError, TypeError) as exc:
        return JsonResponse({"detail": str(exc) or "Enter a valid expiry date."}, status=400)
    if MedicineBatch.objects.filter(branch=branch, batch__iexact=batch_number).exists():
        return JsonResponse({"detail": "That batch number already exists in this branch."}, status=400)

    product, created = MedicationProduct.objects.get_or_create(
        sku=sku,
        defaults={
            "name": name,
            "category": category,
            "product_type": product_type,
        },
    )
    if not created and (
        product.name != name
        or product.category != category
        or product.product_type != product_type
        or not product.is_active
    ):
        return JsonResponse(
            {"detail": "The SKU already belongs to a different or inactive product."},
            status=400,
        )

    policy = _branch_policy(branch)
    witness = None
    if product.is_controlled and (policy is None or policy.controlled_witness_required):
        witness, error = _controlled_witness(request, branch, data.get("witnessId"))
        if error:
            return error

    with transaction.atomic():
        batch = MedicineBatch.objects.create(
            branch=branch,
            product=product,
            batch=batch_number,
            quantity=quantity,
            reorder_level=reorder_level,
            expiry=expiry,
            supplier=supplier,
            reference="",
            purchase_cost=purchase_cost,
            selling_price=selling_price,
        )
        batch.reference = _generated_reference("RCV", batch.pk)
        batch.save(update_fields=["reference"])
        movement = StockMovement.objects.create(
            branch=branch,
            batch=batch,
            type=StockMovement.Type.RECEIVED,
            quantity=quantity,
            supplier=supplier,
            reference=batch.reference,
            actor=request.user,
        )
        if product.is_controlled:
            ControlledDrugRegisterEntry.objects.create(
                movement=movement,
                witness=witness,
                balance_after=batch.quantity,
                notes="Stock receipt",
            )
        _record_audit(
            request,
            branch,
            AuditEvent.Action.CREATED,
            "medicine_batch",
            batch.pk,
            _batch_data(batch),
            batch.reference,
        )
    return JsonResponse({"batch": _batch_data(batch)}, status=201)


@require_POST
def dispense_stock(request):
    data, error = _json_body(request)
    if error:
        return error
    branch, error = _branch_for_user(request, _branch_id(request, data))
    if error:
        return error
    error = _require_roles(request, branch, {"cashier", "pharmacist", "branch_manager"})
    if error:
        return error

    sku = str(data.get("sku", "")).strip()
    transaction_type = data.get("transactionType", "Sale")
    receipt_email = str(data.get("receiptEmail", "")).strip()
    if receipt_email:
        try:
            EmailValidator()(receipt_email)
        except ValidationError:
            return JsonResponse({"detail": "Enter a valid receipt email address."}, status=400)
        if transaction_type != "Sale":
            return JsonResponse({"detail": "Receipt email is only available for sales."}, status=400)
    recipient = (
        "Walk-in customer"
        if transaction_type == "Sale"
        else str(data.get("recipient", "")).strip()
    )
    try:
        quantity = _whole_number(data.get("quantity"), "Quantity")
        amount_received = _money(data.get("amountReceived", 0), "Amount received")
    except (ValueError, TypeError) as exc:
        return JsonResponse({"detail": str(exc) or "Enter a valid quantity."}, status=400)
    if quantity <= 0 or not sku or (
        transaction_type == "Non-sale issue" and not recipient
    ):
        return JsonResponse(
            {"detail": "Enter a valid quantity and medicine; stock issues also require a recipient."},
            status=400,
        )
    if transaction_type not in ("Sale", "Non-sale issue"):
        return JsonResponse({"detail": "Select a valid transaction type."}, status=400)
    membership_role = BranchMembership.objects.filter(
        user=request.user,
        branch=branch,
        is_active=True,
    ).values_list("role", flat=True).first()
    can_view_cost = _can_view_financials(request, branch)
    if transaction_type == "Sale" and membership_role not in {
        BranchMembership.Role.CASHIER,
        BranchMembership.Role.PHARMACIST,
        BranchMembership.Role.BRANCH_MANAGER,
    }:
        return JsonResponse(
            {"detail": "An active cashier, pharmacist, or branch-manager membership is required to record a sale."},
            status=403,
        )
    if transaction_type == "Non-sale issue":
        error = _require_roles(request, branch, {"pharmacist", "branch_manager"})
        if error:
            return error
    payment_method = str(data.get("paymentMethod", "")).strip()
    if transaction_type == "Sale" and not payment_method:
        return JsonResponse({"detail": "Select a payment method for the sale."}, status=400)
    client_request_id = None
    if data.get("clientRequestId") is not None:
        try:
            client_request_id = uuid.UUID(str(data["clientRequestId"]))
        except (ValueError, TypeError, AttributeError):
            return JsonResponse({"detail": "Client request ID must be a UUID."}, status=400)

    def existing_client_sale_response():
        if client_request_id is None:
            return None
        existing_sale = Sale.objects.filter(
            branch=branch,
            client_request_id=client_request_id,
        ).first()
        if existing_sale is None:
            return None
        if (
            existing_sale.actor_id != request.user.id
            or existing_sale.sku != sku
            or existing_sale.quantity != quantity
            or existing_sale.recipient != recipient
            or existing_sale.approval_amount_received != amount_received
            or existing_sale.approval_payment_method != payment_method
        ):
            return JsonResponse(
                {"detail": "Client request ID was already used for a different sale."},
                status=409,
            )
        return JsonResponse(
            {
                "sale": _sale_data(
                    existing_sale,
                    include_cost=can_view_cost,
                ),
                "duplicate": True,
                "receiptEmailQueued": EmailNotification.objects.filter(
                    event_key=f"sale-receipt-{existing_sale.pk}",
                ).exists(),
            },
            status=(
                202
                if existing_sale.approval_status == Sale.ApprovalStatus.PENDING
                else 200
            ),
        )

    duplicate_response = existing_client_sale_response()
    if duplicate_response:
        return duplicate_response

    product = MedicationProduct.objects.filter(sku=sku, is_active=True).first()
    if product is None:
        return JsonResponse({"detail": "The selected medicine could not be found."}, status=404)
    if product.requires_prescription or product.is_controlled:
        return JsonResponse(
            {
                "code": "prescription_required",
                "detail": (
                    "This medicine cannot be dispensed through regular sales. Record and "
                    "verify its prescription in the Prescriptions workflow; controlled "
                    "medicines also require an independent witness."
                )
            },
            status=400,
        )

    with transaction.atomic():
        eligible = list(
            MedicineBatch.objects.select_for_update()
            .select_related("product")
            .filter(branch=branch, product__sku=sku, quantity__gt=0)
            .filter(_eligible_batch_expiry())
            .order_by(models.F("expiry").asc(nulls_last=True), "id")
        )
        duplicate_response = existing_client_sale_response()
        if duplicate_response:
            return duplicate_response
        available = sum(batch.quantity for batch in eligible)
        if quantity > available:
            return JsonResponse(
                {"detail": f"Only {available} units are available in non-expired batches."},
                status=400,
            )
        allocations = []
        remaining = quantity
        for batch in eligible:
            if remaining == 0:
                break
            allocated = min(batch.quantity, remaining)
            allocations.append((batch, allocated))
            remaining -= allocated

        sale_amount = sum(
            (batch.selling_price * allocated for batch, allocated in allocations),
            Decimal("0.00"),
        )
        cost_amount = sum(
            (batch.purchase_cost * allocated for batch, allocated in allocations),
            Decimal("0.00"),
        )
        if transaction_type == "Sale" and amount_received > sale_amount:
            return JsonResponse(
                {"detail": "Amount received cannot exceed the sale total."},
                status=400,
            )

        sale = None
        reference = None
        if transaction_type == "Sale":
            is_cashier = membership_role == BranchMembership.Role.CASHIER
            sale = Sale.objects.create(
                branch=branch,
                sku=sku,
                name=product.name,
                quantity=quantity,
                sale_amount=sale_amount,
                cost_amount=cost_amount,
                amount_received=amount_received,
                balance_due=sale_amount - amount_received,
                payment_method=payment_method,
                recipient=recipient,
                reference="",
                actor=request.user,
                approval_status=Sale.ApprovalStatus.APPROVED,
                approval_amount_received=amount_received,
                approval_payment_method=payment_method,
                client_request_id=client_request_id,
                approved_by=None if is_cashier else request.user,
                approved_at=timezone.now(),
            )
            sale.reference = _generated_reference("SALE", sale.pk)
            sale.save(update_fields=["reference"])
            reference = sale.reference
            if amount_received > 0:
                _create_payment(
                    CustomerPayment,
                    "PAY",
                    sale=sale,
                    amount=amount_received,
                    method=payment_method,
                    actor=request.user,
                )

        first_movement_id = None
        for batch, allocated in allocations:
            batch.quantity -= allocated
            batch.save(update_fields=["quantity", "updated_at"])
            movement = StockMovement.objects.create(
                branch=branch,
                batch=batch,
                type=transaction_type,
                quantity=-allocated,
                recipient=recipient,
                reference=reference or "",
                actor=request.user,
                sale=sale,
            )
            if first_movement_id is None:
                first_movement_id = movement.pk
            if reference is None:
                reference = _generated_reference("ISS", movement.pk)
                movement.reference = reference
                movement.save(update_fields=["reference"])
            if sale:
                SaleLine.objects.create(
                    sale=sale,
                    batch=batch,
                    quantity=allocated,
                    purchase_cost=batch.purchase_cost,
                    selling_price=batch.selling_price,
                )

        if sale:
            _record_audit(
                request,
                branch,
                AuditEvent.Action.SALE_RECORDED,
                "sale",
                sale.pk,
                _sale_data(sale),
                reference,
            )
            _queue_pos_event(sale)
            if receipt_email:
                _queue_email_notification(
                    f"sale-receipt-{sale.pk}",
                    EmailNotification.Type.SALE_RECEIPT,
                    receipt_email,
                    "Your pharmacy receipt is ready",
                    (
                        f"A sale was recorded at {branch.name}. "
                        f"Receipt reference: {sale.reference}. "
                        "This email intentionally contains no product, prescription, or patient details."
                    ),
                )
        else:
            _record_audit(
                request,
                branch,
                AuditEvent.Action.STOCK_ADJUSTED,
                "stock_issue",
                first_movement_id,
                {"sku": sku, "quantity": quantity, "recipient": recipient},
                reference,
            )
    return JsonResponse(
        {
            "sale": _sale_data(sale, include_cost=can_view_cost) if sale else None,
            "reference": reference if sale is None else sale.reference,
            "receiptEmailQueued": bool(sale and receipt_email),
        },
        status=201,
    )


@require_POST
def stock_count(request):
    data, error = _json_body(request)
    if error:
        return error
    branch, error = _branch_for_user(request, _branch_id(request, data))
    if error:
        return error
    error = _require_roles(request, branch, {"pharmacist", "branch_manager"})
    if error:
        return error
    try:
        counted_quantity = _whole_number(data.get("quantity"), "Stock count")
    except (ValueError, TypeError):
        return JsonResponse({"detail": "Enter a whole-number stock count."}, status=400)
    batch_number = str(data.get("batch", "")).strip()
    reason = str(data.get("reason", "")).strip()
    if counted_quantity < 0 or not all([batch_number, reason]):
        return JsonResponse({"detail": "Select a batch, count, and reason."}, status=400)
    with transaction.atomic():
        try:
            batch = MedicineBatch.objects.select_for_update().get(branch=branch, batch=batch_number)
        except MedicineBatch.DoesNotExist:
            return JsonResponse({"detail": "The selected batch could not be found."}, status=404)
        difference = counted_quantity - batch.quantity
        if difference == 0:
            return JsonResponse({"detail": "The counted quantity matches the recorded quantity."}, status=400)
        policy = _branch_policy(branch)
        witness = None
        if batch.product.is_controlled and (policy is None or policy.controlled_witness_required):
            witness, error = _controlled_witness(request, branch, data.get("witnessId"))
            if error:
                return error
        previous_quantity = batch.quantity
        batch.quantity = counted_quantity
        batch.save(update_fields=["quantity", "updated_at"])
        movement = StockMovement.objects.create(
            branch=branch,
            batch=batch,
            type=StockMovement.Type.STOCK_COUNT,
            quantity=difference,
            recipient=reason,
            reason=reason,
            reference="",
            actor=request.user,
        )
        movement.reference = _generated_reference("ADJ", movement.pk)
        movement.save(update_fields=["reference"])
        if batch.product.is_controlled:
            ControlledDrugRegisterEntry.objects.create(
                movement=movement,
                witness=witness,
                balance_after=batch.quantity,
                notes=reason,
            )
        _record_audit(
            request,
            branch,
            AuditEvent.Action.STOCK_ADJUSTED,
            "medicine_batch",
            batch.pk,
            {"quantity": counted_quantity},
            movement.reference,
        )
    return JsonResponse({
        "quantity": counted_quantity,
        "previousQuantity": previous_quantity,
        "reference": movement.reference,
    })


@require_POST
def create_supplier_invoice(request):
    if request.content_type and request.content_type.startswith("multipart/form-data"):
        data, error = request.POST, None
    else:
        data, error = _json_body(request)
        if error:
            return error
    branch, error = _branch_for_user(request, _branch_id(request, data))
    if error:
        return error
    error = _require_roles(request, branch, {"branch_manager"})
    if error:
        return error
    supplier_record = None
    if data.get("supplierId"):
        try:
            supplier_record = Supplier.objects.get(
                pk=int(data["supplierId"]),
                is_active=True,
            )
        except (Supplier.DoesNotExist, ValueError, TypeError):
            return JsonResponse({"detail": "Select a valid active supplier."}, status=400)
        supplier = supplier_record.name
    else:
        supplier = str(data.get("supplier", "")).strip()
    invoice_number = str(data.get("invoiceNumber", "")).strip()
    method = str(data.get("method", "Opening payment")).strip()
    try:
        invoice_amount = _money(data.get("invoiceAmount"), "Invoice total")
        amount_paid = _money(data.get("amountPaid", 0), "Amount paid")
        due_date = date.fromisoformat(data.get("dueDate", ""))
    except (ValueError, TypeError) as exc:
        return JsonResponse({"detail": str(exc) or "Enter valid invoice values."}, status=400)
    if not supplier or not invoice_number or invoice_amount <= 0 or amount_paid > invoice_amount:
        return JsonResponse({"detail": "Enter valid invoice details. Amount paid cannot exceed the invoice total."}, status=400)
    if SupplierInvoice.objects.filter(branch=branch, invoice_number__iexact=invoice_number).exists():
        return JsonResponse({"detail": "That invoice number has already been entered."}, status=400)
    original_document = request.FILES.get("originalDocument")
    if original_document:
        if original_document.size > 10 * 1024 * 1024:
            return JsonResponse({"detail": "Supplier invoice PDF must be 10 MB or smaller."}, status=400)
        if not original_document.name.lower().endswith(".pdf"):
            return JsonResponse({"detail": "Supplier invoice originals must be PDF files."}, status=400)
        if original_document.read(5) != b"%PDF-":
            return JsonResponse({"detail": "The uploaded supplier invoice is not a valid PDF."}, status=400)
        original_document.seek(0)
    purchase_order = None
    if data.get("purchaseOrderId"):
        try:
            purchase_order = PurchaseOrder.objects.get(
                pk=int(data["purchaseOrderId"]),
                branch=branch,
            )
        except (PurchaseOrder.DoesNotExist, ValueError, TypeError):
            return JsonResponse({"detail": "Purchase order does not belong to this branch."}, status=400)
        if (
            purchase_order.supplier.name.casefold() != supplier.casefold()
            or (
                supplier_record
                and purchase_order.supplier_id != supplier_record.pk
            )
        ):
            return JsonResponse({"detail": "Invoice supplier must match the linked purchase order."}, status=400)
    with transaction.atomic():
        invoice = SupplierInvoice.objects.create(
            branch=branch,
            supplier_record=(
                supplier_record
                or (purchase_order.supplier if purchase_order else None)
            ),
            purchase_order=purchase_order,
            supplier=supplier,
            invoice_number=invoice_number,
            invoice_amount=invoice_amount,
            amount_paid=amount_paid,
            due_date=due_date,
            original_document=original_document,
            actor=request.user,
        )
        if amount_paid > 0:
            _create_payment(
                SupplierPayment,
                "SPAY",
                invoice=invoice,
                amount=amount_paid,
                method=method,
                actor=request.user,
            )
        _record_audit(
            request,
            branch,
            AuditEvent.Action.CREATED,
            "supplier_invoice",
            invoice.pk,
            _invoice_data(invoice),
            f"INV-{invoice.pk:06d}",
        )
    return JsonResponse({"invoice": _invoice_data(invoice)}, status=201)


@require_GET
def sale_receipt_pdf(request, sale_id):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required."}, status=401)
    try:
        sale = Sale.objects.select_related("branch", "actor").prefetch_related(
            "lines__batch__product",
        ).get(pk=sale_id)
    except Sale.DoesNotExist:
        return JsonResponse({"detail": "Sale not found."}, status=404)
    branch, error = _branch_for_user(request, sale.branch_id)
    if error:
        return error
    error = _require_roles(
        request,
        branch,
        {"cashier", "pharmacist", "branch_manager"},
    )
    if error:
        return error
    if sale.approval_status != Sale.ApprovalStatus.APPROVED:
        return JsonResponse({"detail": "A receipt is available only after the sale is approved."}, status=409)
    response = HttpResponse(
        render_sale_receipt_pdf(sale),
        content_type="application/pdf",
    )
    response["Content-Disposition"] = f'inline; filename="{sale.reference}.pdf"'
    return response


def _supplier_invoice_for_manager(request, invoice_id):
    if not request.user.is_authenticated:
        return None, JsonResponse({"detail": "Authentication required."}, status=401)
    try:
        invoice = SupplierInvoice.objects.select_related(
            "branch",
            "purchase_order",
        ).get(pk=invoice_id)
    except SupplierInvoice.DoesNotExist:
        return None, JsonResponse({"detail": "Supplier invoice not found."}, status=404)
    branch, error = _branch_for_user(request, invoice.branch_id)
    if error:
        return None, error
    error = _require_roles(request, branch, {"branch_manager"})
    if error:
        return None, error
    return invoice, None


@require_GET
def supplier_invoice_reconciliation_pdf(request, invoice_id):
    invoice, error = _supplier_invoice_for_manager(request, invoice_id)
    if error:
        return error
    response = HttpResponse(
        invoice_reconciliation_pdf(invoice),
        content_type="application/pdf",
    )
    response["Content-Disposition"] = (
        f'inline; filename="INV-{invoice.pk:06d}-reconciliation.pdf"'
    )
    return response


@require_GET
def supplier_invoice_original(request, invoice_id):
    invoice, error = _supplier_invoice_for_manager(request, invoice_id)
    if error:
        return error
    document = invoice.original_document
    if not document:
        return JsonResponse({"detail": "No original invoice PDF was uploaded."}, status=404)
    if not document.storage.exists(document.name):
        return JsonResponse({"detail": "The stored supplier invoice PDF is unavailable."}, status=404)
    return FileResponse(
        document.open("rb"),
        as_attachment=True,
        filename=f"INV-{invoice.pk:06d}-original.pdf",
        content_type="application/pdf",
    )


@require_POST
def supplier_payment(request, invoice_id):
    data, error = _json_body(request)
    if error:
        return error
    branch, error = _branch_for_user(request, _branch_id(request, data))
    if error:
        return error
    error = _require_roles(request, branch, {"branch_manager"})
    if error:
        return error
    try:
        amount = _money(data.get("amount"), "Payment amount")
    except ValueError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    method = str(data.get("method", "")).strip()
    if amount <= 0 or not method:
        return JsonResponse({"detail": "Enter a positive payment and method."}, status=400)
    with transaction.atomic():
        try:
            invoice = SupplierInvoice.objects.select_for_update().get(pk=invoice_id, branch=branch)
        except SupplierInvoice.DoesNotExist:
            return JsonResponse({"detail": "Invoice not found."}, status=404)
        if amount > invoice.invoice_amount - invoice.amount_paid:
            return JsonResponse({"detail": "Payment exceeds the remaining invoice balance."}, status=400)
        invoice.amount_paid += amount
        invoice.save(update_fields=["amount_paid"])
        payment = _create_payment(
            SupplierPayment,
            "SPAY",
            invoice=invoice,
            amount=amount,
            method=method,
            actor=request.user,
        )
        _record_audit(
            request,
            branch,
            AuditEvent.Action.PAYMENT_RECORDED,
            "supplier_invoice",
            invoice.pk,
            {"amountPaid": float(invoice.amount_paid)},
            payment.reference,
        )
    return JsonResponse(
        {"paymentId": payment.pk, "reference": payment.reference},
        status=201,
    )


@require_POST
def reconcile_supplier_invoice(request, invoice_id):
    data, error = _json_body(request)
    if error:
        return error
    branch, error = _branch_for_user(request, _branch_id(request, data))
    if error:
        return error
    error = _require_roles(request, branch, {"branch_manager"})
    if error:
        return error
    with transaction.atomic():
        try:
            invoice = SupplierInvoice.objects.select_for_update().select_related(
                "purchase_order",
            ).get(pk=invoice_id, branch=branch)
        except SupplierInvoice.DoesNotExist:
            return JsonResponse({"detail": "Invoice not found."}, status=404)
        if invoice.purchase_order is None:
            return JsonResponse(
                {"detail": "Link this invoice to a purchase order before reconciling."},
                status=409,
            )
        order = invoice.purchase_order
        if order.status != PurchaseOrder.Status.RECEIVED:
            return JsonResponse(
                {"detail": "Receive the complete purchase order before reconciling its invoice."},
                status=409,
            )
        expected_amount = sum(
            (
                line.unit_cost * line.quantity_received
                for line in order.lines.all()
            ),
            Decimal("0.00"),
        ).quantize(Decimal("0.01"))
        variance = (invoice.invoice_amount - expected_amount).quantize(Decimal("0.01"))
        invoice.reconciliation_status = (
            SupplierInvoice.ReconciliationStatus.MATCHED
            if abs(variance) <= Decimal("0.01")
            else SupplierInvoice.ReconciliationStatus.VARIANCE
        )
        invoice.reconciled_expected_amount = expected_amount
        invoice.reconciliation_variance = variance
        invoice.reconciled_at = timezone.now()
        invoice.save(
            update_fields=[
                "reconciliation_status",
                "reconciled_expected_amount",
                "reconciliation_variance",
                "reconciled_at",
            ]
        )
        _record_audit(
            request,
            branch,
            AuditEvent.Action.UPDATED,
            "supplier_invoice",
            invoice.pk,
            {
                "reconciliationStatus": invoice.reconciliation_status,
                "expectedAmount": str(expected_amount),
                "variance": str(variance),
            },
            invoice.invoice_number,
        )
    return JsonResponse({"invoice": _invoice_data(invoice)})


@require_POST
def customer_payment(request, sale_id):
    data, error = _json_body(request)
    if error:
        return error
    branch, error = _branch_for_user(request, _branch_id(request, data))
    if error:
        return error
    error = _require_roles(request, branch, {"cashier", "pharmacist", "branch_manager"})
    if error:
        return error
    try:
        amount = _money(data.get("amount"), "Payment amount")
    except ValueError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    method = str(data.get("method", "")).strip()
    if amount <= 0 or not method:
        return JsonResponse({"detail": "Enter a positive payment and method."}, status=400)
    with transaction.atomic():
        try:
            sale = Sale.objects.select_for_update().get(pk=sale_id, branch=branch)
        except Sale.DoesNotExist:
            return JsonResponse({"detail": "Sale not found."}, status=404)
        if sale.approval_status != Sale.ApprovalStatus.APPROVED:
            return JsonResponse({"detail": "Only pharmacist-approved sales can receive payments."}, status=409)
        if amount > sale.balance_due:
            return JsonResponse({"detail": "Payment exceeds the outstanding sale balance."}, status=400)
        sale.amount_received += amount
        sale.balance_due -= amount
        sale.save(update_fields=["amount_received", "balance_due"])
        payment = _create_payment(
            CustomerPayment,
            "PAY",
            sale=sale,
            amount=amount,
            method=method,
            actor=request.user,
        )
        _record_audit(
            request,
            branch,
            AuditEvent.Action.PAYMENT_RECORDED,
            "sale",
            sale.pk,
            {"balanceDue": float(sale.balance_due)},
            payment.reference,
        )
        ExternalIntegrationEvent.objects.get_or_create(
            provider="internal-outbox",
            external_id=f"customer-payment-{payment.pk}",
            direction=ExternalIntegrationEvent.Direction.OUTBOUND,
            defaults={
                "event_type": "billing.payment",
                "payload": {
                    "saleId": sale.pk,
                    "paymentId": payment.pk,
                    "amount": str(amount),
                    "method": method,
                    "reference": payment.reference,
                },
            },
        )
    return JsonResponse(
        {"paymentId": payment.pk, "reference": payment.reference},
        status=201,
    )


@require_POST
def approve_sale(request, sale_id):
    data, error = _json_body(request)
    if error:
        return error
    branch, error = _branch_for_user(request, _branch_id(request, data))
    if error:
        return error
    error = _require_pharmacist(request, branch)
    if error:
        return error

    with transaction.atomic():
        try:
            sale = Sale.objects.select_for_update().get(pk=sale_id, branch=branch)
        except Sale.DoesNotExist:
            return JsonResponse({"detail": "Sale not found."}, status=404)
        if sale.approval_status != Sale.ApprovalStatus.PENDING:
            return JsonResponse({"detail": "Only pending sales can be approved."}, status=409)

        product = MedicationProduct.objects.filter(sku=sale.sku, is_active=True).first()
        if product is None or product.requires_prescription or product.is_controlled:
            return JsonResponse(
                {"detail": "This sale requires the prescription workflow and cannot be approved here."},
                status=409,
            )
        batches = list(
            MedicineBatch.objects.select_for_update()
            .filter(
                branch=branch,
                product=product,
                quantity__gt=0,
            )
            .filter(_eligible_batch_expiry())
            .order_by(models.F("expiry").asc(nulls_last=True), "id")
        )
        if sum(batch.quantity for batch in batches) < sale.quantity:
            return JsonResponse({"detail": "Insufficient unexpired stock to approve this sale."}, status=409)

        allocations = []
        remaining = sale.quantity
        for batch in batches:
            allocated = min(batch.quantity, remaining)
            if allocated:
                allocations.append((batch, allocated))
                remaining -= allocated
            if remaining == 0:
                break

        total = sum(
            (batch.selling_price * quantity for batch, quantity in allocations),
            Decimal("0.00"),
        )
        cost = sum(
            (batch.purchase_cost * quantity for batch, quantity in allocations),
            Decimal("0.00"),
        )
        if total != sale.sale_amount:
            return JsonResponse(
                {"detail": "Stock prices changed since checkout. Reject this request and create a new sale."},
                status=409,
            )
        if sale.approval_amount_received > total:
            return JsonResponse({"detail": "The proposed payment exceeds the sale total."}, status=409)

        sale.cost_amount = cost
        sale.amount_received = sale.approval_amount_received
        sale.balance_due = total - sale.amount_received
        sale.payment_method = sale.approval_payment_method
        sale.approval_status = Sale.ApprovalStatus.APPROVED
        sale.approved_by = request.user
        sale.approved_at = timezone.now()
        sale.save(update_fields=[
            "cost_amount",
            "amount_received",
            "balance_due",
            "payment_method",
            "approval_status",
            "approved_by",
            "approved_at",
        ])
        if sale.amount_received > 0:
            _create_payment(
                CustomerPayment,
                "PAY",
                sale=sale,
                amount=sale.amount_received,
                method=sale.payment_method,
                actor=sale.actor or request.user,
            )
        for batch, quantity in allocations:
            batch.quantity -= quantity
            batch.save(update_fields=["quantity", "updated_at"])
            StockMovement.objects.create(
                branch=branch,
                batch=batch,
                type=StockMovement.Type.SALE,
                quantity=-quantity,
                recipient=sale.recipient,
                reference=sale.reference,
                actor=request.user,
                sale=sale,
            )
            SaleLine.objects.create(
                sale=sale,
                batch=batch,
                quantity=quantity,
                purchase_cost=batch.purchase_cost,
                selling_price=batch.selling_price,
            )
        _record_audit(
            request,
            branch,
            AuditEvent.Action.SALE_RECORDED,
            "sale",
            sale.pk,
            _sale_data(sale),
            sale.reference,
        )
        _queue_pos_event(sale)
    return JsonResponse({
        "sale": _sale_data(
            sale,
            include_cost=_can_view_financials(request, branch),
        )
    })


@require_POST
def reject_sale(request, sale_id):
    data, error = _json_body(request)
    if error:
        return error
    branch, error = _branch_for_user(request, _branch_id(request, data))
    if error:
        return error
    error = _require_pharmacist(request, branch)
    if error:
        return error
    reason = str(data.get("reason", "")).strip()
    if not reason:
        return JsonResponse({"detail": "A reason is required to reject a sale."}, status=400)
    with transaction.atomic():
        try:
            sale = Sale.objects.select_for_update().get(pk=sale_id, branch=branch)
        except Sale.DoesNotExist:
            return JsonResponse({"detail": "Sale not found."}, status=404)
        if sale.approval_status != Sale.ApprovalStatus.PENDING:
            return JsonResponse({"detail": "Only pending sales can be rejected."}, status=409)
        sale.approval_status = Sale.ApprovalStatus.REJECTED
        sale.rejected_by = request.user
        sale.rejection_reason = reason
        sale.save(update_fields=["approval_status", "rejected_by", "rejection_reason"])
        _record_audit(
            request,
            branch,
            AuditEvent.Action.UPDATED,
            "sale",
            sale.pk,
            _sale_data(sale),
            sale.reference,
        )
    return JsonResponse({
        "sale": _sale_data(
            sale,
            include_cost=_can_view_financials(request, branch),
        )
    })


def _prescription_data(prescription):
    return {
        "id": prescription.id,
        "reference": prescription.reference,
        "patientReference": prescription.patient_reference,
        "prescriberName": prescription.prescriber_name,
        "prescriberRegistration": prescription.prescriber_registration,
        "issuedDate": prescription.issued_date.isoformat(),
        "expiresDate": prescription.expires_date.isoformat() if prescription.expires_date else "",
        "status": prescription.status,
        "lines": [
            {
                "id": line.id,
                "sku": line.product.sku,
                "name": line.product.name,
                "isControlled": line.product.is_controlled,
                "requiresPrescription": line.product.requires_prescription,
                "quantityPrescribed": line.quantity_prescribed,
                "quantityDispensed": line.quantity_dispensed,
                "directions": line.directions,
            }
            for line in prescription.lines.select_related("product").all()
        ],
    }


@require_GET
def prescriptions_view(request):
    branch, error = _branch_for_user(request, _branch_id(request))
    if error:
        return error
    error = _require_pharmacist(request, branch)
    if error:
        return error
    prescriptions = Prescription.objects.filter(branch=branch).prefetch_related("lines__product")
    return JsonResponse({"prescriptions": [_prescription_data(item) for item in prescriptions]})


@require_POST
def create_prescription(request):
    data, error = _json_body(request)
    if error:
        return error
    branch, error = _branch_for_user(request, _branch_id(request, data))
    if error:
        return error
    error = _require_pharmacist(request, branch)
    if error:
        return error
    lines = data.get("lines")
    reference = str(data.get("reference", "")).strip()
    patient_reference = str(data.get("patientReference", "")).strip()
    prescriber = str(data.get("prescriberName", "")).strip()
    registration = str(data.get("prescriberRegistration", "")).strip()
    policy = _branch_policy(branch)
    try:
        issued = date.fromisoformat(data.get("issuedDate", ""))
        expires = date.fromisoformat(data["expiresDate"]) if data.get("expiresDate") else None
    except (ValueError, TypeError):
        return JsonResponse({"detail": "Enter valid prescription dates."}, status=400)
    if not reference or not prescriber or not isinstance(lines, list) or not lines:
        return JsonResponse({"detail": "Enter prescription reference, patient reference, prescriber, and at least one item."}, status=400)
    if (policy is None or policy.require_patient_reference) and not patient_reference:
        return JsonResponse({"detail": "A patient reference is required by this branch policy."}, status=400)
    if policy and policy.require_prescriber_registration and not registration:
        return JsonResponse({"detail": "Prescriber registration is required by this branch policy."}, status=400)
    if policy and policy.require_expiry_date_on_prescription and not expires:
        return JsonResponse({"detail": "Prescription expiry date is required by this branch policy."}, status=400)
    if expires and expires < issued:
        return JsonResponse({"detail": "Prescription expiry cannot precede its issue date."}, status=400)

    parsed_lines = []
    seen_skus = set()
    for line in lines:
        if not isinstance(line, dict):
            return JsonResponse({"detail": "Prescription items must be objects."}, status=400)
        sku = str(line.get("sku", "")).strip()
        try:
            quantity = _whole_number(line.get("quantity"), "Prescribed quantity")
            product = MedicationProduct.objects.get(sku=sku, is_active=True)
        except (ValueError, MedicationProduct.DoesNotExist):
            return JsonResponse({"detail": "Each item needs an active product and whole-number quantity."}, status=400)
        if product.product_type != MedicationProduct.ProductType.MEDICINE:
            return JsonResponse(
                {"detail": "Only medicines can be added to a prescription."},
                status=400,
            )
        if quantity <= 0 or sku in seen_skus:
            return JsonResponse({"detail": "Quantities must be positive and each product may appear only once."}, status=400)
        seen_skus.add(sku)
        parsed_lines.append((product, quantity, str(line.get("directions", "")).strip()))

    with transaction.atomic():
        prescription = Prescription.objects.create(
            branch=branch,
            reference=reference,
            patient_reference=patient_reference,
            prescriber_name=prescriber,
            prescriber_registration=registration,
            issued_date=issued,
            expires_date=expires,
            notes=str(data.get("notes", "")).strip(),
            received_by=request.user,
        )
        PrescriptionLine.objects.bulk_create([
            PrescriptionLine(
                prescription=prescription,
                product=product,
                quantity_prescribed=quantity,
                directions=directions,
            )
            for product, quantity, directions in parsed_lines
        ])
        _record_audit(request, branch, AuditEvent.Action.CREATED, "prescription", prescription.pk, {"status": prescription.status}, reference)
    return JsonResponse({"prescription": _prescription_data(prescription)}, status=201)


@require_POST
def verify_prescription(request, prescription_id):
    data, error = _json_body(request)
    if error:
        return error
    branch, error = _branch_for_user(request, _branch_id(request, data))
    if error:
        return error
    error = _require_pharmacist(request, branch)
    if error:
        return error
    try:
        prescription = Prescription.objects.prefetch_related("lines__product").get(
            pk=prescription_id,
            branch=branch,
        )
    except Prescription.DoesNotExist:
        return JsonResponse({"detail": "Prescription not found."}, status=404)
    if prescription.status != Prescription.Status.RECEIVED:
        return JsonResponse({"detail": "Only newly received prescriptions can be verified."}, status=409)
    if prescription.issued_date > date.today() or (
        prescription.expires_date and prescription.expires_date < date.today()
    ):
        return JsonResponse({"detail": "Prescription is outside its configured validity dates."}, status=400)
    policy = _branch_policy(branch)
    if policy and policy.max_prescription_age_days is not None:
        if (date.today() - prescription.issued_date).days > policy.max_prescription_age_days:
            return JsonResponse({"detail": "Prescription exceeds the branch-configured maximum age."}, status=400)
    prescription.status = Prescription.Status.VERIFIED
    prescription.verified_by = request.user
    prescription.verified_at = timezone.now()
    prescription.save(update_fields=["status", "verified_by", "verified_at"])
    _record_audit(request, branch, AuditEvent.Action.UPDATED, "prescription", prescription.pk, {"status": prescription.status}, prescription.reference)
    return JsonResponse({"prescription": _prescription_data(prescription)})


@require_POST
def dispense_prescription(request, prescription_id):
    data, error = _json_body(request)
    if error:
        return error
    branch, error = _branch_for_user(request, _branch_id(request, data))
    if error:
        return error
    error = _require_pharmacist(request, branch)
    if error:
        return error
    try:
        line_id = int(data.get("lineId"))
        quantity = _whole_number(data.get("quantity"), "Quantity")
        amount_received = _money(data.get("amountReceived", 0), "Amount received")
    except (ValueError, TypeError):
        return JsonResponse({"detail": "Enter a valid prescription line, quantity, and amount."}, status=400)
    payment_method = str(data.get("paymentMethod", "")).strip()
    try:
        witness_id = int(data.get("witnessId")) if data.get("witnessId") else None
    except (TypeError, ValueError):
        return JsonResponse({"detail": "Select a valid controlled-medicine witness."}, status=400)
    if quantity <= 0 or not payment_method:
        return JsonResponse(
            {"detail": "Enter a positive quantity and payment method."},
            status=400,
        )

    with transaction.atomic():
        try:
            prescription = Prescription.objects.select_for_update().get(pk=prescription_id, branch=branch)
            line = PrescriptionLine.objects.select_for_update().select_related("product").get(
                pk=line_id,
                prescription=prescription,
            )
        except (Prescription.DoesNotExist, PrescriptionLine.DoesNotExist):
            return JsonResponse({"detail": "Prescription or item not found."}, status=404)
        recipient = prescription.patient_reference
        if not recipient:
            return JsonResponse(
                {"detail": "The prescription has no patient reference recorded."},
                status=409,
            )
        if prescription.status not in (Prescription.Status.VERIFIED, Prescription.Status.PARTIALLY_DISPENSED):
            return JsonResponse({"detail": "Verify the prescription before dispensing."}, status=409)
        if prescription.expires_date and prescription.expires_date < date.today():
            return JsonResponse({"detail": "Prescription has expired."}, status=400)
        if quantity > line.quantity_prescribed - line.quantity_dispensed:
            return JsonResponse({"detail": "Quantity exceeds the remaining prescribed amount."}, status=400)

        witness = None
        policy = _branch_policy(branch)
        if line.product.is_controlled and (policy is None or policy.controlled_witness_required):
            witness, witness_error = _controlled_witness(request, branch, witness_id)
            if witness_error:
                return witness_error

        batches = list(
            MedicineBatch.objects.select_for_update()
            .select_related("product")
            .filter(
                branch=branch,
                product=line.product,
                quantity__gt=0,
            )
            .filter(_eligible_batch_expiry())
            .order_by(models.F("expiry").asc(nulls_last=True), "id")
        )
        if sum(item.quantity for item in batches) < quantity:
            return JsonResponse({"detail": "Insufficient unexpired stock for this prescription item."}, status=400)

        allocations = []
        remaining = quantity
        for batch in batches:
            allocated = min(batch.quantity, remaining)
            if allocated:
                allocations.append((batch, allocated))
                remaining -= allocated
            if remaining == 0:
                break
        total = sum((batch.selling_price * amount for batch, amount in allocations), Decimal("0.00"))
        cost = sum((batch.purchase_cost * amount for batch, amount in allocations), Decimal("0.00"))
        if amount_received > total:
            return JsonResponse({"detail": "Amount received cannot exceed the prescription item total."}, status=400)

        sale = Sale.objects.create(
            branch=branch,
            sku=line.product.sku,
            name=line.product.name,
            quantity=quantity,
            sale_amount=total,
            cost_amount=cost,
            amount_received=amount_received,
            balance_due=total - amount_received,
            payment_method=payment_method,
            recipient=recipient,
            reference="",
            actor=request.user,
            approval_status=Sale.ApprovalStatus.APPROVED,
            approved_by=request.user,
            approved_at=timezone.now(),
        )
        sale.reference = _generated_reference("SALE", sale.pk)
        sale.save(update_fields=["reference"])
        if amount_received > 0:
            _create_payment(
                CustomerPayment,
                "PAY",
                sale=sale,
                amount=amount_received,
                method=payment_method,
                actor=request.user,
            )

        for batch, allocated in allocations:
            batch.quantity -= allocated
            batch.save(update_fields=["quantity", "updated_at"])
            movement = StockMovement.objects.create(
                branch=branch,
                batch=batch,
                type=StockMovement.Type.SALE,
                quantity=-allocated,
                recipient=recipient,
                reference=sale.reference,
                actor=request.user,
                sale=sale,
            )
            sale_line = SaleLine.objects.create(
                sale=sale,
                batch=batch,
                quantity=allocated,
                purchase_cost=batch.purchase_cost,
                selling_price=batch.selling_price,
            )
            DispenseLine.objects.create(
                prescription_line=line,
                sale_line=sale_line,
                batch=batch,
                quantity=allocated,
                dispensed_by=request.user,
            )
            if line.product.is_controlled:
                ControlledDrugRegisterEntry.objects.create(
                    movement=movement,
                    witness=witness,
                    patient_reference=prescription.patient_reference,
                    prescriber_reference=prescription.reference,
                    balance_after=batch.quantity,
                    notes=str(data.get("controlledNotes", "")).strip(),
                )
        line.quantity_dispensed += quantity
        line.save(update_fields=["quantity_dispensed"])
        remaining_items = prescription.lines.filter(
            quantity_dispensed__lt=models.F("quantity_prescribed")
        ).exists()
        prescription.status = (
            Prescription.Status.PARTIALLY_DISPENSED
            if remaining_items
            else Prescription.Status.DISPENSED
        )
        prescription.save(update_fields=["status"])
        _record_audit(
            request,
            branch,
            AuditEvent.Action.SALE_RECORDED,
            "prescription_dispense",
            sale.pk,
            _sale_data(sale),
            sale.reference,
        )
        _queue_pos_event(sale)

    return JsonResponse(
        {
            "sale": _sale_data(
                sale,
                include_cost=_can_view_financials(request, branch),
            ),
            "prescription": _prescription_data(prescription),
        },
        status=201,
    )


@require_POST
def create_purchase_order(request):
    data, error = _json_body(request)
    if error:
        return error
    branch, error = _branch_for_user(request, _branch_id(request, data))
    if error:
        return error
    error = _require_roles(request, branch, {"branch_manager"})
    if error:
        return error
    try:
        supplier = Supplier.objects.get(pk=int(data.get("supplierId")), is_active=True)
        lines = data.get("lines")
        expected_date = date.fromisoformat(data["expectedDate"]) if data.get("expectedDate") else None
    except (Supplier.DoesNotExist, ValueError, TypeError):
        return JsonResponse({"detail": "Select a valid supplier and expected date."}, status=400)
    if not isinstance(lines, list) or not lines:
        return JsonResponse({"detail": "At least one product line is required."}, status=400)
    parsed = []
    seen = set()
    for item in lines:
        try:
            product = MedicationProduct.objects.get(sku=str(item.get("sku", "")).strip(), is_active=True)
            quantity = _whole_number(item.get("quantity"), "Order quantity")
            cost = _money(item.get("unitCost"), "Unit cost")
        except (MedicationProduct.DoesNotExist, ValueError, AttributeError):
            return JsonResponse({"detail": "Each line needs an active SKU, whole quantity, and valid unit cost."}, status=400)
        if quantity <= 0 or product.pk in seen:
            return JsonResponse({"detail": "Order quantities must be positive and products may appear once."}, status=400)
        parsed.append((product, quantity, cost))
        seen.add(product.pk)
    with transaction.atomic():
        order = PurchaseOrder.objects.create(
            branch=branch,
            supplier=supplier,
            number=f"TMP-{uuid.uuid4().hex}",
            status=PurchaseOrder.Status.SUBMITTED,
            expected_date=expected_date,
            created_by=request.user,
            submitted_at=timezone.now(),
        )
        order.number = _generated_reference("PO", order.pk)
        order.save(update_fields=["number"])
        PurchaseOrderLine.objects.bulk_create([
            PurchaseOrderLine(
                purchase_order=order,
                product=product,
                quantity_ordered=quantity,
                unit_cost=cost,
            )
            for product, quantity, cost in parsed
        ])
        _record_audit(
            request,
            branch,
            AuditEvent.Action.CREATED,
            "purchase_order",
            order.pk,
            {"status": order.status},
            order.number,
        )
    return JsonResponse({"id": order.pk, "number": order.number, "status": order.status}, status=201)


@require_GET
def purchase_orders_view(request):
    branch, error = _branch_for_user(request, _branch_id(request))
    if error:
        return error
    error = _require_roles(request, branch, {"pharmacist", "branch_manager"})
    if error:
        return error
    can_view_cost = _can_view_financials(request, branch)
    orders = PurchaseOrder.objects.filter(branch=branch).select_related("supplier").prefetch_related("lines__product")
    purchase_orders = []
    for order in orders:
        lines = []
        for line in order.lines.all():
            line_data = {
                "id": line.id,
                "sku": line.product.sku,
                "name": line.product.name,
                "productType": line.product.product_type,
                "quantityOrdered": line.quantity_ordered,
                "quantityReceived": line.quantity_received,
                "isControlled": line.product.is_controlled,
            }
            if can_view_cost:
                line_data["unitCost"] = float(line.unit_cost)
            lines.append(line_data)
        purchase_orders.append({
            "id": order.id,
            "number": order.number,
            "supplierId": order.supplier_id,
            "supplier": order.supplier.name,
            "status": order.status,
            "expectedDate": order.expected_date.isoformat() if order.expected_date else "",
            "lines": lines,
        })
    return JsonResponse({"purchaseOrders": purchase_orders})


@require_POST
def receive_purchase_order(request, order_id):
    data, error = _json_body(request)
    if error:
        return error
    branch, error = _branch_for_user(request, _branch_id(request, data))
    if error:
        return error
    error = _require_roles(request, branch, {"branch_manager"})
    if error:
        return error
    receipts = data.get("receipts")
    if not isinstance(receipts, list) or not receipts:
        return JsonResponse({"detail": "Provide at least one purchase-order receipt line."}, status=400)
    with transaction.atomic():
        try:
            order = PurchaseOrder.objects.select_for_update().select_related("supplier").get(pk=order_id, branch=branch)
        except PurchaseOrder.DoesNotExist:
            return JsonResponse({"detail": "Purchase order not found."}, status=404)
        if order.status not in (PurchaseOrder.Status.SUBMITTED, PurchaseOrder.Status.PARTIALLY_RECEIVED):
            return JsonResponse({"detail": "Only submitted or partially received orders can be received."}, status=409)
        parsed_receipts = []
        for receipt in receipts:
            try:
                line = PurchaseOrderLine.objects.select_for_update().select_related("product").get(
                    pk=int(receipt.get("lineId")),
                    purchase_order=order,
                )
                quantity = _whole_number(receipt.get("quantity"), "Received quantity")
                expiry = _batch_expiry(receipt.get("expiry"), line.product.product_type)
                selling_price = _money(receipt.get("sellingPrice"), "Selling price")
            except (PurchaseOrderLine.DoesNotExist, ValueError, TypeError, AttributeError):
                return JsonResponse({"detail": "Receipt line, quantity, or expiry date is invalid."}, status=400)
            batch_number = str(receipt.get("batch", "")).strip()
            if quantity <= 0 or not batch_number or quantity > line.quantity_ordered - line.quantity_received:
                return JsonResponse({"detail": "Received quantity must be positive and no greater than the outstanding order quantity."}, status=400)
            if MedicineBatch.objects.filter(branch=branch, batch__iexact=batch_number).exists():
                return JsonResponse({"detail": f"Batch {batch_number} already exists in this branch."}, status=409)
            parsed_receipts.append(
                (line, quantity, expiry, batch_number, selling_price, receipt.get("witnessId"))
            )

        policy = _branch_policy(branch)
        validated_receipts = []
        for line, quantity, expiry, batch_number, selling_price, witness_id in parsed_receipts:
            controlled_witness = None
            if line.product.is_controlled and (
                policy is None or policy.controlled_witness_required
            ):
                controlled_witness, witness_error = _controlled_witness(
                    request,
                    branch,
                    witness_id,
                )
                if witness_error:
                    return witness_error
            validated_receipts.append(
                (line, quantity, expiry, batch_number, selling_price, controlled_witness)
            )

        for line, quantity, expiry, batch_number, selling_price, controlled_witness in validated_receipts:
            batch = MedicineBatch.objects.create(
                branch=branch,
                product=line.product,
                batch=batch_number,
                quantity=quantity,
                reorder_level=0,
                expiry=expiry,
                supplier=order.supplier.name,
                reference=order.number,
                purchase_cost=line.unit_cost,
                selling_price=selling_price,
            )
            line.quantity_received += quantity
            line.save(update_fields=["quantity_received"])
            movement = StockMovement.objects.create(
                branch=branch,
                batch=batch,
                type=StockMovement.Type.RECEIVED,
                quantity=quantity,
                supplier=order.supplier.name,
                reference=order.number,
                actor=request.user,
            )
            if line.product.is_controlled:
                ControlledDrugRegisterEntry.objects.create(
                    movement=movement,
                    witness=controlled_witness,
                    balance_after=batch.quantity,
                    notes="Purchase order receipt",
                )
        all_received = not order.lines.filter(quantity_received__lt=models.F("quantity_ordered")).exists()
        order.status = PurchaseOrder.Status.RECEIVED if all_received else PurchaseOrder.Status.PARTIALLY_RECEIVED
        order.save(update_fields=["status"])
        _record_audit(request, branch, AuditEvent.Action.PURCHASE_RECEIVED, "purchase_order", order.pk, {"status": order.status}, order.number)
    return JsonResponse({"id": order.pk, "status": order.status})


@require_GET
def reorder_suggestions_view(request):
    branch, error = _branch_for_user(request, _branch_id(request))
    if error:
        return error
    error = _require_roles(request, branch, {"pharmacist", "branch_manager"})
    if error:
        return error
    can_view_cost = _can_view_financials(request, branch)
    rows = []
    products = MedicationProduct.objects.filter(is_active=True).prefetch_related("batches")
    for product in products:
        batches = [batch for batch in product.batches.all() if batch.branch_id == branch.id]
        if not batches:
            continue
        total = sum(
            batch.quantity for batch in batches
            if (
                batch.expiry is not None and batch.expiry >= date.today()
            ) or (
                product.product_type == MedicationProduct.ProductType.SKIN_CARE
                and batch.expiry is None
            )
        )
        level = max(batch.reorder_level for batch in batches)
        if total <= level:
            preferred = product.supplier_options.filter(
                is_preferred=True,
                supplier__is_active=True,
            ).select_related("supplier").first()
            suggestion = {
                "sku": product.sku,
                "name": product.name,
                "productType": product.product_type,
                "onHand": total,
                "reorderLevel": level,
                "suggestedQuantity": max(0, level * 2 - total),
                "supplierId": preferred.supplier_id if preferred else None,
                "supplier": preferred.supplier.name if preferred else "",
            }
            if can_view_cost:
                suggestion["unitCost"] = float(preferred.unit_cost) if preferred else None
            rows.append(suggestion)
    return JsonResponse({"suggestions": rows})


def _replenishment_recommendations(branch, as_of=None):
    as_of = as_of or timezone.localdate()
    lookback_days = 56
    recent_days = 28
    review_buffer_days = 14
    history_start = as_of - timedelta(days=lookback_days - 1)

    batches_by_product = {}
    for batch in MedicineBatch.objects.filter(
        branch=branch,
        product__is_active=True,
    ).select_related("product").order_by(
        models.F("expiry").asc(nulls_last=True),
        "id",
    ):
        batches_by_product.setdefault(batch.product_id, []).append(batch)
    if not batches_by_product:
        return []

    products = list(
        MedicationProduct.objects.filter(
            pk__in=batches_by_product,
            is_active=True,
        ).order_by("sku")
    )
    daily_units = {product.sku: [0] * lookback_days for product in products}
    for sale in Sale.objects.filter(
        branch=branch,
        approval_status=Sale.ApprovalStatus.APPROVED,
        recorded_at__date__gte=history_start,
        recorded_at__date__lte=as_of,
    ).values("sku", "quantity", "recorded_at"):
        day_index = (sale["recorded_at"].date() - history_start).days
        if sale["sku"] in daily_units and 0 <= day_index < lookback_days:
            daily_units[sale["sku"]][day_index] += sale["quantity"]

    preferred_suppliers = {
        mapping.product_id: mapping
        for mapping in SupplierProduct.objects.filter(
            product_id__in=batches_by_product,
            is_preferred=True,
            supplier__is_active=True,
        ).select_related("supplier")
    }

    recommendations = []
    for product in products:
        days = daily_units[product.sku]
        recent_total = sum(days[-recent_days:])
        previous_total = sum(days[:recent_days])
        recent_daily = Decimal(recent_total) / Decimal(recent_days)
        previous_daily = Decimal(previous_total) / Decimal(recent_days)
        daily_demand = (
            recent_daily * Decimal("0.7") + previous_daily * Decimal("0.3")
            if previous_total
            else recent_daily
        )
        sale_days = sum(1 for quantity in days if quantity > 0)
        total_units_sold = sum(days)

        if sale_days >= 20:
            confidence = "high"
            confidence_reason = f"Approved sales on {sale_days} of {lookback_days} days."
        elif sale_days >= 8:
            confidence = "medium"
            confidence_reason = f"Approved sales on {sale_days} of {lookback_days} days."
        else:
            confidence = "low"
            confidence_reason = (
                f"Sparse approved-sales history ({sale_days} of {lookback_days} days); "
                "the order target falls back to the configured reorder level."
            )

        mapping = preferred_suppliers.get(product.pk)
        lead_time_days = mapping.lead_time_days if mapping else 0
        horizon_days = lead_time_days + review_buffer_days
        expected_demand = math.ceil(daily_demand * horizon_days)
        batches = batches_by_product[product.pk]
        current_stock = sum(
            batch.quantity for batch in batches
            if batch.quantity > 0 and (
                (batch.expiry is not None and batch.expiry >= as_of)
                or (
                    product.product_type == MedicationProduct.ProductType.SKIN_CARE
                    and batch.expiry is None
                )
            )
        )
        expiry_quantities_by_date = {}
        for batch in batches:
            if (
                batch.quantity > 0
                and batch.expiry is not None
                and as_of <= batch.expiry <= as_of + timedelta(days=30)
            ):
                expiry_quantities_by_date[batch.expiry] = (
                    expiry_quantities_by_date.get(batch.expiry, 0) + batch.quantity
                )
        expiring_quantity = sum(expiry_quantities_by_date.values())
        cumulative_expiring_quantity = 0
        expiry_risk = 0
        for expiry_date, quantity in sorted(expiry_quantities_by_date.items()):
            cumulative_expiring_quantity += quantity
            days_to_expiry = max((expiry_date - as_of).days, 1)
            expected_sales_before_expiry = math.ceil(daily_demand * days_to_expiry)
            expiry_risk = max(
                expiry_risk,
                cumulative_expiring_quantity - expected_sales_before_expiry,
                0,
            )
        effective_stock = max(
            0,
            current_stock - (expiry_risk if confidence != "low" else 0),
        )
        reorder_level = max(batch.reorder_level for batch in batches)
        target_stock = (
            reorder_level * 2
            if confidence == "low"
            else max(reorder_level * 2, expected_demand)
        )
        suggested_quantity = max(0, target_stock - effective_stock)

        reasons = [
            f"Weighted daily demand: {daily_demand:.2f} units from the last {lookback_days} days "
            "(recent 28 days weighted 70%, previous 28 days 30%).",
            f"Target covers {horizon_days} days: {lead_time_days} supplier lead-time days "
            f"plus a {review_buffer_days}-day review buffer.",
            f"Target stock {target_stock}; usable stock {effective_stock}; "
            f"suggested order {suggested_quantity}.",
        ]
        if not mapping:
            reasons.append("No preferred active supplier is configured; lead time is assumed to be 0 days.")
        if expiry_risk:
            reasons.append(
                f"An estimated {expiry_risk} units may remain at risk in lots expiring within 30 days."
            )

        recommendations.append({
            "sku": product.sku,
            "name": product.name,
            "category": product.category,
            "productType": product.product_type,
            "lookbackDays": lookback_days,
            "salesDays": sale_days,
            "historicalUnitsSold": total_units_sold,
            "averageDailyDemand": round(float(daily_demand), 3),
            "recentDailyDemand": round(float(recent_daily), 3),
            "previousDailyDemand": round(float(previous_daily), 3),
            "leadTimeDays": lead_time_days,
            "expectedDeliveryDate": (
                as_of + timedelta(days=lead_time_days)
            ).isoformat(),
            "reviewBufferDays": review_buffer_days,
            "forecastHorizonDays": horizon_days,
            "expectedDemand": expected_demand,
            "currentStock": current_stock,
            "effectiveStock": effective_stock,
            "reorderLevel": reorder_level,
            "targetStock": target_stock,
            "expiringWithin30Days": expiring_quantity,
            "estimatedExpiryRisk": expiry_risk,
            "suggestedOrderQuantity": suggested_quantity,
            "supplierId": mapping.supplier_id if mapping else None,
            "supplier": mapping.supplier.name if mapping else "",
            "unitCost": float(mapping.unit_cost) if mapping else None,
            "confidence": confidence,
            "confidenceReason": confidence_reason,
            "reasons": reasons,
            "modelVersion": "weighted-moving-average-v1",
        })
    return recommendations


@require_GET
def replenishment_forecast(request):
    branch, error = _branch_for_user(request, _branch_id(request))
    if error:
        return error
    error = _require_roles(request, branch, {"branch_manager"})
    if error:
        return error
    return JsonResponse({
        "branchId": branch.id,
        "asOf": timezone.localdate().isoformat(),
        "modelVersion": "weighted-moving-average-v1",
        "recommendations": _replenishment_recommendations(branch),
    })


@require_POST
def create_reorder_draft(request):
    data, error = _json_body(request)
    if error:
        return error
    branch, error = _branch_for_user(request, _branch_id(request, data))
    if error:
        return error
    error = _require_roles(request, branch, {"branch_manager"})
    if error:
        return error
    sku = str(data.get("sku", "")).strip()
    try:
        product = MedicationProduct.objects.get(sku=sku, is_active=True)
    except MedicationProduct.DoesNotExist:
        return JsonResponse({"detail": "Active product not found."}, status=404)
    batches = list(MedicineBatch.objects.filter(branch=branch, product=product))
    if not batches:
        return JsonResponse({"detail": "No branch reorder level is configured for this product."}, status=400)
    total = sum(
        batch.quantity for batch in batches
        if (
            batch.expiry is not None and batch.expiry >= date.today()
        ) or (
            product.product_type == MedicationProduct.ProductType.SKIN_CARE
            and batch.expiry is None
        )
    )
    reorder_level = max(batch.reorder_level for batch in batches)
    quantity = max(0, reorder_level * 2 - total)
    if quantity == 0 or total > reorder_level:
        return JsonResponse({"detail": "This product is not currently below its reorder point."}, status=409)
    mapping = product.supplier_options.filter(
        is_preferred=True,
        supplier__is_active=True,
    ).select_related("supplier").first()
    if mapping is None:
        return JsonResponse({"detail": "Configure a preferred active supplier and unit cost for this product first."}, status=409)
    order = PurchaseOrder.objects.create(
        branch=branch,
        supplier=mapping.supplier,
        number=f"TMP-{uuid.uuid4().hex}",
        status=PurchaseOrder.Status.DRAFT,
        created_by=request.user,
    )
    order.number = _generated_reference("PO", order.pk)
    order.save(update_fields=["number"])
    PurchaseOrderLine.objects.create(
        purchase_order=order,
        product=product,
        quantity_ordered=quantity,
        unit_cost=mapping.unit_cost,
    )
    _record_audit(
        request,
        branch,
        AuditEvent.Action.CREATED,
        "purchase_order",
        order.pk,
        {"status": order.status, "sku": sku, "quantity": quantity},
        order.number,
    )
    return JsonResponse(
        {"id": order.pk, "number": order.number, "status": order.status, "quantity": quantity},
        status=201,
    )


@require_POST
def submit_purchase_order(request, order_id):
    data, error = _json_body(request)
    if error:
        return error
    branch, error = _branch_for_user(request, _branch_id(request, data))
    if error:
        return error
    error = _require_roles(request, branch, {"branch_manager"})
    if error:
        return error
    try:
        order = PurchaseOrder.objects.select_related("branch", "supplier").prefetch_related(
            "lines__product",
        ).get(pk=order_id, branch=branch)
    except PurchaseOrder.DoesNotExist:
        return JsonResponse({"detail": "Purchase order not found."}, status=404)
    if order.status != PurchaseOrder.Status.DRAFT:
        return JsonResponse({"detail": "Only draft orders can be submitted."}, status=409)
    email_queued = False
    with transaction.atomic():
        order.status = PurchaseOrder.Status.SUBMITTED
        order.submitted_at = timezone.now()
        order.save(update_fields=["status", "submitted_at"])
        _record_audit(
            request,
            branch,
            AuditEvent.Action.UPDATED,
            "purchase_order",
            order.pk,
            {"status": order.status},
            order.number,
        )
        if order.supplier.email:
            items = "\n".join(
                f"- {line.product.sku} | {line.product.name} | quantity {line.quantity_ordered}"
                for line in order.lines.all()
            )
            _, email_queued = _queue_email_notification(
                f"purchase-order-{order.pk}",
                EmailNotification.Type.PURCHASE_ORDER,
                order.supplier.email,
                f"Purchase order {order.number} from {branch.name}",
                (
                    f"Hello {order.supplier.contact_name or order.supplier.name},\n\n"
                    f"{branch.name} has submitted purchase order {order.number}.\n\n"
                    f"{items}\n\n"
                    "Please contact the branch directly with any questions."
                ),
            )
    return JsonResponse({
        "id": order.pk,
        "status": order.status,
        "emailQueued": email_queued,
    })


@require_POST
def create_transfer(request):
    data, error = _json_body(request)
    if error:
        return error
    source, error = _branch_for_user(request, data.get("sourceBranchId"))
    if error:
        return error
    destination, error = _branch_for_user(request, data.get("destinationBranchId"))
    if error:
        return error
    if source.pk == destination.pk:
        return JsonResponse({"detail": "Source and destination branches must differ."}, status=400)
    error = _require_roles(request, source, {"branch_manager"})
    if error:
        return error
    lines = data.get("lines")
    if not isinstance(lines, list) or not lines:
        return JsonResponse({"detail": "At least one transfer item is required."}, status=400)
    parsed = []
    seen = set()
    for item in lines:
        try:
            product = MedicationProduct.objects.get(sku=str(item.get("sku", "")).strip(), is_active=True)
            quantity = _whole_number(item.get("quantity"), "Transfer quantity")
        except (MedicationProduct.DoesNotExist, ValueError, AttributeError):
            return JsonResponse({"detail": "Each transfer line needs an active SKU and whole-number quantity."}, status=400)
        if quantity <= 0 or product.pk in seen:
            return JsonResponse({"detail": "Transfer quantities must be positive and products may appear once."}, status=400)
        eligible_batches = list(MedicineBatch.objects.filter(
            branch=source,
            product=product,
            quantity__gt=0,
        ).filter(_eligible_batch_expiry()).order_by(
            models.F("expiry").asc(nulls_last=True),
            "id",
        ))
        available_quantity = sum(batch.quantity for batch in eligible_batches)
        if available_quantity < quantity:
            return JsonResponse(
                {"detail": f"Insufficient eligible stock for {product.sku}."},
                status=400,
            )
        seen.add(product.pk)
        outstanding = quantity
        for source_batch in eligible_batches:
            allocated = min(source_batch.quantity, outstanding)
            if allocated:
                parsed.append((product, allocated, source_batch))
                outstanding -= allocated
            if outstanding == 0:
                break
    with transaction.atomic():
        transfer = BranchTransfer.objects.create(
            source_branch=source,
            destination_branch=destination,
            reference=f"TMP-{uuid.uuid4().hex}",
            requested_by=request.user,
        )
        transfer.reference = _generated_reference("TRF", transfer.pk)
        transfer.save(update_fields=["reference"])
        transfer.lines.bulk_create([
            BranchTransferLine(
                transfer=transfer,
                product=product,
                source_batch=source_batch,
                quantity_dispatched=quantity,
            )
            for product, quantity, source_batch in parsed
        ])
    _record_audit(
        request,
        source,
        AuditEvent.Action.CREATED,
        "branch_transfer",
        transfer.pk,
        {"destination": destination.code},
        transfer.reference,
    )
    return JsonResponse(
        {"id": transfer.pk, "status": transfer.status, "reference": transfer.reference},
        status=201,
    )


@require_GET
def transfers_view(request):
    branch, error = _branch_for_user(request, _branch_id(request))
    if error:
        return error
    error = _require_roles(request, branch, {"branch_manager"})
    if error:
        return error
    transfers = BranchTransfer.objects.filter(
        models.Q(source_branch=branch) | models.Q(destination_branch=branch)
    ).select_related("source_branch", "destination_branch").prefetch_related(
        "lines__product",
        "lines__source_batch",
        "lines__destination_batch",
    )
    return JsonResponse({"transfers": [
        {
            "id": transfer.id,
            "reference": transfer.reference,
            "sourceBranchId": transfer.source_branch_id,
            "sourceBranch": transfer.source_branch.name,
            "destinationBranchId": transfer.destination_branch_id,
            "destinationBranch": transfer.destination_branch.name,
            "status": transfer.status,
            "lines": [
                {
                    "id": line.id,
                    "sku": line.product.sku,
                    "name": line.product.name,
                    "batch": line.source_batch.batch,
                    "destinationBatch": line.destination_batch.batch if line.destination_batch_id else "",
                    "quantityDispatched": line.quantity_dispatched,
                    "quantityReceived": line.quantity_received,
                    "quantityOutstanding": line.quantity_dispatched - line.quantity_received,
                    "isControlled": line.product.is_controlled,
                }
                for line in transfer.lines.all()
            ],
        }
        for transfer in transfers
    ]})


@require_POST
def dispatch_transfer(request, transfer_id):
    data, error = _json_body(request)
    if error:
        return error
    branch, error = _branch_for_user(request, _branch_id(request, data))
    if error:
        return error
    error = _require_roles(request, branch, {"branch_manager"})
    if error:
        return error
    with transaction.atomic():
        try:
            transfer = BranchTransfer.objects.select_for_update().get(pk=transfer_id, source_branch=branch)
        except BranchTransfer.DoesNotExist:
            return JsonResponse({"detail": "Transfer not found."}, status=404)
        if transfer.status != BranchTransfer.Status.REQUESTED:
            return JsonResponse({"detail": "Only requested transfers can be dispatched."}, status=409)
        lines = list(transfer.lines.select_related("source_batch", "product").all())
        policy = _branch_policy(branch)
        witness = None
        if any(line.product.is_controlled for line in lines) and (
            policy is None or policy.controlled_witness_required
        ):
            witness, witness_error = _controlled_witness(
                request,
                branch,
                data.get("witnessId"),
            )
            if witness_error:
                return witness_error
        locked_batches = {
            batch.pk: batch
            for batch in MedicineBatch.objects.select_for_update().filter(
                pk__in=[line.source_batch_id for line in lines]
            )
        }
        for line in lines:
            batch = locked_batches[line.source_batch_id]
            if (
                batch.quantity < line.quantity_dispatched
                or (
                    batch.expiry is None
                    and line.product.product_type != MedicationProduct.ProductType.SKIN_CARE
                )
                or (batch.expiry is not None and batch.expiry < date.today())
            ):
                return JsonResponse({"detail": f"Insufficient eligible stock for {line.product.sku}."}, status=409)
        for line in lines:
            batch = locked_batches[line.source_batch_id]
            batch.quantity -= line.quantity_dispatched
            batch.save(update_fields=["quantity", "updated_at"])
            movement = StockMovement.objects.create(
                branch=branch,
                batch=batch,
                type=StockMovement.Type.TRANSFER_OUT,
                quantity=-line.quantity_dispatched,
                reference=transfer.reference,
                recipient=transfer.destination_branch.name,
                actor=request.user,
            )
            if line.product.is_controlled:
                ControlledDrugRegisterEntry.objects.create(
                    movement=movement,
                    witness=witness,
                    balance_after=batch.quantity,
                    notes=f"Transfer dispatch to {transfer.destination_branch.code}",
                )
        transfer.status = BranchTransfer.Status.DISPATCHED
        transfer.dispatched_by = request.user
        transfer.dispatched_at = timezone.now()
        transfer.save(update_fields=["status", "dispatched_by", "dispatched_at"])
        _record_audit(request, branch, AuditEvent.Action.STOCK_ADJUSTED, "branch_transfer", transfer.pk, {"status": transfer.status}, transfer.reference)
    return JsonResponse({"id": transfer.pk, "status": transfer.status})


@require_POST
def receive_transfer(request, transfer_id):
    data, error = _json_body(request)
    if error:
        return error
    branch, error = _branch_for_user(request, _branch_id(request, data))
    if error:
        return error
    error = _require_roles(request, branch, {"branch_manager"})
    if error:
        return error
    with transaction.atomic():
        try:
            transfer = BranchTransfer.objects.select_for_update().select_related("source_branch").get(
                pk=transfer_id,
                destination_branch=branch,
            )
        except BranchTransfer.DoesNotExist:
            return JsonResponse({"detail": "Transfer not found."}, status=404)
        if transfer.status not in (
            BranchTransfer.Status.DISPATCHED,
            BranchTransfer.Status.PARTIALLY_RECEIVED,
        ):
            return JsonResponse({"detail": "Only dispatched or partially received transfers can be received."}, status=409)
        lines = list(transfer.lines.select_related("product", "source_batch").all())
        quantity_map = data.get("quantities", {})
        batch_map = data.get("batches", {})
        if not isinstance(quantity_map, dict) or not isinstance(batch_map, dict):
            return JsonResponse({"detail": "Receipt quantities and batch names must be line maps."}, status=400)
        receipts = []
        batch_names = []
        for line in lines:
            outstanding = line.quantity_dispatched - line.quantity_received
            if outstanding == 0:
                continue
            try:
                quantity = _whole_number(
                    quantity_map.get(str(line.id), outstanding),
                    "Received quantity",
                )
            except ValueError as exc:
                return JsonResponse({"detail": str(exc)}, status=400)
            if quantity == 0:
                continue
            if quantity < 0 or quantity > outstanding:
                return JsonResponse(
                    {"detail": f"Receipt quantity for {line.product.sku} must be between 1 and {outstanding}."},
                    status=400,
                )
            requested_batch = str(batch_map.get(str(line.id), line.source_batch.batch)).strip()
            if not requested_batch:
                return JsonResponse({"detail": "Destination lot numbers cannot be blank."}, status=400)
            if line.destination_batch_id:
                if requested_batch.casefold() != line.destination_batch.batch.casefold():
                    return JsonResponse(
                        {"detail": "A partially received line must continue using its original destination lot."},
                        status=409,
                    )
            else:
                batch_names.append(requested_batch.casefold())
            receipts.append((line, quantity, requested_batch))
        if not receipts:
            return JsonResponse({"detail": "All transfer quantities have already been received."}, status=409)
        if len(batch_names) != len(set(batch_names)):
            return JsonResponse({"detail": "Each transfer line needs a unique destination lot number."}, status=409)
        existing_batches = {
            item.casefold()
            for item in MedicineBatch.objects.filter(branch=branch).values_list("batch", flat=True)
        }
        conflicts = existing_batches.intersection(batch_names)
        if conflicts:
            return JsonResponse({"detail": f"Batch {next(iter(conflicts))} already exists at destination."}, status=409)
        policy = _branch_policy(branch)
        witness = None
        if any(line.product.is_controlled for line, _, _ in receipts) and (
            policy is None or policy.controlled_witness_required
        ):
            witness, witness_error = _controlled_witness(
                request,
                branch,
                data.get("witnessId"),
            )
            if witness_error:
                return witness_error
        all_received = True
        for line, quantity, requested_batch in receipts:
            source = line.source_batch
            if line.destination_batch_id:
                batch = MedicineBatch.objects.select_for_update().get(pk=line.destination_batch_id)
                batch.quantity += quantity
                batch.save(update_fields=["quantity", "updated_at"])
            else:
                batch = MedicineBatch.objects.create(
                    branch=branch,
                    product=line.product,
                    batch=requested_batch,
                    quantity=quantity,
                    reorder_level=source.reorder_level,
                    expiry=source.expiry,
                    supplier=source.supplier,
                    reference=transfer.reference,
                    purchase_cost=source.purchase_cost,
                    selling_price=source.selling_price,
                )
                line.destination_batch = batch
            line.quantity_received += quantity
            line.save(update_fields=["destination_batch", "quantity_received"])
            movement = StockMovement.objects.create(
                branch=branch,
                batch=batch,
                type=StockMovement.Type.TRANSFER_IN,
                quantity=quantity,
                reference=transfer.reference,
                supplier=transfer.source_branch.name,
                actor=request.user,
            )
            if line.product.is_controlled:
                ControlledDrugRegisterEntry.objects.create(
                    movement=movement,
                    witness=witness,
                    balance_after=batch.quantity,
                    notes=f"Transfer receipt from {transfer.source_branch.code}",
                )
            if line.quantity_received < line.quantity_dispatched:
                all_received = False
        transfer.status = (
            BranchTransfer.Status.RECEIVED
            if all_received
            else BranchTransfer.Status.PARTIALLY_RECEIVED
        )
        transfer.received_by = request.user
        if all_received:
            transfer.received_at = timezone.now()
        transfer.save(update_fields=["status", "received_by", "received_at"])
        _record_audit(request, branch, AuditEvent.Action.STOCK_ADJUSTED, "branch_transfer", transfer.pk, {"status": transfer.status}, transfer.reference)
    return JsonResponse({"id": transfer.pk, "status": transfer.status})


@require_GET
def analytics_report(request):
    branch, error = _branch_for_user(
        request,
        _branch_id(request),
        allow_admin_cross_branch=True,
    )
    if error:
        return error
    if not request.user.is_superuser:
        error = _require_roles(request, branch, {"branch_manager"})
        if error:
            return error
    try:
        start = date.fromisoformat(request.GET.get("start", (date.today() - timedelta(days=30)).isoformat()))
        end = date.fromisoformat(request.GET.get("end", date.today().isoformat()))
    except ValueError:
        return JsonResponse({"detail": "Use ISO dates for start and end."}, status=400)
    if end < start or (end - start).days > 366:
        return JsonResponse({"detail": "Date range must be ordered and no longer than 366 days."}, status=400)
    movements = StockMovement.objects.filter(
        branch=branch,
        recorded_at__date__gte=start,
        recorded_at__date__lte=end,
    ).select_related("batch__product")
    movement_data = [
        {
            "date": item.recorded_at.isoformat(),
            "type": item.type,
            "sku": item.batch.product.sku,
            "product": item.batch.product.name,
            "batch": item.batch.batch,
            "quantity": item.quantity,
            "reference": item.reference,
        }
        for item in movements
    ]
    sales = Sale.objects.filter(
        branch=branch,
        recorded_at__date__gte=start,
        recorded_at__date__lte=end,
        approval_status=Sale.ApprovalStatus.APPROVED,
    )
    sales_list = list(sales)
    previous_period_days = (end - start).days + 1
    previous_start = start - timedelta(days=previous_period_days)
    previous_sales = Sale.objects.filter(
        branch=branch,
        recorded_at__date__gte=previous_start,
        recorded_at__date__lt=start,
        approval_status=Sale.ApprovalStatus.APPROVED,
    )
    previous_sales_amount = sum(
        previous_sales.values_list("sale_amount", flat=True),
        Decimal("0.00"),
    )
    sales_by_day = {
        (start + timedelta(days=offset)).isoformat(): {
            "salesAmount": Decimal("0.00"),
            "grossProfit": Decimal("0.00"),
        }
        for offset in range(previous_period_days)
    }
    product_totals = {}
    for sale in sales_list:
        day = sale.recorded_at.date().isoformat()
        sales_by_day[day]["salesAmount"] += sale.sale_amount
        sales_by_day[day]["grossProfit"] += sale.sale_amount - sale.cost_amount
    for line in SaleLine.objects.filter(sale__in=sales).select_related(
        "sale", "batch__product"
    ):
        product = line.batch.product
        totals = product_totals.setdefault(
            product.sku,
            {
                "sku": product.sku,
                "product": product.name,
                "category": product.category,
                "unitsSold": 0,
                "salesAmount": Decimal("0.00"),
                "grossProfit": Decimal("0.00"),
            },
        )
        totals["unitsSold"] += line.quantity
        totals["salesAmount"] += line.selling_price * line.quantity
        totals["grossProfit"] += (
            line.selling_price - line.purchase_cost
        ) * line.quantity
    sales_amount = sum(
        (sale.sale_amount for sale in sales_list),
        Decimal("0.00"),
    )
    gross_profit = sum(
        (sale.sale_amount - sale.cost_amount for sale in sales_list),
        Decimal("0.00"),
    )
    sales_change_percent = (
        float((sales_amount - previous_sales_amount) * Decimal("100") / previous_sales_amount)
        if previous_sales_amount
        else None
    )
    today = timezone.localdate()
    risk_batches = list(
        MedicineBatch.objects.filter(branch=branch).select_related("product")
    )
    stock_by_product = {}
    out_of_stock_lots = 0
    low_stock_lots = 0
    expiring_lots = 0
    for batch in risk_batches:
        is_expired = batch.expiry is not None and batch.expiry < today
        if not is_expired:
            if batch.quantity == 0:
                out_of_stock_lots += 1
            elif batch.quantity <= batch.reorder_level:
                low_stock_lots += 1
            if (
                batch.quantity > 0
                and batch.expiry is not None
                and batch.expiry <= today + timedelta(days=90)
            ):
                expiring_lots += 1
        if batch.product_id not in stock_by_product:
            stock_by_product[batch.product_id] = {
                "isActive": batch.product.is_active,
                "onHand": 0,
                "reorderLevel": 0,
            }
        stock = stock_by_product[batch.product_id]
        if (
            batch.expiry is not None and batch.expiry >= today
        ) or (
            batch.product.product_type == MedicationProduct.ProductType.SKIN_CARE
            and batch.expiry is None
        ):
            stock["onHand"] += batch.quantity
        stock["reorderLevel"] = max(stock["reorderLevel"], batch.reorder_level)
    reorder_product_count = sum(
        stock["isActive"] and stock["onHand"] <= stock["reorderLevel"]
        for stock in stock_by_product.values()
    )
    return JsonResponse({
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "summary": {
            "movementCount": len(movement_data),
            "unitsReceived": sum(row["quantity"] for row in movement_data if row["quantity"] > 0),
            "unitsIssued": -sum(row["quantity"] for row in movement_data if row["quantity"] < 0),
            "salesCount": len(sales_list),
            "salesAmount": float(sales_amount),
            "grossProfit": float(gross_profit),
            "outstandingBalance": float(sum(
                Sale.objects.filter(
                    branch=branch,
                    approval_status=Sale.ApprovalStatus.APPROVED,
                ).values_list("balance_due", flat=True),
                Decimal("0.00"),
            )),
            "pendingApprovalCount": Sale.objects.filter(
                branch=branch,
                recorded_at__date__gte=start,
                recorded_at__date__lte=end,
                approval_status=Sale.ApprovalStatus.PENDING,
            ).count(),
            "previousPeriodSalesAmount": float(previous_sales_amount),
            "salesChangePercent": sales_change_percent,
        },
        "stockRisk": {
            "outOfStockLots": out_of_stock_lots,
            "lowStockLots": low_stock_lots,
            "expiringLots": expiring_lots,
            "reorderProducts": reorder_product_count,
        },
        "salesTrend": [
            {
                "date": day,
                "salesAmount": float(totals["salesAmount"]),
                "grossProfit": float(totals["grossProfit"]),
            }
            for day, totals in sales_by_day.items()
        ],
        "topProducts": sorted(
            (
                {
                    **totals,
                    "salesAmount": float(totals["salesAmount"]),
                    "grossProfit": float(totals["grossProfit"]),
                }
                for totals in product_totals.values()
            ),
            key=lambda product: (-product["unitsSold"], product["sku"]),
        )[:10],
        "movements": movement_data,
        "controlledRegister": [
            {
                "date": entry.recorded_at.isoformat(),
                "sku": entry.movement.batch.product.sku,
                "product": entry.movement.batch.product.name,
                "batch": entry.movement.batch.batch,
                "movement": entry.movement.type,
                "quantity": entry.movement.quantity,
                "witness": entry.witness.get_username() if entry.witness else "Not required by branch policy",
                "balanceAfter": entry.balance_after,
                "reference": entry.movement.reference,
            }
            for entry in ControlledDrugRegisterEntry.objects.filter(
                movement__branch=branch,
                recorded_at__date__gte=start,
                recorded_at__date__lte=end,
            ).select_related("movement__batch__product", "witness")
        ],
    })


@require_GET
def movement_export(request):
    report = analytics_report(request)
    if report.status_code != 200:
        return report
    data = json.loads(report.content)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="pharmacy-stock-movements.csv"'
    writer = csv.writer(response)
    writer.writerow(["Date", "Activity", "SKU", "Product", "Batch", "Quantity", "Reference"])
    for row in data["movements"]:
        writer.writerow([row["date"], row["type"], row["sku"], row["product"], row["batch"], row["quantity"], row["reference"]])
    return response


@require_POST
def record_integration_event(request):
    data, error = _json_body(request)
    if error:
        return error
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required."}, status=401)
    provider = str(data.get("provider", "")).strip()
    external_id = str(data.get("externalId", "")).strip()
    event_type = str(data.get("eventType", "")).strip()
    payload = data.get("payload")
    if not provider or not external_id or event_type not in {"pos.sale", "billing.payment", "patient.reference"}:
        return JsonResponse({"detail": "Provider, unique external ID, and supported event type are required."}, status=400)
    if not isinstance(payload, dict) or len(json.dumps(payload)) > 20000:
        return JsonResponse({"detail": "Integration payload must be an object under 20 KB."}, status=400)
    event, created = ExternalIntegrationEvent.objects.get_or_create(
        provider=provider,
        external_id=external_id,
        direction=ExternalIntegrationEvent.Direction.INBOUND,
        defaults={
            "event_type": event_type,
            "payload": payload,
            "status": ExternalIntegrationEvent.Status.PENDING,
        },
    )
    if not created and (event.event_type != event_type or event.payload != payload):
        return JsonResponse({"detail": "External ID was previously used with a different event."}, status=409)
    return JsonResponse(
        {"id": event.id, "status": event.status, "duplicate": not created},
        status=202 if created else 200,
    )


@ensure_csrf_cookie
@require_GET
def csrf_token(request):
    return JsonResponse({"csrfToken": get_token(request)})


@require_POST
def login_view(request):
    try:
        data = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"detail": "Request must contain valid JSON."}, status=400)

    if not isinstance(data, dict):
        return JsonResponse({"detail": "Request must contain a JSON object."}, status=400)

    username = data.get("username", "")
    password = data.get("password", "")

    if not isinstance(username, str) or not isinstance(password, str):
        return JsonResponse({"detail": "Username and password are required."}, status=400)

    user = authenticate(request, username=username.strip(), password=password)

    if user is None:
        return JsonResponse({"detail": "Invalid username or password."}, status=401)

    login(request, user)
    _record_auth_event(request, user, AuditEvent.Action.LOGIN)

    return JsonResponse({"user": _user_data(user)})


@require_POST
def logout_view(request):
    if request.user.is_authenticated:
        _record_auth_event(request, request.user, AuditEvent.Action.LOGOUT)
        logout(request)

    return JsonResponse({"detail": "Logged out."})


@require_GET
def current_user(request):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required."}, status=401)

    return JsonResponse({"user": _user_data(request.user)})