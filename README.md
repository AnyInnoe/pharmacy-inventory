# Pharmacy Inventory Management System

A branch-aware pharmacy operations application for managing medicine and skin-care products, lot-level inventory, sales, dispensing, purchasing, and operational reports. It includes a Django backend and a React dashboard.

> **Important:** This project is an operational software tool, not a guarantee of legal, clinical, accounting, or regulatory compliance. Have qualified local stakeholders review dispensing workflows, controlled-medicine policies, privacy practices, and deployment before using it with live data.

## Features

- Branch-scoped access with cashier, pharmacist, branch-manager, and administrator roles.
- Medicine and skin-care catalog with automatically generated product SKUs.
- Lot-level inventory, receiving, expiry tracking, stock counts, adjustments, and FEFO (first-expiry-first-out) allocation.
- Ordinary sales and payments, plus separate prescription and controlled-medicine workflows.
- Suppliers, purchase orders, receiving, invoice reconciliation, supplier payments, and branch transfers.
- Operational reports, audit history, controlled-medicine register, and manager-reviewed replenishment forecasts.
- PDF sale receipts and internal supplier-invoice reconciliation documents.
- Optional queued email notifications.
- Offline app-shell/catalog access and queued ordinary-sale drafts in the browser. Drafts are validated by the server after reconnection; they do not reserve stock or record payment.

There are no live POS, insurance, billing, or patient-management integrations. Prescription and controlled-medicine dispensing, approvals, and stock adjustments require an online connection.

## Technology

- **Backend:** Python, Django 6.1, SQLite for local development; PostgreSQL is configurable for deployment.
- **Frontend:** React 19, Vite 8.
- **PDFs:** ReportLab.

## Project layout

```text
.
├── api/                 # Django application, API, models, and tests
├── backend/             # Django project configuration and manage.py
├── docs/                # Requirements, wireframe, and deployment notes
└── frontend/            # React/Vite dashboard
```

## Requirements

- Python 3.12 or newer (the backend uses Django 6.1).
- Node.js and npm.

## Local development

The commands below use PowerShell on Windows. Activate the virtual environment in each backend terminal before running Django commands.

### 1. Set up the backend

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install "Django>=6.1,<6.2" -r .\backend\requirements.txt
python .\backend\manage.py migrate
python .\backend\manage.py createsuperuser
python .\backend\manage.py runserver 127.0.0.1:8000
```

The development configuration uses SQLite by default and creates the local database when migrations are applied. The Django admin is available at <http://127.0.0.1:8000/admin/>.

Sign in to Django admin to create an active branch and assign an active branch membership to the user who will use the dashboard. Choose only the role and permissions that user needs. A superuser can access administration, but needs a branch membership to carry out branch operations.

### 2. Set up the frontend

In a second terminal, from the repository root:

```powershell
Set-Location .\frontend
npm install
npm run dev
```

Open the local URL printed by Vite (normally <http://localhost:5173/>). In development, Vite forwards `/api` requests to `http://127.0.0.1:8000`.

### macOS/Linux equivalents

From the repository root, create and activate a virtual environment, then install dependencies and migrate:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install "Django>=6.1,<6.2" -r backend/requirements.txt
python backend/manage.py migrate
python backend/manage.py createsuperuser
python backend/manage.py runserver 127.0.0.1:8000
```

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

## Tests and checks

Run the backend test suite from the repository root:

```bash
python backend/manage.py test
```

Run frontend linting and create a production build from `frontend/`:

```bash
npm run lint
npm run build
```

## Offline behavior and data handling

After an online sign-in and branch load, the browser can retain the app shell and active-branch catalog for temporary connectivity loss. Cashiers may queue eligible ordinary-sale drafts on that device. A queued draft is not a completed sale: it does not reserve stock or confirm payment, and the server validates it after reconnection. Some drafts may be rejected and require review.

Offline drafts contain sale details. Use offline access only on access-controlled pharmacy devices, not shared or public browser profiles. Prescription and controlled-medicine dispensing, approvals, stock adjustments, and other restricted operations remain online-only. Cached stock may be stale; offline access is not a substitute for a reliable backend or backups.

## Deployment

The Django development server is for local development only and must not be exposed publicly. Production deployment requires explicit configuration for secrets, allowed hosts, database, HTTPS, static files, backups, and operational monitoring.

See the [PostgreSQL deployment guide](docs/POSTGRESQL-DEPLOYMENT.md) for production configuration and release steps. It describes PostgreSQL support, but migrating existing SQLite data to PostgreSQL requires a separate, planned, and verified data migration. See the [project wireframe](docs/PROJECT-WIREFRAME.md) for workflow boundaries and delivery status, and the [stakeholder requirements](docs/STAKEHOLDER-REQUIREMENTS.md) for scope and acceptance considerations.

If email notifications are enabled, configure an SMTP relay and schedule the `send_email_notifications` Django management command. A queued message is not proof of delivery.

DEMO LOGIN DETAILS (USE THIS TO TEST)
Admin Account:
Username: admin
Password: password
Pharmacist Account:
Username: pharmacist1
Password: password@pharm
Cashier Account:
Username: cashier1
Password: password@cash

## License

No license is currently specified. Unless a license is added to this repository, reuse and redistribution are not granted by this README.
