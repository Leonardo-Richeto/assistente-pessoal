"""Gestão do Paperless único (Ficha 6). Roda dentro do webserver, pelo `manage.py shell`:

    docker compose exec -T -u paperless -e GESTAO_ACAO=<acao> -e USUARIOS="leonardo nathalia" \
        -e ADMIN=admin webserver python3 manage.py shell < paperless/deploy/gestao.py

Ações (GESTAO_ACAO):
    preparar   cria ou acerta os usuários comuns, as permissões e os workflows de dono (idempotente)
    conferir   lista o que fere a Ficha 6 e avisa arquivo parado na pasta de entrada (Ficha 7);
               última linha "ok" ou "problemas: N"
    renomear   troca o nome de um usuário comum (DE -> PARA, PARA em USUARIOS) e o do workflow da pasta dele
    contar     linhas "chave<TAB>valor" para o manifesto do backup e o ensaio de restauração
    token      imprime o token da API de GESTAO_USUARIO (cria se não existe)

Nunca apaga nada. Só o `token` imprime segredo.
"""

import os
import sys
import time
from pathlib import Path

from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from guardian.models import GroupObjectPermission, UserObjectPermission

from documents.models import (
    Correspondent,
    Document,
    DocumentType,
    Note,
    StoragePath,
    Tag,
    Workflow,
    WorkflowAction,
    WorkflowTrigger,
)

ACAO = os.environ.get("GESTAO_ACAO", "")
USUARIOS = os.environ.get("USUARIOS", "").split()
ADMIN = os.environ.get("ADMIN", "admin")
CONSUMO = "/usr/src/paperless/consume"
# Ficha 7, item 5: o Paperless apaga o arquivo que entra; o que fica mais que isso na pasta de entrada não entrou.
PARADO_HORAS = float(os.environ.get("PARADO_HORAS") or 24)
# Lixo de sistema e de editor que o Paperless ignora (padrões dele e PAPERLESS_CONSUMER_IGNORE_PATTERNS).
IGNORADOS = ("desktop.ini", "Thumbs.db")

# Item 2 da Ficha 6: ver, criar e trocar o que tem dono; nunca apagar; sem usuários, grupos, e-mail, workflow
# nem tarefas (tarefa sem dono mostra o nome do arquivo do outro). Campo personalizado e visão salva: só ver
# (o campo não tem dono no Paperless). Técnicas: uisettings (a interface web) e auditlog.view_logentry (o
# histórico do documento; o Paperless confere o dono antes).
PERMISSOES = sorted(
    [f"documents.{a}_{m}" for m in ("document", "note", "tag", "correspondent", "documenttype", "storagepath")
     for a in ("view", "add", "change")]
    + ["documents.view_customfield", "documents.view_savedview",
       "documents.view_uisettings", "documents.add_uisettings", "documents.change_uisettings",
       "auditlog.view_logentry"]
)
# Objetos com dono: sem dono, o nome aparece para os dois (item 6).
COM_DONO = (Tag, Correspondent, DocumentType, StoragePath)


def _permissoes():
    achadas = []
    for nome in PERMISSOES:
        app, codigo = nome.split(".")
        achadas.append(Permission.objects.get(content_type__app_label=app, codename=codigo))
    return achadas


def _regras():
    """Workflows de dono. Nos sobrepostos, o último aplicado vence (workflows/mutations.py da 3.3.4):
    a reserva (raiz) roda primeiro, e a pasta de cada pessoa sobrescreve depois."""
    regras = [("dono: raiz de consumir", f"{CONSUMO}/*", USUARIOS[0], 0)]
    return regras + [(f"dono: consumir/{n}", f"{CONSUMO}/{n}/*", n, 10 + i) for i, n in enumerate(USUARIOS)]


def _todos_documentos():
    # Inclui a lixeira: documento apagado também volta pelo restaurar.
    return getattr(Document, "global_objects", Document.objects)


