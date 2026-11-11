from cephalon import persona, render

SOURCES = [("Continuity", "https://wiki.warframe.com/w/Continuity"),
           ("Continuity (Défectueux)", "https://wiki.warframe.com/w/Flawed_Continuity")]


def test_answer_embed():
    embed = render.answer("Que fait Continuité ?", "  +30 % de durée, Tenno.  ", SOURCES)
    assert embed.author.name == "Cephalon Schtroumpfette"
    assert embed.description == "> Que fait Continuité ?\n\n+30 % de durée, Tenno."
    assert embed.color == render.ANSWER_COLOR
    assert [(field.name, field.value) for field in embed.fields] == [
        ("Sources", "[Continuity](https://wiki.warframe.com/w/Continuity)\n"
                    "[Continuity (Défectueux)](https://wiki.warframe.com/w/Flawed_Continuity)")]
    assert embed.footer.text == "Données : warframestat.us"


def test_answer_without_source_has_no_field_and_no_footer():
    embed = render.answer("Quel temps fait-il ?", "Je ne parle que de Warframe.", [])
    assert embed.fields == [] and embed.footer.text is None


def test_multiline_question_is_quoted_on_each_line():
    assert render.answer("Rhino ?\nEt Rhino Prime ?", "Oui.", []).description == "> Rhino ?\n> Et Rhino Prime ?\n\nOui."


def test_long_answer_is_truncated():
    description = render.answer("Q" * 500, "mot " * 2000, []).description
    assert len(description) == render.DESCRIPTION_LIMIT and description.endswith("…")


def test_sources_are_limited():
    many = [(f"Objet {index}", f"https://wiki.warframe.com/w/{index}") for index in range(8)]
    assert render.sources_field(many).count("\n") == render.MAX_SOURCES - 1
    long = [(f"Objet {index}", "https://wiki.warframe.com/w/" + "x" * 400) for index in range(4)]
    value = render.sources_field(long)
    assert value.count("\n") == 1 and len(value) <= render.FIELD_LIMIT


def test_fallback_embed():
    embed = render.fallback("Que fait Continuité ?", persona.ROUNDS_MESSAGE)
    assert embed.author.name == "Cephalon Schtroumpfette"
    assert embed.description == f"> Que fait Continuité ?\n\n{persona.ROUNDS_MESSAGE}"
    assert embed.color == render.FALLBACK_COLOR and embed.fields == []


def test_error_messages():
    messages = persona.ERROR_MESSAGES
    assert len(messages) == len(set(messages)) == 45
    assert all("Tenno" in message and message.strip() == message and len(message) < 200 for message in messages)


def test_error_message_is_drawn_from_the_list(monkeypatch):
    monkeypatch.setattr(persona.random, "choice", lambda messages: messages[7])
    assert persona.error_message() == persona.ERROR_MESSAGES[7]
    monkeypatch.undo()
    assert persona.error_message() in persona.ERROR_MESSAGES


def test_system_prompt_is_static():
    """Texte fixe : il fait partie du préfixe mis en cache."""
    assert "Cephalon Schtroumpfette" in persona.SYSTEM_PROMPT and "Tenno" in persona.SYSTEM_PROMPT
    assert "{" not in persona.SYSTEM_PROMPT
