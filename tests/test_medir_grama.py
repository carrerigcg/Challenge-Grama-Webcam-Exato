"""Testes das funções puras de medir_grama."""
import numpy as np
import pytest

import medir_grama


# --- classify_column ---------------------------------------------------------
# Frame de referência: altura 480 → chão y=432, sep1 y=288, sep2 y=168.

def test_classify_column_none_is_ausente():
    assert medir_grama.classify_column(None, 480, (0.90, 0.60, 0.35)) == 0


def test_classify_column_below_sep1_is_baixa():
    # y_topo=400 está abaixo de sep1(288) → BAIXA
    assert medir_grama.classify_column(400, 480, (0.90, 0.60, 0.35)) == 1


def test_classify_column_exactly_at_sep1_is_media():
    # borda: y_topo == sep1 → conta como atingiu → MÉDIA
    assert medir_grama.classify_column(288, 480, (0.90, 0.60, 0.35)) == 2


def test_classify_column_between_sep1_and_sep2_is_media():
    assert medir_grama.classify_column(220, 480, (0.90, 0.60, 0.35)) == 2


def test_classify_column_exactly_at_sep2_is_alta():
    assert medir_grama.classify_column(168, 480, (0.90, 0.60, 0.35)) == 3


def test_classify_column_above_sep2_is_alta():
    assert medir_grama.classify_column(50, 480, (0.90, 0.60, 0.35)) == 3


def test_classify_column_at_top_is_alta():
    assert medir_grama.classify_column(0, 480, (0.90, 0.60, 0.35)) == 3


# --- classify_frame ----------------------------------------------------------
def test_classify_frame_all_baixa_returns_baixa():
    result = medir_grama.classify_frame([400, 400, 400], 480, (0.90, 0.60, 0.35))
    assert result == (1, "BAIXA")


def test_classify_frame_mediana_between_niveis():
    # (1, 2, 3) → mediana = 2 → MÉDIA
    result = medir_grama.classify_frame([400, 220, 50], 480, (0.90, 0.60, 0.35))
    assert result == (2, "MÉDIA")


def test_classify_frame_all_ausente_returns_ausente():
    result = medir_grama.classify_frame([None, None, None], 480, (0.90, 0.60, 0.35))
    assert result == (0, "AUSENTE")


def test_classify_frame_mixed_ausente_and_baixa():
    # (0, 0, 1) → mediana = 0 → AUSENTE
    result = medir_grama.classify_frame([None, None, 400], 480, (0.90, 0.60, 0.35))
    assert result == (0, "AUSENTE")


def test_classify_frame_all_alta_returns_alta():
    result = medir_grama.classify_frame([50, 100, 150], 480, (0.90, 0.60, 0.35))
    assert result == (3, "ALTA")


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
def test_print_report_contains_top_ys_niveis_and_categoria(capsys):
    medir_grama.print_report([300, 220, 180], [1, 2, 2], "MÉDIA")
    out = capsys.readouterr().out
    assert "300" in out
    assert "220" in out
    assert "180" in out
    assert "MÉDIA" in out
    assert "níveis" in out
    assert "[1, 2, 2]" in out


def test_print_report_handles_none_top_ys(capsys):
    medir_grama.print_report([None, None, None], [0, 0, 0], "AUSENTE")
    out = capsys.readouterr().out
    assert "AUSENTE" in out
    assert "None" in out


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
        frame, mask, [200, 220, 210], (0.25, 0.5, 0.75),
        (0.90, 0.60, 0.35), 2, "MÉDIA", str(out),
    )
    assert out.exists()
    assert out.stat().st_size > 0


def test_save_debug_creates_parent_directory(tmp_path):
    frame = np.zeros((480, 640, 3), np.uint8)
    mask = np.zeros((480, 640), np.uint8)
    out = tmp_path / "sub" / "dir" / "out.png"
    medir_grama.save_debug(
        frame, mask, [None, None, None], (0.25, 0.5, 0.75),
        (0.90, 0.60, 0.35), 0, "AUSENTE", str(out),
    )
    assert out.exists()


def test_save_debug_does_not_raise_on_write_failure(tmp_path, capsys, monkeypatch):
    frame = np.zeros((480, 640, 3), np.uint8)
    mask = np.zeros((480, 640), np.uint8)
    monkeypatch.setattr(medir_grama.cv2, "imwrite", lambda *a, **kw: False)
    medir_grama.save_debug(
        frame, mask, [400, 400, 400], (0.25, 0.5, 0.75),
        (0.90, 0.60, 0.35), 1, "BAIXA", str(tmp_path / "x.png"),
    )
    assert "AVISO" in capsys.readouterr().err


def test_save_debug_draws_green_highlight_for_media(tmp_path, monkeypatch):
    """Quando nivel_final == 2 (MÉDIA), destaca sep1 em verde grosso."""
    frame = np.zeros((480, 640, 3), np.uint8)
    mask = np.zeros((480, 640), np.uint8)
    linhas_grossas_verdes = []
    original_line = medir_grama.cv2.line

    def spy(img, pt1, pt2, color, thickness=1, *a, **kw):
        if color == (0, 255, 0) and thickness == 3:
            linhas_grossas_verdes.append((pt1, pt2))
        return original_line(img, pt1, pt2, color, thickness, *a, **kw)

    monkeypatch.setattr(medir_grama.cv2, "line", spy)
    medir_grama.save_debug(
        frame, mask, [220, 220, 220], (0.25, 0.5, 0.75),
        (0.90, 0.60, 0.35), 2, "MÉDIA", str(tmp_path / "m.png"),
    )
    assert len(linhas_grossas_verdes) == 1


