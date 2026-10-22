"""Acha e tira segredos de um texto (token, chave, senha em linha de comando).

Origem dos padrões: `crates/ai-memory-core/src/sanitize.rs` do ai-memory
(github.com/akitaonrails/ai-memory) e as regras do gitleaks. Os padrões foram
reescritos para o `re` do Python; nenhum código de lá foi copiado.

Dois usos:
- `tirar_segredos(texto)`: troca cada achado por `[segredo:<tipo>]` (hooks de
  sessão do Claude Code, que guardam comandos e títulos).
- `achar_segredo(texto)`: devolve o tipo do primeiro achado ou None (o servidor
  usa para RECUSAR a escrita inteira, sem redigir, e para não comitar no git do
  vault um arquivo com segredo).

Dois tipos de padrão:
- De fornecedor (sk-, ghp_, AKIA, glpat- etc.): o formato basta.
- Com grupo nomeado: só o grupo é trocado, e ele precisa passar num teste.
  `(?P<valor>...)` (genéricos: variável, chave de cabeçalho, `--password`) exige
  `parece_segredo(valor)`: 8+ caracteres, 2+ classes (ou 16+ caracteres), não
  é palavra comum nem marcador de exemplo. `(?P<senha>...)` (contexto que já diz
  "isto é senha": `curl -u`, `sshpass -p`, `docker login -p`, `?token=`) só
  exige que o valor não seja marcador (`$VAR`, `<...>`, `xxx`).

A referência `{{segredo:NOME}}` nunca conta como segredo.

DUAS CÓPIAS IGUAIS, byte a byte: `ferramentas/sessoes/segredos.py` (a canônica, hooks
do Claude Code) e `servidor/assistente/segredos.py` (a imagem Docker só leva `servidor/`).
Mude as duas juntas: um teste em cada pasta compara os bytes.

Só biblioteca padrão; compatível com Python 3.9.
"""
from __future__ import annotations

import re
from typing import List, Optional, Pattern, Tuple

# Valor de uma atribuição: entre aspas (pode ter espaço) ou sem aspas até o
# primeiro espaço ou pontuação de código. `parece_segredo` decide se é segredo.
_VALOR = r"""(?P<valor>"[^"\n]*"|'[^'\n]*'|[^\s"'`;|&()<>\[\]{},]+)"""
# Valor em contexto de senha (só não pode ser marcador).
_SENHA = r"""(?P<senha>"[^"\n]*"|'[^'\n]*'|[^\s"'`;|&]+)"""

