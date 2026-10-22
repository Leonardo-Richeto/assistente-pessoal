"""Padrões de segredo: casam o que devem e deixam em paz o falso positivo comum."""
from __future__ import annotations

import os
import re

import pytest

import segredos

POSITIVOS = [
    ("Authorization: Bearer abcdefghijklmnop1234", "bearer"),
    ("sk-ant-api03-AAAAbbbbCCCCddddEEEE", "chave_api"),
    ("sk_live_AAAAbbbbCCCCddddEEEE", "stripe"),
    ("rk_live_AAAAbbbbCCCCddddEEEE", "stripe"),
    ("ghp_AAAAbbbbCCCCddddEEEEffff1234", "github"),
    ("gho_AAAAbbbbCCCCddddEEEEffff1234", "github"),
    ("github_pat_11AAAAbbbbCCCCddddEEEE_xyz", "github"),
    ("chave AKIAIOSFODNN7EXAMPLE aqui", "aws"),
    ("(ASIAIOSFODNN7EXAMPLE)", "aws"),
    ("AIzaSyA-1234567890abcdefghijklmnopqrstu", "google"),
    ("AQ.Ab1234567890abcdefghijklmnopqrstuvwxyz", "google"),
    ("refresh 1//0gAAAAbbbbCCCCddddEEEEffffGGGGhhhhIIIIjjjjKKKK", "google_oauth"),
    ("EAAGm0PX4ZCpsBAAAAbbbbCCCCdddd", "meta"),
    ("bot 123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw1", "telegram"),
    ("ghl=pit-DEADBEEF-FACE-4B0B-BEEF-CAFEBABE1234", "ghl"),
    ("xoxb-1234567890-abcdefghij", "slack"),
    ("xapp-1-A0123456789-abcdef", "slack"),
    ("eyJhbGciOiJIUzI1NiJ9xx.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c", "jwt"),
    ("-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXk\n-----END OPENSSH PRIVATE KEY-----", "chave_privada"),
    ("postgres://u:S3nhaF0rte@h/banco", "url_com_senha"),
    ("export DB_PASSWORD=hunter2222", "variavel_segredo"),
    ("TOKEN=abc123456789", "variavel_segredo"),
    ("PGPASSWORD=segredo1 psql", "variavel_segredo"),
    ("OPENAI_API_KEY: qualquer123coisa", "variavel_segredo"),
    ("MEU_PWD=abcd1234", "variavel_segredo"),
    ("curl -H 'X-Api-Key: 0123456789abcdef'", "cabecalho_auth"),
    ("password=hunter2222", "cabecalho_auth"),
    ("docker login --password abcd1234", "senha_cli"),
    ("mysql -u root -pS3nhaForte db", "senha_cli"),
    # Achado 2 do revisor (Passo 10): todos estes passavam sem ser vistos.
    ("aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "cabecalho_auth"),
    ("-----BEGIN RSA PRIVATE KEY----- MIIEpAIBAAKCAQEA1234", "chave_privada"),
    ("export DB_PASS=hunter2hunter2", "variavel_segredo"),
    ("export PGPASS=hunter2hunter2", "variavel_segredo"),
    ("export SENHA=minhasenha123", "variavel_segredo"),
    ("export ASSISTENTE_SENHA=minhasenha123", "variavel_segredo"),
    ("export SENHA_BANCO=Tr0ub4dor3", "variavel_segredo"),
    ("SECRET_KEY_BASE=abc123def456ghi", "variavel_segredo"),
    ("ROTEADOR_PASSWD=Tr0ub4dor3", "variavel_segredo"),
    ("TS_AUTHKEY=abc123def456ghi", "variavel_segredo"),
    ("export SECRET=abc123def456ghi", "variavel_segredo"),
    ("GOOGLE_CREDENTIAL=abc123def456ghi", "variavel_segredo"),
    ("CLIENT_SECRET=3f2a1b4c-5d6e-7f80-9a1b-2c3d4e5f6a7b", "variavel_segredo"),
    ("curl -u admin:SuperSecret123 https://x", "senha_cli"),
    ("curl --user admin:SuperSecret123 https://x", "senha_cli"),
    ("curl 'https://api.x.com/v1?api_key=9f8e7d6c5b4a39281706&q=1'", "url_com_token"),
    ("curl 'https://api.x.com/v1?token=9f8e7d6c5b4a39281706'", "url_com_token"),
    ("curl 'https://api.x.com/v1?key=9f8e7d6c5b4a39281706'", "url_com_token"),
    ("curl 'https://x.com/a?apikey=abc&access_token=9f8e7d6c5b4a39281706'", "url_com_token"),
    ("sshpass -p 'MinhaSenha!' ssh user@host", "senha_cli"),
    ("docker login -u x -p dckr_pat_AbCdEfGhIjKl0123456789", "senha_cli"),
    ("docker login -u x --password Abc123def456", "senha_cli"),
    ("glpat-AbCdEfGhIjKlMnOpQrSt", "gitlab"),
    ("hf_AbCdEfGhIjKlMnOpQrStUvWxYz012345", "huggingface"),
    ("sk_test_AbCdEfGhIjKlMnOpQrStUvWx", "stripe"),
    ("tskey-auth-kAbCdEf1CNTRL-AbCdEfGhIjKlMnOpQrStUv", "tailscale"),
    ("AccountKey=Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MGFiY2RlZg==;", "azure"),
    ("pluggy client_secret: 3f2a1b4c-5d6e-7f80-9a1b-2c3d4e5f6a7b", "cabecalho_auth"),
    ('{"password": "hunter2hunter"}', "cabecalho_auth"),
    ('{"api_key": "9f8e7d6c5b4a39281706"}', "cabecalho_auth"),
    ("api_key='9f8e7d6c5b4a39281706'", "cabecalho_auth"),
    ("accessToken: 9f8e7d6c5b4a39281706", "cabecalho_auth"),
    ("""-d '{"clientId":"abc","clientSecret":"3f2a1b4c5d6e7f809a1b"}'""", "cabecalho_auth"),
    ("curl -H 'Authorization: Basic dXNlcjpwYXNzd29yZA==' https://x", "cabecalho_auth"),
    ("--password 'minha senha com espaco'", "senha_cli"),
    ('export ANTHROPIC_API_KEY="sk-ant-api03-AbCdEfGhIjKlMnOp"', "chave_api"),
    # Achado 3 do revisor (Passo 5): senha em texto comum.
    ("A senha do banco é Tr0ca-Est@Senha99", "senha"),
    ("Senha do banco: Tr0ca-Est@Senha99", "senha"),
    ("**Senha:** Tr0ca-Est@Senha99", "senha"),
    ("**Senha**: Tr0ca-Est@Senha99", "senha"),
    ("senha: `Tr0ca-Est@Senha99`", "senha"),
    ("| senha | Tr0ca-Est@Senha99 |", "senha"),
    ("|Senha|Tr0ca-Est@Senha99|", "senha"),
    ("pwd: Tr0ca-Est@Senha99", "senha"),
    ("pass: Tr0ca-Est@Senha99", "senha"),
    ("senha: 12345678", "senha"),
    ("PIN do cartão: 98213377", "senha"),
    ("my password is Tr0ca-Est@Senha99", "senha"),
    ("Senha:: Tr0ca-Est@Senha99", "senha"),
    ("minha senha do wifi eh CasaDoLeo2024", "senha"),
    # O resto do valor depois da referência conta.
    ("password: {{segredo:a}}Tr0ca-Est@Senha99", "cabecalho_auth"),
    ("senha do banco: {{segredo:a}}Tr0ca-Est@Senha99", "senha"),
    ("postgres://u:{{segredo:a}}S3nhaF0rte@h/banco", "url_com_senha"),
]

# Achado 2 do revisor (Passo 5): prefixos de fornecedor, no formato real (montados em partes).
FORNECEDORES = [
    ("SG." + "Ab1" * 7 + "x" + "." + "Cd2" * 14 + "y", "sendgrid"),
    ("npm_" + "Ab1" * 12, "npm"),
    ("pypi-AgEIcHlwaS5vcmc" + "Ab1-" * 15, "pypi"),
    ("dop_v1_" + "a1" * 32, "digitalocean"),
    ("AGE-SECRET-KEY-1" + "QPZRY9X8GF" * 5 + "2TVDW0S3", "age"),
    ("glsa_" + "Ab1" * 10 + "Cd" + "_" + "0a1b2c3d", "grafana"),
    ("shpat_" + "0a1b" * 8, "shopify"),
    ("shpss_" + "0a1b" * 8, "shopify"),
    ("ntn_" + "1" * 11 + "Ab1" * 11 + "Cd", "notion"),
    ("lin_api_" + "Ab1x" * 10, "linear"),
]
# Parecidos com os prefixos, sem o formato: não casam.
FORNECEDORES_FALSOS = [
    "SG." + "Ab1" * 7 + "x",              # sem a segunda parte
    "SG.foo.bar",
    "npm_install_script e npm_" + "Ab1" * 11,  # 33 caracteres
    "pypi-upload pypi-AgEIcHlwaS5vcmc",
    "dop_v1_" + "a1" * 31,                # 62
    "dop_v1_" + "g" * 64,                 # fora do hexadecimal
    "AGE-SECRET-KEY-1 no manual do age",
    "AGE-SECRET-KEY-1" + "b" * 58,        # fora do alfabeto bech32 (maiúsculo)
    "glsa_token_do_grafana",
    "shpat_" + "0a1b" * 7,                # 28
    "ntn_12345 e ntn_" + "1" * 10 + "Ab1" * 11 + "Cd",
    "lin_api_key e lin_api_" + "Ab1x" * 9,
]

NEGATIVOS = [
    "ASIAPACIFICREGION",
    "ASIAEAST1CLUSTER",
    "planning the pit-stop-strategy-analysis",
    "commit 3f2a9c1d8e7b6a5f4e3d2c1b0a9f8e7d6c5b4a39",
    "minha-senha-e-forte",
    "{{segredo:ROTEADOR}}",
    "DB_PASSWORD={{segredo:BANCO}}",
    "postgres://u:{{segredo:BANCO}}@h/banco",
    "Authorization: Bearer {{segredo:API}}",
    "export TOKEN=$TOKEN",
    "API_KEY=<sua chave>",
    "cd $PWD && PWD=/tmp ls",
    "psql -h localhost -p 5432 banco",
    "docker login --password-stdin",
    "task-manager-de-tarefas-longas",
    "aspect ratio 16:9 widescreen",
    "00:00:00,000 --> 00:00:04,120",
    "api_key = config.get('x')",
    "https://github.com/akitaonrails/ai-memory",
    "git@github.com:leo/repo.git",
    # Achado 14 do revisor (Passo 10): falsos positivos.
    "sed -i 's/TOKEN: str/TOKEN: Optional[str]/' x.py",
    "Corrige o bearer token no README e a regra de authorization: bearerAuth",
    "docker run -e POSTGRES_PASSWORD=postgres postgres:16",
    "o campo password: obrigatorio",
    "mysql -u root -proot",
    "Ajusta session-token: renovarAutomatico no config",
    "Monta a ficha: Credentials: armazenadosNoCofre",
    "1//abcdefghijklmnopqrstuvwx",
    "echo 1234567:AAabcdefghijklmnopqrstuvwxyz0123456789",
    "AuthorizationPolicy: allowAll1234",
    "key: value e secret: escondidoMesmo",
    "git log --format='%H' -- password_reset.py",
    "grep -rn 'password=' servidor/",
    "grep -rn PASSWORD_HASH servidor/",
    "uv run pytest -k test_api_key_rotation",
    "python -c 'import os; print(os.environ[\"API_KEY\"])'",
    "cat .env | grep SECRET_KEY=",
    "echo $SECRET_KEY",
    "export TOKEN=$(cat ~/.token)",
    "export TOKEN=${TOKEN}",
    "pg_dump --password=$PGPASS",
    "echo 'Authorization: Bearer <token>'",
    "DB_PASSWORD=changeme",
    "SENHA=xxxxxxxxxxxx",
    "API_TOKEN=***********",
    "SECRET_KEY=...",
    "curl -u \"$USUARIO:$SENHA\" https://x",
    "sshpass -p \"$SENHA\" ssh user@host",
    "curl 'https://x.com/a?token=<seu-token>'",
    "PASSWORD=hunter2",
    "PASSWORD_FILE=/run/secrets/db1",
    "TOKEN_URL=https://oauth2.googleapis.com/token",
    "ssh leo@i7.tailnet.ts.net 'ls'",
    "rsync -av user@host:/path .",
    "python manage.py runserver 0.0.0.0:8000",
    "ffmpeg -i in.mp4 -c:v libx264 -preset slow -crf 22 -c:a aac -b:a 128k out.mp4",
    "export SENHA={{segredo:ROTEADOR}}",
    "curl -u admin:{{segredo:ADMIN}} https://x",
    "--password '{{segredo:BANCO}}'",
    # Achado 3 do revisor (Passo 5): texto comum sobre senha não é senha.
    "a senha é forte",
    "a senha do wifi está no cofre",
    "senha: {{segredo:wifi}}",
    "Senha do banco: {{segredo:banco}}",
    "password: obrigatório",
    "Senha: ver no Vaultwarden",
    "pin: 1234",
    "senha do cartão: 4821",
    "PASS: todos os testes passaram (609 passed)",
    "Passo 5: senha_padrao: definida no primeiro acesso",
    "password is required",
    "A senha: precisa ter 12 caracteres e um símbolo.",
    "senha: AniversarioDaMae",
    "Senha expira em: 2026-11-01",
    "| Senha | Onde |",
    "password = getpass.getpass('Senha: ')",
    # Achado 8 do revisor (Passo 5): falsos positivos que travavam o uso normal.
    "postgresql+psycopg://app:${DB_PASS}@db:5432/app",
    "postgres://u:senha@h/banco",
    "credentials: ~/.config/gcloud/application_default_credentials.json",
    "credentials: /srv/assistente/secrets/google.json",
    "secret_key = config.secret_key_base64",
    "client_secret: settings.google_client_secret",
    "Authorization: Basic usuario:senha em base64",
    "REDIS_PASSWORD=\nAPI_TOKEN=${API_TOKEN}",
    "https://meet.google.com/abc-defg-hij?authuser=0&key=chave",
    "Prefixo sk-learn-model-selection-guide em URL",
    "scikit-learn (sk-learn) usa sk-learn-pipeline-estimators",
    "JWT_SIGNING_KEY: ${JWT_SIGNING_KEY:?obrigatorio}",
    "token: 2026-10-22T10:30:00",
    "EAAAAAAAAAAAAAAAAAAAAAAAAAAAH grito",
]


@pytest.mark.parametrize("texto,tipo", POSITIVOS)
def test_acha_e_tira(texto, tipo):
    assert segredos.achar_segredo(texto) == tipo
    saida = segredos.tirar_segredos(texto)
    assert "[segredo:" in saida


@pytest.mark.parametrize("texto,tipo", FORNECEDORES)
def test_fornecedor_no_formato_real_casa(texto, tipo):
    assert segredos.achar_segredo(f"chave {texto} aqui") == tipo
    assert segredos.tirar_segredos(f"chave {texto} aqui") == f"chave [segredo:{tipo}] aqui"


@pytest.mark.parametrize("texto", FORNECEDORES_FALSOS)
def test_fornecedor_fora_do_formato_nao_casa(texto):
    assert segredos.achar_segredo(texto) is None


def test_atribuicao_nao_atravessa_linha():
    """`REDIS_PASSWORD=` vazio não pega a linha de baixo como valor (com `\\s*` pegava)."""
    assert segredos.achar_segredo("REDIS_PASSWORD=\nAbc123def456ghi") is None
    assert segredos.achar_segredo("password:\n  Tr0ca-Est@Senha99") is None
    assert segredos.achar_segredo("REDIS_PASSWORD=Abc123def456ghi") == "variavel_segredo"


def test_troca_so_a_senha_do_texto():
    assert segredos.tirar_segredos("A senha do banco é Tr0ca-Est@Senha99, ok?") == (
        "A senha do banco é [segredo:senha], ok?")
    assert segredos.tirar_segredos("postgres://u:S3nhaF0rte@h/banco") == "postgres://u:[segredo:url_com_senha]@h/banco"
    assert segredos.tirar_segredos("usa sk-proj-abcDEF123456789xyzABC") == "usa [segredo:chave_api]"


@pytest.mark.parametrize("texto", NEGATIVOS)
def test_falso_positivo_nao_casa(texto):
    assert segredos.achar_segredo(texto) is None
    assert segredos.tirar_segredos(texto) == texto


def test_tira_mantendo_o_resto():
    saida = segredos.tirar_segredos("aws AKIAIOSFODNN7EXAMPLE e ghp_AAAAbbbbCCCCddddEEEEffff1234 fim")
    assert saida == "aws [segredo:aws] e [segredo:github] fim"


def test_referencia_junto_de_segredo_real_casa():
    assert segredos.achar_segredo("DB_TOKEN=valorReal123{{segredo:X}}") == "variavel_segredo"


def test_troca_so_o_valor_e_guarda_o_nome():
    assert segredos.tirar_segredos("export DB_PASS=hunter2hunter2 && ls") == (
        "export DB_PASS=[segredo:variavel_segredo] && ls"
    )
    assert segredos.tirar_segredos("curl -u admin:SuperSecret123 https://x") == (
        "curl -u admin:[segredo:senha_cli] https://x"
    )
    assert segredos.tirar_segredos("--password 'minha senha com espaco' -h x") == (
        "--password [segredo:senha_cli] -h x"
    )


def test_pem_sem_fim_vai_ate_o_fim_do_texto():
    texto = "antes\n-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\nmais linha\n"
    assert segredos.tirar_segredos(texto) == "antes\n[segredo:chave_privada]"


@pytest.mark.parametrize("valor,esperado", [
    ("hunter2222", True),             # minúscula + dígito
    ("Tr0ub4dor&3", True),
    ("abcdefghijklmnopqrstu", True),  # 16+ caracteres, uma classe
    ("hunter2", False),               # menos de 8
    ("postgres", False),
    ("changeme", False),
    ("obrigatorio", False),
    ("renovarAutomatico", False),     # camelCase: nome, não segredo
    ("minha-senha-e-forte", False),   # palavras com hífen
    ("config.get", False),
    ("$TOKEN", False),
    ("${TOKEN}", False),
    ("<sua chave>", False),
    ("xxxxxxxxxxxx", False),
    ("'{{segredo:X}}'", False),
    ("[segredo:aws]", False),
    ("~/.config/gcloud/application_default_credentials.json", False),  # caminho
    ("/run/secrets/paperless", False),
    ("secrets/google.json", False),
    ("config.secret_key_base64", False),  # atributo de código
    ("process.env.OPENAI_API_KEY", False),
    ("2026-10-22T10:30:00-03:00", False),  # data
    ("?obrigatorio", False),  # ${X:?obrigatorio}
    ("wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", True),  # base64 com / não é caminho
    ("Tr0ca.Est@99", True),
    ("{{segredo:a}}Tr0ca-Est@Senha99", True),  # o resto, sem a referência
])
def test_parece_segredo(valor, esperado):
    assert segredos.parece_segredo(valor) is esperado


def test_vazio():
    assert segredos.achar_segredo("") is None
    assert segredos.tirar_segredos("") == ""


def test_padroes_compilam_e_tem_tipo():
    assert len(segredos.PADROES) >= 20
    for padrao, tipo in segredos.PADROES:
        re.compile(padrao)
        assert re.match(r"^[a-z0-9_]+$", tipo)


def test_copia_do_servidor_igual():
    """O servidor guarda uma cópia deste arquivo (a imagem só leva servidor/); as duas são iguais byte a byte."""
    raiz = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    caminho = os.path.join(raiz, "servidor", "assistente", "segredos.py")
    if not os.path.exists(caminho):
        pytest.skip("servidor/assistente/segredos.py não existe (cópia fora do repositório)")
    with open(caminho, "rb") as f1, open(segredos.__file__, "rb") as f2:
        assert f1.read() == f2.read(), "As duas cópias de segredos.py divergem: mude as duas juntas."
    import importlib.util

    spec = importlib.util.spec_from_file_location("segredos_servidor", caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    assert list(modulo.PADROES) == list(segredos.PADROES)
    assert getattr(modulo, "REFERENCIA", segredos.REFERENCIA) == segredos.REFERENCIA


# Achado 4 do revisor (Passo 5): cada padrão com 1 milhão de caracteres hostis. Medido no Mac (2026-10-22): o pior
# padrão leva ~0,14 s; o limite de 2 s dá folga para CI e para o i7.
HOSTIS = ["-", "_", "a", " ", "=", ":", "a-_ =:", "aA1-", "x-api-", "curl ", "mysql ", "sshpass ", "docker login ",
          "pin ", "senha ", "a://a:", "{{segredo:a}}", "basic "]


@pytest.mark.parametrize("unidade", HOSTIS)
def test_cada_padrao_e_linear(unidade):
    import time

    texto = (unidade * (1_000_000 // len(unidade) + 1))[:1_000_000] + "!"
    lentos = []
    for (regex, tipo), (padrao, _) in zip(segredos._COMPILADOS, segredos.PADROES):
        inicio = time.perf_counter()
        for _ in regex.finditer(texto):
            pass
        if (gasto := time.perf_counter() - inicio) > 2.0:
            lentos.append((tipo, round(gasto, 2), padrao[:40]))
    assert lentos == []


@pytest.mark.parametrize("unidade", [
    "a-", "__", "TOKEN_", "password://AKIA", ".curl ", "mysql ", "sshpass ", "docker login ", "a://b:", "a" * 7,
    "x-api-", "API_", "curl -u a:", "eyJ", "-----BEGIN ", "?token=",
])
def test_sem_backtracking_quadratico(unidade):
    """Texto hostil de 50.000 caracteres (nota, comando) não trava: cada padrão tem limite (antes, 'a-' levava minutos)."""
    import time

    texto = (unidade * (50_000 // len(unidade) + 1))[:50_000]
    inicio = time.perf_counter()
    segredos.achar_segredo(texto)
    segredos.tirar_segredos(texto)
    assert time.perf_counter() - inicio < 3.0
