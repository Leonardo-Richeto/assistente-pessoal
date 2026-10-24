"""Ficha 6: cada token do Paperless único só vê os documentos do próprio dono.

Só roda contra um Paperless de TESTE (paperless/scripts/preparar.sh com documentos sintéticos). Sem as
variáveis, o teste é pulado. O teste sobe documentos sintéticos; nunca aponte para o Paperless real.

    PAPERLESS_TESTE_URL=http://127.0.0.1:8010
    PAPERLESS_TESTE_TOKEN_A=$(PAPERLESS_HOME=<teste> paperless/scripts/token.sh leonardo)
    PAPERLESS_TESTE_TOKEN_B=$(PAPERLESS_HOME=<teste> paperless/scripts/token.sh esposa)
    PAPERLESS_TESTE_CONSUMIR=<teste>/consumir     # opcional: confere os workflows de dono
    uv run pytest tests/test_paperless_isolamento.py

A parte da peça (paperless-mcp pelo proxy, como o servidor monta) roda com `uvx` no PATH.
"""

import os
import io
import shutil
import time
import uuid
import zipfile
from pathlib import Path

import httpx2 as httpx
import pytest
from fastmcp import Client
from fastmcp.server import create_proxy

URL = os.environ.get("PAPERLESS_TESTE_URL", "").rstrip("/")
TOKEN_A = os.environ.get("PAPERLESS_TESTE_TOKEN_A", "")
TOKEN_B = os.environ.get("PAPERLESS_TESTE_TOKEN_B", "")
CONSUMIR = os.environ.get("PAPERLESS_TESTE_CONSUMIR", "")

pytestmark = pytest.mark.skipif(not (URL and TOKEN_A and TOKEN_B), reason="sem Paperless de teste (PAPERLESS_TESTE_*)")


def _pdf(texto: str) -> bytes:
    """PDF mínimo com uma linha de texto (camada de texto: o OCR não precisa rodar)."""
    conteudo = f"BT /F1 18 Tf 72 720 Td ({texto}) Tj ET".encode()
    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(conteudo) + conteudo + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    saida = bytearray(b"%PDF-1.4\n")
    posicoes = []
    for i, o in enumerate(objetos, 1):
        posicoes.append(len(saida))
        saida += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(saida)
    saida += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objetos) + 1)
    for p in posicoes:
        saida += b"%010d 00000 n \n" % p
    saida += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objetos) + 1, xref)
    return bytes(saida)


def _zip(arquivos: dict[str, str]) -> bytes:
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as z:
        for nome, texto in arquivos.items():
            z.writestr(nome, texto)
    return saida.getvalue()


_RELS = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
         '<Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="{}"/>'
         '</Relationships>')


def _docx(texto: str) -> bytes:
    """Word mínimo (um parágrafo)."""
    return _zip({
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        "_rels/.rels": _RELS.format("word/document.xml"),
        "word/document.xml": '<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:body><w:p><w:r><w:t>{texto}</w:t></w:r></w:p></w:body></w:document>',
    })


def _xlsx(texto: str) -> bytes:
    """Excel mínimo (uma célula de texto e uma fórmula)."""
    return _zip({
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        "_rels/.rels": _RELS.format("xl/workbook.xml"),
        "xl/workbook.xml": '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Gastos" sheetId="1" r:id="r1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                                       '<Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                                       '</Relationships>'),
        "xl/worksheets/sheet1.xml": '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        f'<row r="1"><c r="A1" t="inlineStr"><is><t>{texto}</t></is></c><c r="B1"><v>2</v></c><c r="C1"><f>B1*21</f><v>42</v></c></row>'
        '</sheetData></worksheet>',
    })


DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _cliente(token: str) -> httpx.Client:
    return httpx.Client(base_url=URL, headers={"Authorization": f"Token {token}", "Accept": "application/json; version=9"},
                        timeout=30)


def _esperar_documento(c: httpx.Client, titulo: str, limite: float = 180) -> dict:
    inicio = time.monotonic()
    while time.monotonic() - inicio < limite:
        r = c.get("/api/documents/", params={"title__icontains": titulo})
        r.raise_for_status()
        if r.json()["results"]:
            return r.json()["results"][0]
        time.sleep(3)
    raise AssertionError(f"documento '{titulo}' não apareceu em {limite}s")


