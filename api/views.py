import csv
import json
import uuid
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib.auth import authenticate, login, logout
from django.db import models, transaction
from django.http import HttpResponse, JsonResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .models import (
    AuditEvent,
    Branch,
    BranchCompliancePolicy,
    BranchTransfer,
    BranchTransferLine,
    BranchMembership,
    BarcodeAlias,
    ControlledDrugRegisterEntry,
    CustomerPayment,
    DispenseLine,
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


def _branch_for_user(request, branch_id):
    if not request.user.is_authenticated:
        return None, JsonResponse({"detail": "Authentication required."}, status=401)
    try:
        branch = Branch.objects.get(pk=branch_id, is_active=True)
    except (Branch.DoesNotExist, ValueError, TypeError):
        return None, JsonResponse({"detail": "Select a valid active branch."}, status=400)

    if not request.user.is_superuser and not BranchMembership.objects.filter(
        user=request.user,
        branch=branch,
        is_active=True,
    ).exists():
        return None, JsonResponse({"detail": "You do not have access to this branch."}, status=403)
    return branch, None


def _branch_role(request, branch):
    if request.user.is_superuser:
        return "administrator"
    membership = BranchMembership.objects.filter(
        user=request.user,
        branch=branch,
        is_active=True,
    ).first()
    return membership.role if membership else None


def _require_roles(request, branch, roles):
    if request.user.is_superuser:
        return None
    role = _branch_role(request, branch)
    if role not in roles:
        return JsonResponse({"detail": "You do not have permission for this action."}, status=403)
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


def _batch_data(batch):
    return {
        "id": batch.id,
        "sku": batch.product.sku,
        "name": batch.product.name,
        "category": batch.product.category,
        "batch": batch.batch,
        "quantity": batch.quantity,
        "reorderLevel": batch.reorder_level,
        "expiry": batch.expiry.isoformat(),
        "supplier": batch.supplier,
        "reference": batch.reference,
        "purchaseCost": float(batch.purchase_cost),
        "sellingPrice": float(batch.selling_price),
        "requiresPrescription": batch.product.requires_prescription,
        "isControlled": batch.product.is_controlled,
        "controlledSchedule": batch.product.controlled_schedule,
        "barcode": batch.product.barcode,
    }


def _sale_data(sale):
    return {
        "id": str(sale.pk),
        "sku": sale.sku,
        "name": sale.name,
        "quantity": sale.quantity,
        "saleAmount": float(sale.sale_amount),
        "costAmount": float(sale.cost_amount),
        "grossProfit": float(sale.sale_amount - sale.cost_amount),
        "amountReceived": float(sale.amount_received),
        "balanceDue": float(sale.balance_due),
        "paymentMethod": sale.payment_method,
        "recipient": sale.recipient,
        "reference": sale.reference,
        "recordedAt": sale.recorded_at.isoformat(),
    }


def _invoice_data(invoice):
    return {
        "id": str(invoice.pk),
        "supplier": invoice.supplier,
        "invoiceNumber": invoice.invoice_number,
        "invoiceAmount": float(invoice.invoice_amount),
        "amountPaid": float(invoice.amount_paid),
        "dueDate": invoice.due_date.isoformat(),
        "createdAt": invoice.created_at.isoformat(),
        "purchaseOrderId": invoice.purchase_order_id,
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
                "unit": product.unit,
                "barcode": product.barcode or "",
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
    if not request.user.is_staff:
        return JsonResponse({"detail": "Administrator access is required to manage the product catalog."}, status=403)
    sku = str(data.get("sku", "")).strip()
    name = str(data.get("name", "")).strip()
    category = str(data.get("category", "")).strip()
    barcode = str(data.get("barcode", "")).strip()
    if not sku or not name or not category:
        return JsonResponse({"detail": "SKU, product name, and category are required."}, status=400)
    if MedicationProduct.objects.filter(sku__iexact=sku).exists():
        return JsonResponse({"detail": "SKU is already in use."}, status=409)
    if barcode and MedicationProduct.objects.filter(barcode__iexact=barcode).exists():
        return JsonResponse({"detail": "Barcode is already in use."}, status=409)
    if not isinstance(data.get("requiresPrescription", False), bool) or not isinstance(
        data.get("isControlled", False), bool
    ):
        return JsonResponse({"detail": "Prescription and controlled flags must be booleans."}, status=400)
    product = MedicationProduct.objects.create(
        sku=sku,
        name=name,
        category=category,
        unit=str(data.get("unit", "unit")).strip() or "unit",
        barcode=barcode or None,
        requires_prescription=bool(data.get("requiresPrescription")),
        is_controlled=bool(data.get("isControlled")),
        controlled_schedule=str(data.get("controlledSchedule", "")).strip(),
    )
    return JsonResponse({"sku": product.sku}, status=201)


@require_GET
def suppliers_view(request):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required."}, status=401)
    return JsonResponse({
        "suppliers": [
            {"id": supplier.id, "name": supplier.name, "phone": supplier.phone, "email": supplier.email}
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
    if not request.user.is_staff:
        return JsonResponse({"detail": "Administrator access is required to manage suppliers."}, status=403)
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
    return JsonResponse({"id": supplier.id, "name": supplier.name}, status=201)


@require_POST
def set_supplier_product(request):
    data, error = _json_body(request)
    if error:
        return error
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required."}, status=401)
    if not request.user.is_staff:
        return JsonResponse({"detail": "Administrator access is required."}, status=403)
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

    batches = MedicineBatch.objects.filter(branch=branch)
    movements = StockMovement.objects.filter(branch=branch).select_related("batch")
    sales = Sale.objects.filter(branch=branch)
    invoices = SupplierInvoice.objects.filter(branch=branch)
    supplier_payments = SupplierPayment.objects.filter(invoice__branch=branch).select_related("invoice")
    customer_payments = CustomerPayment.objects.filter(sale__branch=branch).select_related("sale")
    return JsonResponse({
        "inventory": [_batch_data(batch) for batch in batches],
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
        "sales": [_sale_data(sale) for sale in sales],
        "supplierInvoices": [_invoice_data(invoice) for invoice in invoices],
        "supplierPayments": [
            {
                "id": payment.id,
                "invoiceId": str(payment.invoice_id),
                "supplier": payment.invoice.supplier,
                "invoiceNumber": payment.invoice.invoice_number,
                "amount": float(payment.amount),
                "method": payment.method,
                "reference": payment.reference,
                "recordedAt": payment.recorded_at.isoformat(),
            }
            for payment in supplier_payments
        ],
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
    try:
        quantity = _whole_number(data.get("quantity"), "Quantity")
        reorder_level = _whole_number(data.get("reorderLevel"), "Reorder level")
        purchase_cost = _money(data.get("purchaseCost"), "Purchase cost")
        selling_price = _money(data.get("sellingPrice"), "Selling price")
        expiry = date.fromisoformat(data.get("expiry", ""))
    except (ValueError, TypeError) as exc:
        return JsonResponse({"detail": str(exc) or "Enter valid batch values."}, status=400)

    sku = str(data.get("sku", "")).strip()
    name = str(data.get("name", "")).strip()
    category = str(data.get("category", "")).strip()
    batch_number = str(data.get("batch", "")).strip()
    supplier = str(data.get("supplier", "")).strip()
    reference = str(data.get("reference", "")).strip()
    if not all([sku, name, category, batch_number, supplier, reference]):
        return JsonResponse({"detail": "Complete all required batch fields."}, status=400)
    if quantity < 0 or reorder_level < 0:
        return JsonResponse({"detail": "Quantity and reorder level cannot be negative."}, status=400)
    if MedicineBatch.objects.filter(branch=branch, batch__iexact=batch_number).exists():
        return JsonResponse({"detail": "That batch number already exists in this branch."}, status=400)

    product, created = MedicationProduct.objects.get_or_create(
        sku=sku,
        defaults={"name": name, "category": category},
    )
    if not created and (
        product.name != name or product.category != category or not product.is_active
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
            reference=reference,
            purchase_cost=purchase_cost,
            selling_price=selling_price,
        )
        movement = StockMovement.objects.create(
            branch=branch,
            batch=batch,
            type=StockMovement.Type.RECEIVED,
            quantity=quantity,
            supplier=supplier,
            reference=reference,
            actor=request.user,
        )
        if product.is_controlled:
            ControlledDrugRegisterEntry.objects.create(
                movement=movement,
                witness=witness,
                balance_after=batch.quantity,
                notes="Stock receipt",
            )
        _record_audit(request, branch, AuditEvent.Action.CREATED, "medicine_batch", batch.pk, _batch_data(batch), reference)
    return JsonResponse({"batch": _batch_data(batch)}, status=201)


@require_POST
def dispense_stock(request):
    data, error = _json_body(request)
    if error:
        return error
    branch, error = _branch_for_user(request, _branch_id(request, data))
    if error:
        return error

    sku = str(data.get("sku", "")).strip()
    recipient = str(data.get("recipient", "")).strip()
    reference = str(data.get("reference", "")).strip()
    transaction_type = data.get("transactionType")
    try:
        quantity = _whole_number(data.get("quantity"), "Quantity")
        amount_received = _money(data.get("amountReceived", 0), "Amount received")
    except (ValueError, TypeError) as exc:
        return JsonResponse({"detail": str(exc) or "Enter a valid quantity."}, status=400)
    if quantity <= 0 or not all([sku, recipient, reference]):
        return JsonResponse({"detail": "Enter a valid quantity, medicine, recipient, and reference."}, status=400)
    if transaction_type not in ("Sale", "Non-sale issue"):
        return JsonResponse({"detail": "Select a valid transaction type."}, status=400)
    payment_method = str(data.get("paymentMethod", "")).strip()
    if transaction_type == "Sale" and not payment_method:
        return JsonResponse({"detail": "Select a payment method for the sale."}, status=400)

    product = MedicationProduct.objects.filter(sku=sku, is_active=True).first()
    if product is None:
        return JsonResponse({"detail": "The selected medicine could not be found."}, status=404)
    if product.requires_prescription or product.is_controlled:
        return JsonResponse(
            {
                "detail": (
                    "This medicine requires the prescription or controlled-medicine "
                    "workflow, which is not available yet."
                )
            },
            status=400,
        )

    with transaction.atomic():
        eligible = list(
            MedicineBatch.objects.select_for_update()
            .select_related("product")
            .filter(branch=branch, product__sku=sku, quantity__gt=0, expiry__gte=date.today())
            .order_by("expiry", "id")
        )
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
        if transaction_type == "Sale":
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
                reference=reference,
                actor=request.user,
            )
            if amount_received > 0:
                CustomerPayment.objects.create(
                    sale=sale,
                    amount=amount_received,
                    method=payment_method,
                    reference=reference,
                    actor=request.user,
                )

        for batch, allocated in allocations:
            batch.quantity -= allocated
            batch.save(update_fields=["quantity", "updated_at"])
            StockMovement.objects.create(
                branch=branch,
                batch=batch,
                type=transaction_type,
                quantity=-allocated,
                recipient=recipient,
                reference=reference,
                actor=request.user,
                sale=sale,
            )
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
    return JsonResponse({"sale": _sale_data(sale) if sale else None}, status=201)


@require_POST
def stock_count(request):
    data, error = _json_body(request)
    if error:
        return error
    branch, error = _branch_for_user(request, _branch_id(request, data))
    if error:
        return error
    try:
        counted_quantity = _whole_number(data.get("quantity"), "Stock count")
    except (ValueError, TypeError):
        return JsonResponse({"detail": "Enter a whole-number stock count."}, status=400)
    batch_number = str(data.get("batch", "")).strip()
    reason = str(data.get("reason", "")).strip()
    reference = str(data.get("reference", "")).strip()
    if counted_quantity < 0 or not all([batch_number, reason, reference]):
        return JsonResponse({"detail": "Select a batch, count, reason, and reference."}, status=400)
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
            reference=reference,
            actor=request.user,
        )
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
            reference,
        )
    return JsonResponse({"quantity": counted_quantity, "previousQuantity": previous_quantity})


@require_POST
def create_supplier_invoice(request):
    data, error = _json_body(request)
    if error:
        return error
    branch, error = _branch_for_user(request, _branch_id(request, data))
    if error:
        return error
    error = _require_roles(request, branch, {"branch_manager"})
    if error:
        return error
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
    purchase_order = None
    if data.get("purchaseOrderId"):
        try:
            purchase_order = PurchaseOrder.objects.get(
                pk=int(data["purchaseOrderId"]),
                branch=branch,
            )
        except (PurchaseOrder.DoesNotExist, ValueError, TypeError):
            return JsonResponse({"detail": "Purchase order does not belong to this branch."}, status=400)
        if purchase_order.supplier.name.casefold() != supplier.casefold():
            return JsonResponse({"detail": "Invoice supplier must match the linked purchase order."}, status=400)
    with transaction.atomic():
        invoice = SupplierInvoice.objects.create(
            branch=branch,
            supplier_record=purchase_order.supplier if purchase_order else None,
            purchase_order=purchase_order,
            supplier=supplier,
            invoice_number=invoice_number,
            invoice_amount=invoice_amount,
            amount_paid=amount_paid,
            due_date=due_date,
            actor=request.user,
        )
        if amount_paid > 0:
            SupplierPayment.objects.create(
                invoice=invoice,
                amount=amount_paid,
                method=method,
                reference=invoice_number,
                actor=request.user,
            )
        _record_audit(request, branch, AuditEvent.Action.CREATED, "supplier_invoice", invoice.pk, _invoice_data(invoice), invoice_number)
    return JsonResponse({"invoice": _invoice_data(invoice)}, status=201)


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
    reference = str(data.get("reference", "")).strip()
    if amount <= 0 or not method or not reference:
        return JsonResponse({"detail": "Enter a positive payment, method, and reference."}, status=400)
    with transaction.atomic():
        try:
            invoice = SupplierInvoice.objects.select_for_update().get(pk=invoice_id, branch=branch)
        except SupplierInvoice.DoesNotExist:
            return JsonResponse({"detail": "Invoice not found."}, status=404)
        if amount > invoice.invoice_amount - invoice.amount_paid:
            return JsonResponse({"detail": "Payment exceeds the remaining invoice balance."}, status=400)
        invoice.amount_paid += amount
        invoice.save(update_fields=["amount_paid"])
        payment = SupplierPayment.objects.create(
            invoice=invoice,
            amount=amount,
            method=method,
            reference=reference,
            actor=request.user,
        )
        _record_audit(request, branch, AuditEvent.Action.PAYMENT_RECORDED, "supplier_invoice", invoice.pk, {"amountPaid": float(invoice.amount_paid)}, reference)
    return JsonResponse({"paymentId": payment.pk}, status=201)


@require_POST
def customer_payment(request, sale_id):
    data, error = _json_body(request)
    if error:
        return error
    branch, error = _branch_for_user(request, _branch_id(request, data))
    if error:
        return error
    try:
        amount = _money(data.get("amount"), "Payment amount")
    except ValueError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    method = str(data.get("method", "")).strip()
    reference = str(data.get("reference", "")).strip()
    if amount <= 0 or not method or not reference:
        return JsonResponse({"detail": "Enter a positive payment, method, and reference."}, status=400)
    with transaction.atomic():
        try:
            sale = Sale.objects.select_for_update().get(pk=sale_id, branch=branch)
        except Sale.DoesNotExist:
            return JsonResponse({"detail": "Sale not found."}, status=404)
        if amount > sale.balance_due:
            return JsonResponse({"detail": "Payment exceeds the outstanding sale balance."}, status=400)
        sale.amount_received += amount
        sale.balance_due -= amount
        sale.save(update_fields=["amount_received", "balance_due"])
        payment = CustomerPayment.objects.create(
            sale=sale,
            amount=amount,
            method=method,
            reference=reference,
            actor=request.user,
        )
        _record_audit(request, branch, AuditEvent.Action.PAYMENT_RECORDED, "sale", sale.pk, {"balanceDue": float(sale.balance_due)}, reference)
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
                    "reference": reference,
                },
            },
        )
    return JsonResponse({"paymentId": payment.pk}, status=201)


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
def barcode_lookup(request):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required."}, status=401)
    value = request.GET.get("value", "").strip()
    if not value:
        return JsonResponse({"detail": "Provide a barcode or SKU."}, status=400)
    product = MedicationProduct.objects.filter(is_active=True).filter(
        models.Q(barcode__iexact=value) | models.Q(barcode_aliases__value__iexact=value) | models.Q(sku__iexact=value)
    ).distinct().first()
    if product is None:
        return JsonResponse({"detail": "No active product matches this barcode or SKU."}, status=404)
    return JsonResponse({
        "product": {
            "sku": product.sku,
            "name": product.name,
            "category": product.category,
            "barcode": product.barcode,
            "requiresPrescription": product.requires_prescription,
            "isControlled": product.is_controlled,
            "controlledSchedule": product.controlled_schedule,
        }
    })


@require_POST
def add_barcode_alias(request):
    data, error = _json_body(request)
    if error:
        return error
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required."}, status=401)
    if not request.user.is_superuser and not request.user.is_staff:
        return JsonResponse({"detail": "Administrator access is required."}, status=403)
    value = str(data.get("value", "")).strip()
    sku = str(data.get("sku", "")).strip()
    try:
        product = MedicationProduct.objects.get(sku=sku, is_active=True)
    except MedicationProduct.DoesNotExist:
        return JsonResponse({"detail": "Active product not found."}, status=404)
    if not value:
        return JsonResponse({"detail": "Barcode value is required."}, status=400)
    alias, created = BarcodeAlias.objects.get_or_create(
        value=value,
        defaults={"product": product, "symbology": str(data.get("symbology", ""))},
    )
    if not created and alias.product_id != product.id:
        return JsonResponse({"detail": "Barcode is already assigned to another product."}, status=409)
    return JsonResponse(
        {"barcode": alias.value, "sku": product.sku, "created": created},
        status=201 if created else 200,
    )


@require_GET
def prescriptions_view(request):
    branch, error = _branch_for_user(request, _branch_id(request))
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
    try:
        line_id = int(data.get("lineId"))
        quantity = _whole_number(data.get("quantity"), "Quantity")
        amount_received = _money(data.get("amountReceived", 0), "Amount received")
    except (ValueError, TypeError):
        return JsonResponse({"detail": "Enter a valid prescription line, quantity, and amount."}, status=400)
    payment_method = str(data.get("paymentMethod", "")).strip()
    reference = str(data.get("reference", "")).strip()
    recipient = str(data.get("patientReference", "")).strip()
    try:
        witness_id = int(data.get("witnessId")) if data.get("witnessId") else None
    except (TypeError, ValueError):
        return JsonResponse({"detail": "Select a valid controlled-medicine witness."}, status=400)
    if quantity <= 0 or not reference or not recipient or not payment_method:
        return JsonResponse({"detail": "Quantity, patient reference, payment method, and dispensing reference are required."}, status=400)

    with transaction.atomic():
        try:
            prescription = Prescription.objects.select_for_update().get(pk=prescription_id, branch=branch)
            line = PrescriptionLine.objects.select_for_update().select_related("product").get(
                pk=line_id,
                prescription=prescription,
            )
        except (Prescription.DoesNotExist, PrescriptionLine.DoesNotExist):
            return JsonResponse({"detail": "Prescription or item not found."}, status=404)
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
                expiry__gte=date.today(),
            )
            .order_by("expiry", "id")
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
            reference=reference,
            actor=request.user,
        )
        if amount_received > 0:
            CustomerPayment.objects.create(
                sale=sale,
                amount=amount_received,
                method=payment_method,
                reference=reference,
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
                reference=reference,
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
        _record_audit(request, branch, AuditEvent.Action.SALE_RECORDED, "prescription_dispense", sale.pk, _sale_data(sale), reference)
        _queue_pos_event(sale)

    return JsonResponse({"sale": _sale_data(sale), "prescription": _prescription_data(prescription)}, status=201)


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
    number = str(data.get("number", "")).strip()
    if not number or not isinstance(lines, list) or not lines:
        return JsonResponse({"detail": "Purchase order number and at least one product line are required."}, status=400)
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
            number=number,
            status=PurchaseOrder.Status.SUBMITTED,
            expected_date=expected_date,
            created_by=request.user,
            submitted_at=timezone.now(),
        )
        PurchaseOrderLine.objects.bulk_create([
            PurchaseOrderLine(
                purchase_order=order,
                product=product,
                quantity_ordered=quantity,
                unit_cost=cost,
            )
            for product, quantity, cost in parsed
        ])
        _record_audit(request, branch, AuditEvent.Action.CREATED, "purchase_order", order.pk, {"status": order.status}, number)
    return JsonResponse({"id": order.pk, "number": order.number, "status": order.status}, status=201)


