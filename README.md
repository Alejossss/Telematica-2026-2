# Plataforma Distribuida de Telemetría y Gestión de Infraestructura Inteligente

Proyecto de Telemática 2026-2.

Sistema distribuido para monitorear infraestructura inteligente repartida
geográficamente. Nodos IoT simulados reportan variables (temperatura, humedad,
consumo, vibración, estado operativo) a un **servidor central en C** desplegado
en la nube, que identifica los dispositivos, detecta valores anómalos, genera
alertas y atiende de forma concurrente las consultas de varios operadores. Un
**servicio web** ofrece una vista de solo lectura del estado del sistema.

Toda la comunicación se hace con **TSP/1.0** (*Telemetry Simple Protocol*), un
protocolo de aplicación propio, basado en texto, especificado en
[`docs/PROTOCOLO.md`](docs/PROTOCOLO.md). No se apoya en HTTP, MQTT ni ningún
otro protocolo de aplicación existente: viaja directamente sobre sockets TCP y
UDP.

## Integrantes

- Alejandro Jaramillo Rodriguez
- Samuel Herrera Galvis
- Simon Castro Valencia
- Juan Esteban Orrego

---

## Visión general

La cadena que el proyecto integra y demuestra es:

> aplicación → sockets → TCP/UDP → direccionamiento → DNS → Internet → nube → Docker → análisis de tráfico

| Componente | Rol | Lenguaje | Ubicación |
|---|---|---|---|
| **Servidor central** | Recibe telemetría, detecta anomalías, genera alertas, responde a operadores | C | [`server/`](server/) |
| **Nodos de telemetría** | Dispositivos IoT simulados que reportan mediciones periódicas | Python | [`clients/telemetry_node.py`](clients/telemetry_node.py) |
| **Cliente operador** | Consulta nodos, mediciones, alertas y estado; CLI y GUI | Python | [`clients/operator_cli.py`](clients/operator_cli.py), [`clients/operator_gui.py`](clients/operator_gui.py) |
| **Servicio web** | Interfaz HTTP de solo lectura del estado del sistema | Python | [`web/servicio_web.py`](web/servicio_web.py) |

Se usan **dos lenguajes** (C para el servidor, Python para clientes y web), como
exige el enunciado.

---

## Arquitectura

```
   NODOS DE TELEMETRÍA (Python)          SERVIDOR CENTRAL (C)              OPERADORES (Python)
   ============================          ========================         ===================

   NODO01 NODO02 NODO03 ...              +----------------------+
      |      |      |                    |  hilo UDP  (telemetría)
      |  REGISTER (TCP 6000) ----------> |  hilo/cliente TCP     |
      |      |      |                    |  hilo monitor (caídas)|
      +------+------+                    |                       |
             |                           |  registro de nodos    |
      TELEMETRY (UDP 5000) ------------> |  detección de anomalías
             |                           |  historial de alertas |
             |                           +----------------------+
                                              ^   |        ^
                     consultas y comandos     |   |        |
                             (TCP 6000) ------+   |        |  alertas empujadas (TCP)
                                                  |        +----> operator_cli.py / operator_gui.py
                                                  |
                                    LIST_NODES/GET_* (TCP 6000)
                                                  |
                                          SERVICIO WEB (HTTP 8080, Python)
                                          lee el estado como un operador más
```

El servidor central atiende **concurrentemente** a los nodos y a varios
operadores mediante hilos POSIX:

- un hilo dedicado al socket **UDP** que recibe la telemetría;
- **un hilo por cada conexión TCP** (`pthread` en modo *detached*), que atiende
  tanto el registro de nodos como las sesiones de operador;
- un **hilo monitor** que marca `OFFLINE` los nodos que dejan de reportar y
  emite la alerta de disponibilidad.

El servicio web no reimplementa el protocolo: reutiliza la biblioteca cliente
[`clients/tsp.py`](clients/tsp.py) y se comporta como un operador TSP más.

### Elección de transporte

| Servicio | Transporte | Justificación |
|---|---|---|
| Envío periódico de mediciones (`TELEMETRY`) | **UDP** | Alta frecuencia y pérdida tolerable: la siguiente medición llega en segundos. Sin conexión ni retransmisiones. |
| Alta de un dispositivo (`REGISTER`) | **TCP** | Ocurre una vez y es información crítica: debe llegar completa y confirmada. |
| Consultas y comandos del operador | **TCP** | Exigen entrega fiable, ordenada y una respuesta asociada a cada petición. |
| Alertas hacia el operador (`ALERT`) | **TCP** | Una alerta no se puede perder: se empuja por la conexión del operador suscrito. |

