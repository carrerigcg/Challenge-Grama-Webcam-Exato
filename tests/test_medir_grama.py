"""Testes das funções puras de medir_grama."""
import json

import numpy as np
import pytest

import medir_grama


@pytest.fixture(autouse=True)
def _stub_buscar_clima(monkeypatch):
    """Impede chamada real ao Open-Meteo em qualquer teste que exercite
    enviar_medicao. Testes que querem verificar clima no payload sobrescrevem
    monkeypatch.setattr(medir_grama, "buscar_clima", ...) explicitamente."""
    monkeypatch.setattr(medir_grama, "buscar_clima", lambda lat, lon: (None, None))


# --- load_calibration --------------------------------------------------------
def _valid_calibration_dict():
    return {
        "px_por_cm": 8.5,
        "y_chao": 420,
        "resolucao": [640, 480],
        "created_at": "2026-08-19T14:30:00",
        "segmento_cm_referencia": 10.0,
    }


def test_load_calibration_valid_file(tmp_path):
    path = tmp_path / "calibration.json"
    data = _valid_calibration_dict()
    path.write_text(json.dumps(data), encoding="utf-8")
    result = medir_grama.load_calibration(str(path))
    assert result["px_por_cm"] == 8.5
    assert result["y_chao"] == 420


def test_load_calibration_missing_file_raises_with_hint(tmp_path):
    path = tmp_path / "nao_existe.json"
    with pytest.raises(FileNotFoundError, match="calibrar"):
        medir_grama.load_calibration(str(path))


def test_load_calibration_invalid_json_raises(tmp_path):
    path = tmp_path / "calibration.json"
    path.write_text("{ isso nao eh json valido", encoding="utf-8")
    with pytest.raises(RuntimeError, match="JSON"):
        medir_grama.load_calibration(str(path))


def test_load_calibration_missing_field_raises(tmp_path):
    path = tmp_path / "calibration.json"
    data = _valid_calibration_dict()
    del data["px_por_cm"]
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(RuntimeError, match="px_por_cm"):
        medir_grama.load_calibration(str(path))


def test_load_calibration_invalid_px_por_cm_raises(tmp_path):
    path = tmp_path / "calibration.json"
    data = _valid_calibration_dict()
    data["px_por_cm"] = 0
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(RuntimeError, match="px_por_cm"):
        medir_grama.load_calibration(str(path))


# --- y_para_altura_cm --------------------------------------------------------
def test_y_para_altura_cm_normal():
    # y_topo=340, y_chao=420, px_por_cm=8 → (420-340)/8 = 10.0 cm
    assert medir_grama.y_para_altura_cm(340, 420, 8.0) == 10.0


def test_y_para_altura_cm_none_returns_none():
    assert medir_grama.y_para_altura_cm(None, 420, 8.0) is None


def test_y_para_altura_cm_topo_no_chao_returns_zero():
    # y_topo == y_chao → altura = 0
    assert medir_grama.y_para_altura_cm(420, 420, 8.0) == 0.0


def test_y_para_altura_cm_topo_abaixo_do_chao_returns_zero():
    # y_topo > y_chao (grama detectada abaixo do chão calibrado — ignora)
    assert medir_grama.y_para_altura_cm(450, 420, 8.0) == 0.0


def test_y_para_altura_cm_float_precision():
    # (400-350)/8.5 = ~5.882 cm
    result = medir_grama.y_para_altura_cm(350, 400, 8.5)
    assert abs(result - (50 / 8.5)) < 1e-9


# --- classify_cm -------------------------------------------------------------
def test_classify_cm_none_is_ausente():
    assert medir_grama.classify_cm(None, 3.0, 7.0) == (0, "AUSENTE")


def test_classify_cm_below_baixa_is_baixa():
    assert medir_grama.classify_cm(2.9, 3.0, 7.0) == (1, "BAIXA")


def test_classify_cm_zero_is_baixa():
    assert medir_grama.classify_cm(0.0, 3.0, 7.0) == (1, "BAIXA")


def test_classify_cm_exactly_at_baixa_boundary_is_baixa():
    # <= faixa_baixa → BAIXA
    assert medir_grama.classify_cm(3.0, 3.0, 7.0) == (1, "BAIXA")


def test_classify_cm_between_boundaries_is_media():
    assert medir_grama.classify_cm(5.0, 3.0, 7.0) == (2, "MÉDIA")


def test_classify_cm_exactly_at_media_boundary_is_media():
    assert medir_grama.classify_cm(7.0, 3.0, 7.0) == (2, "MÉDIA")


def test_classify_cm_above_media_is_alta():
    assert medir_grama.classify_cm(7.1, 3.0, 7.0) == (3, "ALTA")


def test_classify_cm_very_tall_is_alta():
    assert medir_grama.classify_cm(50.0, 3.0, 7.0) == (3, "ALTA")


# --- classify_frame_cm -------------------------------------------------------
def test_classify_frame_cm_all_none_is_ausente():
    result = medir_grama.classify_frame_cm([None, None, None], 3.0, 7.0)
    assert result == (0, "AUSENTE", None)


def test_classify_frame_cm_all_baixa():
    result = medir_grama.classify_frame_cm([2.0, 2.5, 2.8], 3.0, 7.0)
    assert result[0] == 1
    assert result[1] == "BAIXA"
    assert abs(result[2] - 2.5) < 1e-9  # mediana


