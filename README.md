# Bid Monitor

Bid Monitor checks agency procurement pages, stores a daily result, and
provides a dashboard at `/`. The existing `bids` table is the read-only source
of agency URLs and spider health; check results and daily history are stored
separately.

## Database connections

The monitoring application uses the local MySQL/MariaDB database `bid_status`
served by XAMPP (`localhost:3306`). Django reads the database connection from
`DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, and `DB_PORT` in
`.env`. The expected local values are `django.db.backends.mysql`, `bid_status`,
`root`, an empty password, `localhost`, and `3306`.

Create the database in XAMPP:

1. Start **MySQL** in the XAMPP Control Panel.
2. Open `http://localhost/phpmyadmin`, select **SQL**, and execute:

   ```sql
   CREATE DATABASE IF NOT EXISTS bid_status
     CHARACTER SET utf8mb4
     COLLATE utf8mb4_unicode_ci;
   ```

3. From the project directory, apply the Django migrations:

   ```powershell
   .\.venv\Scripts\python.exe manage.py migrate
   ```

These migrations create the internal `AgencyMonitor`, `MonitorRun`, and
`AgencyCheck` tables used for selectors and report history. Add monitored sites
to the existing `bids` table with their `ecgains`, `agency_name`, and
`agency_url`. The monitoring command treats `bids` as read-only and does not
change any of its fields, including `broken`. It writes the check outcome into
the matching `bid_status` row, creating one if necessary. It stores `SUCCESS`
or `ERROR` in `spider_status` and `ACTIVE`, `NO_BID`, `UNKNOWN`, or `ERROR` in
`active_status`, plus the check time and error detail. Repair request fields
are left unchanged.

For example, add a site in phpMyAdmin with:

```sql
INSERT INTO bids (ecgains, agency_name, agency_url)
VALUES ('your-ecgains-id', 'Agency Name', 'https://agency.example/bids');
```

Replace the example values with the actual EC Gains identifier, agency name,
and bid-listing URL.

This project is pinned to Django 4.2.30 because the XAMPP MariaDB version
currently in use is 10.4.32. Django 4.2 supports MariaDB 10.4, but Django 4.2
reached end of security support in April 2026. Keep this configuration local
only; upgrade MariaDB to 10.11 or later before deploying or exposing the app.

Optional `brk_db` and `smi` MySQL connections are read from their corresponding
`BRK_DB_*` and `SMI_DB_*` variables when configured. These aliases remain
separate from the local default database. The installed `mysqlclient`
dependency provides Django's MySQL driver.

Verify Django loads the settings with:

```powershell
.\.venv\Scripts\python.exe manage.py check
```

To test that Django can connect to XAMPP, use:

```powershell
.\.venv\Scripts\python.exe manage.py check --database default
```

Keep `.env` out of version control and never put database passwords in source
files. A local XAMPP database is only accessible to processes on that machine;
Render deployments need their own reachable hosted database configuration.

### Report categories

The daily report at `/` displays the decision-table results without sending
email or other notifications:

- **Active bids on broken spiders:** `ACTIVE` and broken at check time.
- **Broken spiders needing review:** `UNKNOWN` or `ERROR` and broken at check
  time.
- **No-bid sites:** `NO_BID`, regardless of broken status.
- **Logged only:** `ACTIVE` on a healthy spider, or `UNKNOWN`/`ERROR` on a
  healthy spider.

The `bids` table remains read-only. The daily command saves the page result in
`bid_status` and a check snapshot in the monitoring tables; the report groups
results using the spider broken value captured for each check.

## Scheduling daily agency checks

The `check_agencies` management command checks each row in the `bids` table
and records the results for the daily report. Run it manually from the project
directory after adding sites:

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
durable file is required. Configure a hosted persistent database reachable
from Render before relying on scheduled results; a local XAMPP database cannot
be accessed by the Render job.