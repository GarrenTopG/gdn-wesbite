from app.models.entities import NeedUrgency


def parse_need_urgency(value: str) -> NeedUrgency:
    return NeedUrgency(value.strip().capitalize())
