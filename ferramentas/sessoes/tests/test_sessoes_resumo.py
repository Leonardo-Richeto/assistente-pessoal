"""Resumo por regra a partir do transcript sintético."""
from __future__ import annotations

import json
import os
import re

import pytest
from conftest import SESSAO, escrever_transcript

import resumo


def _resumir(transcript, projeto, cwd=None):
    return resumo.resumir(transcript, str(cwd or projeto / "servidor"), SESSAO, "prompt_input_exit")


def test_campos_basicos(transcript, projeto, estado):
    r = _resumir(transcript, projeto)
    assert r["sessao"] == SESSAO
    assert r["projeto"] == "meu-projeto"
    assert r["raiz"] == str(projeto)
    assert r["maquina"] == "maquina-teste"
    assert r["inicio"] == "2026-10-20T13:00:00+00:00"
    assert r["fim"] == "2026-10-20T13:47:10+00:00"
    assert r["duracao_min"] == 47
    assert r["motivo_fim"] == "prompt_input_exit"
    assert r["versao_resumo"] == 2
    assert "parcial" not in r


def test_titulo_e_a_primeira_mensagem_digitada_sem_meta_e_sem_segredo(transcript, projeto, estado):
    titulo = _resumir(transcript, projeto)["titulo"]
    assert titulo.startswith("Arruma o deploy do servidor com GITHUB_TOKEN=[segredo:")
    assert "ghp_" not in titulo
    assert "lembrete" not in titulo and "<" not in titulo
    assert len(titulo) == 120


def test_arquivos_relativos_sem_repetir_e_sem_leitura(transcript, projeto, estado):
    arquivos = _resumir(transcript, projeto)["arquivos"]
    assert arquivos == ["servidor/app.py", "/var/outro/fora.txt", "analise.ipynb", "CONTEXTO.md"]


def test_comandos_com_segredo_tirado(transcript, projeto, estado):
    comandos = _resumir(transcript, projeto)["comandos"]
    texto = "\n".join(comandos)
    for vazado in ("AKIAIOSFODNN7EXAMPLE", "senha@", "abc123456789"):
        assert vazado not in texto
    assert "[segredo:aws]" in comandos[0]
    assert "[segredo:url_com_senha]" in comandos[1]
    assert "TOKEN=[segredo:" in comandos[1] or "[segredo:variavel_segredo]" in comandos[1]
    assert "{{segredo:BANCO}}" in comandos[2]
    assert all(len(c.split(" [+")[0]) <= 200 for c in comandos)
    assert len(comandos) == 9
    # Commit com heredoc: só a primeira linha, sem o corpo da mensagem.
    assert 'git add -A && git commit -m " \u2026 [+5 linhas]' in comandos
    assert "Corpo longo" not in texto


def test_commits_so_do_git_commit(transcript, projeto, estado):
    assert _resumir(transcript, projeto)["commits"] == [
        {"id": "1a2b3c4", "mensagem": "Corrige o deploy"},
        {"id": "5e6f7a8", "mensagem": "Ajusta testes"},  # commit -q + log --oneline -1
        {"id": "abcdef123456", "mensagem": ""},  # só o sha de toolUseResult.gitOperation
    ]


def test_passagem_detectada(transcript, projeto, estado):
    assert _resumir(transcript, projeto)["passagem"] is True


def test_sem_passagem(tmp_path, projeto, estado):
    t = escrever_transcript(tmp_path / "sem.jsonl", projeto, sem=("CONTEXTO.md",))
    assert _resumir(t, projeto)["passagem"] is False


def test_nunca_guarda_conteudo(transcript, projeto, estado):
    bruto = json.dumps(_resumir(transcript, projeto), ensure_ascii=False)
    for proibido in ("conteudo que nunca", "conteudo secreto", "Vou olhar", "pensando", "anota a passagem",
                     "agente terminou", "blob-nao-conta", "so-lido", "Título gerado"):
        assert proibido not in bruto