@transaction.atomic
def preparar():
    if not USUARIOS:
        sys.exit("USUARIOS vazio.")
    perms = _permissoes()
    for nome in USUARIOS:
        u, novo = User.objects.get_or_create(username=nome)
        if novo:
            u.set_unusable_password()  # entra na web só depois de o admin definir a senha
        u.is_superuser = False
        u.is_staff = False
        u.is_active = True
        u.save()
        u.user_permissions.set(perms)
        u.groups.clear()
        print(f"usuário {nome}: {'criado' if novo else 'acertado'}, {len(perms)} permissões")

    for nome, caminho, dono, ordem in _regras():
        wf = Workflow.objects.filter(name=nome).first()
        if wf is None:
            wf = Workflow.objects.create(name=nome, order=ordem)
            wf.triggers.add(WorkflowTrigger.objects.create(
                type=WorkflowTrigger.WorkflowTriggerType.CONSUMPTION))
            wf.actions.add(WorkflowAction.objects.create(
                type=WorkflowAction.WorkflowActionType.ASSIGNMENT))
        wf.order = ordem
        wf.enabled = True
        wf.save()
        for t in wf.triggers.all():
            t.type = WorkflowTrigger.WorkflowTriggerType.CONSUMPTION
            t.sources = [str(WorkflowTrigger.DocumentSourceChoices.CONSUME_FOLDER.value)]
            t.filter_path = caminho
            t.filter_filename = None
            t.save()
        for a in wf.actions.all():
            a.type = WorkflowAction.WorkflowActionType.ASSIGNMENT
            a.assign_owner = User.objects.get(username=dono)
            a.save()
            # Nenhuma permissão extra para ninguém (item 5: sem compartilhamento).
            a.assign_view_users.clear()
            a.assign_view_groups.clear()
            a.assign_change_users.clear()
            a.assign_change_groups.clear()
        print(f"workflow '{nome}': {caminho} -> {dono} (ordem {ordem})")


def _parados():
    """{pasta: [arquivos]} com mais de PARADO_HORAS na pasta de consumo. Conta pela chegada (ctime): o Syncthing
    mantém a data de modificação do aparelho, que pode ser antiga. Oculto (.stfolder/, .stignore, temporário do
    Syncthing) e trava de editor ficam fora."""
    limite = time.time() - PARADO_HORAS * 3600
    raiz = Path(CONSUMO)
    achados = {}
    for caminho in sorted(raiz.rglob("*")):
        rel = caminho.relative_to(raiz)
        if (any(p.startswith(".") for p in rel.parts) or caminho.name.startswith("~$")
                or caminho.name in IGNORADOS or not caminho.is_file()):
            continue
        try:
            chegada = caminho.stat().st_ctime
        except FileNotFoundError:  # o Paperless consumiu entre o rglob e o stat
            continue
        if chegada < limite:
            pasta = f"consumir/{rel.parts[0]}" if len(rel.parts) > 1 else "raiz de consumir"
            achados.setdefault(pasta, []).append(str(rel))
    return achados


def conferir():
    problemas = []
    docs = _todos_documentos()
    sem_dono = list(docs.filter(owner__isnull=True).values_list("id", flat=True)[:20])
    if sem_dono:
        problemas.append(f"{docs.filter(owner__isnull=True).count()} documento(s) sem dono (visíveis aos dois): ids {sem_dono}")

    tipo_doc = ContentType.objects.get_for_model(Document)
    dados = UserObjectPermission.objects.filter(content_type=tipo_doc)
    if dados.exists():
        problemas.append(f"{dados.count()} permissão(ões) de documento dadas a usuário (sem compartilhamento): "
                         f"documentos {sorted(set(dados.values_list('object_pk', flat=True)))[:20]}")
    dados_g = GroupObjectPermission.objects.filter(content_type=tipo_doc)
    if dados_g.exists():
        problemas.append(f"{dados_g.count()} permissão(ões) de documento dadas a grupo")
    for g in Group.objects.all():
        if g.user_set.exists():
            problemas.append(f"grupo '{g.name}' com membros (sem compartilhamento, não há grupo)")

    for modelo in COM_DONO:
        n = modelo.objects.filter(owner__isnull=True).count()
        if n:
            nomes = list(modelo.objects.filter(owner__isnull=True).values_list("name", flat=True)[:5])
            problemas.append(f"{n} {modelo.__name__} sem dono (o nome aparece para os dois): {nomes}")

    for u in User.objects.filter(is_superuser=True).exclude(username=ADMIN):
        problemas.append(f"superusuário inesperado: {u.username}")
    esperadas = set(PERMISSOES)
    for nome in USUARIOS:
        u = User.objects.filter(username=nome).first()
        if u is None:
            problemas.append(f"usuário {nome} não existe (rode preparar.sh)")
            continue
        if u.is_superuser or u.is_staff:
            problemas.append(f"usuário {nome} é superusuário ou staff")
        diretas = {f"{p.content_type.app_label}.{p.codename}" for p in u.user_permissions.all()}
        if diretas != esperadas:
            problemas.append(f"usuário {nome} com permissões diferentes da Ficha 6: "
                             f"a mais {sorted(diretas - esperadas)}, a menos {sorted(esperadas - diretas)}")
        if u.groups.exists():
            problemas.append(f"usuário {nome} em grupo")

    for nome, caminho, dono, _ in _regras():
        wf = Workflow.objects.filter(name=nome, enabled=True).first()
        if wf is None:
            problemas.append(f"workflow '{nome}' ausente ou desligado (rode preparar.sh)")
            continue
        gatilhos, acoes = list(wf.triggers.all()), list(wf.actions.all())
        certo = (
            len(gatilhos) == 1 and len(acoes) == 1
            and gatilhos[0].type == WorkflowTrigger.WorkflowTriggerType.CONSUMPTION
            and [str(x) for x in gatilhos[0].sources] == [str(WorkflowTrigger.DocumentSourceChoices.CONSUME_FOLDER.value)]
            and gatilhos[0].filter_path == caminho and not gatilhos[0].filter_filename
            and acoes[0].type == WorkflowAction.WorkflowActionType.ASSIGNMENT
            and acoes[0].assign_owner is not None and acoes[0].assign_owner.username == dono
            and not (acoes[0].assign_view_users.exists() or acoes[0].assign_view_groups.exists()
                     or acoes[0].assign_change_users.exists() or acoes[0].assign_change_groups.exists())
        )
        if not certo:
            problemas.append(f"workflow '{nome}' mudou (esperado {caminho} -> {dono}, sem permissão extra; rode preparar.sh)")
    outros = Workflow.objects.exclude(name__in=[r[0] for r in _regras()]).filter(enabled=True)
    if outros.exists():
        problemas.append(f"workflow fora da Ficha 6 ligado: {list(outros.values_list('name', flat=True))}")

    # Aviso, não problema: não fere a Ficha 6 (Ficha 7, item 5). Nomes só no log do i7.
    for pasta, arquivos in _parados().items():
        print(f"AVISO: {len(arquivos)} arquivo(s) parado(s) há mais de {PARADO_HORAS:g} h em {pasta} "
              f"(não entraram no Paperless): {arquivos[:5]}")

    for p in problemas:
        print(f"PROBLEMA: {p}")
    print("ok" if not problemas else f"problemas: {len(problemas)}")


