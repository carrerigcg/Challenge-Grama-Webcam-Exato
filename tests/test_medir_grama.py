"""Testes das funções puras de medir_grama."""
import json

import numpy as np
import pytest

import medir_grama


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
    medir_grama.print_report([5.2, 6.1, 5.5], 5.5, "MÉDIA")
    out = capsys.readouterr().out
    assert "5,2 cm" in out
    assert "6,1 cm" in out
    assert "5,5 cm" in out
    assert "MÉDIA" in out


def test_print_report_handles_none_alturas(capsys):
    medir_grama.print_report([None, None, None], None, "AUSENTE")
    out = capsys.readouterr().out
    assert "AUSENTE" in out
    assert "—" in out  # placeholder pra None


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
    result = medir_grama.main()
    assert result == 0
    assert (tmp_path / "out.png").exists()


def test_main_missing_calibration_returns_one(monkeypatch, capsys):
    def raise_fnf(p):
        raise FileNotFoundError("calibration.json não encontrado. Rode: python calibrar.py")
    monkeypatch.setattr(medir_grama, "load_calibration", raise_fnf)
    result = medir_grama.main()
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
    result = medir_grama.main()
    assert result == 1
    assert "ERRO" in capsys.readouterr().err


def test_main_keyboard_interrupt_returns_130(monkeypatch, capsys):
    def raise_kbint(*a, **kw):
        raise KeyboardInterrupt
    monkeypatch.setattr(medir_grama, "load_calibration", lambda p: _fake_calibration())
    monkeypatch.setattr(medir_grama, "preview_camera", lambda *a, **kw: True)
    monkeypatch.setattr(medir_grama, "countdown", raise_kbint)
    result = medir_grama.main()
    assert result == 130
    assert "Cancelado" in capsys.readouterr().out


def test_main_no_green_detected_still_returns_zero_with_warning(monkeypatch, tmp_path, capsys):
    empty_frames = [np.zeros((480, 640, 3), np.uint8) for _ in range(5)]
    monkeypatch.setattr(medir_grama, "load_calibration", lambda p: _fake_calibration())
    monkeypatch.setattr(medir_grama, "preview_camera", lambda *a, **kw: True)
    monkeypatch.setattr(medir_grama, "capture_frames", lambda *a, **kw: empty_frames)
    monkeypatch.setattr(medir_grama, "countdown", lambda s: None)
    monkeypatch.setattr(medir_grama, "DEBUG_PATH", str(tmp_path / "out.png"))
    result = medir_grama.main()
    assert result == 0
    assert "nenhuma grama" in capsys.readouterr().err.lower()


def test_main_reports_altura_em_cm(monkeypatch, tmp_path, capsys):
    """End-to-end: frames com verde na parte inferior → output com valor em cm."""
    monkeypatch.setattr(medir_grama, "load_calibration", lambda p: _fake_calibration())
    monkeypatch.setattr(medir_grama, "preview_camera", lambda *a, **kw: True)
    monkeypatch.setattr(medir_grama, "capture_frames", lambda *a, **kw: _fake_green_frames())
    monkeypatch.setattr(medir_grama, "countdown", lambda s: None)
    monkeypatch.setattr(medir_grama, "DEBUG_PATH", str(tmp_path / "out.png"))
    result = medir_grama.main()
    assert result == 0
    out = capsys.readouterr().out
    # Verde começa em y=240, chão y=420, px/cm=8 → altura = (420-240)/8 = 22.5cm
    assert "22,5 cm" in out
    assert "ALTA" in out
