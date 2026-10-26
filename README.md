# Aurorah CAN Digital Hub

Aurorah CAN Digital Hub is a community support platform built to connect beneficiaries, donors, volunteers, and administrators in one place. It helps simplify assistance requests, donation tracking, volunteer onboarding, and public impact updates for community-driven organizations.

## Key Features

- Request assistance through a structured, privacy-aware beneficiary form
- Publish staff-created fundraising campaigns with admin-reviewed simulated contributions
- Accept general monetary pledges, need-specific pledges, and in-kind offers with admin review
- Give signed-in donors a private notifications page for pledge and campaign review updates
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
- Node.js and npm when rebuilding the Tailwind stylesheets

The app uses a local SQLite database. No external cloud credentials are required for the default local setup, but a secret key must be set before the server starts; no default administrator account or secret is included.

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/GarrenTopG/gdn-wesbite.git
cd gdn-wesbite
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

The site uses precompiled local Tailwind stylesheets rather than compiling styles in the visitor's browser. If you change Tailwind classes or either theme, install the locked frontend build dependencies with `npm ci` and regenerate both stylesheets with `npm run build:css`.

### Python quality checks

Install the pinned development checks and run the complete local Python gate:

```bash
python -m pip install -r requirements-dev.txt
python scripts/check.py
```

The command checks Ruff lint and formatting, mypy on the application entry point,
database/session, authentication, and mobile API modules, Python syntax
buildability, and the full unittest suite. CI runs the same command on Python 3.11
for every push and pull request. Its separate frontend job rebuilds both committed
Tailwind stylesheets and fails if generated output differs. Require the **Python
checks** status in repository branch protection to block merges on failures.

Tests use isolated in-memory SQLite databases and cover app startup, migration
paths, retention calculations, role rules, CSRF, authentication, authorization,
and key public/mobile workflows. SQL Server compatibility currently includes
compiled schema and query checks; these are not a substitute for a live SQL
Server integration run. Run those checks against a dedicated disposable SQL
Server database before production database changes.

The test client currently emits one upstream `StarletteDeprecationWarning`: Starlette
1.4.1 deprecates its `httpx` backend in favor of `httpx2`. The CSS build can also
report that the pinned `caniuse-lite` browser data is outdated. Both warnings are
documented rather than hidden or automatically changing locked dependencies;
the project pins `httpx` as part of its application dependency set.

Quality gates are:

| Area | Gate |
| --- | --- |
| Maintainability | Ruff lint and formatting pass across `main.py`, `app`, `migrations`, and `tests`. |
| Types and buildability | mypy passes on the critical application modules and all Python files compile without writing bytecode. |
| Tests and runtime | The full unittest suite passes with isolated in-memory SQLite databases and startup coverage. |
| Security and privacy | Tests cover staff MFA, expiration, revocation, and role authorization; tests do not connect to or modify the application database. |
| Release readiness | Python CI is green and the frontend build reproduces committed CSS. |

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

Install the migration command and initialize the selected database before starting the app:

```powershell
python -m pip install -r requirements-migrations.txt
python -m alembic upgrade head
```

The migration command uses the same database settings as the application. The FastAPI
startup check validates database connectivity and the current migration revision; it does
not create tables, run migrations, or seed content. The Docker image runs
`python -m alembic upgrade head` before starting the web server, so Docker deployments
apply pending migrations automatically.

```bash
uvicorn main:app --reload
```

Then open the app in your browser at:

```text
http://127.0.0.1:8000
```

See [docs/database-migrations.md](./docs/database-migrations.md) for database access and
transaction conventions, fresh and existing database upgrades, and the production backup
and migration procedure.

### Website accounts

Visitors can browse without signing in, and guest donation pledges are allowed with an optional email address. Requesting assistance or applying to volunteer requires a website account. Create an account at `/account/register`, sign in at `/account/login`, and sign out from the site navigation. Account passwords must be at least 12 characters; sessions use HTTP-only cookies and expire after 12 hours. Website accounts are separate from staff accounts and cannot access the admin workspace.

Website sessions use the `user_session` HTTP-only cookie and are stored server-side. They authorize only regular website accounts; they are not accepted as staff sessions or mobile bearer tokens.

### Android mobile API