def test_classify_frame_cm_ignores_none_in_median():
    # [None, 5.0, 6.0] → mediana ignora None → mediana([5.0, 6.0]) = 5.5 → MÉDIA
    result = medir_grama.classify_frame_cm([None, 5.0, 6.0], 3.0, 7.0)
    assert result[0] == 2
    assert result[1] == "MÉDIA"
    assert abs(result[2] - 5.5) < 1e-9


def test_classify_frame_cm_mix_baixa_media_alta():
    # [2.0, 5.0, 9.0] → mediana=5.0 → MÉDIA
    result = medir_grama.classify_frame_cm([2.0, 5.0, 9.0], 3.0, 7.0)
    assert result[0] == 2
    assert result[1] == "MÉDIA"


def test_classify_frame_cm_all_alta():
    result = medir_grama.classify_frame_cm([8.0, 9.0, 10.0], 3.0, 7.0)
    assert result[0] == 3
    assert result[1] == "ALTA"


# --- measure_top_y -----------------------------------------------------------
def test_measure_top_y_all_columns_have_grass():
    mask = np.zeros((100, 100), np.uint8)
    mask[60:100, 25] = 255  # topo y=60
    mask[30:100, 50] = 255  # topo y=30
    mask[80:100, 75] = 255  # topo y=80
    result = medir_grama.measure_top_y(mask, (0.25, 0.50, 0.75))
    assert result == [60, 30, 80]


def test_measure_top_y_empty_mask_returns_all_none():
    mask = np.zeros((100, 100), np.uint8)
    result = medir_grama.measure_top_y(mask, (0.25, 0.50, 0.75))
    assert result == [None, None, None]


def test_measure_top_y_column_without_green_returns_none_for_that_column():
    mask = np.zeros((100, 100), np.uint8)
    mask[50:100, 25] = 255  # só a coluna 25% tem verde
    result = medir_grama.measure_top_y(mask, (0.25, 0.50, 0.75))
    assert result == [50, None, None]


def test_measure_top_y_returns_ints_not_numpy_scalars():
    mask = np.zeros((100, 100), np.uint8)
    mask[70:100, 50] = 255
    result = medir_grama.measure_top_y(mask, (0.50,))
    assert isinstance(result[0], int)


# --- median_stack ------------------------------------------------------------
def test_median_stack_identical_masks_returns_same_mask():
    m = np.array([[0, 255], [255, 0]], np.uint8)
    result = medir_grama.median_stack([m.copy() for _ in range(5)])
    np.testing.assert_array_equal(result, m)


def test_median_stack_majority_wins():
    zero = np.zeros((2, 2), np.uint8)
    um = np.full((2, 2), 255, np.uint8)
    # 3 zeros vs 2 uns → mediana = 0
    result = medir_grama.median_stack([zero, zero, zero, um, um])
    np.testing.assert_array_equal(result, zero)


def test_median_stack_returns_uint8():
    m = np.zeros((3, 3), np.uint8)
    result = medir_grama.median_stack([m, m, m])
    assert result.dtype == np.uint8


def test_median_stack_shape_matches_input():
    m = np.zeros((10, 20), np.uint8)
    result = medir_grama.median_stack([m, m, m])
    assert result.shape == (10, 20)


# --- apply_mask --------------------------------------------------------------
def test_apply_mask_pure_green_becomes_255():
    frame = np.zeros((30, 30, 3), np.uint8)
    frame[:, :] = (0, 180, 0)  # verde puro em BGR
    result = medir_grama.apply_mask(frame)
    assert result.shape == (30, 30)
    assert result.dtype == np.uint8
    assert (result == 255).all()


def test_apply_mask_pure_black_becomes_0():
    frame = np.zeros((30, 30, 3), np.uint8)
    result = medir_grama.apply_mask(frame)
    assert (result == 0).all()


def test_apply_mask_pure_red_becomes_0():
    frame = np.zeros((30, 30, 3), np.uint8)
    frame[:, :] = (0, 0, 200)  # vermelho em BGR
    result = medir_grama.apply_mask(frame)
    assert (result == 0).all()


def test_apply_mask_removes_isolated_green_pixel_via_morfologia():
    # 1 pixel verde solto no meio de preto — o open 3×3 deve engolir
    frame = np.zeros((30, 30, 3), np.uint8)
    frame[15, 15] = (0, 180, 0)
    result = medir_grama.apply_mask(frame)
    assert result[15, 15] == 0


# --- countdown ---------------------------------------------------------------
def test_countdown_prints_countdown_and_snap(capsys, monkeypatch):
    monkeypatch.setattr(medir_grama.time, "sleep", lambda s: None)
    medir_grama.countdown(3)
    out = capsys.readouterr().out
    assert "3" in out and "2" in out and "1" in out
    assert "snap" in out.lower()


def test_countdown_zero_seconds_still_prints_snap(capsys, monkeypatch):
    monkeypatch.setattr(medir_grama.time, "sleep", lambda s: None)
    medir_grama.countdown(0)
    out = capsys.readouterr().out
    assert "snap" in out.lower()


