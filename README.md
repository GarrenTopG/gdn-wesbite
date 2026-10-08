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
Startup also removes only the four legacy seeded-news slugs and converts old internal-need placeholder contact values to empty values.
Back up an existing `aurorah.db` before the first upgraded launch; startup applies the additive schema and the narrowly scoped legacy-data cleanup.

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