@require_GET
def purchase_orders_view(request):
    branch, error = _branch_for_user(request, _branch_id(request))
    if error:
        return error
    orders = PurchaseOrder.objects.filter(branch=branch).select_related("supplier").prefetch_related("lines__product")
    return JsonResponse({"purchaseOrders": [
        {
            "id": order.id,
            "number": order.number,
            "supplierId": order.supplier_id,
            "supplier": order.supplier.name,
            "status": order.status,
            "expectedDate": order.expected_date.isoformat() if order.expected_date else "",
            "lines": [
                {
                    "id": line.id,
                    "sku": line.product.sku,
                    "name": line.product.name,
                    "quantityOrdered": line.quantity_ordered,
                    "quantityReceived": line.quantity_received,
                    "unitCost": float(line.unit_cost),
                    "isControlled": line.product.is_controlled,
                }
                for line in order.lines.all()
            ],
        }
        for order in orders
    ]})


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
                expiry = date.fromisoformat(receipt.get("expiry", ""))
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
    rows = []
    products = MedicationProduct.objects.filter(is_active=True).prefetch_related("batches")
    for product in products:
        batches = [batch for batch in product.batches.all() if batch.branch_id == branch.id]
        if not batches:
            continue
        total = sum(batch.quantity for batch in batches if batch.expiry >= date.today())
        level = max(batch.reorder_level for batch in batches)
        if total <= level:
            preferred = product.supplier_options.filter(
                is_preferred=True,
                supplier__is_active=True,
            ).select_related("supplier").first()
            rows.append({
                "sku": product.sku,
                "name": product.name,
                "onHand": total,
                "reorderLevel": level,
                "suggestedQuantity": max(0, level * 2 - total),
                "supplierId": preferred.supplier_id if preferred else None,
                "supplier": preferred.supplier.name if preferred else "",
                "unitCost": float(preferred.unit_cost) if preferred else None,
            })
    return JsonResponse({"suggestions": rows})


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
    total = sum(batch.quantity for batch in batches if batch.expiry >= date.today())
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
        number=f"RO-{branch.code}-{timezone.now():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}",
        status=PurchaseOrder.Status.DRAFT,
        created_by=request.user,
    )
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
        order = PurchaseOrder.objects.get(pk=order_id, branch=branch)
    except PurchaseOrder.DoesNotExist:
        return JsonResponse({"detail": "Purchase order not found."}, status=404)
    if order.status != PurchaseOrder.Status.DRAFT:
        return JsonResponse({"detail": "Only draft orders can be submitted."}, status=409)
    order.status = PurchaseOrder.Status.SUBMITTED
    order.submitted_at = timezone.now()
    order.save(update_fields=["status", "submitted_at"])
    _record_audit(request, branch, AuditEvent.Action.UPDATED, "purchase_order", order.pk, {"status": order.status}, order.number)
    return JsonResponse({"id": order.pk, "status": order.status})


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
    reference = str(data.get("reference", "")).strip()
    if not reference or not isinstance(lines, list) or not lines:
        return JsonResponse({"detail": "Transfer reference and at least one item are required."}, status=400)
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
        source_batch = MedicineBatch.objects.filter(
            branch=source,
            product=product,
            quantity__gte=quantity,
            expiry__gte=date.today(),
        ).order_by("expiry", "id").first()
        if source_batch is None:
            return JsonResponse(
                {"detail": f"No single eligible lot can fulfill the transfer for {product.sku}."},
                status=400,
            )
        seen.add(product.pk)
        parsed.append((product, quantity, source_batch))
    transfer = BranchTransfer.objects.create(
        source_branch=source,
        destination_branch=destination,
        reference=reference,
        requested_by=request.user,
    )
    transfer.lines.bulk_create([
        BranchTransferLine(
            transfer=transfer,
            product=product,
            source_batch=source_batch,
            quantity_dispatched=quantity,
        )
        for product, quantity, source_batch in parsed
    ])
    _record_audit(request, source, AuditEvent.Action.CREATED, "branch_transfer", transfer.pk, {"destination": destination.code}, reference)
    return JsonResponse({"id": transfer.pk, "status": transfer.status}, status=201)