# --- print_report ------------------------------------------------------------
def test_print_report_contains_alturas_mediana_e_categoria(capsys):
    medir_grama.print_report([5.2, 6.1, 5.5], 5.5, 0.45, "MÉDIA")
    out = capsys.readouterr().out
    assert "5,2 cm" in out
    assert "6,1 cm" in out
    assert "5,5 cm" in out
    assert "MÉDIA" in out


def test_print_report_handles_none_alturas(capsys):
    medir_grama.print_report([None, None, None], None, None, "AUSENTE")
    out = capsys.readouterr().out
    assert "AUSENTE" in out
    assert "—" in out  # placeholder pra None


def test_print_report_com_margem_imprime_no_output(capsys):
    medir_grama.print_report([2.5, 3.0, 3.5], 3.0, 0.5, "BAIXA")
    out = capsys.readouterr().out
    assert "3,0 cm ± 0,5 cm" in out


def test_print_report_sem_margem_imprime_placeholder(capsys):
    medir_grama.print_report([2.5, None, None], 2.5, None, "BAIXA")
    out = capsys.readouterr().out
    assert "2,5 cm ± —" in out


# --- capture_frames ----------------------------------------------------------
class _FakeCapOK:
    """Fake VideoCapture que sempre retorna frames válidos."""
    def isOpened(self):
        return True
    def read(self):
        return True, np.zeros((480, 640, 3), np.uint8)
    def release(self):
        pass


class _FakeCapNotOpened:
    def isOpened(self):
        return False
    def release(self):
        pass


class _FakeCapReadFails:
    def isOpened(self):
        return True
    def read(self):
        return False, None
    def release(self):
        pass


class _FakeCapFirstOkThenFails:
    """Retorna n_ok frames válidos, depois sempre falha."""
    def __init__(self, n_ok):
        self.n_ok = n_ok
        self.calls = 0
    def isOpened(self):
        return True
    def read(self):
        self.calls += 1
        if self.calls <= self.n_ok:
            return True, np.zeros((480, 640, 3), np.uint8)
        return False, None
    def release(self):
        pass


def test_capture_frames_returns_n_frames(monkeypatch):
    monkeypatch.setattr(medir_grama.cv2, "VideoCapture", lambda *a, **kw: _FakeCapOK())
    frames = medir_grama.capture_frames(5, 0, medir_grama.cv2.CAP_MSMF)
    assert len(frames) == 5
    assert all(f.shape == (480, 640, 3) for f in frames)
    assert all(f.dtype == np.uint8 for f in frames)


def test_capture_frames_raises_when_camera_wont_open(monkeypatch):
    monkeypatch.setattr(medir_grama.cv2, "VideoCapture", lambda *a, **kw: _FakeCapNotOpened())
    with pytest.raises(RuntimeError, match="webcam"):
        medir_grama.capture_frames(5, 0, medir_grama.cv2.CAP_MSMF)


def test_capture_frames_raises_when_all_reads_fail(monkeypatch):
    monkeypatch.setattr(medir_grama.cv2, "VideoCapture", lambda *a, **kw: _FakeCapReadFails())
    with pytest.raises(RuntimeError):
        medir_grama.capture_frames(5, 0, medir_grama.cv2.CAP_MSMF)


def test_capture_frames_partial_capture_prints_warning(monkeypatch, capsys):
    monkeypatch.setattr(
        medir_grama.cv2, "VideoCapture", lambda *a, **kw: _FakeCapFirstOkThenFails(3)
    )
    frames = medir_grama.capture_frames(5, 0, medir_grama.cv2.CAP_MSMF)
    assert len(frames) == 3
    err = capsys.readouterr().err
    assert "AVISO" in err
    assert "3/5" in err


# --- save_debug --------------------------------------------------------------
def test_save_debug_creates_png_file(tmp_path):
    frame = np.zeros((480, 640, 3), np.uint8)
    mask = np.zeros((480, 640), np.uint8)
    out = tmp_path / "out.png"
    medir_grama.save_debug(
        frame, mask,
        top_ys=[200, 220, 210],
        alturas_cm=[27.5, 25.0, 26.25],
        altura_mediana_cm=26.25,
        margem_cm=1.25,
        col_fractions=(0.25, 0.5, 0.75),
        y_chao=420,
        px_por_cm=8.0,
        categoria="ALTA",
        path=str(out),
    )
    assert out.exists()
    assert out.stat().st_size > 0


def test_save_debug_creates_parent_directory(tmp_path):
    frame = np.zeros((480, 640, 3), np.uint8)
    mask = np.zeros((480, 640), np.uint8)
    out = tmp_path / "sub" / "dir" / "out.png"
    medir_grama.save_debug(
        frame, mask,
        top_ys=[None, None, None],
        alturas_cm=[None, None, None],
        altura_mediana_cm=None,
        margem_cm=None,
        col_fractions=(0.25, 0.5, 0.75),
        y_chao=420, px_por_cm=8.0, categoria="AUSENTE",
        path=str(out),
    )
    assert out.exists()


