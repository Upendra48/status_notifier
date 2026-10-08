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
default SQLite database (`db.sqlite3`). An optional `smi` MySQL connection can
be enabled for the source agency data. Copy `.env.example` to `.env`, set a
private `DJANGO_SECRET_KEY`, then fill in `SMI_DB_NAME`, `SMI_DB_USER`,
`SMI_DB_PASSWORD`, and `SMI_DB_HOST`. `SMI_DB_PORT` defaults to `3306`.
The alias is added only when at least one `SMI_DB_*` variable is supplied;
once enabled, all four required values must be provided. The installed
`mysqlclient` dependency provides Django's MySQL driver.

Verify Django loads the settings with:

```powershell
python manage.py check
```

To test access to the configured source database, use:

```powershell
python manage.py check --database smi
```

Keep `.env` out of version control and never put database passwords in source
files. The SMI alias only configures a connection; source tables and columns
must be identified before importing agency names, URLs, or broken status.

## Scheduling daily agency checks

The `check_agencies` management command checks the URLs in
`monitors/site.json` and records the results. Run it manually from the project
directory to verify the setup:

```powershell
.\.venv\Scripts\python.exe manage.py check_agencies
```

### Windows Task Scheduler

1. Create a `logs` directory in the project directory.
2. Open **Task Scheduler** and choose **Create Basic Task** (or **Create Task**
   for additional settings). Choose **Daily** and set the desired morning time.
3. For the action, choose **Start a program** and use:
   - **Program/script:** `C:\path\to\new_bid_notifier\.venv\Scripts\python.exe`
   - **Add arguments:** `manage.py check_agencies`
   - **Start in:** `C:\path\to\new_bid_notifier`
4. To append standard output and errors to a log file, use `cmd.exe` for the
   program instead:
   - **Program/script:** `%SystemRoot%\System32\cmd.exe`
   - **Add arguments:**
     ```text
     /d /c ""C:\path\to\new_bid_notifier\.venv\Scripts\python.exe" manage.py check_agencies >> "C:\path\to\new_bid_notifier\logs\check_agencies.log" 2>&1"
     ```
   - **Start in:** `C:\path\to\new_bid_notifier`

Replace `C:\path\to\new_bid_notifier` with the actual project directory. Ensure
the Windows account that runs the task can read the project and `.env`, write
to `logs` and the database, and access the network. In Task Scheduler, enable
**Run whether user is logged on or not** if it should run when you are signed
out.

### Render Cron Job

Create a **Cron Job** in Render for this repository, select the project’s
runtime/build setup, and set the command to:

```sh
python manage.py check_agencies
```

Choose a daily schedule for the desired morning time. Render cron schedules
use UTC, so convert from the desired local timezone (and account for daylight
saving changes where applicable). Add the same required environment variables
as the deployed Django app; at minimum this project requires
`DJANGO_SECRET_KEY`. Do not commit the secret to the repository.

Render captures the command’s standard output and errors in the Cron Job logs.
Unlike the local Task Scheduler setup, writing a log file in a Render job’s
filesystem does not provide durable storage across executions. Use Render’s
job logs for routine review, or configure external/persistent log storage if a
durable file is required. Also configure the project to use a persistent
database shared with the deployed app before relying on scheduled results:
the current default database is local SQLite (`db.sqlite3`), which is not
shared with another service and is not durable on Render’s ephemeral
filesystem.