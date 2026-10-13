# Aurorah CAN Digital Hub

Aurorah CAN Digital Hub is a community support platform built to connect beneficiaries, donors, volunteers, and administrators in one place. It helps simplify assistance requests, donation tracking, volunteer onboarding, and public impact updates for community-driven organizations.

## Key Features

- Request assistance through a structured, privacy-aware beneficiary form
- Accept monetary and in-kind donations with targeting and tax-certificate support
- Register and track volunteers by skills, availability, and assigned tasks
- Publish updates and impact stories through a news and announcements feed
- Manage operations from a secure admin dashboard with login, data review, and exports
- Generate PDF reports and Section 18A tax certificates for donor records
- Provide responsive, keyboard-operable public navigation, reduced-motion support, and accessible form feedback

## Tech Stack

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?logo=fastapi&logoColor=white)
![SQLModel](https://img.shields.io/badge/SQLModel-ORM-FF6F61)
![SQLite](https://img.shields.io/badge/SQLite-Database-003B57?logo=sqlite&logoColor=white)
![Jinja2](https://img.shields.io/badge/Jinja2-Templates-B41717)
![ReportLab](https://img.shields.io/badge/ReportLab-PDF-FF6B35)

- Python 3.11+
- FastAPI for the web API and app routing
- SQLModel + SQLite for data persistence
- Jinja2 templates for server-rendered pages
- HTML, CSS, and JavaScript for the frontend experience
- ReportLab for PDF report generation

## Prerequisites

Before you begin, make sure you have the following installed:

- Python 3.11 or newer
- pip (Python package manager)
- Git
- A terminal or shell with access to the project folder

Optional but recommended:

- A virtual environment manager such as `venv`
- VS Code or another IDE for local development

The app uses a local SQLite database. No external cloud credentials are required for the default local setup, but a secret key must be set before the server starts; no default administrator account or secret is included.

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/your-username/aurorah-can-digital-hub.git
cd aurorah-can-digital-hub
```

### 2. Create and activate a virtual environment

On Windows PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

On macOS/Linux:

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the application

Create a local `.env` file with a randomly generated application secret:

```powershell
@"
APP_SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
COOKIE_SECURE=false
"@ | Set-Content .env
```

On macOS/Linux:

```bash
cat > .env <<EOF
APP_SECRET_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(48))')
COOKIE_SECURE=false
EOF
```

The app loads `.env` automatically for local development. Keep this file private; it is excluded from Git.
For production, set `APP_SECRET_KEY` and `COOKIE_SECURE=true` in the deployment environment instead.
```bash
uvicorn main:app --reload
```

Then open the app in your browser at:

```text
http://127.0.0.1:8000
```

The app creates the SQLite database and required tables if they do not already exist.
Startup adds five supplied Aurorah community stories when their slugs are not already present, attaches their supplied local images, removes the duplicate “A Win Worth Celebrating” story, preserves missing original publication dates, and converts old internal-need placeholder contact values to empty values. Older news records keep their existing creation date as the publication date.
Back up an existing `aurorah.db` before the first upgraded launch; startup applies additive schema changes and a narrowly scoped legacy-data cleanup.

### Website accounts

Visitors can browse without signing in, and guest donation pledges are allowed with an optional email address. Requesting assistance or applying to volunteer requires a website account. Create an account at `/account/register`, sign in at `/account/login`, and sign out from the site navigation. Account passwords must be at least 12 characters; sessions use HTTP-only cookies and expire after 12 hours. Website accounts are separate from staff accounts and cannot access the admin workspace.

### Android mobile API

The Android app and website use this FastAPI service and the same configured database; the mobile app must not connect directly to SQLite or SQL Server. The JSON API uses the `/api` prefix:

| Endpoint | Authentication | Purpose |
| --- | --- | --- |
| `POST /api/auth/register` | Public | Create a regular user account (`fullName`, `email`, `password`; password minimum 12 characters). Any submitted `role` is ignored. |
| `POST /api/auth/login` | Public | Sign in with email and password. |
| `POST /api/auth/google-sso` | Public | Verify a Firebase ID token and sign in or create a regular user account. |
| `POST /api/auth/change-password` | Bearer token | Change the signed-in user's password (`email`, `oldPassword`, `newPassword`). |
| `GET /api/news` | Public | Return published news items. |
| `GET /api/needs` | Public | Return open, public community needs without beneficiary contact details. |
| `POST /api/needs/offer-assistance` | Bearer token | Submit an offer for an open community need (`needId`, `userEmail`, `volunteerSkill`, `notes`). |
| `POST /api/donations` | Bearer token | Record a monetary donation pledge (`category`, `amount`, `paymentMethod`, `userEmail`). |

Successful sign-in and registration responses include `success`, `message`, `token`, and a `user` object. Send the token on protected requests as `Authorization: Bearer <token>`; mobile sessions expire after 12 hours. Account roles are assigned by the server, never trusted from the app. Failed or malformed requests return HTTP error responses.

Google sign-in accepts a **Firebase ID token** in the JSON field `idToken` (not a raw Google ID token). Set `FIREBASE_PROJECT_ID` to the Firebase project used by Android, and configure Application Default Credentials for the website process. In local development, this can be done with `GOOGLE_APPLICATION_CREDENTIALS` pointing to a private service-account JSON file; in production, prefer the hosting platform's attached service identity. Keep credential files outside Git and never put credentials in Android, website JavaScript, or chat. Google sign-in returns a clear service-unavailable error until this configuration and the `firebase-admin` dependency are available.

Mobile donation submissions are **pledges only**. The website currently has no online payment processor: `paymentMethod` is not used to charge or verify a payment, and the API response explicitly says no payment was processed. Donations remain unverified until staff handle them through the existing admin workflow. Offers to help are saved with `Pending` status; staff with community-needs access can review them in Admin → Needs and mark them reviewed.

### Connect to Azure SQL Server

The website connects to its database from the FastAPI backend; `base.html` must not connect directly to SQL Server. SQLite remains the default for local development. To use the Azure database, install the SQL Server adapter and the Microsoft ODBC Driver 18 for SQL Server on the machine running the app:

```powershell
pip install -r requirements-sqlserver.txt
```

Add these settings to the private `.env` file (or the deployment's secret environment). Replace the username and password with a dedicated website database login; do not use the shared server administrator account:

```dotenv
DATABASE_BACKEND=sqlserver
DATABASE_AUTO_CREATE_SCHEMA=false
MSSQL_SERVER=aurorah-sql-server.database.windows.net
MSSQL_DATABASE=aurorah-db
MSSQL_USERNAME=your-website-database-login
MSSQL_PASSWORD=your-website-database-password
MSSQL_DRIVER=ODBC Driver 18 for SQL Server
```

For a new, empty database, initialize the tables once with a schema-provisioning login: temporarily set `DATABASE_AUTO_CREATE_SCHEMA=true`, run `python -c "from app.db.session import create_db_and_tables; create_db_and_tables()"`, then switch it back to `false` and configure the restricted website login. The website login should have only the data permissions it needs; keep schema-owner/admin credentials out of the running website. Schema initialization does not migrate records from `aurorah.db`.

When upgrading an existing SQL Server database, rerun the one-time schema setup with `DATABASE_AUTO_CREATE_SCHEMA=true` and a schema-provisioning login before starting the app with the restricted website login. This creates missing tables and applies additive schema updates, including the news publication-date field; it does not migrate SQLite records.

Allow the app machine's outbound IP address in the Azure SQL firewall. The IP auto-added when connecting through SSMS is your workstation's IP; it does not automatically allow a separately hosted website. Keep all database credentials in `.env` or a hosting secret store—never in templates, frontend JavaScript, or Git.

## Staff Accounts

There are no built-in or shared admin credentials. Create an individual account from the project directory. For the first account, replace the example email and name with the administrator's details:

```bash
python -m app.manage_staff create staff@example.org "Staff Member"
```

The command securely prompts for and confirms a password (minimum 12 characters); enter it in the terminal, not in a command, source file, or chat. Passwords are stored as PBKDF2-SHA256 hashes. Operators can reset passwords or disable accounts with:

```bash
python -m app.manage_staff reset-password staff@example.org
python -m app.manage_staff deactivate staff@example.org
python -m app.manage_staff activate staff@example.org
```

For local development, start the app and open the sign-in page here:

```text
http://127.0.0.1:8000/admin/login
```

In real use, the organization deploys the app to its own domain with HTTPS. An operator creates staff accounts on that deployed server (using the same database the live app uses); each administrator then visits `https://your-domain.example/admin/login` in a browser and signs in with their own email and password. The login page does not need to appear in public navigation: staff can bookmark the direct URL, and the dashboard still requires an authenticated staff account. Do not create a production account only in a developer's local database, since it will not exist in the live system.

The staff dashboard is a separate dark workspace with a collapsible desktop sidebar, an accessible mobile menu, quick row filtering, and a staff sign-out action. Dashboard metrics and charts use the selected reporting dates; set the `from` and `to` query parameters to share or bookmark a reporting window, for example:

```text
http://127.0.0.1:8000/admin/dashboard?tab=overview&from=2026-01-01&to=2026-01-31
```

The `tab` parameter preserves the selected workspace section (`overview`, `volunteers`, `donations`, `beneficiaries`, `needs`, `news`, or `reports`). Empty activity windows show an explanatory state instead of placeholder charts.

Staff sessions are stored server-side, expire after 12 hours, and are revoked on sign-out or password reset. In production, set `APP_ENV=production` and `COOKIE_SECURE=true`, serve the app only over HTTPS, and protect the SQLite file and backups using operating-system access controls and disk encryption.

All state-changing forms require CSRF tokens. Sign-in attempts are limited to five per 15 minutes per client IP; each public form is limited to five submissions per hour per client IP. Do not expose the app directly to the internet behind an untrusted proxy: rate limits use the connecting client IP and intentionally do not trust forwarded-IP headers.

### Staff roles, MFA, and audit trail

Administrative accounts are provisioned by an operator; there is no public staff registration or self-service role assignment. Use `create` with an explicit role when provisioning a non-administrator:

```powershell
python -m app.manage_staff create caseworker@example.org "Case Worker" --role case_worker
python -m app.manage_staff create finance@example.org "Finance Officer" --role finance
python -m app.manage_staff create editor@example.org "Content Editor" --role content_editor
python -m app.manage_staff create reports@example.org "Read Only" --role read_only
```

Every staff role must enroll an authenticator app using TOTP at first sign-in, and enter a fresh six-digit code at each subsequent sign-in. Keep the enrollment key private; administrators can change staff roles or revoke their sessions through the authenticated `/admin/staff` endpoints. Account creation, activation, password resets, and deactivation remain operator-controlled CLI operations. Available commands include:

```powershell
python -m app.manage_staff set-role caseworker@example.org finance
python -m app.manage_staff revoke-sessions caseworker@example.org
python -m app.manage_staff deactivate caseworker@example.org
python -m app.manage_staff activate caseworker@example.org
```

The role permissions are enforced on the server for dashboard data, mutations, and exports. Administrators can manage active staff roles, revoke sessions, deactivate accounts, and review recent audit events from `/admin/security`; the authenticated `/admin/staff` and `/admin/audit-log` endpoints provide the corresponding JSON views.

| Role | Access |
| --- | --- |
| Administrator | All operational areas, staff management, and audit log |
| Case Worker | Beneficiary requests, community needs, and volunteer scheduling |
| Finance | Donation verification and allocations, financial summaries, and permitted reports |
| Content Editor | News and announcements |
| Read-Only | Aggregated operational summaries only; no individual records or edits |

The Read-Only dashboard uses aggregate database queries and does not return beneficiary contact details or individual donation/volunteer records. The audit trail records staff authentication attempts, account changes, sensitive dashboard access, mutations, and exports with actor, action, timestamp, and target record. It is append-only in the application and enforced against update/delete statements by SQLite triggers. Protect the database file and its backups as described above, since host-level database administrators can bypass application controls.

### Daily operational workflows

- The dashboard priority queue links urgent assistance cases, donations awaiting verification, volunteer assignments due within seven days, and overdue case follow-ups to the underlying records.
- Assistance lists support status, urgency, category, region, and date-range filters. Contact details are masked in the list and visible only on the permission-checked case detail page. Assignment, internal notes, follow-up dates, status changes, and their reasons are recorded in case history. A reason is required to fulfil/close or reject a request.
- Donation states are `Submitted` → `Payment Pending` → `Received/Verified` → `Allocated`, with `Refunded` available from pending, verified, or allocated states. Allocation checks both the remaining donation balance and the target need's remaining funding server-side. The finance workspace provides an access-logged CSV reconciliation export.
- Tax receipts are not available from an unverified pledge. A donor who requests one receives a private download link that remains unusable until staff verify payment; successful verification creates the time-limited receipt access record.
- Volunteer lists can be filtered by skills, location, availability, and onboarding status. Assignments can include a date/time and appear in the upcoming-work queue.
- Community need targets and deadlines can be updated with funding progress history. News content follows `Draft` → `Preview` → `Published` → `Archive`; only published articles appear publicly.
- Operational records are archived rather than permanently deleted, preserving history and audit context. Include archived records from the dashboard's assistance filter when reviewing historical work.

## Personal-data retention

- Beneficiary contact name, phone, precise address, public title, and area are redacted 24 months after case closure; cases never closed are measured from submission.
- Donor contact, tax-identification, address, message, proof-of-payment, and pickup details are redacted five years after the end of the applicable South African tax year. Donation accounting values are retained.
- Tax receipt download access uses a random 256-bit token, never a donation ID; tokens expire after 30 days and return a receipt only after the donation has been verified. Expired receipt access and staff sessions are removed by the retention task.
- Run a dry report monthly, then apply the purge after reviewing the counts:

```bash
python -m app.retention
python -m app.retention --apply
```

Schedule the reviewed `--apply` command monthly using the host's task scheduler. Check the organization's legal, tax, and records-management obligations before production use; apply an approved legal hold before running a purge if required. Beneficiary and donor record views, exports, and administrative updates require an active staff session.
## Usage Examples

### Submit a volunteer application

Visit:

```text
http://127.0.0.1:8000/volunteer
```

Complete the volunteer form with:

- full name
- phone number
- email
- skills
- location
- availability

This stores the volunteer record in the database and makes them available for admin review.

### Submit an assistance request

Visit:

```text
http://127.0.0.1:8000/requestassistance
```

Fill in the assistance form with:

- contact name and phone number
- area or location
- type of assistance needed
- urgency and description

The app stores the request in a privacy-conscious format and anonymizes public-facing summaries for internal use.

### Make a donation

Visit:

```text
http://127.0.0.1:8000/donate
```

The donation flow supports:

- monetary contributions
- in-kind donations
- targeted funding toward a specific need
- optional tax certificate requests

Monetary donations are pledges only; this project does not process payments. Requested certificates are downloaded as clearly marked demo documents and are not valid proof of payment or for tax purposes.

Example API-style flow:

```bash
curl -X GET http://127.0.0.1:8000/donate
```

### View news and updates

Visit:

```text
http://127.0.0.1:8000/news
```

The news route displays featured stories, categorized content, and detail pages for each article.

## Project Structure

```text
.
├── main.py
├── requirements.txt
├── aurorah.db
├── app/
│   ├── db/
│   │   └── session.py
│   ├── models/
│   │   └── entities.py
│   ├── routers/
│   │   ├── admin/
│   │   ├── assistance.py
│   │   ├── donations.py
│   │   ├── news.py
│   │   └── volunteers.py
│   ├── static/
│   │   ├── css/
│   │   │   ├── admin.css
│   │   │   └── modern.css
│   │   └── js/
│   ├── templates/
│   │   ├── admin/
│   │   ├── partials/
│   │   ├── about.html
│   │   ├── adminbase.html
│   │   ├── base.html
│   │   ├── donate.html
│   │   ├── index.html
│   │   ├── news.html
│   │   ├── newsdetail.html
│   │   ├── requestassistance.html
│   │   └── volunteer.html
│   ├── templatesconfig.py
│   └── utils/
│       └── pdfexports.py
└── README.md
```

## Notes

- The project is built for community operations and nonprofit workflow automation.
- All data is stored locally in SQLite by default, making it easy to develop and test without needing a separate database service.
- The admin dashboard is intended for internal operational use and includes simple approval, reporting, and export workflows.

## License

This project is for internal or organizational use unless a separate license file is added by the repository owner.
