"""Instalador dos hooks num settings.json temporário."""
from __future__ import annotations

import json
import os

import instalar

OUTRO = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo outro", "timeout": 3}]}


def _settings(tmp_path, conteudo):
    caminho = tmp_path / "settings.json"
    caminho.write_text(json.dumps(conteudo))
    return caminho


def _ler(caminho):
    return json.loads(caminho.read_text(encoding="utf-8"))


def _baks(tmp_path):
    return sorted(n for n in os.listdir(tmp_path) if n.startswith("settings.json.bak-"))


def test_acrescenta_mantendo_o_resto(tmp_path, capsys):
    caminho = _settings(tmp_path, {"model": "opus", "hooks": {"SessionStart": [OUTRO], "PreToolUse": [OUTRO]}})
    assert instalar.main(["--settings", str(caminho)]) == 0
    d = _ler(caminho)
    assert d["model"] == "opus"
    assert d["hooks"]["PreToolUse"] == [OUTRO]
    assert d["hooks"]["SessionStart"][0] == OUTRO
    meu = d["hooks"]["SessionStart"][1]["hooks"][0]
    assert meu["type"] == "command" and meu["timeout"] == 5
    assert d["hooks"]["SessionEnd"][0]["hooks"][0]["timeout"] == 10
    assert meu["command"].endswith('ferramentas/sessoes/sessao_inicio.py"')
    assert d["hooks"]["SessionEnd"][0]["hooks"][0]["command"].endswith('ferramentas/sessoes/sessao_fim.py"')
    assert len(_baks(tmp_path)) == 1


def test_idempotente(tmp_path):
    caminho = _settings(tmp_path, {"hooks": {"SessionStart": [OUTRO]}})
    instalar.main(["--settings", str(caminho)])
    primeira = caminho.read_text()
    assert instalar.main(["--settings", str(caminho)]) == 0
    assert caminho.read_text() == primeira
    assert len(_baks(tmp_path)) == 1  # segunda vez não muda nada, não faz cópia
    d = _ler(caminho)
    assert len(d["hooks"]["SessionStart"]) == 2 and len(d["hooks"]["SessionEnd"]) == 1


def test_troca_python_sem_duplicar(tmp_path):
    caminho = _settings(tmp_path, {})
    d = instalar.aplicar(_ler(caminho), python="/velho/python3")
    d = instalar.aplicar(d, python="/novo/python3")
    assert len(d["hooks"]["SessionEnd"]) == 1
    assert d["hooks"]["SessionEnd"][0]["hooks"][0]["command"].startswith('"/novo/python3"')


def test_remove_so_o_seu(tmp_path):
    caminho = _settings(tmp_path, {"theme": "dark", "hooks": {"SessionStart": [OUTRO]}})
    instalar.main(["--settings", str(caminho)])
    assert instalar.main(["--settings", str(caminho), "--remover"]) == 0
    assert _ler(caminho) == {"theme": "dark", "hooks": {"SessionStart": [OUTRO]}}


def test_remove_grupo_misto_mantem_o_outro_hook(tmp_path):
    meu = {"type": "command", "command": '"/x/python3" "/r/ferramentas/sessoes/sessao_fim.py"', "timeout": 10}
    outro = {"type": "command", "command": "echo fim"}
    d = instalar.aplicar({"hooks": {"SessionEnd": [{"hooks": [outro, meu]}]}}, remover=True)
    assert d == {"hooks": {"SessionEnd": [{"hooks": [outro]}]}}


def test_remove_tudo_tira_hooks_vazio(tmp_path):
    caminho = _settings(tmp_path, {"model": "opus"})
    instalar.main(["--settings", str(caminho)])
    instalar.main(["--settings", str(caminho), "--remover"])
    assert _ler(caminho) == {"model": "opus"}
    assert len(_baks(tmp_path)) >= 1


def test_mostrar_nao_grava(tmp_path, capsys):
    caminho = _settings(tmp_path, {"model": "opus"})
    assert instalar.main(["--settings", str(caminho), "--mostrar"]) == 0
    impresso = json.loads(capsys.readouterr().out)
    assert "SessionStart" in impresso["hooks"]
    assert _ler(caminho) == {"model": "opus"}
    assert _baks(tmp_path) == []


def test_settings_inexistente_e_criado_sem_backup(tmp_path):
    caminho = tmp_path / "novo" / "settings.json"
    assert instalar.main(["--settings", str(caminho)]) == 0
    assert "SessionEnd" in _ler(caminho)["hooks"]