def test_transcript_ausente(tmp_path, projeto, estado):
    r = _resumir(str(tmp_path / "nao-existe.jsonl"), projeto)
    assert r["titulo"] == "" and r["arquivos"] == [] and r["inicio"] is None
    assert r["fim"]  # hora do hook
    assert r["duracao_min"] == 0


def test_transcript_vazio(tmp_path, projeto, estado):
    vazio = tmp_path / "vazio.jsonl"
    vazio.write_text("")
    assert _resumir(str(vazio), projeto)["comandos"] == []


def test_sem_git_usa_o_cwd(tmp_path, transcript, estado):
    pasta = tmp_path / "solta"
    pasta.mkdir()
    r = resumo.resumir(transcript, str(pasta), SESSAO, "")
    assert r["projeto"] == "solta" and r["raiz"] == str(pasta)


def test_subagentes_contam_arquivos_mas_nao_titulo(tmp_path, projeto, estado):
    t = escrever_transcript(tmp_path / (SESSAO + ".jsonl"), projeto, sem=("CONTEXTO.md",))
    sub = tmp_path / SESSAO / "subagents"
    sub.mkdir(parents=True)
    linha = {
        "type": "assistant", "isSidechain": True, "agentId": "x", "timestamp": "2026-10-20T13:30:00.000Z",
        "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_sub", "name": "Write",
             "input": {"file_path": str(projeto / "SPRINT_NOTAS.md"), "content": "x"}}]},
    }
    usuario = {"type": "user", "isSidechain": True, "timestamp": "2026-10-20T13:29:00.000Z",
               "message": {"role": "user", "content": "prompt do subagente"}}
    ok = {"type": "user", "isSidechain": True, "timestamp": "2026-10-20T13:30:01.000Z",
          "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_sub", "content": "ok"}]}}
    (sub / "agent-abc.jsonl").write_text("\n".join(json.dumps(x) for x in (usuario, linha, ok)) + "\n")
    r = _resumir(t, projeto)
    assert r["passagem"] is True
    assert "SPRINT_NOTAS.md" in r["arquivos"]
    assert "subagente" not in r["titulo"]


def test_maquina_do_hostname(monkeypatch):
    monkeypatch.delenv("ASSISTENTE_MAQUINA", raising=False)
    monkeypatch.setattr(resumo.socket, "gethostname", lambda: "MacBook-Air.local")
    assert resumo.nome_maquina() == "macbook-air"


@pytest.mark.parametrize("bruto, esperado", [
    ("MacBook do Léo.local", "macbook-do-l-o"),
    ("PC_Trabalho", "pc_trabalho"),
    ("i7;rm -rf", "i7-rm--rf"),
    ("x" * 80, "x" * 60),
    ("   ", "desconhecida"),
])
def test_maquina_normalizada_no_formato_do_importador(monkeypatch, bruto, esperado):
    """O importador recusa `maquina` fora de ^[a-z0-9._-]{1,60}$ (revisor do Passo 11): o hook já sai nesse formato."""
    monkeypatch.delenv("ASSISTENTE_MAQUINA", raising=False)
    monkeypatch.setattr(resumo.socket, "gethostname", lambda: bruto)
    nome = resumo.nome_maquina()
    assert nome == esperado and re.fullmatch(r"[a-z0-9._-]{1,60}", nome)
    monkeypatch.setenv("ASSISTENTE_MAQUINA", bruto)
    assert resumo.nome_maquina() == esperado


# --- Transcripts pequenos montados no teste (achados 1, 4, 5, 9 e 11 do revisor do Passo 10) ---

_S = "aaaaaaaa-2222-4333-8444-555555555555"


def _u(i, content, **kw):
    d = {"type": "user", "timestamp": "2026-10-20T13:00:%02d.000Z" % i, "sessionId": _S,
         "message": {"role": "user", "content": content}}
    d.update(kw)
    return d


