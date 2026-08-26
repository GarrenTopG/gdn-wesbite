from fastapi.templating import Jinja2Templates

# Centralized Jinja2 templates instance to prevent circular imports
templates = Jinja2Templates(directory="app/templates")