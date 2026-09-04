from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.db.session import create_db_and_tables
from app.routers import admin, assistance, donations, news, volunteers
from app.templatesconfig import templates

# FastAPI application instance with lifespan event for database initialization
@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    yield


app = FastAPI(title="Aurorah CAN Digital Hub", lifespan=lifespan)

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Include Modular Routers
app.include_router(volunteers.router)
app.include_router(assistance.router)
app.include_router(donations.router)
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