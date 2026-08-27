"""Testes da configuração de câmera por plataforma."""
import sys

import cv2
import pytest

import camera


# --- backend -----------------------------------------------------------------
def test_windows_usa_msmf(monkeypatch):
    monkeypatch.delenv("CAMERA_BACKEND", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    assert camera.detectar_backend() == cv2.CAP_MSMF


def test_linux_usa_v4l2(monkeypatch):
    """Raspberry Pi roda Linux; MSMF não existe lá."""
    monkeypatch.delenv("CAMERA_BACKEND", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    assert camera.detectar_backend() == cv2.CAP_V4L2


def test_env_var_sobrescreve_a_plataforma(monkeypatch):
    """Escape hatch: câmera CSI ou driver esquisito exigindo outro backend."""
    monkeypatch.setenv("CAMERA_BACKEND", "CAP_V4L2")
    monkeypatch.setattr(sys, "platform", "win32")
    assert camera.detectar_backend() == cv2.CAP_V4L2


def test_backend_inexistente_da_erro_claro(monkeypatch):
    monkeypatch.setenv("CAMERA_BACKEND", "CAP_TANTOFAZ")
    with pytest.raises(RuntimeError, match="CAMERA_BACKEND"):
        camera.detectar_backend()


def test_backend_que_nao_e_constante_de_captura_da_erro(monkeypatch):
    """cv2.imread existe, mas não é backend — não pode passar como válido."""
    monkeypatch.setenv("CAMERA_BACKEND", "imread")
    with pytest.raises(RuntimeError, match="CAMERA_BACKEND"):
        camera.detectar_backend()


# --- índice ------------------------------------------------------------------
def test_indice_default_e_zero(monkeypatch):
    monkeypatch.delenv("CAMERA_INDEX", raising=False)
    assert camera.detectar_indice() == 0


def test_indice_vem_do_env(monkeypatch):
    monkeypatch.setenv("CAMERA_INDEX", "2")
    assert camera.detectar_indice() == 2


def test_indice_invalido_da_erro_claro(monkeypatch):
    monkeypatch.setenv("CAMERA_INDEX", "a primeira")
    with pytest.raises(RuntimeError, match="CAMERA_INDEX"):
        camera.detectar_indice()