The Android app and website use this FastAPI service and the same configured database; the mobile app must not connect directly to SQLite or SQL Server. The JSON API uses the `/api` prefix:

| Endpoint | Authentication | Purpose |
| --- | --- | --- |
| `POST /api/auth/register` | Public | Create a regular user account (`fullName`, `email`, `password`; password minimum 12 characters). Any submitted `role` is ignored. |
| `POST /api/auth/login` | Public | Sign in with email and password. |
| `POST /api/auth/google-sso` | Public | Compatibility endpoint for older Android versions using a Firebase ID token; new clients use the shared browser SSO flow. |
| `GET /api/auth/sso/providers` | Public | List configured providers available to the Android sign-in screen. |
| `GET /api/auth/sso/{provider}/start?challenge=...` | Public | Start Google or Microsoft browser-based SSO for Android using a PKCE challenge. |
| `POST /api/auth/sso/exchange` | Public | Exchange a short-lived, one-use mobile SSO code and PKCE verifier for a bearer session. |
| `PUT /api/auth/profile` | Bearer token | Update the signed-in user's `full_name`, `phone_number`, and optional `preferences`. |
| `POST /api/auth/change-password` | Bearer token | Change the signed-in user's password (`email`, `oldPassword`, `newPassword`). |
| `GET /api/news` | Public | Return published news items, including each article's summary and full content. |
| `GET /api/needs` | Public | Return open, public community needs without beneficiary contact details. |
| `POST /api/needs/offer-assistance` | Bearer token | Submit an offer for an open community need (`needId`, `userEmail`, `volunteerSkill`, `notes`). |
| `POST /api/assistance-requests` | Bearer token | Submit a request (`category`, `description`, `urgency`, `location`, `contact_phone`) as the signed-in user. |
| `POST /api/donations` | Bearer token | Record a monetary pledge (`category`, `amount`) or in-kind offer (`item_category`, `item_description`, `drop_off_option`). |

Successful sign-in and registration responses include `success`, `message`, `token`, and a `user` object. Send the token on protected requests as `Authorization: Bearer <token>`; mobile bearer sessions expire after 12 hours. Mobile tokens are distinct from both website cookies and staff sessions. Account roles are assigned by the server, never trusted from the app. Failed or malformed requests return HTTP error responses.

Google and Microsoft sign-in use the same server-side OpenID Connect authorization-code flow on the website and Android. Configure `SSO_BASE_URL` as the public HTTPS origin and set `SSO_GOOGLE_CLIENT_ID`, `SSO_GOOGLE_CLIENT_SECRET`, `SSO_MICROSOFT_CLIENT_ID`, and `SSO_MICROSOFT_CLIENT_SECRET` in the deployment environment. Configure each provider's exact callback URI as `SSO_BASE_URL/auth/sso/callback/google` or `SSO_BASE_URL/auth/sso/callback/microsoft`. Microsoft uses the `common` authority so personal Microsoft accounts and work/school accounts can sign in. Keep client secrets only in the server's secret store.

The Android handoff uses the app link `https://aurorah-web-hub.onrender.com/mobile-auth/callback` by default; override `MOBILE_SSO_REDIRECT_URI` only if the Android app-link manifest and domain association are updated to the same URL. Publish a Digital Asset Links file at `https://aurorah-web-hub.onrender.com/.well-known/assetlinks.json` for the Android application ID and release signing certificate to enable verified app links. The app opens the server authorization URL in the system browser, receives a short-lived one-use code through the app link, then exchanges it with a PKCE verifier. Provider tokens and mobile bearer tokens are never placed in the redirect URL.

New Android clients and the website use browser-based OIDC. For compatibility, `POST /api/auth/google-sso` remains available to older Android versions that send Firebase ID tokens. Set `FIREBASE_PROJECT_ID` and provide the server's Firebase Application Default Credentials only if that compatibility endpoint is needed; it verifies the Firebase token and resolves the linked Google provider subject before issuing the same mobile session. Historical accounts created through that older Google flow can be upgraded when their verified Google identity is next used. Provider subjects, not email addresses, are the durable identity keys. A verified Google email may create a new regular user account; Microsoft email claims are used as account contact identifiers and are not used to link accounts. For other existing accounts, sign in to the website and use the account menu's **Connect Google sign-in** or **Connect Microsoft sign-in** action. SSO never grants staff roles or bypasses staff MFA.