# (regex, tipo). Ordem importa: os específicos antes dos genéricos.
# Sem backtracking quadrático: todo trecho de tamanho livre que pode falhar no fim tem limite (`{0,80}`, `{1,256}`,
# `{0,300}?`) ou começa só no início de uma palavra. Um texto hostil de 200.000 caracteres (nota, comando) não pode
# travar o servidor nem o hook; `test_sem_backtracking_quadratico` confere.
PADROES: List[Tuple[str, str]] = [
    # Chave privada PEM (várias linhas). Sem END, vai até o fim do texto.
    (
        r"(?s)-----BEGIN [A-Z ]*PRIVATE KEY-----(?:.*?-----END [A-Z ]*PRIVATE KEY-----|.*)",
        "chave_privada",
    ),
    # URL com usuário:senha@ (postgres://u:senha@h, https://u:t@github.com).
    (r"(?<![a-zA-Z0-9+\-.])[a-zA-Z][a-zA-Z0-9+\-.]{0,30}://[^:/\s@]{1,256}:[^@\s]{1,256}@[^\s]+", "url_com_senha"),
    # Authorization: Bearer <token>.
    (r"(?i)\bbearer\s+[A-Za-z0-9._\-+/=]{16,}", "bearer"),
    # Stripe (secreta e restrita, produção e teste).
    (r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9_\-]{16,}", "stripe"),
    # OpenAI, Anthropic (sk-ant-...) e outros `sk-`.
    (r"\bsk-[A-Za-z0-9_\-]{16,}", "chave_api"),
    # GitHub: ghp_, gho_, ghu_, ghs_, ghr_ e github_pat_.
    (r"\bgh[pousr]_[A-Za-z0-9]{20,}", "github"),
    (r"\bgithub_pat_[A-Za-z0-9_]{20,}", "github"),
    # GitLab, Hugging Face, Tailscale, Azure Storage.
    (r"\bglpat-[A-Za-z0-9_\-]{20,}", "gitlab"),
    (r"\bhf_[A-Za-z0-9]{30,}", "huggingface"),
    (r"\btskey-[A-Za-z0-9\-]{20,}", "tailscale"),
    (r"\bAccountKey=[A-Za-z0-9+/]{20,}={0,2}", "azure"),
    # AWS: AKIA/ASIA + 16 exatos (ASIAPACIFICREGION não casa).
    (r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b", "aws"),
    # Google / Gemini.
    (r"AIza[A-Za-z0-9_\-]{30,}", "google"),
    (r"AQ\.Ab[A-Za-z0-9_\-]{30,}", "google"),
    # Refresh token OAuth do Google: `1//0` + dezenas de caracteres.
    (r"(?<![A-Za-z0-9:/])1//0[0-9A-Za-z_\-]{40,}", "google_oauth"),
    # Meta / Facebook Graph.
    (r"\bEAA[A-Za-z0-9]{20,}", "meta"),
    # Telegram: <id do bot, 8 a 10 dígitos>:<segredo>.
    (r"\b\d{8,10}:(?:AA[A-Za-z0-9_\-]{30,}|[A-Za-z0-9_\-]{34,35})\b", "telegram"),
    # GoHighLevel: pit-<uuid> (pit-stop não casa).
    (r"\bpit-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", "ghl"),
    # Slack.
    (r"\bxox[abprs]-[A-Za-z0-9\-]{10,}", "slack"),
    (r"\bxapp-[A-Za-z0-9\-]{10,}", "slack"),
    # JWT (três partes) e JSON em base64 longo (token de túnel Cloudflare).
    (r"\beyJ[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}", "jwt"),
    (r"\beyJ[A-Za-z0-9_\-+/]{40,}={0,2}", "token_base64"),
    # Senha em contexto de senha: curl -u usuario:senha, sshpass -p, docker login -p.
    (
        r"(?<![\w-])curl\b[^\n|;&]{0,300}?\s(?:-u|--user)(?:=|\s+)[\"']?[^\s:\"']+:" + _SENHA,
        "senha_cli",
    ),
    (r"(?<![\w-])sshpass\b[^\n|;&]{0,300}?\s-p\s*" + _SENHA, "senha_cli"),
    (r"(?<![\w-])docker\s+login\b[^\n|;&]{0,300}?\s(?:-p|--password)(?:=|\s+)" + _SENHA, "senha_cli"),
    # Token em parâmetro de URL: ?api_key=..., &token=...
    (
        r"(?i)[?&](?:api_key|apikey|token|key|secret|access_token)=(?P<senha>[^&\s\"'#]+)",
        "url_com_token",
    ),
    # Senha na linha de comando: --password valor / --password=valor / --password 'com espaço'
    # (qualquer programa) e -pSENHA colado no mysql/mariadb/mysqldump. No psql, -p é a
    # porta, e no mysql `-p valor` (com espaço) pede a senha e `valor` é o banco.
    (r"--password(?:=|\s+)" + _VALOR, "senha_cli"),
    (
        r"\b(?:mysql|mysqldump|mysqladmin|mariadb|mariadb-dump)\b[^\n|;&]{0,300}?\s-p(?P<valor>[^\s\-]\S{3,})",
        "senha_cli",
    ),
    # Variável de ambiente (MAIÚSCULAS, com ou sem `export`): *_KEY, *_PWD e, com ou sem
    # prefixo e sufixo, TOKEN, SECRET, PASSWORD, PASSWD, PASS, SENHA, AUTHKEY, APIKEY,
    # CREDENTIAL(S) (DB_PASS, PGPASS, SENHA_BANCO, SECRET_KEY_BASE). Sufixo de metadado
    # (_FILE, _PATH, _URL, _HASH...) fica de fora. `PWD` sozinho é a pasta atual do shell e
    # `KEY` sozinho é genérico demais.
    (
        r"(?<![A-Za-z0-9_])(?:[A-Z][A-Z0-9_]{0,80}_(?:KEY|PWD)"
        r"|(?![A-Z0-9_]{0,80}_(?:FILE|PATH|URL|URI|HASH|NAME|DIR|TYPE|LEN|LENGTH|ENDPOINT|TTL)[\"']?\s*[=:])"
        r"(?:[A-Z][A-Z0-9_]{0,80}_|PG|MYSQL)?(?:TOKEN|SECRET|PASSWORD|PASSWD|PASS|SENHA|AUTHKEY|APIKEY|CREDENTIALS?)"
        r"(?:_[A-Z0-9]{1,40}){0,8})[\"']?\s*[=:]\s*" + _VALOR,
        "variavel_segredo",
    ),
    # Campo ou cabecalho de autenticação, qualquer caixa: password=..., X-Api-Key: ...,
    # api_key='...', clientSecret: ..., {"access_token": "..."}, Authorization: Basic ...
    (
        r"(?i)(?<![A-Za-z0-9])[A-Za-z0-9_-]{0,40}?(?:authorization|credentials?|password|passwd|senha|apikey|"
        r"authtoken|authkey|(?:api|auth|access|secret|private|session|refresh|client|app)[_-]?"
        r"(?:key|token|secret))[\"']?\s*[=:]\s*(?:(?:basic|bearer|token)\s+)?" + _VALOR,
        "cabecalho_auth",
    ),
]

# Referência ao cofre: nunca é segredo e o servidor nunca a resolve.
REFERENCIA = r"\{\{segredo:[A-Za-z0-9_.\-]+\}\}"

# Palavras que aparecem no lugar do valor em exemplo, documentação ou docker-compose.
PALAVRAS_DE_EXEMPLO = frozenset(
    {
        "obrigatorio", "obrigatório", "opcional", "postgres", "changeme", "password", "senha", "secret",
        "segredo", "example", "exemplo", "placeholder", "redacted", "none", "null", "undefined", "true",
        "false", "string", "valor", "value", "token", "your-token", "seu-token",
    }
)

_COMPILADOS: List[Tuple[Pattern[str], str]] = [(re.compile(p), t) for p, t in PADROES]
_REFERENCIA = re.compile(REFERENCIA)
# Palavras (minúsculas, MAIÚSCULAS, Capitalizada, camelCase) separadas por `. _ - /`:
# nome de campo, caminho ou frase, não segredo (`renovarAutomatico`, `str/TOKEN`), desde
# que cada pedaço tenha menos de 16 letras.
_PALAVRAS = re.compile(r"(?:[a-z]+|[A-Z]+|[A-Z]?[a-z]+(?:[A-Z][a-z]+)*)(?:[._/\-](?:[a-z]+|[A-Z]+|[A-Z]?[a-z]+(?:[A-Z][a-z]+)*))*")
_PEDACO = re.compile(r"[A-Z]?[a-z]+|[A-Z]+")
_MARCADOR = re.compile(r"^(?:\$|<|%|\[segredo:|\{\{)|xxx|\*\*\*|\.\.\.|\u2026", re.IGNORECASE)


def _sem_aspas(valor: str) -> str:
    v = valor.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    elif v[:1] in "\"'":
        v = v[1:]
    # Pontuação colada no fim (`TOKEN: str/TOKEN:`) não faz parte do valor.
    return _REFERENCIA.sub("", v).strip().rstrip(":.,;!?")


def e_marcador(valor: str) -> bool:
    """O valor é marcador de exemplo (`$VAR`, `${X}`, `<sua chave>`, `xxx`, `***`, `...`) ou vazio?"""
    v = _sem_aspas(valor)
    if not v:
        return True
    return bool(_MARCADOR.search(v)) or v.lower() in PALAVRAS_DE_EXEMPLO


def parece_segredo(valor: str) -> bool:
    """O valor de uma atribuição genérica parece segredo de verdade?

    Exige 8+ caracteres, não ser marcador nem palavra comum, e misturar 2+ classes
    (minúscula, maiúscula, dígito, símbolo) ou ter 16+ caracteres.
    """
    if not isinstance(valor, str) or e_marcador(valor):
        return False
    v = _sem_aspas(valor)
    if len(v) < 8:
        return False
    # Palavras de verdade (cada pedaço com menos de 16 letras) não são segredo.
    if _PALAVRAS.fullmatch(v) and max(len(p) for p in _PEDACO.findall(v)) < 16:
        return False
    classes = (
        any(c.islower() for c in v)
        + any(c.isupper() for c in v)
        + any(c.isdigit() for c in v)
        + any(not c.isalnum() for c in v)
    )
    return classes >= 2 or len(v) >= 16


def _grupo(m: "re.Match[str]") -> Optional[str]:
    """Nome do grupo testado (`valor` ou `senha`) que casou, ou None."""
    grupos = m.groupdict()
    for nome in ("valor", "senha"):
        if grupos.get(nome) is not None:
            return nome
    return None


def _vale(regex: Pattern[str], m: "re.Match[str]") -> bool:
    """O achado é segredo? (testa o grupo; sem grupo, ignora a referência `{{segredo:X}}`)."""
    nome = _grupo(m)
    if nome == "valor":
        return parece_segredo(m.group("valor"))
    if nome == "senha":
        return not e_marcador(m.group("senha"))
    trecho = m.group(0)
    if not _REFERENCIA.search(trecho):
        return True
    return regex.search(_REFERENCIA.sub("", trecho)) is not None


def achar_segredo(texto: str) -> Optional[str]:
    """Tipo do primeiro segredo achado no texto, ou None."""
    if not texto:
        return None
    for regex, tipo in _COMPILADOS:
        for m in regex.finditer(texto):
            if _vale(regex, m):
                return tipo
    return None


def tirar_segredos(texto: str) -> str:
    """Troca cada segredo por `[segredo:<tipo>]` (com grupo, só o valor é trocado)."""
    if not texto:
        return texto
    saida = texto
    for regex, tipo in _COMPILADOS:

        def _troca(m: "re.Match[str]", _regex: Pattern[str] = regex, _tipo: str = tipo) -> str:
            if not _vale(_regex, m):
                return m.group(0)
            marca = "[segredo:%s]" % _tipo
            nome = _grupo(m)
            if nome is None:
                return marca
            ini, fim = m.start(nome) - m.start(), m.end(nome) - m.start()
            return m.group(0)[:ini] + marca + m.group(0)[fim:]

        saida = regex.sub(_troca, saida)
    return saida