def _a(i, tid, name, inp):
    return {"type": "assistant", "timestamp": "2026-10-20T13:01:%02d.000Z" % i, "sessionId": _S,
            "message": {"role": "assistant", "content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]}}


def _r(i, tid, text, erro=False, **kw):
    d = {"type": "user", "timestamp": "2026-10-20T13:02:%02d.000Z" % i, "sessionId": _S,
         "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid, "content": text,
                                                   "is_error": erro}]}}
    d.update(kw)
    return d


def _gravar(tmp_path, regs, nome="t.jsonl"):
    caminho = tmp_path / nome
    caminho.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in regs), encoding="utf-8")
    return str(caminho)


def test_comando_sem_conteudo(tmp_path, projeto, estado):
    longa = "x" * 41
    regs = [
        _a(1, "t1", "Bash", {"command": "cat > notas.md <<'EOF'\nConteudo privado: CPF 123.456.789-00\nEOF"}),
        _a(2, "t2", "Bash", {"command": "python3 - <<'PY'\nimport json\ndados = {'saldo': 9876.54}\nPY"}),
        _a(3, "t3", "Bash", {"command": "echo 'minha senha do banco é hunter2 e mais texto privado' > /tmp/x"}),
        _a(4, "t4", "Bash", {"command": "export TOKEN=$(cat ~/.token) && ls"}),
        _a(5, "t5", "Bash", {"command": "uv run pytest -q \\\n  tests/a.py \\\n  tests/b.py"}),
        _a(6, "t6", "Bash", {"command": 'grep -rn "%s" .' % longa}),
        _a(7, "t7", "Bash", {"command": 'grep -rn "%s" .' % ("x" * 40)}),
        _a(8, "t8", "Bash", {"command": "curl -u admin:SuperSecret123 https://x ; export SENHA_BANCO=Tr0ub4dor3"}),
    ]
    comandos = _resumir(_gravar(tmp_path, regs), projeto)["comandos"]
    assert comandos == [
        "cat > notas.md … [+2 linhas]",
        "python3 - … [+3 linhas]",
        'echo "…" > /tmp/x',
        "export TOKEN= …",
        "uv run pytest -q \\ [+2 linhas]",
        'grep -rn "…" .',
        'grep -rn "%s" .' % ("x" * 40),
        "curl -u admin:[segredo:senha_cli] https://x ; export SENHA_BANCO=[segredo:variavel_segredo]",
    ]
    bruto = json.dumps(comandos, ensure_ascii=False)
    for proibido in ("CPF", "saldo", "hunter2", "SuperSecret", "Tr0ub4dor3", ".token"):
        assert proibido not in bruto


def test_comando_cortado_em_200_mais_linhas(tmp_path, projeto, estado):
    comando = "echo " + "a " * 150 + "\nsegunda\nterceira"
    c = _resumir(_gravar(tmp_path, [_a(1, "t1", "Bash", {"command": comando})]), projeto)["comandos"][0]
    assert c.endswith(" [+2 linhas]") and len(c) == 200 + len(" [+2 linhas]")


