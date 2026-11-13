# Pharmacy inventory frontend

React and Vite dashboard for the Django pharmacy inventory API.

## Local development

1. Start the Django API from the repository root:

   ```powershell
   .\.venv314\Scripts\python.exe .\backend\manage.py migrate
   .\.venv314\Scripts\python.exe .\backend\manage.py runserver 127.0.0.1:8000
   ```

2. Create a Django administrator and at least one active branch. Assign the
   user an active branch membership in Django admin, or sign in as a superuser.
   Branch memberships support cashier, pharmacist, and branch-manager roles.
   Cashier sales stay pending until a pharmacist or branch manager approves
   them; approval records payment and reduces stock. Assign users only the
   branch roles and permissions they need.

3. In another terminal:

   ```powershell
   Set-Location .\frontend
   npm.cmd install
   npm.cmd run dev
   ```

   Vite proxies `/api` requests to `http://127.0.0.1:8000`.

   ## Offline behavior

   The production frontend caches its app shell. After signing in and loading a
   branch while connected, the same browser session can view cached inventory and
   catalog data if the connection drops. Cashiers can queue ordinary POS sale
   drafts on the device; drafts sync with the server when reconnected and still
   require pharmacist or manager approval. They do not reserve stock or record
   payments. Stock adjustments, approvals, prescriptions, and controlled-medicine
   dispensing remain online-only. Offline drafts contain sale details, so use only
   on access-controlled pharmacy devices; do not use shared/public browser
   profiles. The browser's connectivity indicator is not a guarantee that the
   backend is available; use “Retry connection” to test it.

## Validation

Run `npm.cmd run lint` and `npm.cmd run build` from this directory. Run backend
tests from the repository root with
`.\.venv314\Scripts\python.exe .\backend\manage.py test`.

## Production deployment

See [the PostgreSQL deployment guide](../docs/POSTGRESQL-DEPLOYMENT.md) for
backend dependency installation, PostgreSQL configuration, production security
settings, migrations, static files, and operational requirements. The Django
development server is for local use only.

See [the project wireframe](../docs/PROJECT-WIREFRAME.md) for the implemented
internal workflows, jurisdiction and integration boundaries, and remaining
release limitations.
