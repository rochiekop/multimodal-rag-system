import pytest

from app.chat.small_talk import small_talk


@pytest.mark.parametrize(
    "text",
    ["hello", "Hi!", "hey there", "Good morning", "hello?", "  HELLO  ", "how are you?", "hi bot"],
)
def test_greetings(text: str) -> None:
    assert small_talk(text) == "greeting"


@pytest.mark.parametrize("text", ["thanks", "Thank you!", "thank you so much", "thx", "cheers"])
def test_thanks(text: str) -> None:
    assert small_talk(text) == "thanks"


@pytest.mark.parametrize("text", ["bye", "Goodbye.", "see you later", "have a nice day"])
def test_goodbyes(text: str) -> None:
    assert small_talk(text) == "goodbye"


@pytest.mark.parametrize(
    "text",
    [
        "hello, how many days of annual leave do I get?",
        "can you tell me about simple present",
        "thanks to the new policy, what changed?",
        "Hi team: what is the travel budget?",
        "",
    ],
)
def test_real_questions_are_not_small_talk(text: str) -> None:
    assert small_talk(text) is None