### Estructura del repositorio

```
.
├── server/                 Servidor central en C
│   ├── server_concurrent.c   sockets, bind/listen/accept, hilos TCP+UDP
│   ├── protocol.c/.h         sintaxis TSP/1.0: parseo, errores, framing TCP
│   ├── handlers.c/.h         semántica: qué hace el servidor con cada mensaje
│   ├── registry.c/.h         estado: nodos, mediciones, umbrales, alertas, stats
│   ├── client_tcp_test.c     cliente TCP crudo para probar el protocolo a mano
│   ├── client_udp_test.c     cliente UDP crudo de prueba
│   └── Dockerfile            build multietapa del servidor
├── clients/                Nodos y operador en Python
│   ├── tsp.py                biblioteca TSP/1.0 (lado cliente)
│   ├── telemetry_node.py     nodo de telemetría simulado
│   ├── run_nodes.py          lanzador de 5+ nodos simultáneos
│   ├── operator_cli.py       cliente operador de línea de comandos
│   └── operator_gui.py       cliente operador con interfaz gráfica (tkinter)
├── web/                    Servicio web HTTP (Python, solo stdlib)
│   ├── servicio_web.py
│   └── Dockerfile
├── docs/
│   ├── PROTOCOLO.md          especificación completa de TSP/1.0 (fuente de verdad)
│   └── DEPLOY.md             guía detallada de despliegue en AWS y DNS
├── docker-compose.yml      orquesta servidor-central + servicio-web
├── setup_ec2.sh            aprovisionamiento automático de una instancia EC2
└── Makefile                compilación del servidor y clientes en C
```

`server/server_tcp.c` y `server/server_udp.c` son versiones iniciales de cada
socket por separado; se conservan como material de estudio. El binario que se
despliega es `server_concurrent`.

---

## El protocolo TSP/1.0 en breve

Cada mensaje es una línea de texto con campos separados por `|` y terminada en
`\n`. La especificación completa (formato, tipos, parámetros, respuestas,
códigos de error y ejemplos de intercambio) está en
[`docs/PROTOCOLO.md`](docs/PROTOCOLO.md).

| Mensaje | Transporte | Propósito |
|---|---|---|
| `REGISTER` | TCP | Alta del nodo y declaración de variables |
| `TELEMETRY` / `ACK` | UDP | Reporte de mediciones y su confirmación informativa |
| `HELLO` | TCP | Apertura de sesión de operador |
| `LIST_NODES`, `GET_STATUS`, `GET_LAST`, `GET_ALERTS`, `GET_SYSTEM` | TCP | Consultas del operador |
| `SET_THRESHOLD` | TCP | Cambio de umbrales de anomalía en caliente |
| `SUBSCRIBE` / `UNSUBSCRIBE` | TCP | Alertas empujadas en tiempo real |
| `PING` / `BYE` | TCP | Prueba de vida y cierre ordenado |
| `ALERT` | TCP | Notificación asíncrona de anomalía |

Ejemplos de mensajes reales:

```
REGISTER|NODO01|SENSOR_AMBIENTAL|PLANTA_A|TEMP|C|HUM|%|PWR|W|VIB|mm/s|STATUS|-
TELEMETRY|NODO01|7|TEMP|24.8|HUM|58.2|PWR|1180.5|VIB|1.4|STATUS|1.0
ALERT|NODO01|TEMP_HIGH|42.1|1774900812|CRITICAL
```

---

## Requisitos

- **Servidor**: `gcc`, `make`, `pthread` (Linux; en Windows usar WSL o Docker).
- **Clientes y web**: Python 3.8+ (solo biblioteca estándar). La GUI del
  operador requiere `tkinter`.
- **Despliegue**: Docker Engine y el complemento Docker Compose.

No hace falta instalar dependencias de Python para ejecutar el sistema.

---

## Compilación del servidor

```bash
make            # compila server/server_concurrent
make clients    # compila los clientes de prueba en C
make all        # todo
make clean      # borra los binarios
```

Equivalente a mano:

```bash
gcc -Wall -Wextra -O2 -o server/server_concurrent \
    server/server_concurrent.c server/protocol.c \
    server/registry.c server/handlers.c -pthread
```

