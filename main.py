from contextlib import asynccontextmanager
from dataclasses import dataclass
import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.engine import Engine
from starlette.concurrency import run_in_threadpool
from sqlmodel import Session

from app.db.session import (
    engine as default_engine,
    get_session,
    validate_database_ready,
)
from app.routers import (
    accounts,
    admin,
    assistance,
    donations,
    mobile_api,
    news,
    volunteers,
)
from app.security import (
    CSRF_COOKIE_NAME,
    csrf_cookie_options,
    make_csrf_token,
    valid_csrf_token,
    validate_security_configuration,
)
from app.templatesconfig import templates

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppSettings:
    cors_allowed_origins: Optional[tuple[str, ...]] = None


def create_app(
    *,
    database_engine: Optional[Engine] = None,
    initialize_database: bool = True,
    settings: Optional[AppSettings] = None,
) -> FastAPI:
    configured_engine = database_engine or default_engine
    app_settings = settings or AppSettings()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        validate_security_configuration()
        if application.state.initialize_database:
            validate_database_ready(application.state.database_engine)
        yield

    application = FastAPI(title="Aurorah CAN Digital Hub", lifespan=lifespan)
    application.state.database_engine = configured_engine
    application.state.initialize_database = initialize_database
    application.state.settings = app_settings
    if database_engine is not None:

        def configured_session():
            with Session(configured_engine) as session:
                try:
                    yield session
                except Exception:
                    session.rollback()
                    raise

        application.dependency_overrides[get_session] = configured_session

    cors_allowed_origins = (
        list(app_settings.cors_allowed_origins)
        if app_settings.cors_allowed_origins is not None
        else [
            origin.strip()
            for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
            if origin.strip()
        ]
    )
    cors_allowed_origins.extend(
        [
            "http://10.0.2.2:8000",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "https://aurorahcan.org.za",
            "https://www.aurorahcan.org.za",
        ]
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(dict.fromkeys(cors_allowed_origins)),
        allow_origin_regex=(
            r"^https?://(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
            r"192\.168\.\d{1,3}\.\d{1,3}|"
            r"172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})"
            r"(?::\d{1,5})?$"
        ),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @application.exception_handler(SQLAlchemyError)
    async def handle_database_error(request: Request, exc: SQLAlchemyError):
        if not request.url.path.startswith("/api/"):
            raise exc
        logger.exception("Database operation failed for %s", request.url.path)
        return JSONResponse(
            {"detail": "Database temporarily unavailable."},
            status_code=503,
        )

    @application.exception_handler(HTTPException)
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
                headers={
                    "Cache-Control": "no-store",
                    "Referrer-Policy": "no-referrer",
                },
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

    @application.middleware("http")
    async def add_csrf_cookie(request: Request, call_next):
        cookie_token = request.cookies.get(CSRF_COOKIE_NAME, "")
        token_valid = bool(cookie_token) and valid_csrf_token(cookie_token)
        request.state.csrf_token = cookie_token if token_valid else make_csrf_token()
        request.state.public_user = None
        if request.cookies.get(
            accounts.USER_COOKIE_NAME
        ) and not request.url.path.startswith("/static/"):
            session_provider = request.app.dependency_overrides.get(
                get_session, get_session
            )

            def resolve_public_user():
                session_generator = session_provider()
                try:
                    database_session = next(session_generator)
                    return accounts.get_public_user(request, database_session)
                finally:
                    session_generator.close()

            request.state.public_user = await run_in_threadpool(resolve_public_user)
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

    application.mount(
        "/static",
        StaticFiles(directory=Path(__file__).resolve().parent / "app" / "static"),
        name="static",
    )

    application.include_router(volunteers.router)
    application.include_router(assistance.router)
    application.include_router(donations.router)
    application.include_router(donations.receipt_router)
    application.include_router(accounts.router)
    application.include_router(mobile_api.router)
    application.include_router(news.router)
    application.include_router(admin.router)

    @application.get("/", response_class=HTMLResponse)
    def read_root(request: Request):
        return templates.TemplateResponse(
            request=request, name="index.html", context={"active_page": "home"}
        )

    @application.get("/about", response_class=HTMLResponse)
    def read_about(request: Request):
        return templates.TemplateResponse(
            request=request, name="about.html", context={"active_page": "about"}
        )

    return application


app = create_app()
