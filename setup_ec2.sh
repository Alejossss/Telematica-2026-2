#!/usr/bin/env bash
#
# setup_ec2.sh — Aprovisionamiento de la Plataforma Distribuida de Telemetria
#                sobre una instancia Ubuntu Server de AWS EC2 (Punto 8).
#
# Que hace:
#   1. Instala Docker Engine + complemento Docker Compose (repo oficial Docker).
#   2. Habilita y arranca el servicio docker.
#   3. Anade el usuario actual al grupo docker (uso sin sudo).
#   4. Configura el firewall UFW: 22/tcp, 6000/tcp, 5000/udp, 8080/tcp.
#   5. Construye y levanta el sistema con: docker compose up --build -d.
#   6. Muestra estado y resumen de verificacion.
#
# No modifica ningun codigo fuente del proyecto. Es idempotente: se puede
# volver a ejecutar sin duplicar reglas ni reinstalar lo ya instalado.
#
# Uso (dentro de la instancia, desde la raiz del repositorio clonado):
#   chmod +x setup_ec2.sh
#   ./setup_ec2.sh
#
# Requiere Ubuntu 22.04/24.04 y permisos sudo.

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuracion
# ---------------------------------------------------------------------------
TCP_PORT="6000"      # TSP: registro de nodos, comandos de operador, alertas
UDP_PORT="5000"      # TSP: telemetria
WEB_PORT="8080"      # Servicio_Web (HTTP)
SSH_PORT="22"        # Acceso remoto de administracion

# Directorio del script = raiz del repositorio (donde vive docker-compose.yml)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Usuario real (no root) al que dar acceso a docker
TARGET_USER="${SUDO_USER:-$(id -un)}"

# ---------------------------------------------------------------------------
# Utilidades de log
# ---------------------------------------------------------------------------
log()  { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m  OK\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m  !!\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# Ejecuta un comando como root usando sudo si no somos root
run() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    else
        sudo "$@"
    fi
}

# ---------------------------------------------------------------------------
# 0. Comprobaciones previas
# ---------------------------------------------------------------------------
log "Comprobaciones previas"

if [ "$(id -u)" -ne 0 ] && ! command -v sudo >/dev/null 2>&1; then
    die "Se necesita sudo (o ejecutar como root)."
fi

if [ ! -f "${SCRIPT_DIR}/docker-compose.yml" ]; then
    die "No se encontro docker-compose.yml en ${SCRIPT_DIR}. Ejecuta el script desde la raiz del repositorio."
fi
ok "docker-compose.yml encontrado en ${SCRIPT_DIR}"

# ---------------------------------------------------------------------------
# 1. Instalar Docker Engine + Compose
# ---------------------------------------------------------------------------
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    ok "Docker y el complemento Compose ya estan instalados; se omite la instalacion."
else
    log "Instalando Docker Engine y el complemento Docker Compose (repo oficial)"

    run apt-get update -y
    run apt-get install -y ca-certificates curl gnupg lsb-release

    # Clave GPG oficial de Docker (idempotente)
    run install -m 0755 -d /etc/apt/keyrings
    if [ ! -f /etc/apt/keyrings/docker.gpg ]; then
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
            | run gpg --dearmor -o /etc/apt/keyrings/docker.gpg
        run chmod a+r /etc/apt/keyrings/docker.gpg
    fi

    # Repositorio de Docker
    ARCH="$(dpkg --print-architecture)"
    CODENAME="$(. /etc/os-release && echo "${VERSION_CODENAME}")"
    echo \
        "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${CODENAME} stable" \
        | run tee /etc/apt/sources.list.d/docker.list >/dev/null

    run apt-get update -y
    run apt-get install -y \
        docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin

    ok "Docker instalado."
fi

# ---------------------------------------------------------------------------
# 2. Habilitar y arrancar el servicio docker
# ---------------------------------------------------------------------------
log "Habilitando y arrancando el servicio docker"
run systemctl enable --now docker
ok "Servicio docker activo."

# ---------------------------------------------------------------------------
# 3. Anadir el usuario al grupo docker
# ---------------------------------------------------------------------------
if id -nG "${TARGET_USER}" | tr ' ' '\n' | grep -qx docker; then
    ok "El usuario '${TARGET_USER}' ya pertenece al grupo docker."
