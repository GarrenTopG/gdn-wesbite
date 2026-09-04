# Aurorah CAN Digital Hub

Aurorah CAN Digital Hub is a community support platform built to connect beneficiaries, donors, volunteers, and administrators in one place. It helps simplify assistance requests, donation tracking, volunteer onboarding, and public impact updates for community-driven organizations.

## Key Features

- Request assistance through a structured, privacy-aware beneficiary form
- Accept monetary and in-kind donations with targeting and tax-certificate support
- Register and track volunteers by skills, availability, and assigned tasks
- Publish updates and impact stories through a news and announcements feed
- Manage operations from a secure admin dashboard with login, data review, and exports
- Generate PDF reports and Section 18A tax certificates for donor records

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

No external cloud credentials or environment variables are required for the default local setup; the app uses a local SQLite database.

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

```bash
uvicorn main:app --reload
```

Then open the app in your browser at:

```text
http://127.0.0.1:8000
```

The app will automatically create the SQLite database file if it does not already exist.

## Default Admin Access

For the local demo environment, the admin login is:

- Username: `admin`
- Password: `admin`

Access the dashboard here:

```text
http://127.0.0.1:8000/admin/login
```

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
│   │   └── js/
│   ├── templates/
│   │   ├── admin/
│   │   ├── partials/
│   │   ├── about.html
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
