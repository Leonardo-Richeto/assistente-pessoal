# Ferramentas dos scripts de backup e migração para máquinas sem `age` instalado (Windows, Mac).
# No Debian, o preparar_host.sh instala o age do sistema e esta imagem não é usada.
# Versões fixas: para atualizar, troque a tag e o digest juntos e a versão do pacote.
FROM alpine:3.24.2@sha256:294b683cb724975bec92580e1e685676bd4b50bda910ddb8c51d4cabeaec77e6
RUN apk add --no-cache age=1.3.2-r1
USER 1000:1000
