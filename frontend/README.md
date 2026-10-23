# Pharmacy inventory frontend

React and Vite dashboard for the Django pharmacy inventory API.

## Local development

1. Start the Django API from the repository root:

   ```powershell
   .\.venv314\Scripts\python.exe .\backend\manage.py migrate
   .\.venv314\Scripts\python.exe .\backend\manage.py runserver 127.0.0.1:8001
   ```

2. Create a Django administrator and at least one active branch. Assign the
   user an active branch membership in Django admin, or sign in as a superuser.

3. In another terminal:

   ```powershell
   Set-Location .\frontend
   npm.cmd install
   npm.cmd run dev
   ```

   Vite proxies `/api` requests to `http://127.0.0.1:8001`.

## Validation

Run `npm.cmd run lint` and `npm.cmd run build` from this directory. Run backend
tests from the repository root with
`.\.venv314\Scripts\python.exe .\backend\manage.py test`.

## Production note

The Django settings currently use development defaults. Before deployment,
configure secrets, `DEBUG`, allowed hosts, HTTPS/secure cookies, database
backups, static files, logging, and environment-specific CSRF trusted origins.
See [the project wireframe](../docs/PROJECT-WIREFRAME.md) for planned modules
and capabilities that are not yet implemented.