Mobile monetary donation submissions are **pledges only**. The website currently has no online payment processor: `paymentMethod` is not used to charge or verify a payment, and the API response explicitly says no payment was processed. Donations remain unverified until staff handle them through the existing admin workflow. In-kind submissions record the item details and whether the donor will drop off or requests pickup. Assistance requests are stored as private beneficiary needs and linked to the authenticated account. Offers to help are saved with `Pending` status; staff with community-needs access can review them in Admin → Needs and mark them reviewed.

The API enables CORS for the Android emulator origin `http://10.0.2.2:8000`, private IPv4 development hosts, and `https://aurorah-web-hub.onrender.com`. Set `CORS_ALLOWED_ORIGINS` to a comma-separated list of additional exact origins for a different production app domain; do not use `*` for production. SQLAlchemy connection failures on API requests are logged server-side and return a generic JSON `503` response.

### Connect to Azure SQL Server

The website connects to its database from the FastAPI backend; `base.html` must not connect directly to SQL Server. SQLite remains the default for local development. To use the Azure database, install the SQL Server adapter and the Microsoft ODBC Driver 18 for SQL Server on the machine running the app:

```powershell
pip install -r requirements-sqlserver.txt
```

Add these settings to the private `.env` file (or the deployment's secret environment). Replace the username and password with a dedicated website database login; do not use the shared server administrator account:

```dotenv
DATABASE_BACKEND=sqlserver
MSSQL_SERVER=aurorah-sql-server.database.windows.net
MSSQL_DATABASE=aurorah-db
MSSQL_USERNAME=your-website-database-login
MSSQL_PASSWORD=your-website-database-password
MSSQL_DRIVER=ODBC Driver 18 for SQL Server
```

Install the SQL Server adapter and migration dependency in the migration environment,
then use a schema-provisioning login to run `python -m alembic upgrade head`. After
migration, run the application with its restricted website login. Keep schema-owner
credentials out of the running website. Migrations apply to the configured SQL Server
database; they do not copy records from `aurorah.db`. See
[docs/database-migrations.md](./docs/database-migrations.md) for backup and production
steps.

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

Staff sessions are stored server-side and expire 12 hours after successful MFA verification. Password-only challenges expire after five minutes and cannot access protected routes. Staff sessions are revoked on sign-out, password reset, role changes, or administrator deactivation. In production, set `APP_ENV=production` and `COOKIE_SECURE=true`, serve the app only over HTTPS, and protect the SQLite file and backups using operating-system access controls and disk encryption.

All state-changing forms require CSRF tokens. Sign-in attempts are limited to five per 15 minutes per client IP; each public form is limited to five submissions per hour per client IP. Do not expose the app directly to the internet behind an untrusted proxy: rate limits use the connecting client IP and intentionally do not trust forwarded-IP headers.

### Staff roles, MFA, and audit trail

Administrative accounts are provisioned by an operator; there is no public staff registration or self-service role assignment. Use `create` with an explicit role when provisioning a non-administrator:

```powershell
python -m app.manage_staff create caseworker@example.org "Case Worker" --role case_worker
python -m app.manage_staff create finance@example.org "Finance Officer" --role finance
python -m app.manage_staff create editor@example.org "Content Editor" --role content_editor
python -m app.manage_staff create reports@example.org "Read Only" --role read_only
```

MFA is required for every staff account. On the first password-authenticated sign-in, the staff member receives a short-lived, unverified challenge and an enrollment key; protected routes remain unavailable until a valid six-digit TOTP code confirms enrollment. The enrollment key is then saved to the staff account and is no longer displayed. Every later sign-in requires a valid, unused TOTP code before the 12-hour staff session is issued. MFA verification is rate-limited to five attempts per 15 minutes. Keep the enrollment key private; administrators can change staff roles or revoke their sessions through the authenticated `/admin/staff` endpoints. Account creation, activation, password resets, and deactivation remain operator-controlled CLI operations. Available commands include:

```powershell
python -m app.manage_staff set-role caseworker@example.org finance
python -m app.manage_staff revoke-sessions caseworker@example.org
python -m app.manage_staff deactivate caseworker@example.org
python -m app.manage_staff activate caseworker@example.org
```

The role permissions are enforced on the server for dashboard data, mutations, and exports. Administrators can manage active staff roles, revoke sessions, deactivate accounts, and review recent audit events from `/admin/security`; the authenticated `/admin/staff` and `/admin/audit-log` endpoints provide the corresponding JSON views.

| Role | Access |
| --- | --- |
| Administrator | All operational areas, campaign publishing, staff management, and audit log |
| Case Worker | Beneficiary requests, internal operational needs, and volunteer scheduling |
| Finance | Donation verification and allocations, financial summaries, and permitted reports |
| Content Editor | News and announcements |
| Read-Only | Aggregated operational summaries only; no individual records or edits |

The Read-Only dashboard uses aggregate database queries and does not return beneficiary contact details or individual donation/volunteer records. The audit trail records staff authentication attempts, account changes, sensitive dashboard access, mutations, and exports with actor, action, timestamp, and target record. It is append-only in the application and enforced against update/delete statements by SQLite triggers. Protect the database file and its backups as described above, since host-level database administrators can bypass application controls.

### Daily operational workflows

- The dashboard priority queue links urgent assistance cases, donations awaiting verification, volunteer assignments due within seven days, and overdue case follow-ups to the underlying records.
- Assistance lists support status, urgency, category, region, and date-range filters. Contact details are masked in the list and visible only on the permission-checked case detail page. Assignment, internal notes, follow-up dates, status changes, and their reasons are recorded in case history. A reason is required to fulfil/close or reject a request.
- General donation states remain `Submitted` → `Payment Pending` → `Received/Verified` → `Allocated`, with `Refunded` available from pending, verified, or allocated states. Allocation checks both the remaining donation balance and the target need's remaining funding server-side.
- A monetary pledge made from a public community need is linked to that specific need and starts as `Payment Pending`. Staff approve or reject the pledge without reallocating it. Only approved pledges count toward the need's public total; reaching the target does not close the card, and the due date controls when new pledges stop. Pledges submitted before the due date remain reviewable after it.
- Signed-in donors see pending, approved, and rejected community-pledge updates on `/account/notifications`, linked below their name in the account menu. Guest pledges remain available but are not linked to an in-app notification account.
- Campaign contributions are simulated school-project records, require a signed-in account, and do not process or collect payment credentials. Staff approve or reject them; only approved, non-reversed contributions count in campaign progress. Approval, rejection, campaign lifecycle updates, and completion updates appear on the contributor's private `/account/notifications` page. Simulated campaign contributions are kept out of general donation totals and the donation PDF/CSV exports; campaign progress is shown separately in campaign management.
- Public campaigns are separate from private beneficiary assistance records. Campaigns follow `Draft` → `Published` → `Paused` / automatically `Completed` → `Archived`; completed campaigns remain visible below active campaigns but cannot accept new contributions. Archiving hides a campaign without removing its history.
- Tax receipts are not available from an unverified pledge. A donor who requests one receives a private download link that remains unusable until staff verify payment; successful verification creates the time-limited receipt access record.
- Volunteer lists can be filtered by skills, location, availability, and onboarding status. Assignments can include a date/time and appear in the upcoming-work queue.
- Internal operational-need targets and deadlines can be updated with funding progress history. Public campaigns are managed separately in the campaign section of the admin workspace. News content follows `Draft` → `Preview` → `Published` → `Archive`; only published articles appear publicly.
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

- general monetary pledges
- monetary pledges linked to a specific open community need
- in-kind donations
- staff-created public campaigns with simulated contributions
- optional tax certificate requests

General monetary contributions remain pledges only. Community-need pledges stay attached to the need selected by the donor; approval updates its public progress, and rejection does not. The card remains open after reaching its target until its due date. Campaign contributions require an account and admin approval, but are simulations only: the site does not take payment or collect card/bank details. Progress counts approved demo contributions, not pending submissions. Campaign images can currently be added by URL; uploads are deferred until durable storage is confirmed for the Render deployment. Any requested certificate is a clearly marked demo document and is not valid proof of payment or for tax purposes.

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