def test_save_debug_does_not_raise_on_write_failure(tmp_path, capsys, monkeypatch):
    frame = np.zeros((480, 640, 3), np.uint8)
    mask = np.zeros((480, 640), np.uint8)
    monkeypatch.setattr(medir_grama.cv2, "imwrite", lambda *a, **kw: False)
    medir_grama.save_debug(
        frame, mask,
        top_ys=[400, 400, 400],
        alturas_cm=[2.5, 2.5, 2.5],
        altura_mediana_cm=2.5,
        margem_cm=0.0,
        col_fractions=(0.25, 0.5, 0.75),
        y_chao=420, px_por_cm=8.0, categoria="BAIXA",
        path=str(tmp_path / "x.png"),
    )
    assert "AVISO" in capsys.readouterr().err


def test_save_debug_desenha_linha_do_chao_branca(tmp_path, monkeypatch):
    """Confirma que a linha branca do chão é desenhada no y_chao correto."""
    frame = np.zeros((480, 640, 3), np.uint8)
    mask = np.zeros((480, 640), np.uint8)
    linhas_brancas_grossas = []
    original_line = medir_grama.cv2.line

    def spy(img, pt1, pt2, color, thickness=1, *a, **kw):
        if color == (255, 255, 255) and thickness == 2:
            linhas_brancas_grossas.append((pt1, pt2))
        return original_line(img, pt1, pt2, color, thickness, *a, **kw)

    monkeypatch.setattr(medir_grama.cv2, "line", spy)
    medir_grama.save_debug(
        frame, mask,
        top_ys=[300, 300, 300],
        alturas_cm=[15.0, 15.0, 15.0],
        altura_mediana_cm=15.0,
        margem_cm=0.0,
        col_fractions=(0.25, 0.5, 0.75),
        y_chao=420, px_por_cm=8.0, categoria="ALTA",
        path=str(tmp_path / "c.png"),
    )
    # Deve ter desenhado ao menos uma linha branca grossa na horizontal em y=420
    horizontais = [
        (p1, p2) for p1, p2 in linhas_brancas_grossas
        if p1[1] == 420 and p2[1] == 420
    ]
    assert len(horizontais) >= 1


def test_save_debug_bolinha_colorida_por_categoria(tmp_path, monkeypatch):
    """Cada coluna deve ter bolinha desenhada com a cor da sua categoria."""
    frame = np.zeros((480, 640, 3), np.uint8)
    mask = np.zeros((480, 640), np.uint8)
    circles = []
    original_circle = medir_grama.cv2.circle

    def spy(img, center, radius, color, thickness, *a, **kw):
        circles.append((center, color))
        return original_circle(img, center, radius, color, thickness, *a, **kw)

    monkeypatch.setattr(medir_grama.cv2, "circle", spy)
    # Alturas: 2,5cm (BAIXA), 5,0cm (MÉDIA), 10,0cm (ALTA) com faixas 3/7
    medir_grama.save_debug(
        frame, mask,
        top_ys=[400, 380, 340],
        alturas_cm=[2.5, 5.0, 10.0],
        altura_mediana_cm=5.0,
        margem_cm=3.75,
        col_fractions=(0.25, 0.5, 0.75),
        y_chao=420, px_por_cm=8.0, categoria="MÉDIA",
        path=str(tmp_path / "c.png"),
    )
    cores = [color for _, color in circles]
    assert (0, 255, 0) in cores      # BAIXA — verde
    assert (0, 255, 255) in cores    # MÉDIA — amarelo
    assert (0, 0, 255) in cores      # ALTA — vermelho


def test_save_debug_titulo_contem_margem(tmp_path, monkeypatch):
    """O texto grande no topo deve incluir a margem ± cm."""
    frame = np.zeros((480, 640, 3), np.uint8)
    mask = np.zeros((480, 640), np.uint8)
    textos = []
    original_putText = medir_grama.cv2.putText

    def spy(img, text, org, font, scale, color, thickness, *a, **kw):
        textos.append(text)
        return original_putText(img, text, org, font, scale, color, thickness, *a, **kw)

    monkeypatch.setattr(medir_grama.cv2, "putText", spy)
    medir_grama.save_debug(
        frame, mask,
        top_ys=[400, 400, 400],
        alturas_cm=[2.5, 2.5, 2.5],
        altura_mediana_cm=2.5,
        margem_cm=0.3,
        col_fractions=(0.25, 0.5, 0.75),
        y_chao=420, px_por_cm=8.0, categoria="BAIXA",
        path=str(tmp_path / "t.png"),
    )
    juntos = " ".join(textos)
    assert "2,5 cm ± 0,3 cm" in juntos
    assert "BAIXA" in juntos


# --- main --------------------------------------------------------------------
def _fake_green_frames(n=5):
    """Frame 640×480 com verde na metade inferior (altura ≈ 240 px)."""
    frame = np.zeros((480, 640, 3), np.uint8)
    frame[240:, :] = (0, 180, 0)  # verde puro em BGR
    return [frame.copy() for _ in range(n)]


def _fake_calibration():
    return {"px_por_cm": 8.0, "y_chao": 420, "resolucao": [640, 480]}


def test_main_success_returns_zero(monkeypatch, tmp_path):
    monkeypatch.setattr(medir_grama, "load_calibration", lambda p: _fake_calibration())
    monkeypatch.setattr(medir_grama, "preview_camera", lambda *a, **kw: True)
    monkeypatch.setattr(medir_grama, "capture_frames", lambda *a, **kw: _fake_green_frames())
    monkeypatch.setattr(medir_grama, "countdown", lambda s: None)
    monkeypatch.setattr(medir_grama, "DEBUG_PATH", str(tmp_path / "out.png"))
    result = medir_grama.main([])
    assert result == 0
    assert (tmp_path / "out.png").exists()