---

## Ejecución local

Los puertos por defecto son **TCP 6000** (registro, comandos, alertas) y
**UDP 5000** (telemetría). Se pueden cambiar sin recompilar con las variables de
entorno `TSP_TCP_PORT` y `TSP_UDP_PORT`.

### 1. Servidor central

```bash
./server/server_concurrent
```

### 2. Nodos de telemetría (5 o más simultáneos)

```bash
cd clients
python3 run_nodes.py --count 5 --host localhost
```

O un nodo suelto:

```bash
python3 telemetry_node.py --id NODO01 --host localhost
```

Cada nodo simula 5 variables (`TEMP`, `HUM`, `PWR`, `VIB`, `STATUS`), localiza
el servidor **por DNS** y reintenta con espera incremental si la comunicación
falla. Para inyectar anomalías periódicas: `--anomaly-every 10`.

### 3. Cliente operador

```bash
cd clients
python3 operator_cli.py --host localhost
```

Comandos interactivos: `nodes`, `node <ID>`, `last [n]`, `alerts [n]`,
`system`, `threshold <nodo|*> <VAR> <min> <max>`, `subscribe`, `unsubscribe`,
`ping`, `raw`, `help`, `quit`.

Interfaz gráfica (requiere `tkinter`):

```bash
python3 operator_gui.py --host localhost
```

Consulta puntual sin entrar al modo interactivo:

```bash
python3 operator_cli.py --once system
python3 operator_cli.py --once "node NODO01"
```

### 4. Servicio web

```bash
cd web
python3 servicio_web.py       # escucha en WEB_PORT (por defecto 8080)
```

Luego abre `http://localhost:8080/`. Muestra estado del servidor, nodos
registrados y activos, últimas mediciones y alertas recientes.

### Variables de entorno

Evitan repetir el host y los puertos en cada comando:

```bash
export TSP_SERVER_HOST=telemetria.midominio.com
export TSP_TCP_PORT=6000
export TSP_UDP_PORT=5000
export WEB_PORT=8080
```

---

## Despliegue con Docker

El servidor en C y el servicio web se contenerizan y se orquestan con
`docker compose`. El binario lee sus puertos del entorno y enlaza a todas las
interfaces, así que no se modifica ninguna fuente C para contenerizarlo.

- [`server/Dockerfile`](server/Dockerfile) — build **multietapa**: compila
  `server_concurrent` con `make server` en una etapa con la cadena de
  herramientas y lo ejecuta en una imagen mínima (`debian:bookworm-slim`,
  glibc + pthread) sin compilador.
- [`web/Dockerfile`](web/Dockerfile) — imagen `python:3-slim` que copia la
  biblioteca TSP y el servicio web (solo stdlib).
- [`docker-compose.yml`](docker-compose.yml) — levanta `servidor-central`
  (TCP 6000 + UDP 5000) y `servicio-web` (HTTP 8080) en la misma red. El web
  localiza al servidor por el **nombre DNS interno de compose**
  (`TSP_SERVER_HOST=servidor-central`), nunca por una IP fija.

### Sistema completo (recomendado)

Desde la raíz del repositorio:

```bash
docker compose up --build          # en primer plano
docker compose up --build -d       # en segundo plano
docker compose ps                  # estado de los servicios
docker compose logs -f             # logs en vivo
docker compose down                # detener
```

El navegador accede al servicio web en `http://<host>:8080/`.

### Solo el servidor

Construir la imagen (el contexto de build necesita `Makefile` y `server/`):

```bash
docker build -f server/Dockerfile -t servidor-central .
```

Ejecutar publicando los puertos TCP y UDP:

```bash
docker run --rm -p 6000:6000 -p 5000:5000/udp servidor-central
```

Si la compilación falla, Docker aborta el build y no genera imagen final.

---

## Despliegue en AWS EC2

El servidor se despliega en una instancia **EC2** (por ejemplo Ubuntu Server)
con Docker + Compose. Los clientes localizan el servidor por **nombre DNS**, no
por IP fija, como exige el enunciado. La guía completa (creación de la
instancia, grupo de seguridad, SSH, DNS y verificación externa) está en
[`docs/DEPLOY.md`](docs/DEPLOY.md); a continuación, el camino corto.

### 1. Puertos a abrir

