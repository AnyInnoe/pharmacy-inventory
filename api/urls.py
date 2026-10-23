from django.urls import path

from . import views

urlpatterns = [
    path("auth/csrf/", views.csrf_token, name="csrf-token"),
    path("auth/login/", views.login_view, name="login"),
    path("auth/logout/", views.logout_view, name="logout"),
    path("auth/me/", views.current_user, name="current-user"),
    path("branches/", views.branches_view, name="branches"),
    path("data/", views.dashboard_data, name="dashboard-data"),
    path("batches/", views.create_batch, name="create-batch"),
    path("dispense/", views.dispense_stock, name="dispense-stock"),
    path("stock-count/", views.stock_count, name="stock-count"),
    path("supplier-invoices/", views.create_supplier_invoice, name="create-supplier-invoice"),
    path(
        "supplier-invoices/<int:invoice_id>/payments/",
        views.supplier_payment,
        name="supplier-payment",
    ),
    path("sales/<int:sale_id>/payments/", views.customer_payment, name="customer-payment"),
]