@require_GET
def transfers_view(request):
    branch, error = _branch_for_user(request, _branch_id(request))
    if error:
        return error
    transfers = BranchTransfer.objects.filter(
        models.Q(source_branch=branch) | models.Q(destination_branch=branch)
    ).select_related("source_branch", "destination_branch").prefetch_related("lines__product", "lines__source_batch")
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
                    "quantityDispatched": line.quantity_dispatched,
                    "quantityReceived": line.quantity_received,
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
            if batch.quantity < line.quantity_dispatched or batch.expiry < date.today():
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
        if transfer.status != BranchTransfer.Status.DISPATCHED:
            return JsonResponse({"detail": "Only dispatched transfers can be received."}, status=409)
        lines = list(transfer.lines.select_related("product", "source_batch").all())
        batch_names = []
        batch_map = data.get("batches", {})
        if not isinstance(batch_map, dict):
            return JsonResponse({"detail": "Batch names must be provided as a line-to-batch map."}, status=400)
        for line in lines:
            requested_batch = str(batch_map.get(str(line.id), line.source_batch.batch)).strip()
            if not requested_batch:
                return JsonResponse({"detail": "Destination lot numbers cannot be blank."}, status=400)
            batch_names.append(requested_batch.casefold())
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
        for line in lines:
            requested_batch = str(batch_map.get(str(line.id), line.source_batch.batch)).strip()
            source = line.source_batch
            batch = MedicineBatch.objects.create(
                branch=branch,
                product=line.product,
                batch=requested_batch,
                quantity=line.quantity_dispatched,
                reorder_level=source.reorder_level,
                expiry=source.expiry,
                supplier=source.supplier,
                reference=transfer.reference,
                purchase_cost=source.purchase_cost,
                selling_price=source.selling_price,
            )
            line.destination_batch = batch
            line.quantity_received = line.quantity_dispatched
            line.save(update_fields=["destination_batch", "quantity_received"])
            movement = StockMovement.objects.create(
                branch=branch,
                batch=batch,
                type=StockMovement.Type.TRANSFER_IN,
                quantity=line.quantity_received,
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
        transfer.status = BranchTransfer.Status.RECEIVED
        transfer.received_by = request.user
        transfer.received_at = timezone.now()
        transfer.save(update_fields=["status", "received_by", "received_at"])
        _record_audit(request, branch, AuditEvent.Action.STOCK_ADJUSTED, "branch_transfer", transfer.pk, {"status": transfer.status}, transfer.reference)
    return JsonResponse({"id": transfer.pk, "status": transfer.status})


@require_GET
def analytics_report(request):
    branch, error = _branch_for_user(request, _branch_id(request))
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
    sales = Sale.objects.filter(branch=branch, recorded_at__date__gte=start, recorded_at__date__lte=end)
    return JsonResponse({
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "summary": {
            "movementCount": len(movement_data),
            "unitsReceived": sum(row["quantity"] for row in movement_data if row["quantity"] > 0),
            "unitsIssued": -sum(row["quantity"] for row in movement_data if row["quantity"] < 0),
            "salesCount": sales.count(),
            "salesAmount": float(sum(sales.values_list("sale_amount", flat=True), Decimal("0.00"))),
            "grossProfit": float(sum((sale.sale_amount - sale.cost_amount for sale in sales), Decimal("0.00"))),
            "outstandingBalance": float(sum(Sale.objects.filter(branch=branch).values_list("balance_due", flat=True), Decimal("0.00"))),
        },
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