"""Greetings, thanks and goodbyes get a short friendly reply instead of a document search,
which would only answer "I couldn't find this" with unrelated closest matches. Only whole
messages match: "hello, how many leave days do I get?" is still a question."""

import re
from typing import Literal

SmallTalk = Literal["greeting", "thanks", "goodbye"]

_ADDRESSEE = r"(?: (?:there|everyone|all|team|bot|assistant))?"
_PATTERNS: tuple[tuple[SmallTalk, re.Pattern[str]], ...] = (
    (
        "greeting",
        re.compile(
            r"(?:hi|hello|hey|hiya|howdy|greetings|good (?:morning|afternoon|evening|day)"
            r"|how are you(?: doing)?|what'?s up)" + _ADDRESSEE
        ),
    ),
    (
        "thanks",
        re.compile(
            r"(?:thanks?(?: you)?(?: (?:so much|a lot|very much))?|thx|ty|cheers"
            r"|much appreciated)" + _ADDRESSEE
        ),
    ),
    (
        "goodbye",
        re.compile(r"(?:bye|goodbye|good bye|see you(?: later)?|have a (?:nice|good) day)"),
    ),
)

THANKS_REPLY = "You're welcome! Ask me anything else about your documents."
GOODBYE_REPLY = "Goodbye! Come back any time you have a question about your documents."


def small_talk(text: str) -> SmallTalk | None:
    """The kind of small talk a whole message is, or None for anything else."""
    normalized = " ".join(re.sub(r"[^\w\s']", " ", text.lower()).split())
    for kind, pattern in _PATTERNS:
        if pattern.fullmatch(normalized):
            return kind
    return None
