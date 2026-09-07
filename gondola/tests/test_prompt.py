

def test_el_esquema_viaja_en_el_prompt_cuando_no_hay_response_format(monkeypatch):
    """Medido: la decodificación restringida del proveedor mete tabuladores
    sueltos y rompe el JSON en la mitad de las fotos. Sin ella el esquema
    tiene que llegar por texto, o el modelo no sabe qué devolver."""
    from gondola.app import prompt

    monkeypatch.setattr(prompt.get_settings(), "usar_response_format", False, raising=False)
    mensajes = prompt.construir_mensajes([], "data:image/jpeg;base64,AAA")

    assert "frentes_por_nivel" in mensajes[0]["content"]
    assert "EXCLUSIVAMENTE un objeto JSON" in mensajes[0]["content"]


def test_sin_esquema_en_el_prompt_si_lo_fuerza_el_proveedor(monkeypatch):
    """Con response_format puesto, repetirlo en el texto solo gasta tokens
    de entrada en cada foto."""
    from gondola.app import prompt

    monkeypatch.setattr(prompt.get_settings(), "usar_response_format", True, raising=False)
    mensajes = prompt.construir_mensajes([], "data:image/jpeg;base64,AAA")

    assert "EXCLUSIVAMENTE un objeto JSON" not in mensajes[0]["content"]