def _explode(*a, **kw):
    raise AssertionError("não deveria ter sido chamado no modo --auto")


def test_main_auto_pula_preview(monkeypatch, tmp_path):
    """Pi sem monitor: preview travaria esperando tecla que nunca vem."""
    monkeypatch.setattr(medir_grama, "load_calibration", lambda p: _fake_calibration())
    monkeypatch.setattr(medir_grama, "preview_camera", _explode)
    monkeypatch.setattr(medir_grama, "countdown", lambda s: None)
    monkeypatch.setattr(
        medir_grama, "capture_frames", lambda *a, **kw: _fake_green_frames()
    )
    monkeypatch.setattr(medir_grama, "DEBUG_PATH", str(tmp_path / "out.png"))

    assert medir_grama.main(["--auto"]) == 0


def test_main_auto_pula_countdown(monkeypatch, tmp_path):
    """Countdown só faz sentido com humano presente."""
    monkeypatch.setattr(medir_grama, "load_calibration", lambda p: _fake_calibration())
    monkeypatch.setattr(medir_grama, "preview_camera", lambda *a, **kw: True)
    monkeypatch.setattr(medir_grama, "countdown", _explode)
    monkeypatch.setattr(
        medir_grama, "capture_frames", lambda *a, **kw: _fake_green_frames()
    )
    monkeypatch.setattr(medir_grama, "DEBUG_PATH", str(tmp_path / "out.png"))

    assert medir_grama.main(["--auto"]) == 0


def test_main_auto_ainda_envia_a_medicao(monkeypatch, tmp_path):
    enviadas = []
    monkeypatch.setattr(medir_grama, "load_calibration", lambda p: _fake_calibration())
    monkeypatch.setattr(medir_grama, "preview_camera", _explode)
    monkeypatch.setattr(medir_grama, "countdown", _explode)
    monkeypatch.setattr(
        medir_grama, "capture_frames", lambda *a, **kw: _fake_green_frames()
    )
    monkeypatch.setattr(medir_grama, "DEBUG_PATH", str(tmp_path / "out.png"))
    monkeypatch.setattr(
        medir_grama, "enviar_medicao",
        lambda a, c, r=None: enviadas.append((a, c, r)),
    )

    medir_grama.main(["--auto"])

    assert len(enviadas) == 1


def test_main_passa_regiao_da_calibration_pra_enviar_medicao(monkeypatch, tmp_path):
    """calibration.json vira fonte de verdade da identidade da estação."""
    enviadas = []

    def _calibration_com_regiao(_):
        cal = _fake_calibration()
        cal["regiao"] = "rodoanel norte"
        return cal

    monkeypatch.setattr(medir_grama, "load_calibration", _calibration_com_regiao)
    monkeypatch.setattr(medir_grama, "preview_camera", _explode)
    monkeypatch.setattr(medir_grama, "countdown", _explode)
    monkeypatch.setattr(
        medir_grama, "capture_frames", lambda *a, **kw: _fake_green_frames()
    )
    monkeypatch.setattr(medir_grama, "DEBUG_PATH", str(tmp_path / "out.png"))
    monkeypatch.setattr(
        medir_grama, "enviar_medicao",
        lambda a, c, r=None: enviadas.append((a, c, r)),
    )

    medir_grama.main(["--auto"])

    assert enviadas[0][2] == "rodoanel norte"


def test_main_sem_auto_continua_mostrando_preview(monkeypatch, tmp_path):
    """As 10 estações Windows seguem com preview — o padrão não muda."""
    chamou = []
    monkeypatch.setattr(medir_grama, "load_calibration", lambda p: _fake_calibration())
    monkeypatch.setattr(
        medir_grama, "preview_camera", lambda *a, **kw: chamou.append(1) or True
    )
    monkeypatch.setattr(medir_grama, "countdown", lambda s: None)
    monkeypatch.setattr(
        medir_grama, "capture_frames", lambda *a, **kw: _fake_green_frames()
    )
    monkeypatch.setattr(medir_grama, "DEBUG_PATH", str(tmp_path / "out.png"))

    medir_grama.main([])

    assert chamou == [1]


def test_main_missing_calibration_returns_one(monkeypatch, capsys):
    def raise_fnf(p):
        raise FileNotFoundError("calibration.json não encontrado. Rode: python calibrar.py")
    monkeypatch.setattr(medir_grama, "load_calibration", raise_fnf)
    result = medir_grama.main([])
    assert result == 1
    err = capsys.readouterr().err
    assert "ERRO" in err
    assert "calibrar" in err


def test_main_camera_failure_returns_one(monkeypatch, capsys):
    def raise_runtime(*a, **kw):
        raise RuntimeError("webcam nao acessivel")
    monkeypatch.setattr(medir_grama, "load_calibration", lambda p: _fake_calibration())
    monkeypatch.setattr(medir_grama, "preview_camera", lambda *a, **kw: True)
    monkeypatch.setattr(medir_grama, "countdown", lambda s: None)
    monkeypatch.setattr(medir_grama, "capture_frames", raise_runtime)
    result = medir_grama.main([])
    assert result == 1
    assert "ERRO" in capsys.readouterr().err


