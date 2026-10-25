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

3. In another terminal:

   ```powershell
   Set-Location .\frontend
   npm.cmd install
   npm.cmd run dev
   ```

   Vite proxies `/api` requests to `http://127.0.0.1:8000`.

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
