# Plataforma Distribuida de Telemetría

Proyecto de Telemática 2026-2.

Sistema distribuido de monitoreo de infraestructura inteligente: nodos IoT
simulados envían mediciones a un servidor central desplegado en la nube, que
detecta valores anómalos, genera alertas y responde las consultas de los
operadores.

## Integrantes

- Alejandro Jaramillo Rodriguez
- Samuel Herrera
- Simon Castro
- JE

## Arquitectura

```
   NODOS DE TELEMETRIA (Python)              SERVIDOR CENTRAL (C)           OPERADORES (Python)
   ============================              ====================           ===================

   NODO01  NODO02  NODO03 ...                 +----------------+
      |       |       |                       | hilo UDP       |
      |  REGISTER (TCP 6000)  --------------> | hilo por cliente TCP
      |       |       |                       | hilo monitor   |
      +-------+-------+                       |                |
              |                               | registro de nodos
        TELEMETRY (UDP 5000) ---------------> | deteccion de anomalias
              |                               | historial de alertas
              |                               +----------------+
                                                   ^        |
                            consultas y comandos   |        |  alertas empujadas
                                    (TCP 6000) ----+        +----> operator_cli.py
                                                                   operator_gui.py
```

Los tres elementos hablan **TSP/1.0**, un protocolo de aplicación propio,
basado en texto, especificado en [`docs/PROTOCOLO.md`](docs/PROTOCOLO.md).

### Elección de transporte

| Servicio | Transporte | Por qué |
|---|---|---|
| Envío periódico de mediciones | **UDP** | Alta frecuencia y pérdida tolerable: la siguiente medición llega en segundos. Sin conexión ni retransmisiones. |
| Alta de un dispositivo (`REGISTER`) | **TCP** | Ocurre una vez y es crítica: debe llegar completa y confirmada. |
| Consultas y comandos del operador | **TCP** | Exigen entrega fiable, ordenada y una respuesta por petición. |
| Alertas hacia el operador | **TCP** | Una alerta no se puede perder. |

## Puertos

- TCP: 6000 — registro de nodos, consultas y comandos de operador
- UDP: 5000 — telemetría

Ambos se pueden cambiar sin recompilar con las variables de entorno
`TSP_TCP_PORT` y `TSP_UDP_PORT`, lo que facilita publicarlos desde Docker.

## Servidor

Desarrollado en **C**. Atiende concurrentemente a los nodos de telemetría y a
varios operadores mediante hilos POSIX:

- un hilo dedicado al socket UDP;
- un hilo por cada cliente TCP (`pthread`, modo *detached*);
- un hilo monitor que marca como `OFFLINE` los nodos que dejan de reportar.

| Archivo | Responsabilidad |
|---|---|
| [`server/server_concurrent.c`](server/server_concurrent.c) | Sockets, `bind`, `listen`, `accept`, hilos y ciclo de vida de las conexiones |
| [`server/protocol.c`](server/protocol.c) | Sintaxis TSP: análisis de mensajes, errores y separación del flujo TCP en líneas |
| [`server/handlers.c`](server/handlers.c) | Semántica: qué hace el servidor con cada mensaje |
| [`server/registry.c`](server/registry.c) | Estado: nodos, mediciones, umbrales, alertas y estadísticas |

Funciona con:

- comunicación TCP y UDP simultánea;
- identificación de los dispositivos conectados;
- detección de valores anómalos y generación de alertas;
- alertas empujadas en tiempo real a los operadores suscritos;
- estimación de datagramas perdidos a partir del número de secuencia;
- manejo de desconexiones y mensajes inválidos sin finalizar el proceso.

`server/server_tcp.c` y `server/server_udp.c` son las versiones iniciales de
cada socket por separado; se conservan como material de estudio, el servidor
que se despliega es `server_concurrent`.

## Compilación

```bash
make            # servidor
make clients    # clientes de prueba en C
make all        # todo
make clean
```

O a mano:

```bash
gcc -Wall -Wextra -O2 -o server/server_concurrent \
    server/server_concurrent.c server/protocol.c \
    server/registry.c server/handlers.c -pthread
```

## Ejecución

### 1. Servidor

```bash
./server/server_concurrent
```

### 2. Nodos de telemetría (5 o más simultáneos)

```bash
cd clients
python3 run_nodes.py --count 5 --host <nombre-dns-del-servidor>
```

O un nodo suelto:

```bash
python3 telemetry_node.py --id NODO01 --host <nombre-dns-del-servidor>
```

Cada nodo simula 5 variables (`TEMP`, `HUM`, `PWR`, `VIB`, `STATUS`), localiza
el servidor **por DNS** y reintenta con espera incremental si la comunicación
falla. Para provocar alertas automáticamente: `--anomaly-every 10`.

### 3. Cliente operador

```bash
cd clients
python3 operator_cli.py --host <nombre-dns-del-servidor>
```

Comandos: `nodes`, `node <ID>`, `last [n]`, `alerts [n]`, `system`,
`threshold <nodo|*> <VAR> <min> <max>`, `subscribe`, `ping`, `raw`, `help`,
`quit`.

Interfaz gráfica (requiere tkinter):

```bash
python3 operator_gui.py --host <nombre-dns-del-servidor>
```

Consulta puntual sin entrar al modo interactivo:

```bash
python3 operator_cli.py --once system
python3 operator_cli.py --once "node NODO01"
```

### Variables de entorno

Evitan repetir el nombre del servidor en cada comando:

```bash
export TSP_SERVER_HOST=telemetria.ejemplo.com
export TSP_TCP_PORT=6000
export TSP_UDP_PORT=5000
```

## Cómo provocar una alerta en la sustentación

Sin tocar el código de los nodos, desde el cliente operador:

```
tsp> subscribe
tsp> threshold * TEMP -10 20
```

El siguiente `TELEMETRY` de cualquier nodo con temperatura por encima de 20 °C
dispara la alerta, y el servidor la empuja al operador en el momento.

Para volver al umbral normal: `threshold * TEMP -10 40`.

## Probar el protocolo a mano

Como TSP es texto plano, se puede hablar con el servidor sin clientes:

```bash
nc <servidor> 6000
LIST_NODES
GET_STATUS|NODO01
GET_SYSTEM
BYE
```

Los programas `server/client_tcp_test.c` y `server/client_udp_test.c` son
clientes de socket crudos para estas pruebas. El de TCP lee lo que se escriba
por teclado, así que sirve para enviar mensajes TSP; el de UDP envía un texto
fijo que no es TSP y por eso el servidor le responde
`ERR|401|UNKNOWN_COMMAND`, lo que demuestra el manejo de errores.

## Documentación

- [`docs/PROTOCOLO.md`](docs/PROTOCOLO.md) — especificación completa de TSP/1.0:
  formato, tipos de mensaje, parámetros, respuestas, códigos de error y
  ejemplos de intercambio.
