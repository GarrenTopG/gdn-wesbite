from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from app.db.session import create_db_and_tables
from app.routers import admin, assistance, donations, news, volunteers
from app.security import (
    CSRF_COOKIE_NAME,
    csrf_cookie_options,
    make_csrf_token,
    valid_csrf_token,
    validate_security_configuration,
)
from app.templatesconfig import templates

# FastAPI application instance with lifespan event for database initialization
@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_security_configuration()
    create_db_and_tables()
    yield


app = FastAPI(title="Aurorah CAN Digital Hub", lifespan=lifespan)


@app.middleware("http")
async def add_csrf_cookie(request: Request, call_next):
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME, "")
    token_valid = bool(cookie_token) and valid_csrf_token(cookie_token)
    request.state.csrf_token = cookie_token if token_valid else make_csrf_token()
    response = await call_next(request)
    if not token_valid:
        response.set_cookie(
            key=CSRF_COOKIE_NAME,
            value=request.state.csrf_token,
            **csrf_cookie_options(),
        )
    if (
        request.url.path.startswith("/admin/")
        or request.url.path == "/donate/tax-certificate"
        or (request.url.path == "/donate" and request.method == "POST")
    ):
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Include Modular Routers
app.include_router(volunteers.router)
app.include_router(assistance.router)
app.include_router(donations.router)
app.include_router(donations.receipt_router)
app.include_router(news.router)
app.include_router(admin.router)


# --- ROOT STATIC ROUTES ---
@app.get("/", response_class=HTMLResponse)
def read_root(request: Request):
    return templates.TemplateResponse(
        request=request, name="index.html", context={"active_page": "home"}
    )

# --- ADDITIONAL STATIC ROUTES ---
@app.get("/about", response_class=HTMLResponse)
def read_about(request: Request):
    return templates.TemplateResponse(
        request=request, name="about.html", context={"active_page": "about"}
    )