def test_save_debug_draws_green_highlight_for_alta(tmp_path, monkeypatch):
    """Quando nivel_final == 3 (ALTA), destaca sep2 em verde grosso."""
    frame = np.zeros((480, 640, 3), np.uint8)
    mask = np.zeros((480, 640), np.uint8)
    linhas_grossas_verdes = []
    original_line = medir_grama.cv2.line

    def spy(img, pt1, pt2, color, thickness=1, *a, **kw):
        if color == (0, 255, 0) and thickness == 3:
            linhas_grossas_verdes.append((pt1, pt2))
        return original_line(img, pt1, pt2, color, thickness, *a, **kw)

    monkeypatch.setattr(medir_grama.cv2, "line", spy)
    medir_grama.save_debug(
        frame, mask, [50, 50, 50], (0.25, 0.5, 0.75),
        (0.90, 0.60, 0.35), 3, "ALTA", str(tmp_path / "a.png"),
    )
    assert len(linhas_grossas_verdes) == 1


def test_save_debug_no_green_highlight_for_baixa_or_ausente(tmp_path, monkeypatch):
    """Quando nivel_final < 2 (BAIXA ou AUSENTE), não desenha o destaque verde."""
    frame = np.zeros((480, 640, 3), np.uint8)
    mask = np.zeros((480, 640), np.uint8)
    linhas_grossas_verdes = []
    original_line = medir_grama.cv2.line

    def spy(img, pt1, pt2, color, thickness=1, *a, **kw):
        if color == (0, 255, 0) and thickness == 3:
            linhas_grossas_verdes.append((pt1, pt2))
        return original_line(img, pt1, pt2, color, thickness, *a, **kw)

    monkeypatch.setattr(medir_grama.cv2, "line", spy)
    medir_grama.save_debug(
        frame, mask, [400, 400, 400], (0.25, 0.5, 0.75),
        (0.90, 0.60, 0.35), 1, "BAIXA", str(tmp_path / "b.png"),
    )
    medir_grama.save_debug(
        frame, mask, [None, None, None], (0.25, 0.5, 0.75),
        (0.90, 0.60, 0.35), 0, "AUSENTE", str(tmp_path / "au.png"),
    )
    assert linhas_grossas_verdes == []


# --- main --------------------------------------------------------------------
def _fake_green_frames(n=5):
    """Frame 640×480 com verde na metade inferior (altura ≈ 240 px)."""
    frame = np.zeros((480, 640, 3), np.uint8)
    frame[240:, :] = (0, 180, 0)  # verde puro em BGR
    return [frame.copy() for _ in range(n)]


def test_main_success_returns_zero(monkeypatch, tmp_path):
    monkeypatch.setattr(medir_grama, "preview_camera", lambda *a, **kw: True)
    monkeypatch.setattr(medir_grama, "capture_frames", lambda *a, **kw: _fake_green_frames())
    monkeypatch.setattr(medir_grama, "countdown", lambda s: None)
    monkeypatch.setattr(medir_grama, "DEBUG_PATH", str(tmp_path / "out.png"))
    result = medir_grama.main()
    assert result == 0
    assert (tmp_path / "out.png").exists()


def test_main_camera_failure_returns_one(monkeypatch, capsys):
    def raise_runtime(*a, **kw):
        raise RuntimeError("webcam nao acessivel")
    monkeypatch.setattr(medir_grama, "preview_camera", lambda *a, **kw: True)
    monkeypatch.setattr(medir_grama, "countdown", lambda s: None)
    monkeypatch.setattr(medir_grama, "capture_frames", raise_runtime)
    result = medir_grama.main()
    assert result == 1
    assert "ERRO" in capsys.readouterr().err


def test_main_keyboard_interrupt_returns_130(monkeypatch, capsys):
    def raise_kbint(*a, **kw):
        raise KeyboardInterrupt
    monkeypatch.setattr(medir_grama, "preview_camera", lambda *a, **kw: True)
    monkeypatch.setattr(medir_grama, "countdown", raise_kbint)
    result = medir_grama.main()
    assert result == 130
    assert "Cancelado" in capsys.readouterr().out


def test_main_no_green_detected_still_returns_zero_with_warning(monkeypatch, tmp_path, capsys):
    empty_frames = [np.zeros((480, 640, 3), np.uint8) for _ in range(5)]
    monkeypatch.setattr(medir_grama, "preview_camera", lambda *a, **kw: True)
    monkeypatch.setattr(medir_grama, "capture_frames", lambda *a, **kw: empty_frames)
    monkeypatch.setattr(medir_grama, "countdown", lambda s: None)
    monkeypatch.setattr(medir_grama, "DEBUG_PATH", str(tmp_path / "out.png"))
    result = medir_grama.main()
    assert result == 0
    assert "nenhuma grama" in capsys.readouterr().err.lower()