def _subir(c: httpx.Client, titulo: str, texto: str, ext: str = "pdf", conteudo: bytes | None = None,
           tipo: str = "application/pdf") -> dict:
    conteudo = _pdf(texto) if conteudo is None else conteudo
    r = c.post("/api/documents/post_document/", files={"document": (f"{titulo}.{ext}", conteudo, tipo)},
               data={"title": titulo})
    assert r.status_code == 200, r.text
    return _esperar_documento(c, titulo)


@pytest.fixture(scope="module")
def docs():
    marca = uuid.uuid4().hex[:8]
    with _cliente(TOKEN_A) as a, _cliente(TOKEN_B) as b:
        da = _subir(a, f"sintetico-a-{marca}", f"Nota fiscal geladeira {marca} alfa")
        db = _subir(b, f"sintetico-b-{marca}", f"Contrato aluguel {marca} beta")
        yield {"marca": marca, "a": da, "b": db}


@pytest.mark.parametrize("ext,fazer,tipo", [("docx", _docx, DOCX), ("xlsx", _xlsx, XLSX)])
def test_word_e_excel_entram_com_texto_e_ficam_isolados(docs, ext, fazer, tipo):
    """Tika extrai o texto; Gotenberg gera o PDF de visualização; o original volta igual no download."""
    titulo = f"office-{ext}-{docs['marca']}"
    original = fazer(f"Planilha sintetica {docs['marca']} {ext}")
    with _cliente(TOKEN_A) as a, _cliente(TOKEN_B) as b:
        doc = _subir(a, titulo, "", ext, original, tipo)
        assert docs["marca"] in a.get(f"/api/documents/{doc['id']}/").json()["content"]
        assert a.get(f"/api/documents/{doc['id']}/preview/").headers["content-type"].startswith("application/pdf")
        assert a.get(f"/api/documents/{doc['id']}/download/", params={"original": "true"}).content == original
        assert b.get(f"/api/documents/{doc['id']}/").status_code == 404
        busca = b.get("/api/documents/", params={"query": f"{docs['marca']} {ext}"}).json()["results"]
        assert doc["id"] not in {d["id"] for d in busca}


def test_tag_criada_pela_api_sem_owner_fica_com_o_dono(docs):
    """Pela interface (sem o campo owner), a tag nasce com o dono. A peça manda owner nulo e por isso
    paperless_create_tag está bloqueada (test_bloqueadas)."""
    with _cliente(TOKEN_A) as a, _cliente(TOKEN_B) as b:
        r = a.post("/api/tags/", json={"name": f"tag-a-{docs['marca']}"})
        assert r.status_code == 201, r.text
        assert r.json()["owner"] == _usuario(a)
        assert f"tag-a-{docs['marca']}" not in {t["name"] for t in b.get("/api/tags/").json()["results"]}


def test_tarefas_fechadas_para_o_usuario_comum():
    """Tarefa da pasta de consumo nasce sem dono e mostra o nome do arquivo: o usuário comum não lê tarefas."""
    with _cliente(TOKEN_A) as a:
        assert a.get("/api/tasks/").status_code == 403


def _usuario(c: httpx.Client) -> int:
    r = c.get("/api/ui_settings/")
    r.raise_for_status()
    return r.json()["user"]["id"]


def test_upload_pela_api_sai_com_o_dono_do_token(docs):
    with _cliente(TOKEN_A) as a, _cliente(TOKEN_B) as b:
        assert docs["a"]["owner"] == _usuario(a)
        assert docs["b"]["owner"] == _usuario(b)
        assert docs["a"]["owner"] != docs["b"]["owner"]


@pytest.mark.parametrize("caminho", ["/api/documents/{id}/", "/api/documents/{id}/download/",
                                     "/api/documents/{id}/preview/", "/api/documents/{id}/thumb/",
                                     "/api/documents/{id}/metadata/", "/api/documents/{id}/notes/",
                                     "/api/documents/{id}/history/", "/api/documents/{id}/suggestions/"])
def test_id_direto_do_outro_nao_abre(docs, caminho):
    with _cliente(TOKEN_A) as a, _cliente(TOKEN_B) as b:
        for c, outro in ((a, docs["b"]), (b, docs["a"])):
            r = c.get(caminho.format(id=outro["id"]))
            assert r.status_code in (403, 404), (caminho, r.status_code)


