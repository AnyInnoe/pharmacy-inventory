import json
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib.auth import authenticate, login, logout
from django.db import transaction
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

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
        StockMovement.objects.create(
            branch=branch,
            batch=batch,
            type=StockMovement.Type.RECEIVED,
            quantity=quantity,
            supplier=supplier,
            reference=reference,
            actor=request.user,
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
        previous_quantity = batch.quantity
        batch.quantity = counted_quantity
        batch.save(update_fields=["quantity", "updated_at"])
        StockMovement.objects.create(
            branch=branch,
            batch=batch,
            type=StockMovement.Type.STOCK_COUNT,
            quantity=difference,
            recipient=reason,
            reason=reason,
            reference=reference,
            actor=request.user,
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
    with transaction.atomic():
        invoice = SupplierInvoice.objects.create(
            branch=branch,
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
    return JsonResponse({"paymentId": payment.pk}, status=201)


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