def test_main_keyboard_interrupt_returns_130(monkeypatch, capsys):
    def raise_kbint(*a, **kw):
        raise KeyboardInterrupt
    monkeypatch.setattr(medir_grama, "load_calibration", lambda p: _fake_calibration())
    monkeypatch.setattr(medir_grama, "preview_camera", lambda *a, **kw: True)
    monkeypatch.setattr(medir_grama, "countdown", raise_kbint)
    result = medir_grama.main([])
    assert result == 130
    assert "Cancelado" in capsys.readouterr().out


def test_main_no_green_detected_still_returns_zero_with_warning(monkeypatch, tmp_path, capsys):
    empty_frames = [np.zeros((480, 640, 3), np.uint8) for _ in range(5)]
    monkeypatch.setattr(medir_grama, "load_calibration", lambda p: _fake_calibration())
    monkeypatch.setattr(medir_grama, "preview_camera", lambda *a, **kw: True)
    monkeypatch.setattr(medir_grama, "capture_frames", lambda *a, **kw: empty_frames)
    monkeypatch.setattr(medir_grama, "countdown", lambda s: None)
    monkeypatch.setattr(medir_grama, "DEBUG_PATH", str(tmp_path / "out.png"))
    result = medir_grama.main([])
    assert result == 0
    assert "nenhuma grama" in capsys.readouterr().err.lower()


def test_main_reports_altura_em_cm(monkeypatch, tmp_path, capsys):
    """End-to-end: frames com verde na parte inferior → output com valor em cm."""
    monkeypatch.setattr(medir_grama, "load_calibration", lambda p: _fake_calibration())
    monkeypatch.setattr(medir_grama, "preview_camera", lambda *a, **kw: True)
    monkeypatch.setattr(medir_grama, "capture_frames", lambda *a, **kw: _fake_green_frames())
    monkeypatch.setattr(medir_grama, "countdown", lambda s: None)
    monkeypatch.setattr(medir_grama, "DEBUG_PATH", str(tmp_path / "out.png"))
    result = medir_grama.main([])
    assert result == 0
    out = capsys.readouterr().out
    # Verde começa em y=240, chão y=420, px/cm=8 → altura = (420-240)/8 = 22.5cm
    assert "22,5 cm" in out
    assert "ALTA" in out


def test_main_output_inclui_margem_de_erro(monkeypatch, tmp_path, capsys):
    """End-to-end: output do main() deve conter '± ... cm' na linha da mediana."""
    monkeypatch.setattr(medir_grama, "load_calibration", lambda p: _fake_calibration())
    monkeypatch.setattr(medir_grama, "preview_camera", lambda *a, **kw: True)
    monkeypatch.setattr(medir_grama, "capture_frames", lambda *a, **kw: _fake_green_frames())
    monkeypatch.setattr(medir_grama, "countdown", lambda s: None)
    monkeypatch.setattr(medir_grama, "DEBUG_PATH", str(tmp_path / "out.png"))
    result = medir_grama.main([])
    assert result == 0
    out = capsys.readouterr().out
    # _fake_green_frames tem verde uniforme → 3 colunas com mesma altura →
    # amplitude = 0 → margem = 0,0 cm
    assert "±" in out
    assert "0,0 cm" in out  # margem calculada


# --- margem_erro_cm ----------------------------------------------------------
def test_margem_erro_cm_lista_vazia_returns_none():
    assert medir_grama.margem_erro_cm([]) is None


def test_margem_erro_cm_uma_valida_returns_none():
    assert medir_grama.margem_erro_cm([2.0]) is None


def test_margem_erro_cm_uma_valida_com_nones_returns_none():
    assert medir_grama.margem_erro_cm([2.0, None, None]) is None


def test_margem_erro_cm_duas_validas_returns_metade_da_amplitude():
    # (4.0 - 2.0) / 2 = 1.0
    assert medir_grama.margem_erro_cm([2.0, 4.0]) == 1.0


def test_margem_erro_cm_tres_validas_ignora_ordem():
    # (4.0 - 2.0) / 2 = 1.0, independente da ordem
    assert medir_grama.margem_erro_cm([2.0, 3.0, 4.0]) == 1.0
    assert medir_grama.margem_erro_cm([4.0, 2.0, 3.0]) == 1.0


def test_margem_erro_cm_todas_iguais_returns_zero():
    assert medir_grama.margem_erro_cm([3.0, 3.0, 3.0]) == 0.0


def test_margem_erro_cm_ignora_none_no_calculo():
    # Só 2.0 e 4.0 contam → (4-2)/2 = 1.0
    assert medir_grama.margem_erro_cm([None, 2.0, 4.0, None]) == 1.0


# --- _formatar_mediana_com_margem --------------------------------------------
def test_formatar_mediana_com_margem_mediana_none_returns_placeholder():
    assert medir_grama._formatar_mediana_com_margem(None, None) == "—"
    assert medir_grama._formatar_mediana_com_margem(None, 0.4) == "—"


def test_formatar_mediana_com_margem_sem_margem_mostra_placeholder():
    assert medir_grama._formatar_mediana_com_margem(2.8, None) == "2,8 cm ± —"


def test_formatar_mediana_com_margem_com_valor():
    assert medir_grama._formatar_mediana_com_margem(2.8, 0.4) == "2,8 cm ± 0,4 cm"


