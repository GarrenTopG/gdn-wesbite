from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

# Centralized Jinja2 templates instance to prevent circular imports
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["csrf_input"] = lambda request: Markup(
    '<input type="hidden" name="csrf_token" value="{}">'.format(
        escape(request.state.csrf_token)
    )
)