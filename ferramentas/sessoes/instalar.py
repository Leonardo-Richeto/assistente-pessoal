"""Instala (ou tira) os hooks de sessão no settings.json do Claude Code.

Uso:
    python3 instalar.py [--settings ~/.claude/settings.json] [--python CAMINHO]
                        [--substituir] [--remover] [--mostrar]

Acrescenta em `hooks.SessionStart` e `hooks.SessionEnd` um grupo sem `matcher`
(vale para todas as ocorrências) com
`{"type": "command", "command": "<python> <script>", "timeout": N}`
(5 s no SessionStart, 10 s no SessionEnd, cujo padrão é 1,5 s). Não mexe nas
outras entradas. É idempotente: reconhece as suas pelo caminho
`ferramentas/sessoes/sessao_*.py` no comando. Se já houver uma entrada sua com
OUTRO caminho de script (outra cópia do repositório), só a troca com
`--substituir`; sem ele, avisa e sai com 1 sem gravar.

Grava no arquivo real (segue link simbólico), com o mesmo modo do original.
Antes de gravar, copia o arquivo para `settings.json.bak-AAAAMMDD-HHMMSS` e
lista o que acrescenta e o que tira. `--mostrar` só imprime o JSON resultante.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

PASTA = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = {"SessionStart": "sessao_inicio.py", "SessionEnd": "sessao_fim.py"}
TIMEOUTS = {"SessionStart": 5, "SessionEnd": 10}
_SCRIPT_NO_COMANDO = re.compile(r"""(?:"([^"]*ferramentas/sessoes/sessao_\w+\.py)"|(\S*ferramentas/sessoes/sessao_\w+\.py))""")


class OutraCopia(ValueError):
    """Já há entrada deste instalador apontando para outro caminho de script."""


def _barra(caminho: str) -> str:
    return caminho.replace("\\", "/")


def python_padrao() -> str:
    """No macOS, `/usr/bin/python3` (se existe); senão, o Python que rodou o instalador."""
    if sys.platform == "darwin" and os.path.exists("/usr/bin/python3"):
        return "/usr/bin/python3"
    return sys.executable


def comando(script: str, python: Optional[str] = None) -> str:
    """Comando do hook: `"<python>" "<caminho absoluto do script>"` (barras `/`, que o Windows aceita)."""
    exe = _barra(python or python_padrao())
    alvo = _barra(os.path.join(PASTA, script))
    return '"%s" "%s"' % (exe, alvo)


def _e_meu(hook: Any, script: str) -> bool:
    if not isinstance(hook, dict) or not isinstance(hook.get("command"), str):
        return False
    return ("ferramentas/sessoes/" + script) in _barra(hook["command"])


def _script_do_comando(cmd: str) -> str:
    m = _SCRIPT_NO_COMANDO.search(_barra(cmd))
    return (m.group(1) or m.group(2)) if m else ""


def _mesmo_caminho(a: str, b: str) -> bool:
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def _tirar_meus(grupos: List[Any], script: str) -> List[Any]:
    saida = []
    for grupo in grupos:
        if isinstance(grupo, dict) and isinstance(grupo.get("hooks"), list):
            restantes = [h for h in grupo["hooks"] if not _e_meu(h, script)]
            if not restantes and len(restantes) != len(grupo["hooks"]):
                continue  # o grupo só tinha o meu hook
            if len(restantes) != len(grupo["hooks"]):
                grupo = dict(grupo, hooks=restantes)
        saida.append(grupo)
    return saida


def _grupos_meus(grupos: List[Any], script: str) -> List[Any]:
    return [
        g for g in grupos
        if isinstance(g, dict) and isinstance(g.get("hooks"), list) and any(_e_meu(h, script) for h in g["hooks"])
    ]


def aplicar(
    config: Dict[str, Any], remover: bool = False, python: Optional[str] = None, substituir: bool = False
) -> Dict[str, Any]:
    """Devolve uma cópia de `config` com os hooks postos (ou tirados).

    Levanta `OutraCopia` se for instalar por cima de entrada sua com outro caminho de script
    e `substituir` for False.
    """
    novo = json.loads(json.dumps(config))
    hooks = novo.get("hooks")
    if hooks is None:
        hooks = {}
    if not isinstance(hooks, dict):
        raise ValueError("'hooks' no settings não é um objeto; não mexo")
    for evento, script in SCRIPTS.items():
        grupos = hooks.get(evento, [])
        if not isinstance(grupos, list):
            raise ValueError("'hooks.%s' no settings não é uma lista; não mexo" % evento)
        desejado = {"type": "command", "command": comando(script, python), "timeout": TIMEOUTS[evento]}
        if not remover:
            if _grupos_meus(grupos, script) == [{"hooks": [desejado]}]:
                continue  # já instalado igual: não mexe nem muda a ordem
            alvo = os.path.join(PASTA, script)
            outros = sorted({
                _script_do_comando(h["command"])
                for g in _grupos_meus(grupos, script)
                for h in g["hooks"]
                if _e_meu(h, script) and not _mesmo_caminho(_script_do_comando(h["command"]), alvo)
            })
            if outros and not substituir:
                raise OutraCopia(
                    "hooks.%s já aponta para outra cópia (%s); use --substituir para trocar por %s"
                    % (evento, ", ".join(outros), _barra(alvo))
                )
        grupos = _tirar_meus(grupos, script)
        if not remover:
            grupos.append({"hooks": [desejado]})
        if grupos:
            hooks[evento] = grupos
        else:
            hooks.pop(evento, None)
    if hooks:
        novo["hooks"] = hooks
    else:
        novo.pop("hooks", None)
    return novo