def test_formatar_mediana_com_margem_zero_ainda_imprime_zero():
    assert medir_grama._formatar_mediana_com_margem(3.0, 0.0) == "3,0 cm ± 0,0 cm"


# --- _draw_legenda_niveis -------------------------------------------------------
def test_draw_legenda_niveis_modifica_imagem():
    """Smoke test: desenhar em preto deve deixar algum pixel != 0."""
    img = np.zeros((60, 800, 3), np.uint8)
    medir_grama._draw_legenda_niveis(img, 3.0, 7.0)
    assert (img > 0).any(), "esperava pixels desenhados na imagem"


def test_draw_legenda_niveis_usa_todas_cores_dos_niveis():
    """Cada uma das 4 cores de nível deve aparecer na imagem."""
    img = np.zeros((60, 800, 3), np.uint8)
    medir_grama._draw_legenda_niveis(img, 3.0, 7.0)
    # Confere que cada cor BGR aparece em pelo menos 1 pixel.
    for cor in medir_grama.LEVEL_COLORS_BGR:
        b, g, r = cor
        match = (img[:, :, 0] == b) & (img[:, :, 1] == g) & (img[:, :, 2] == r)
        assert match.any(), f"cor {cor} nao aparece na legenda"


# --- enviar_medicao ----------------------------------------------------------
class _RespostaFake:
    def raise_for_status(self):
        pass

    def json(self):
        return {"id": 1, "clima": "Nublado"}


def test_enviar_medicao_inclui_regiao_do_env(monkeypatch):
    """Cada estação se identifica, senão medições de locais diferentes colidem."""
    enviados = {}
    chamada = {}

    def _fake_post(url, json, headers, timeout):
        chamada["url"] = url
        enviados.update(json)
        return _RespostaFake()

    monkeypatch.setattr(medir_grama.requests, "post", _fake_post)
    monkeypatch.setattr(medir_grama, "API_KEY_WRITE", "chave")
    monkeypatch.setattr(medir_grama, "REGIAO", "rodoanel norte")

    medir_grama.enviar_medicao(5.2, "MÉDIA")

    # URL é a única string em enviar_medicao cuja falha é muda: se o path
    # estiver errado, a estação mede, tenta enviar e perde a leitura só com
    # um AVISO no stderr — que ninguém lê numa Raspberry Pi na beira da estrada.
    assert chamada["url"] == f"{medir_grama.API_URL}/leituras"
    assert enviados["regiao"] == "rodoanel norte"
    assert enviados["altura_cm"] == 5.2
    assert enviados["nivel_risco"] == "MEDIA"


def test_enviar_medicao_usa_chave_de_escrita_no_header(monkeypatch):
    """A estação escreve, então carrega API_KEY_WRITE — nunca a de leitura."""
    capturado = {}

    def _fake_post(url, json, headers, timeout):
        capturado.update(headers)
        return _RespostaFake()

    monkeypatch.setattr(medir_grama.requests, "post", _fake_post)
    monkeypatch.setattr(medir_grama, "API_KEY_WRITE", "chave-de-escrita")
    monkeypatch.setattr(medir_grama, "REGIAO", "oeste")

    medir_grama.enviar_medicao(5.2, "MÉDIA")

    assert capturado["X-API-Key"] == "chave-de-escrita"


def test_enviar_medicao_usa_timeout_generoso(monkeypatch):
    """Render free hiberna; acordar leva ~50s. Timeout curto perde a medição."""
    capturado = {}

    def _fake_post(url, json, headers, timeout):
        capturado["timeout"] = timeout
        return _RespostaFake()

    monkeypatch.setattr(medir_grama.requests, "post", _fake_post)
    monkeypatch.setattr(medir_grama, "API_KEY_WRITE", "chave")
    monkeypatch.setattr(medir_grama, "REGIAO", "norte")

    medir_grama.enviar_medicao(5.2, "MÉDIA")

    assert capturado["timeout"] >= 60


def test_enviar_medicao_repete_apos_timeout(monkeypatch, capsys):
    """1ª tentativa acorda o Render, 2ª entrega o dado."""
    tentativas = []

    def _fake_post(url, json, headers, timeout):
        tentativas.append(1)
        if len(tentativas) == 1:
            raise medir_grama.requests.Timeout("servico hibernando")
        return _RespostaFake()

    monkeypatch.setattr(medir_grama.requests, "post", _fake_post)
    monkeypatch.setattr(medir_grama, "API_KEY_WRITE", "chave")
    monkeypatch.setattr(medir_grama, "REGIAO", "norte")

    medir_grama.enviar_medicao(5.2, "MÉDIA")

    assert len(tentativas) == 2
    assert "OK: medição enviada" in capsys.readouterr().out


def test_enviar_medicao_nao_repete_quando_api_rejeita(monkeypatch):
    """401/422 é erro de chave ou payload — repetir não conserta nada."""
    tentativas = []

    class _Resp401:
        status_code = 401
        text = "API key inválida"

        def raise_for_status(self):
            erro = medir_grama.requests.HTTPError("401")
            erro.response = self
            raise erro

    def _fake_post(url, json, headers, timeout):
        tentativas.append(1)
        return _Resp401()

    monkeypatch.setattr(medir_grama.requests, "post", _fake_post)
    monkeypatch.setattr(medir_grama, "API_KEY_WRITE", "chave-errada")
    monkeypatch.setattr(medir_grama, "REGIAO", "norte")

    medir_grama.enviar_medicao(5.2, "MÉDIA")

    assert len(tentativas) == 1


