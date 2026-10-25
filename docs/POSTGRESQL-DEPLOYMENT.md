# PostgreSQL deployment

The Django API uses SQLite by default for local development. Set `DATABASE_URL`
or the `DB_*` variables to use PostgreSQL. Production startup requires
PostgreSQL, a secret key, and explicit allowed hosts; it will not silently fall
back to SQLite.

## Dependencies

Install the backend dependencies from the repository root:

```powershell
.\.venv314\Scripts\python.exe -m pip install -r .\backend\requirements.txt
```

Use a supported PostgreSQL release for the deployed Django version. Create a
dedicated database and application role, grant that role only the permissions
the application needs, and keep database credentials in the deployment
platform's secret manager. Do not commit a populated environment file.

## Configuration

Set these environment variables in the application service:

| Variable | Required | Description |
| --- | --- | --- |
| `DJANGO_DEBUG` | Production | Set to `false`. |
| `DJANGO_SECRET_KEY` | Production | Long, unique secret generated and stored outside source control. |
| `DJANGO_ALLOWED_HOSTS` | Production | Comma-separated hostnames serving the API, without URL schemes. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | As needed | Comma-separated full frontend origins, including `https://`. |
| `DATABASE_URL` | Yes, unless using `DB_NAME` | PostgreSQL URL, e.g. `postgresql://user:password@db-host:5432/pharmacy`. URL-encode reserved characters in credentials. |
| `DB_SSLMODE` | Recommended | PostgreSQL TLS mode. Defaults to `require` in production; use `verify-full` with the provider's CA configuration when available. |
| `DB_CONN_MAX_AGE` | No | Persistent connection lifetime in seconds; defaults to `60`. |
| `DB_CONNECT_TIMEOUT` | No | Connection timeout in seconds; defaults to `10`. |
| `EMAIL_HOST` | If using email | SMTP relay hostname. |
| `EMAIL_PORT` | No | SMTP port; defaults to `587`. |
| `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | As needed | SMTP credentials, stored as deployment secrets. |
| `EMAIL_USE_TLS`, `EMAIL_USE_SSL` | No | SMTP transport security; TLS defaults to enabled in production. Enable at most one. |
| `EMAIL_TIMEOUT` | No | SMTP connection timeout in seconds; defaults to `10`. |
| `DJANGO_SECURE_SSL_REDIRECT` | No | Defaults to `true`. Set `DJANGO_TRUST_PROXY_SSL_HEADER=true` only when the app is reachable exclusively through a trusted TLS-terminating proxy that sets `X-Forwarded-Proto`. |
| `DJANGO_SECURE_HSTS_SECONDS` | No | HSTS duration; defaults to one year. |
| `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS` | No | Defaults to `false`; enable only when every subdomain is permanently HTTPS-only. |

Alternatively, configure `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, and
`DB_PORT` (default `5432`) instead of `DATABASE_URL`. `DB_SSLMODE` applies to
both configuration styles.

## Release and startup

Run these commands as part of a controlled release, not automatically in every
web worker startup:

```powershell
.\.venv314\Scripts\python.exe .\backend\manage.py check --deploy
.\.venv314\Scripts\python.exe .\backend\manage.py migrate --noinput
.\.venv314\Scripts\python.exe .\backend\manage.py collectstatic --noinput
```

Run the ASGI or WSGI application with a production process manager and configure
the platform's liveness/readiness checks, resource limits, and graceful
shutdown. Restrict database network access to the application and operations
services. Establish and regularly test encrypted, off-site backups and restore
procedures before storing operational data. Keep Django, PostgreSQL, and
dependencies patched; review `check --deploy` output for the actual hosting
topology. Do not expose Django's development server to the public internet.

`check --deploy` may report `security.W005` because HSTS subdomain coverage is
disabled by default, and `security.W021` because HSTS preload is not enabled.
Enable subdomain coverage only after confirming every subdomain is HTTPS-only;
enable preload only after validating Django's preload requirements and your
long-term domain policy. Configure SMTP variables if email is enabled by a
future feature.

The application does not automatically migrate existing SQLite records to
PostgreSQL. Plan and verify a separate data migration before switching a live
installation.
