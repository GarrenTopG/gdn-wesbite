from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
load_dotenv()

from app.db.session import create_db_and_tables, get_session
from app.routers import accounts, admin, assistance, donations, mobile_api, news, volunteers
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


@app.exception_handler(HTTPException)
async def render_html_errors(request: Request, exc: HTTPException):
    if (
        request.method == "POST"
        and request.url.path == "/donate"
        and exc.status_code < 500
    ):
        return templates.TemplateResponse(
            request=request,
            name="donate.html",
            status_code=exc.status_code,
            context={
                "active_page": "donate",
                "active_needs": getattr(request.state, "donation_active_needs", []),
                "donation_form_values": getattr(
                    request.state, "donation_form_values", {}
                ),
                "selected_need_id": getattr(
                    request.state, "donation_form_values", {}
                ).get("need_id"),
                "error": exc.detail,
            },
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )

    if (
        request.url.path.startswith("/admin/")
        and request.method in {"GET", "HEAD"}
        and exc.status_code == 401
        and "text/html" in request.headers.get("accept", "")
    ):
        return RedirectResponse("/admin/login", status_code=303)

    return JSONResponse(
        {"detail": exc.detail},
        status_code=exc.status_code,
        headers=exc.headers,
    )


@app.middleware("http")
async def add_csrf_cookie(request: Request, call_next):
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME, "")
    token_valid = bool(cookie_token) and valid_csrf_token(cookie_token)
    request.state.csrf_token = cookie_token if token_valid else make_csrf_token()
    request.state.public_user = None
    if request.cookies.get(accounts.USER_COOKIE_NAME) and not request.url.path.startswith(
        "/static/"
    ):
        session_provider = app.dependency_overrides.get(get_session, get_session)
        session_generator = session_provider()
        try:
            database_session = next(session_generator)
            request.state.public_user = accounts.get_public_user(
                request, database_session
            )
        finally:
            session_generator.close()
    response = await call_next(request)
    if not token_valid:
        response.set_cookie(
            key=CSRF_COOKIE_NAME,
            value=request.state.csrf_token,
            **csrf_cookie_options(),
        )
    if (
        request.url.path.startswith("/admin/")
        or request.url.path.startswith("/api/auth/")
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
app.include_router(accounts.router)
app.include_router(mobile_api.router)
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