def diferencas(antes: Dict[str, Any], depois: Dict[str, Any]) -> List[Tuple[str, str, str]]:
    """(ação, evento, comando) das entradas deste instalador que entram ou saem."""
    saida = []
    for evento, script in SCRIPTS.items():
        def _meus(cfg: Dict[str, Any]) -> List[str]:
            grupos = (cfg.get("hooks") or {}).get(evento) or []
            return [
                "%s (timeout %s)" % (h["command"], h.get("timeout"))
                for g in grupos if isinstance(g, dict) and isinstance(g.get("hooks"), list)
                for h in g["hooks"] if _e_meu(h, script)
            ]

        a, d = _meus(antes), _meus(depois)
        saida += [("Tiro", evento, c) for c in a if c not in d]
        saida += [("Acrescento", evento, c) for c in d if c not in a]
    return saida


def _ler(caminho: str) -> Dict[str, Any]:
    if not os.path.exists(caminho):
        return {}
    with open(caminho, "r", encoding="utf-8") as f:
        texto = f.read()
    if not texto.strip():
        return {}
    dados = json.loads(texto)
    if not isinstance(dados, dict):
        raise ValueError("o settings não é um objeto JSON")
    return dados


def _gravar(caminho: str, dados: Dict[str, Any]) -> Optional[str]:
    """Faz a cópia de segurança (se o arquivo existe) e grava de forma atômica, com o modo do original."""
    pasta = os.path.dirname(caminho)
    os.makedirs(pasta, exist_ok=True)
    copia = None
    modo = None
    if os.path.exists(caminho):
        modo = stat.S_IMODE(os.stat(caminho).st_mode)
        copia = "%s.bak-%s" % (caminho, datetime.now().strftime("%Y%m%d-%H%M%S"))
        shutil.copy2(caminho, copia)
    fd, temporario = tempfile.mkstemp(prefix=".settings-", suffix=".json", dir=pasta)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
            f.write("\n")
        if modo is not None:
            os.chmod(temporario, modo)
        os.replace(temporario, caminho)
    except BaseException:
        try:
            os.unlink(temporario)
        except OSError:
            pass
        raise
    return copia


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Instala os hooks de sessão do Claude Code.")
    parser.add_argument("--settings", default=os.path.join("~", ".claude", "settings.json"))
    parser.add_argument("--python", default=None,
                        help="Python dos hooks (padrão: /usr/bin/python3 no macOS, senão o atual)")
    parser.add_argument("--substituir", action="store_true",
                        help="troca a entrada de outra cópia do repositório por esta")
    parser.add_argument("--remover", action="store_true", help="tira os hooks deste instalador")
    parser.add_argument("--mostrar", action="store_true", help="só imprime o JSON resultante")
    args = parser.parse_args(argv)

    # Segue link simbólico: grava no arquivo de verdade, não troca o link por um arquivo.
    caminho = os.path.realpath(os.path.expanduser(args.settings))
    python = args.python or python_padrao()
    if not args.remover and not os.path.exists(python):
        print("Aviso: o Python %s não existe nesta máquina." % python, file=sys.stderr)
    try:
        atual = _ler(caminho)
        novo = aplicar(atual, remover=args.remover, python=python, substituir=args.substituir)
    except OutraCopia as erro:
        print("Não mexi no %s: %s" % (caminho, erro), file=sys.stderr)
        return 1
    except (OSError, ValueError) as erro:
        print("Não mexi no %s: %s" % (caminho, erro), file=sys.stderr)
        return 1

    if args.mostrar:
        print(json.dumps(novo, ensure_ascii=False, indent=2))
        return 0
    if novo == atual:
        print("Nada a mudar em %s." % caminho)
        return 0
    for acao, evento, cmd in diferencas(atual, novo):
        print("%s em %s: %s" % (acao, evento, cmd))
    copia = _gravar(caminho, novo)
    acao = "Tirei" if args.remover else "Instalei"
    print("%s os hooks de sessão em %s." % (acao, caminho))
    if copia:
        print("Cópia anterior: %s" % copia)
    return 0


if __name__ == "__main__":
    sys.exit(main())