def test_enviar_medicao_avisa_quando_todas_tentativas_falham(monkeypatch, capsys):
    def _fake_post(url, json, headers, timeout):
        raise medir_grama.requests.Timeout("sem resposta")

    monkeypatch.setattr(medir_grama.requests, "post", _fake_post)
    monkeypatch.setattr(medir_grama, "API_KEY_WRITE", "chave")
    monkeypatch.setattr(medir_grama, "REGIAO", "norte")

    medir_grama.enviar_medicao(5.2, "MÉDIA")

    assert "AVISO" in capsys.readouterr().err


def test_enviar_medicao_com_altura_none_envia_zero(monkeypatch):
    """AUSENTE não tem mediana; manda 0.0 pra API não rejeitar."""
    enviados = {}

    def _fake_post(url, json, headers, timeout):
        enviados.update(json)
        return _RespostaFake()

    monkeypatch.setattr(medir_grama.requests, "post", _fake_post)
    monkeypatch.setattr(medir_grama, "API_KEY_WRITE", "chave")
    monkeypatch.setattr(medir_grama, "REGIAO", "leste")

    medir_grama.enviar_medicao(None, "AUSENTE")

    assert enviados["altura_cm"] == 0.0
    assert enviados["nivel_risco"] == "AUSENTE"


def test_enviar_medicao_inclui_clima_quando_buscar_clima_retorna_valores(monkeypatch):
    """Estação fetch-a Open-Meteo antes de postar e inclui no payload."""
    enviados = {}

    def _fake_post(url, json, headers, timeout):
        enviados.update(json)
        return _RespostaFake()

    monkeypatch.setattr(medir_grama.requests, "post", _fake_post)
    monkeypatch.setattr(medir_grama, "buscar_clima", lambda lat, lon: (22.3, "Ensolarado"))
    monkeypatch.setattr(medir_grama, "API_KEY_WRITE", "chave")
    monkeypatch.setattr(medir_grama, "REGIAO", "norte")

    medir_grama.enviar_medicao(5.2, "MÉDIA")

    assert enviados["temperatura_c"] == 22.3
    assert enviados["clima"] == "Ensolarado"


def test_enviar_medicao_regiao_explicita_vence_env(monkeypatch):
    """Calibration.json é fonte de verdade; .env é só fallback pra estações
    antigas que não recalibraram ainda."""
    enviados = {}

    def _fake_post(url, json, headers, timeout):
        enviados.update(json)
        return _RespostaFake()

    monkeypatch.setattr(medir_grama.requests, "post", _fake_post)
    monkeypatch.setattr(medir_grama, "API_KEY_WRITE", "chave")
    monkeypatch.setattr(medir_grama, "REGIAO", "envval-antigo")

    medir_grama.enviar_medicao(5.2, "MÉDIA", regiao="calibrado-novo")

    assert enviados["regiao"] == "calibrado-novo"


def test_enviar_medicao_cai_no_env_quando_regiao_none(monkeypatch):
    """Estação antiga sem regiao na calibration.json continua funcionando."""
    enviados = {}

    def _fake_post(url, json, headers, timeout):
        enviados.update(json)
        return _RespostaFake()

    monkeypatch.setattr(medir_grama.requests, "post", _fake_post)
    monkeypatch.setattr(medir_grama, "API_KEY_WRITE", "chave")
    monkeypatch.setattr(medir_grama, "REGIAO", "fallback-env")

    medir_grama.enviar_medicao(5.2, "MÉDIA", regiao=None)

    assert enviados["regiao"] == "fallback-env"


def test_enviar_medicao_sem_regiao_em_lugar_nenhum_avisa(monkeypatch, capsys):
    """Sem calibration.json e sem .env: aviso claro, não envia."""
    chamou = False

    def _fake_post(*a, **k):
        nonlocal chamou
        chamou = True
        return _RespostaFake()

    monkeypatch.setattr(medir_grama.requests, "post", _fake_post)
    monkeypatch.setattr(medir_grama, "API_KEY_WRITE", "chave")
    monkeypatch.setattr(medir_grama, "REGIAO", None)

    medir_grama.enviar_medicao(5.2, "MÉDIA", regiao=None)

    assert chamou is False
    assert "regiao" in capsys.readouterr().err.lower()


def test_enviar_medicao_omite_clima_quando_open_meteo_falha(monkeypatch):
    """Falha silenciosa do Open-Meteo (autouse stub) → payload sem clima."""
    enviados = {}

    def _fake_post(url, json, headers, timeout):
        enviados.update(json)
        return _RespostaFake()

    monkeypatch.setattr(medir_grama.requests, "post", _fake_post)
    monkeypatch.setattr(medir_grama, "API_KEY_WRITE", "chave")
    monkeypatch.setattr(medir_grama, "REGIAO", "norte")

    medir_grama.enviar_medicao(5.2, "MÉDIA")

    assert "temperatura_c" not in enviados
    assert "clima" not in enviados