def test_commit_nao_le_saida_de_outro_comando(tmp_path, projeto, estado):
    regs = [
        # Nada a commitar, e o `cat` depois imprime algo com cara de commit.
        _a(1, "t1", "Bash", {"command": "git commit -am wip; cat relatorio.txt"}),
        _r(1, "t1", "On branch main\nnothing to commit\n[conta 1234567] Saldo privado da conta\n"),
        # `[branch sha]` fora da primeira linha não conta.
        _a(2, "t2", "Bash", {"command": "cat log.txt; git commit -m x"}),
        _r(2, "t2", "texto qualquer\n[main 2222222] mensagem falsa\n"),
        # Formato --oneline sem `git log --oneline` depois do commit não conta.
        _a(3, "t3", "Bash", {"command": "git commit -q -m x && sha256sum a.txt"}),
        _r(3, "t3", "abcdef1 a.txt\n"),
        # Erro: nem o sha do gitOperation conta.
        _a(4, "t4", "Bash", {"command": "git commit -q -m y && git log --oneline -1"}),
        _r(4, "t4", "Exit code 1\n0000000 velho", erro=True,
           toolUseResult={"gitOperation": {"commit": {"sha": "4444444"}}}),
        # Hook do git (linhas com espaço e hint:) antes da linha do commit.
        _a(5, "t5", "Bash", {"command": "git commit -m 'Arruma'"}),
        _r(5, "t5", "  ruff ok\nhint: algo\n[main 5555555] Arruma\n 1 file changed"),
        # --oneline depois do commit: só a primeira linha da saída.
        _a(6, "t6", "Bash", {"command": "git commit -q -m z && git log --oneline -3"}),
        _r(6, "t6", "6666666 Novo\n7777777 Antigo\n"),
        # gitOperation tem preferência; a mensagem vem da linha `[branch sha]` se for o mesmo sha.
        _a(7, "t7", "Bash", {"command": "git commit -m w"}),
        _r(7, "t7", "[main 8888888] Com sha anotado\n", toolUseResult={"gitOperation": {"commit": {"sha": "8888888abc"}}}),
    ]
    commits = _resumir(_gravar(tmp_path, regs), projeto)["commits"]
    assert commits == [
        {"id": "5555555", "mensagem": "Arruma"},
        {"id": "6666666", "mensagem": "Novo"},
        {"id": "8888888abc", "mensagem": "Com sha anotado"},
    ]


def test_edicao_so_conta_com_resultado_sem_erro(tmp_path, projeto, estado):
    raiz = str(projeto)
    regs = [
        _a(1, "t1", "Edit", {"file_path": raiz + "/CONTEXTO.md", "old_string": "x", "new_string": "y"}),
        _r(1, "t1", "<tool_use_error>File has not been read yet.</tool_use_error>", toolUseResult="Error: x"),
        _a(2, "t2", "Write", {"file_path": raiz + "/SPRINT_NOTAS.md", "content": "x"}),  # sem resultado
        _a(3, "t3", "Write", {"file_path": raiz + "/a.py", "content": "x"}),
        _r(3, "t3", "ok", erro=True),
        _a(4, "t4", "Write", {"file_path": raiz + "/b.py", "content": "x"}),
        _r(4, "t4", "File created successfully"),
    ]
    r = _resumir(_gravar(tmp_path, regs), projeto)
    assert r["arquivos"] == ["b.py"]
    assert r["passagem"] is False


def test_passagem_pelo_mcp_e_pelo_bash(tmp_path, projeto, estado):
    casos = [
        (_a(1, "t1", "mcp__assistente__escrever_nota", {"caminho": "00-inbox/onde-parei.md", "conteudo": "x"}), True),
        (_a(1, "t1", "mcp__claude_ai_Assistente__vault_write_note", {"path": "00-inbox/onde-parei.md"}), True),
        (_a(1, "t1", "mcp__x__vault_patch_note", {"path": "00-inbox/onde-parei.md"}), True),
        (_a(1, "t1", "mcp__x__vault_write_note", {"path": "00-inbox/outra.md"}), False),
        (_a(1, "t1", "mcp__x__ler_nota", {"caminho": "00-inbox/onde-parei.md"}), False),
        (_a(1, "t1", "Bash", {"command": "cat >> docs/CONTEXTO.md <<'EOF'\nfeito\nEOF"}), True),
        (_a(1, "t1", "Bash", {"command": "echo feito > SPRINT_NOTAS.md"}), True),
        (_a(1, "t1", "Bash", {"command": "echo x | tee -a \"ACOMPANHAMENTO.md\""}), True),
        (_a(1, "t1", "Bash", {"command": "sed -i '' 's/a/b/' CONTEXTO.md"}), True),
        (_a(1, "t1", "Bash", {"command": "grep feito CONTEXTO.md > /tmp/x"}), False),
        (_a(1, "t1", "Bash", {"command": "cat CONTEXTO.md"}), False),
        (_a(1, "t1", "Bash", {"command": "echo x > CONTEXTO.md.bak"}), False),
    ]
    for chamada, esperado in casos:
        t = _gravar(tmp_path, [chamada, _r(1, "t1", "ok")])
        assert _resumir(t, projeto)["passagem"] is esperado, chamada
    # Com erro, não conta.
    t = _gravar(tmp_path, [casos[0][0], _r(1, "t1", "falhou", erro=True)])
    assert _resumir(t, projeto)["passagem"] is False