def contar():
    docs = _todos_documentos()
    print(f"documentos\t{docs.count()}")
    print(f"documentos_sem_dono\t{docs.filter(owner__isnull=True).count()}")
    for u in User.objects.order_by("username"):
        print(f"documentos_de_{u.username}\t{docs.filter(owner=u).count()}")
    print(f"notas\t{Note.objects.count()}")
    for modelo in COM_DONO:
        print(f"{modelo.__name__.lower()}\t{modelo.objects.count()}")
    print(f"usuarios\t{User.objects.count()}")
    print(f"workflows\t{Workflow.objects.count()}")


@transaction.atomic
def renomear():
    """Troca o nome do usuário DE para PARA (o de USUARIOS) e o nome e o caminho do workflow da pasta dele, juntos:
    nunca há um momento em que a pasta nova cai só no workflow da raiz (dono errado). Documentos, token e
    permissões ficam com o mesmo usuário. Idempotente: com PARA já existente e DE não, não faz nada."""
    de, para = os.environ.get("DE", ""), os.environ.get("PARA", "")
    if not de or para not in USUARIOS or de in USUARIOS:
        sys.exit(f"renomear: DE ('{de}') fora de USUARIOS e PARA ('{para}') em USUARIOS.")
    antigo, novo = User.objects.filter(username=de).first(), User.objects.filter(username=para).first()
    if antigo is None:
        if novo is None:
            sys.exit(f"renomear: nem {de} nem {para} existem; confira os nomes.")
        print(f"usuário {de}: não existe (já renomeado)")
        return
    if novo is not None:
        sys.exit(f"renomear: {de} e {para} existem os dois; acerte pela interface web (como admin).")
    if antigo.is_superuser or antigo.is_staff:
        sys.exit(f"renomear: {de} é superusuário ou staff.")
    antigo.username = para
    antigo.save()
    n = 0
    for wf in Workflow.objects.filter(name=f"dono: consumir/{de}"):
        wf.name = f"dono: consumir/{para}"
        wf.save()
        wf.triggers.update(filter_path=f"{CONSUMO}/{para}/*")
        n += 1
    print(f"usuário {de} -> {para}; workflows renomeados: {n}")


def token():
    from rest_framework.authtoken.models import Token

    nome = os.environ.get("GESTAO_USUARIO", "")
    u = User.objects.filter(username=nome).first()
    if u is None or nome not in USUARIOS:
        sys.exit(f"usuário comum '{nome}' não existe (só os de USUARIOS têm token).")
    if u.is_superuser or u.is_staff:
        sys.exit(f"'{nome}' é superusuário ou staff: token recusado.")
    print(Token.objects.get_or_create(user=u)[0].key)


ACOES = {"preparar": preparar, "conferir": conferir, "contar": contar, "renomear": renomear, "token": token}
if ACAO not in ACOES:
    sys.exit(f"GESTAO_ACAO inválida: '{ACAO}' (use {', '.join(ACOES)}).")
ACOES[ACAO]()