En el **Grupo de Seguridad** de la instancia, añadir reglas de entrada:

| Puerto | Protocolo | Uso | Origen |
|---|---|---|---|
| `6000/tcp` | TCP | Registro de nodos, comandos, alertas | `0.0.0.0/0` |
| `5000/udp` | UDP | Telemetría | `0.0.0.0/0` |
| `8080/tcp` | TCP | Servicio web (HTTP) | `0.0.0.0/0` |
| `22/tcp` | TCP | SSH (administración) | tu IP `/32` |

El Grupo de Seguridad de AWS y el firewall del sistema (UFW) son capas
independientes; el tráfico debe pasar ambas. El script de aprovisionamiento
configura UFW automáticamente.

### 2. Aprovisionamiento automático

Conéctate por SSH, clona el repositorio y ejecuta el script incluido:

```bash
ssh -i telemetria-key.pem ubuntu@<IP_O_DNS_PUBLICO>

sudo apt-get update && sudo apt-get install -y git
git clone <URL_DEL_REPOSITORIO_PRIVADO> telemetria
cd telemetria
chmod +x setup_ec2.sh
./setup_ec2.sh
```

[`setup_ec2.sh`](setup_ec2.sh) instala Docker + Compose, habilita el servicio,
abre `22/tcp`, `6000/tcp`, `5000/udp` y `8080/tcp` en UFW, y levanta el sistema
con `docker compose up --build -d`. Es idempotente: se puede volver a ejecutar
sin duplicar reglas.

### 3. DNS

Para que los clientes usen un nombre y no una IP, asigna una **Elastic IP** a la
instancia (la IP pública por defecto cambia al reiniciar) y crea un registro
DNS que apunte a ella:

```
telemetria.midominio.com.   A   300   <ELASTIC_IP>
```

Sirve Route 53, el proveedor de tu dominio o un DNS dinámico gratuito
(DuckDNS, No-IP). Verifica con `dig +short telemetria.midominio.com`. El detalle
de tipos de registro (A / CNAME), TTL y proveedores está en
[`docs/DEPLOY.md`](docs/DEPLOY.md#5-configuración-del-dns).

### 4. Verificación desde un equipo externo

La prueba debe hacerse **desde fuera de la instancia** (no `localhost`), contra
el nombre DNS público:

```bash
# TCP 6000 — un comando TSP recibe respuesta (escribe LIST_NODES y luego BYE)
nc telemetria.midominio.com 6000

# UDP 5000 — un nodo real envía telemetría y recibe ACK
python3 clients/telemetry_node.py --id NODO01 --host telemetria.midominio.com

# HTTP 8080 — el servicio web responde
curl http://telemetria.midominio.com:8080/
```

Si los tres responden, el sistema contenerizado está accesible por Internet y
localizable por DNS.

---

## Provocar una alerta en la sustentación

Sin tocar el código de los nodos, desde el cliente operador:

```
tsp> subscribe
tsp> threshold * TEMP -10 20
```

El siguiente `TELEMETRY` de cualquier nodo con temperatura por encima de 20 °C
dispara la alerta, y el servidor la empuja al operador en el momento. Para
volver al umbral normal: `threshold * TEMP -10 40`.

---

## Probar el protocolo a mano

Como TSP es texto plano, se puede hablar con el servidor sin clientes:

```bash
nc <servidor> 6000
LIST_NODES
GET_STATUS|NODO01
GET_SYSTEM
BYE
```

Los programas [`server/client_tcp_test.c`](server/client_tcp_test.c) y
[`server/client_udp_test.c`](server/client_udp_test.c) son clientes de socket
crudos para estas pruebas. El de TCP envía lo que se escriba por teclado; el de
UDP manda un texto que no es TSP, por lo que el servidor responde
`ERR|401|UNKNOWN_COMMAND`, demostrando el manejo de errores.

---

## Documentación

- [`docs/PROTOCOLO.md`](docs/PROTOCOLO.md) — especificación completa de TSP/1.0:
  formato, reglas, tipos de mensaje, parámetros, respuestas, códigos de error,
  detección de anomalías, máquina de estados y ejemplos de intercambio. Es la
  **fuente de verdad** del protocolo.
- [`docs/DEPLOY.md`](docs/DEPLOY.md) — guía paso a paso de despliegue en AWS EC2,
  configuración del grupo de seguridad, DNS y verificación desde Internet.