def test_titulo_pula_resumo_de_compactacao(tmp_path, projeto, estado):
    regs = [
        _u(1, "This session is being continued from a previous conversation...", isCompactSummary=True),
        _u(2, "resumo visivel so no transcript", isVisibleInTranscriptOnly=True),
        _u(3, "Pergunta de verdade do dono"),
    ]
    assert _resumir(_gravar(tmp_path, regs), projeto)["titulo"] == "Pergunta de verdade do dono"


def _transcript_grande(tmp_path, projeto, n_meio):
    raiz = str(projeto)
    regs = [_u(0, "Começo"), _a(1, "t1", "Write", {"file_path": raiz + "/a.py", "content": "x"}), _r(1, "t1", "ok")]
    regs += [_u(5, "ruido " * 50, isMeta=True) for _ in range(n_meio)]
    fim = _a(9, "t9", "Edit", {"file_path": raiz + "/CONTEXTO.md", "old_string": "x", "new_string": "y"})
    fim["timestamp"] = "2026-10-20T15:00:00.000Z"
    regs += [fim, _r(9, "t9", "ok")]
    regs[-1]["timestamp"] = "2026-10-20T15:00:01.000Z"
    return _gravar(tmp_path, regs, SESSAO + ".jsonl")


def test_transcript_grande_le_comeco_e_fim_e_marca_parcial(tmp_path, projeto, estado, monkeypatch):
    monkeypatch.setattr(resumo, "LIMITE_TOTAL", 60_000)
    monkeypatch.setattr(resumo, "FIM_BYTES", 10_000)
    t = _transcript_grande(tmp_path, projeto, 1000)
    assert os.path.getsize(t) > 200_000
    r = _resumir(t, projeto)
    assert r["parcial"] is True
    assert r["titulo"] == "Começo"
    assert r["arquivos"] == ["a.py", "CONTEXTO.md"]
    assert r["passagem"] is True
    assert r["fim"] == "2026-10-20T15:00:01+00:00"


def test_limite_vale_para_sessao_mais_subagentes(tmp_path, projeto, estado, monkeypatch):
    t = _transcript_grande(tmp_path, projeto, 10)
    monkeypatch.setattr(resumo, "LIMITE_TOTAL", os.path.getsize(t) + 10)
    sub = tmp_path / SESSAO / "subagents"
    sub.mkdir(parents=True)
    regs = [_a(1, "s1", "Write", {"file_path": str(projeto / "sub.py"), "content": "x"}), _r(1, "s1", "ok")]
    _gravar(sub, regs, "agent-a.jsonl")
    r = _resumir(t, projeto)
    assert r["parcial"] is True and "sub.py" not in r["arquivos"]
    monkeypatch.setattr(resumo, "LIMITE_TOTAL", 10 * 1024 * 1024)
    r = _resumir(t, projeto)
    assert "parcial" not in r and "sub.py" in r["arquivos"]


def test_linha_gigante_e_pulada(tmp_path, projeto, estado, monkeypatch):
    monkeypatch.setattr(resumo, "MAX_LINHA", 1000)
    regs = [_u(1, "a" * 5000), _u(2, "Título curto")]
    assert _resumir(_gravar(tmp_path, regs), projeto)["titulo"] == "Título curto"


def test_aspas_curtas_nao_viram_string_longa():
    """A aspa que fecha `'x'` não pode abrir uma string falsa até o fim da linha."""
    c = "git commit -q -m 'x' && git log --oneline -1 && sha256sum segredo.txt"
    assert resumo.resumir_comando(c) == c
    assert resumo.resumir_comando('echo "a\\"b%s" fim' % ("z" * 45)) == 'echo "…" fim'
    assert resumo.resumir_comando('python -c "import os; print(1) e mais um monte de texto aqui') == 'python -c "…"'
