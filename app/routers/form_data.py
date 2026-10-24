from fastapi import Request
from starlette.datastructures import FormData


async def parse_form_data(request: Request) -> FormData:
    return await request.form()
