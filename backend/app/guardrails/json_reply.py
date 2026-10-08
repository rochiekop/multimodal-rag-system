"""Small models sometimes wrap JSON in prose or code fences; take the outermost object."""

from pydantic import BaseModel


def parse_json_reply[T: BaseModel](text: str, model: type[T]) -> T:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise ValueError("No JSON object in the model reply")
    return model.model_validate_json(text[start : end + 1])  # ValidationError is a ValueError