def test_settings_quebrado_nao_mexe(tmp_path):
    caminho = tmp_path / "settings.json"
    caminho.write_text("{quebrado")
    assert instalar.main(["--settings", str(caminho)]) == 1
    assert caminho.read_text() == "{quebrado"
    assert _baks(tmp_path) == []


# --- Achados 6 e 7 do revisor do Passo 10 ---


def test_timeouts_e_grupo_sem_matcher(tmp_path):
    d = instalar.aplicar({}, python="/x/python3")
    inicio = d["hooks"]["SessionStart"][0]
    fim = d["hooks"]["SessionEnd"][0]
    assert inicio == {"hooks": [{"type": "command", "command": instalar.comando("sessao_inicio.py", "/x/python3"),
                                 "timeout": 5}]}
    assert fim["hooks"][0]["timeout"] == 10
    assert "matcher" not in inicio and "matcher" not in fim


def test_grupo_meu_com_matcher_e_trocado(tmp_path):
    d = instalar.aplicar({}, python="/x/python3")
    d["hooks"]["SessionStart"][0]["matcher"] = "startup"
    d = instalar.aplicar(d, python="/x/python3")
    assert d["hooks"]["SessionStart"] == [{"hooks": [d["hooks"]["SessionStart"][0]["hooks"][0]]}]


def test_python_escolhido(tmp_path):
    caminho = _settings(tmp_path, {})
    assert instalar.main(["--settings", str(caminho), "--python", "/opt/py/bin/python3"]) == 0
    cmd = _ler(caminho)["hooks"]["SessionEnd"][0]["hooks"][0]["command"]
    assert cmd.startswith('"/opt/py/bin/python3" "')


def test_python_padrao(monkeypatch):
    monkeypatch.setattr(instalar.sys, "platform", "darwin")
    monkeypatch.setattr(instalar.os.path, "exists", lambda p: p == "/usr/bin/python3")
    assert instalar.python_padrao() == "/usr/bin/python3"
    monkeypatch.setattr(instalar.sys, "platform", "linux")
    assert instalar.python_padrao() == instalar.sys.executable


def test_outra_copia_so_com_substituir(tmp_path, capsys):
    outro = {"type": "command", "command": '"/usr/bin/python3" "/clone/velho/ferramentas/sessoes/sessao_fim.py"',
             "timeout": 10}
    original = {"hooks": {"SessionEnd": [{"hooks": [outro]}]}}
    caminho = _settings(tmp_path, original)
    assert instalar.main(["--settings", str(caminho)]) == 1
    assert "--substituir" in capsys.readouterr().err
    assert _ler(caminho) == original and _baks(tmp_path) == []
    assert instalar.main(["--settings", str(caminho), "--substituir"]) == 0
    d = _ler(caminho)
    assert len(d["hooks"]["SessionEnd"]) == 1
    assert "/clone/velho/" not in d["hooks"]["SessionEnd"][0]["hooks"][0]["command"]


def test_lista_o_que_muda(tmp_path, capsys):
    caminho = _settings(tmp_path, {})
    instalar.main(["--settings", str(caminho), "--python", "/x/python3"])
    saida = capsys.readouterr().out
    assert "Acrescento em SessionStart: " in saida and "Acrescento em SessionEnd: " in saida
    instalar.main(["--settings", str(caminho), "--python", "/y/python3"])
    saida = capsys.readouterr().out
    assert "Tiro em SessionEnd: \"/x/python3\"" in saida and "Acrescento em SessionEnd: \"/y/python3\"" in saida
    instalar.main(["--settings", str(caminho), "--remover"])
    assert "Tiro em SessionStart" in capsys.readouterr().out


def test_segue_link_simbolico_e_guarda_o_modo(tmp_path):
    real = tmp_path / "dotfiles" / "settings.json"
    real.parent.mkdir()
    real.write_text(json.dumps({"model": "opus"}))
    os.chmod(real, 0o600)
    link = tmp_path / "claude" / "settings.json"
    link.parent.mkdir()
    os.symlink(real, link)
    assert instalar.main(["--settings", str(link)]) == 0
    assert os.path.islink(link)
    assert "SessionEnd" in _ler(real)["hooks"]
    assert oct(os.stat(real).st_mode & 0o777) == oct(0o600)
    assert any(n.startswith("settings.json.bak-") for n in os.listdir(real.parent))
