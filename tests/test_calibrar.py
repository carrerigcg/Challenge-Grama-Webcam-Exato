"""Testes das funções puras de calibrar."""
import json

import pytest

import calibrar


def test_calcular_px_por_cm_horizontal():
    # Dois pontos a 80 pixels de distância representando 10cm → 8 px/cm
    result = calibrar.calcular_px_por_cm((100, 200), (180, 200), 10.0)
    assert result == 8.0


def test_calcular_px_por_cm_vertical():
    # 80 pixels na vertical representando 10cm
    result = calibrar.calcular_px_por_cm((100, 100), (100, 180), 10.0)
    assert result == 8.0


def test_calcular_px_por_cm_diagonal():
    # (0,0) → (3,4) = distância 5. Se cm_ref=1 → 5 px/cm
    result = calibrar.calcular_px_por_cm((0, 0), (3, 4), 1.0)
    assert abs(result - 5.0) < 1e-9


def test_calcular_px_por_cm_zero_cm_raises():
    with pytest.raises(ValueError, match="cm_ref"):
        calibrar.calcular_px_por_cm((0, 0), (10, 0), 0.0)


def test_calcular_px_por_cm_negative_cm_raises():
    with pytest.raises(ValueError, match="cm_ref"):
        calibrar.calcular_px_por_cm((0, 0), (10, 0), -5.0)


def test_calcular_px_por_cm_same_point_raises():
    with pytest.raises(ValueError, match="pontos"):
        calibrar.calcular_px_por_cm((100, 100), (100, 100), 10.0)


def test_montar_calibration_dict_contem_todos_os_campos():
    data = calibrar.montar_calibration_dict(
        px_por_cm=8.5, y_chao=420, resolucao=(640, 480), cm_ref=10.0,
    )
    assert data["px_por_cm"] == 8.5
    assert data["y_chao"] == 420
    assert data["resolucao"] == [640, 480]
    assert data["segmento_cm_referencia"] == 10.0
    assert "created_at" in data
    # ISO 8601 tem "T" separando data e hora
    assert "T" in data["created_at"]


def test_montar_calibration_dict_inclui_regiao_quando_passada():
    data = calibrar.montar_calibration_dict(
        px_por_cm=8.5, y_chao=420, resolucao=(640, 480), cm_ref=10.0,
        regiao="rodoanel norte",
    )
    assert data["regiao"] == "rodoanel norte"


def test_montar_calibration_dict_omite_regiao_quando_none():
    """Backwards compat: calibrações antigas sem regiao continuam válidas."""
    data = calibrar.montar_calibration_dict(
        px_por_cm=8.5, y_chao=420, resolucao=(640, 480), cm_ref=10.0,
    )
    assert "regiao" not in data


def test_salvar_calibration_cria_arquivo(tmp_path):
    path = tmp_path / "cal.json"
    data = {"px_por_cm": 8.0, "y_chao": 400, "resolucao": [640, 480]}
    calibrar.salvar_calibration(data, str(path))
    assert path.exists()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded == data


def test_salvar_calibration_overwrite_existing(tmp_path):
    path = tmp_path / "cal.json"
    path.write_text('{"px_por_cm": 1.0, "y_chao": 1}', encoding="utf-8")
    novo = {"px_por_cm": 10.0, "y_chao": 500, "resolucao": [1280, 720]}
    calibrar.salvar_calibration(novo, str(path))
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded == novo


def test_ler_regiao_devolve_valor_stripado(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "  rodoanel sul  ")
    assert calibrar._ler_regiao() == "rodoanel sul"


def test_ler_regiao_vazio_devolve_none(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _: "   ")
    assert calibrar._ler_regiao() is None
    assert "regiao" in capsys.readouterr().err.lower()


def test_ler_regiao_ctrl_c_devolve_none(monkeypatch):
    def _boom(_):
        raise KeyboardInterrupt
    monkeypatch.setattr("builtins.input", _boom)
    assert calibrar._ler_regiao() is None


def test_salvar_calibration_uses_utf8_encoding(tmp_path):
    """Garante que caracteres não-ASCII no timestamp/campos não quebram."""
    path = tmp_path / "cal.json"
    data = calibrar.montar_calibration_dict(8.0, 420, (640, 480), 10.0)
    calibrar.salvar_calibration(data, str(path))
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["px_por_cm"] == 8.0