else
    log "Anadiendo '${TARGET_USER}' al grupo docker"
    run usermod -aG docker "${TARGET_USER}"
    warn "Para usar docker sin sudo en esta sesion ejecuta: newgrp docker (o reconectate por SSH)."
fi

# ---------------------------------------------------------------------------
# 4. Firewall UFW (firewall del sistema operativo)
# ---------------------------------------------------------------------------
# NOTA: Ademas de UFW, en AWS debes abrir estos mismos puertos en el
#       Grupo de Seguridad de la instancia. Son dos capas independientes.
log "Configurando el firewall UFW"

if ! command -v ufw >/dev/null 2>&1; then
    run apt-get install -y ufw
fi

# Permitir SSH SIEMPRE antes de habilitar UFW, para no perder el acceso remoto.
run ufw allow "${SSH_PORT}/tcp"    comment "SSH admin"          || true
run ufw allow "${TCP_PORT}/tcp"    comment "TSP TCP comandos"   || true
run ufw allow "${UDP_PORT}/udp"    comment "TSP UDP telemetria" || true
run ufw allow "${WEB_PORT}/tcp"    comment "Servicio_Web HTTP"  || true

# Habilitar UFW de forma no interactiva si no esta activo
if run ufw status | grep -q "Status: active"; then
    ok "UFW ya estaba activo; reglas aseguradas."
else
    run bash -c "yes | ufw enable" >/dev/null 2>&1 || run ufw --force enable
    ok "UFW habilitado."
fi

run ufw status verbose || true

# ---------------------------------------------------------------------------
# 5. Construir y levantar el sistema con Docker Compose
# ---------------------------------------------------------------------------
log "Construyendo y levantando el sistema (docker compose up --build -d)"
cd "${SCRIPT_DIR}"

# Usa sudo para compose porque el grupo docker recien anadido aun no aplica
# en esta misma sesion; en ejecuciones posteriores tras reconectar no hara falta.
run docker compose up --build -d

ok "Contenedores levantados."

# ---------------------------------------------------------------------------
# 6. Estado y verificacion
# ---------------------------------------------------------------------------
log "Estado de los servicios"
run docker compose ps

# IP publica de la instancia (best-effort via metadata de EC2 IMDSv2)
PUBLIC_IP=""
if command -v curl >/dev/null 2>&1; then
    TOKEN="$(curl -s -X PUT "http://169.254.169.254/latest/api/token" \
        -H "X-aws-ec2-metadata-token-ttl-seconds: 60" 2>/dev/null || true)"
    if [ -n "${TOKEN}" ]; then
        PUBLIC_IP="$(curl -s -H "X-aws-ec2-metadata-token: ${TOKEN}" \
            http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || true)"
    fi
fi
[ -z "${PUBLIC_IP}" ] && PUBLIC_IP="<IP_PUBLICA_DE_EC2>"

cat <<EOF

============================================================
  Despliegue completado.
============================================================
  Puertos publicados por el sistema:
    - TCP  ${TCP_PORT}  -> Servidor_Central (registro, comandos, alertas)
    - UDP  ${UDP_PORT}  -> Servidor_Central (telemetria)
    - TCP  ${WEB_PORT}  -> Servicio_Web (HTTP)

  Verificacion desde un EQUIPO EXTERNO (no localhost):
    nc  ${PUBLIC_IP} ${TCP_PORT}      # escribe: LIST_NODES  y luego  BYE
    curl http://${PUBLIC_IP}:${WEB_PORT}/
    python3 clients/telemetry_node.py --id NODO01 --host ${PUBLIC_IP}

  Recuerda:
    * Abrir 22/tcp, ${TCP_PORT}/tcp, ${UDP_PORT}/udp y ${WEB_PORT}/tcp
      en el GRUPO DE SEGURIDAD de AWS (ademas de UFW).
    * Configurar el DNS (registro A -> Elastic IP) segun docs/DEPLOY.md
      para que los clientes localicen el servidor por NOMBRE, no por IP.
============================================================
EOF
