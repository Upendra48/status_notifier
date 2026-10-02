# Development Notes

## Django primary-key warning (models.W042)

Django creates an `id` primary key when a model does not declare one. Warning
W042 means the active app configuration would use the older 32-bit
`AutoField`. Set `DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'` in
settings, or set `default_auto_field = 'django.db.models.BigAutoField'` on an
app's `AppConfig`, to use 64-bit IDs by default.

This project already sets `DEFAULT_AUTO_FIELD` to `BigAutoField`, and its
initial migration uses `BigAutoField` for the monitor models. The project-local
`python manage.py check` currently reports no issues. If changing an existing
project from `AutoField`, review and apply the migration Django generates; do
not edit an already-applied migration by hand.

Verify with:

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
```

## Database connections

The monitoring application stores its own agencies, runs, and checks in the
default SQLite database (`db.sqlite3`). An optional `smi` MySQL connection is
configured from `SMI_DB_*` environment variables. Copy `.env.example` to
`.env`, set a private `DJANGO_SECRET_KEY`, then fill in `SMI_DB_NAME`,
`SMI_DB_USER`, `SMI_DB_PASSWORD`, and `SMI_DB_HOST` to enable it.
`SMI_DB_PORT` defaults to `3306`.

Keep `.env` out of version control and never put database passwords in source
files. The SMI alias only configures a connection; source tables and columns
must be identified before importing agency names, URLs, or broken status.