def test_buscas_e_estatistica_so_mostram_o_proprio(docs):
    with _cliente(TOKEN_A) as a:
        r = a.get("/api/documents/", params={"page_size": 100000})
        assert r.status_code == 200
        ids = {d["id"] for d in r.json()["results"]}
        assert docs["a"]["id"] in ids and docs["b"]["id"] not in ids
        r = a.get("/api/documents/", params={"query": f"{docs['marca']}"})
        assert r.status_code == 200
        texto = r.json()["results"]
        assert {d["id"] for d in texto} <= ids
        assert docs["b"]["id"] not in {d["id"] for d in texto}
        r = a.get("/api/search/", params={"query": docs["marca"]})
        assert r.status_code == 200
        assert docs["b"]["id"] not in {d["id"] for d in r.json()["documents"]}
        # "Parecidos com" o documento do outro: o Paperless recusa (403) em vez de devolver vazio.
        r = a.get("/api/documents/", params={"more_like_id": docs["b"]["id"]})
        assert r.status_code == 403 or docs["b"]["id"] not in {d["id"] for d in r.json()["results"]}
        r = a.get("/api/search/autocomplete/", params={"term": "bet"})
        assert r.status_code == 200 and "beta" not in r.json()
        r = a.get("/api/statistics/")
        assert r.status_code == 200
        estat = r.json()
        assert estat["documents_total"] == len(ids)


def test_mudanca_no_documento_do_outro_e_recusada(docs):
    with _cliente(TOKEN_A) as a:
        r = a.patch(f"/api/documents/{docs['b']['id']}/", json={"title": "invadido"})
        assert r.status_code in (403, 404)
        r = a.post(f"/api/documents/{docs['b']['id']}/notes/", json={"note": "invadido"})
        assert r.status_code in (403, 404)
        r = a.delete(f"/api/documents/{docs['a']['id']}/")
        assert r.status_code == 403  # nem o próprio: sem permissão de apagar (item 2)


@pytest.mark.skipif(not CONSUMIR, reason="sem PAPERLESS_TESTE_CONSUMIR")
def test_workflows_poem_o_dono_pela_pasta(docs):
    with _cliente(TOKEN_A) as a, _cliente(TOKEN_B) as b:
        ua, ub = _usuario(a), _usuario(b)
        casos = {"": (a, ua), "esposa": (b, ub), "leonardo": (a, ua)}
        for pasta, (c, dono) in casos.items():
            titulo = f"pasta-{pasta or 'raiz'}-{docs['marca']}"
            (Path(CONSUMIR) / pasta / f"{titulo}.pdf").write_bytes(_pdf(f"Pasta {pasta or 'raiz'} {docs['marca']}"))
            doc = _esperar_documento(c, titulo)
            assert doc["owner"] == dono, (pasta, doc["owner"], dono)


@pytest.mark.skipif(not shutil.which("uvx"), reason="sem uvx para rodar a peça paperless-mcp")
async def test_peca_paperless_mcp_com_o_token_de_um_nao_ve_o_outro(docs):
    proxy = create_proxy({"mcpServers": {"paperless": {
        "command": "uvx", "args": ["--from", "paperless-mcp==0.1.0", "paperless-mcp", "--stdio"],
        "env": {"PAPERLESS_URL": URL, "PAPERLESS_TOKEN": TOKEN_A},
    }}})
    async with Client(proxy) as c:
        r = await c.call_tool("search_documents", {"query": docs["marca"]}, raise_on_error=False)
        assert not r.is_error
        ids = {d["id"] for d in r.structured_content["documents"]}
        assert docs["a"]["id"] in ids and docs["b"]["id"] not in ids
        assert "sintetico-b" not in str(r.structured_content)
        # A peça devolve o 404 do Paperless como resultado, não como erro de protocolo.
        r = await c.call_tool("get_document", {"document_id": docs["b"]["id"]}, raise_on_error=False)
        assert r.is_error or (r.structured_content or {}).get("error") == "not_found", r
        r = await c.call_tool("get_document", {"document_id": docs["a"]["id"]}, raise_on_error=False)
        assert not r.is_error
