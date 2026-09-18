# TSP/1.0 — Telemetry Simple Protocol

Protocolo propio de capa de aplicación, basado en texto, diseñado para la
Plataforma Distribuida de Telemetría y Gestión de Infraestructura Inteligente.

> **Punto 5 del enunciado.** TSP no se apoya en HTTP, MQTT ni en ningún otro
> protocolo de aplicación existente: se transporta directamente sobre sockets
> TCP y UDP (capa de transporte), y toda su sintaxis y semántica se define en
> este documento.

| | |
|---|---|
| Nombre | TSP (Telemetry Simple Protocol) |
| Versión | 1.0 |
| Codificación | UTF-8 (el subconjunto usado en la práctica es ASCII imprimible) |
| Estilo | Texto plano, orientado a línea, delimitado por campos |
| Transportes | UDP (telemetría) y TCP (registro, consultas, comandos, alertas) |
| Puertos por defecto | UDP 5000, TCP 6000 |

---

## 1. Formato de los mensajes

Todo mensaje TSP es **una sola línea de texto** con la siguiente estructura:

```
<TIPO>|<campo_1>|<campo_2>|...|<campo_n>\n
```

Reglas del formato:

| Regla | Descripción |
|---|---|
| R1 | El **separador de campos** es la barra vertical `\|` (0x7C). |
| R2 | El **terminador de mensaje** es el salto de línea `\n` (0x0A). Se acepta `\r\n` y el `\r` se descarta. |
| R3 | El primer campo es siempre el **tipo de mensaje**, en MAYÚSCULAS. |
| R4 | Un campo **no puede contener** `\|` ni `\n`. |
| R5 | La longitud máxima de un mensaje, incluido el terminador, es de **1024 bytes**. |
| R6 | El número de campos es fijo por tipo de mensaje, salvo en `TELEMETRY` y `REGISTER`, que aceptan pares repetidos. |
| R7 | Los identificadores de nodo y los nombres de variable se comparan **sin distinguir mayúsculas** y se normalizan a mayúsculas. |
| R8 | Los valores numéricos usan **punto decimal** (`24.8`), nunca coma. |
| R9 | Las marcas de tiempo son **epoch UNIX en segundos** (entero, UTC). |

### 1.1. Delimitación según el transporte

Como TCP es un flujo de bytes sin fronteras de mensaje y UDP es orientado a
datagrama, la delimitación se resuelve de forma distinta en cada caso:

| Transporte | Delimitación |
|---|---|
| **TCP** | El receptor acumula bytes en un buffer y procesa una unidad cada vez que encuentra `\n`. Una lectura de `recv()` puede contener mensajes parciales o varios mensajes. |
| **UDP** | **Un datagrama = un mensaje**. El `\n` final es opcional. No se permite fragmentar un mensaje TSP en varios datagramas. |

---

## 2. Roles y uso de cada transporte

TSP define tres roles. La elección de transporte por servicio es la que se
justifica en el punto 4 del informe:

| Rol | Transporte | Mensajes | Justificación |
|---|---|---|---|
| **Nodo de telemetría** | UDP | `TELEMETRY` | Envío periódico de alta frecuencia. La pérdida de una medición aislada es tolerable porque la siguiente llega en pocos segundos; no se paga el costo del establecimiento de conexión ni de la retransmisión. |
| **Nodo de telemetría** | TCP | `REGISTER` | El alta del dispositivo es información crítica y ocurre una sola vez: debe llegar completa y confirmada. |
| **Operador** | TCP | `HELLO`, `GET_*`, `LIST_NODES`, `SET_THRESHOLD`, `SUBSCRIBE`, `PING`, `BYE` | Consultas y comandos que exigen entrega fiable, ordenada y una respuesta asociada a cada petición. |
| **Servidor** | TCP | `ALERT` (asíncrono) | Una alerta no puede perderse: se empuja por la conexión TCP del operador suscrito. |

---

## 3. Tipos de mensajes

### 3.1. Resumen

| Tipo | Dirección | Transporte | Propósito |
|---|---|---|---|
| `REGISTER` | Nodo → Servidor | TCP | Da de alta el dispositivo y declara sus variables |
| `TELEMETRY` | Nodo → Servidor | UDP | Reporta una o más mediciones |
| `ACK` | Servidor → Nodo | UDP | Confirma la recepción de un `TELEMETRY` |
| `HELLO` | Operador → Servidor | TCP | Abre la sesión de operador |
| `LIST_NODES` | Operador → Servidor | TCP | Lista los nodos registrados |
| `GET_STATUS` | Operador → Servidor | TCP | Consulta un dispositivo específico |
| `GET_LAST` | Operador → Servidor | TCP | Últimas mediciones del sistema |
| `GET_ALERTS` | Operador → Servidor | TCP | Alertas recientes |
| `GET_SYSTEM` | Operador → Servidor | TCP | Estado general del sistema |
| `SET_THRESHOLD` | Operador → Servidor | TCP | Modifica los umbrales de anomalía |
| `SUBSCRIBE` / `UNSUBSCRIBE` | Operador → Servidor | TCP | Activa o desactiva el envío de alertas en tiempo real |
| `PING` | Operador → Servidor | TCP | Prueba de vida de la conexión |
| `BYE` | Cliente → Servidor | TCP | Cierre ordenado |
| `OK` | Servidor → Cliente | TCP | Respuesta afirmativa (cabecera) |
| `NODE`, `VAR`, `MEAS`, `STAT`, `EVENT` | Servidor → Operador | TCP | Registros de una respuesta múltiple |
| `END` | Servidor → Operador | TCP | Fin de una respuesta múltiple |
| `ALERT` | Servidor → Operador | TCP | Notificación asíncrona de anomalía |
| `PONG` | Servidor → Operador | TCP | Respuesta a `PING` |
| `ERR` | Servidor → Cliente | TCP/UDP | Respuesta de error |

### 3.2. Respuestas simples y múltiples

* **Respuesta simple**: una única línea `OK|...`, `PONG|...`, `ACK|...` o `ERR|...`.
* **Respuesta múltiple**: una línea de cabecera `OK|<COMANDO>|<n>|...`, seguida
  de exactamente `n` líneas de registro, y cerrada por `END|<COMANDO>`.

El cliente **debe** usar el contador `n` de la cabecera y el centinela `END`
para saber dónde termina la respuesta. Esto evita depender de temporizadores y
permite que el operador envíe comandos consecutivos sobre la misma conexión.

### 3.3. Por qué los registros nunca reutilizan el tipo `ALERT`

Cada tipo de registro (`NODE`, `VAR`, `MEAS`, `STAT`, `EVENT`) es **distinto
del tipo de cualquier mensaje asíncrono**. Esto no es cosmético: el servidor
puede empujar un `ALERT` en mitad de una respuesta múltiple, así que el cliente
tiene que decidir qué es cada línea **mirando esa línea sola**, sin contexto.

Si el historial de `GET_ALERTS` devolviera registros con el tipo `ALERT`, un
cliente que lee en un hilo aparte —como el operador de referencia— no podría
saber si una línea `ALERT|...` es una notificación que debe mostrar ya o una
fila de la respuesta que está esperando. Por eso el historial usa `EVENT` y el
empuje asíncrono usa `ALERT`: mismos campos, tipos distintos, cero ambigüedad.

---

## 4. Especificación por mensaje

### 4.1. `REGISTER` — alta de un nodo (TCP)

```
REGISTER|<NODE_ID>|<TIPO>|<UBICACION>|<VAR>|<UNIDAD>[|<VAR>|<UNIDAD>]...
```

| Parámetro | Tipo | Obligatorio | Descripción |
|---|---|---|---|
| `NODE_ID` | cadena, 1–31 car. | sí | Identificador único del dispositivo |
| `TIPO` | cadena, 1–31 car. | sí | Clase de dispositivo (p. ej. `SENSOR_AMBIENTAL`) |
| `UBICACION` | cadena, 1–63 car. | sí | Instalación donde está desplegado |
| `VAR` / `UNIDAD` | pares repetidos, 1–8 pares | sí | Variables que el nodo reportará y su unidad |

**Respuesta:**

```
OK|REGISTER|<NODE_ID>|<UDP_PORT>|<INTERVALO_SUGERIDO>
```

`UDP_PORT` es el puerto al que el nodo debe enviar la telemetría e
`INTERVALO_SUGERIDO` el período de muestreo en segundos recomendado por el
servidor.

Un `REGISTER` sobre un `NODE_ID` ya existente **no es un error**: actualiza la
declaración del nodo y reinicia sus contadores. Esto permite que un nodo se
recupere solo tras un reinicio del servidor.

### 4.2. `TELEMETRY` — envío de mediciones (UDP)

```
TELEMETRY|<NODE_ID>|<SEQ>|<VAR>|<VALOR>[|<VAR>|<VALOR>]...
```

| Parámetro | Tipo | Obligatorio | Descripción |
|---|---|---|---|
| `NODE_ID` | cadena | sí | Nodo emisor, previamente registrado |
| `SEQ` | entero ≥ 0 | sí | Número de secuencia, incremental por nodo |
| `VAR` / `VALOR` | pares repetidos, 1–8 pares | sí | Nombre de la variable y su valor numérico |

`SEQ` es lo que permite al servidor **estimar los datagramas perdidos**: si
llega `SEQ = k` y el último recibido fue `k - 1 - p`, entonces se contabilizan
`p` mensajes perdidos para ese nodo (métrica exigida por el punto 11 del
enunciado).

**Respuesta:**

```
ACK|<NODE_ID>|<SEQ>|<ALERTAS_GENERADAS>
```

`ALERTAS_GENERADAS` es el número de alertas que produjo ese datagrama concreto
(`0` en condiciones normales), de modo que el propio nodo sabe si su medición
fue considerada anómala.

> El `ACK` es **informativo, no fiable**: el nodo no retransmite si no lo
> recibe. Se usa para diagnóstico y para medir la pérdida en el sentido
> servidor → nodo.

### 4.3. `HELLO` — apertura de sesión de operador (TCP)

```
HELLO|<NOMBRE_OPERADOR>
```

**Respuesta:**

```
OK|HELLO|<SERVER_ID>|TSP/1.0|<UPTIME_SEG>
```

`HELLO` es el primer mensaje de una conexión de operador e identifica su rol
frente al de un nodo, que se identifica con `REGISTER`.

El servidor es **tolerante** en este punto: si una conexión lanza directamente
un `GET_*`, la atiende y la da por operador sin nombre. Esto permite demostrar
el protocolo a mano con `nc servidor 6000`, y no debilita nada porque TSP no
define autenticación.

### 4.4. `LIST_NODES` — nodos registrados y activos (TCP)

```
LIST_NODES
```

**Respuesta múltiple:**

```
OK|LIST_NODES|<n>
NODE|<NODE_ID>|<ESTADO>|<TIPO>|<UBICACION>|<HACE_SEG>|<MSGS>|<PERDIDOS>
...
END|LIST_NODES
```

| Campo | Descripción |
|---|---|
| `ESTADO` | `ONLINE` u `OFFLINE` |
| `HACE_SEG` | Segundos transcurridos desde la última medición recibida |
| `MSGS` | Datagramas de telemetría aceptados del nodo |
| `PERDIDOS` | Datagramas perdidos estimados a partir de `SEQ` |

### 4.5. `GET_STATUS` — consulta de un dispositivo específico (TCP)

```
GET_STATUS|<NODE_ID>
```

**Respuesta múltiple:**

```
OK|GET_STATUS|<NODE_ID>|<ESTADO>|<HACE_SEG>|<n>
VAR|<NOMBRE>|<VALOR>|<UNIDAD>|<TIMESTAMP>
...
END|GET_STATUS
```

Errores posibles: `404 NODE_NOT_FOUND`.

### 4.6. `GET_LAST` — últimas mediciones del sistema (TCP)

```
GET_LAST|<N>
```

`N` es opcional (por defecto `10`) y se satura al tamaño del buffer circular
del servidor.

**Respuesta múltiple:**

```
OK|GET_LAST|<n>
MEAS|<NODE_ID>|<VAR>|<VALOR>|<UNIDAD>|<TIMESTAMP>
...
END|GET_LAST
```

Los registros se devuelven **del más reciente al más antiguo**.

### 4.7. `GET_ALERTS` — alertas recientes (TCP)

```
GET_ALERTS|<N>
```

**Respuesta múltiple:**

```
OK|GET_ALERTS|<n>
EVENT|<NODE_ID>|<TIPO_ALERTA>|<VALOR>|<TIMESTAMP>|<SEVERIDAD>
...
END|GET_ALERTS
```

Los registros van **de la más reciente a la más antigua** y usan el tipo
`EVENT`, no `ALERT`, por la razón explicada en la sección 3.3.

En una alerta `NODE_OFFLINE` el campo `VALOR` no es una medición: lleva los
**segundos de silencio** del nodo cuando el monitor lo dio por caído.

### 4.8. `GET_SYSTEM` — estado general del sistema (TCP)

```
GET_SYSTEM
```

**Respuesta múltiple:**

```
OK|GET_SYSTEM|<n>
STAT|<CLAVE>|<VALOR>
...
END|GET_SYSTEM
```

Claves publicadas por la implementación actual:

| Clave | Significado |
|---|---|
| `UPTIME_SEG` | Segundos desde el arranque del servidor |
| `NODOS_REGISTRADOS` | Nodos dados de alta |
| `NODOS_ACTIVOS` | Nodos en estado `ONLINE` |
| `OPERADORES_CONECTADOS` | Sesiones de operador abiertas |
| `TELEMETRIA_RECIBIDA` | Datagramas `TELEMETRY` válidos procesados |
| `TELEMETRIA_RECHAZADA` | Datagramas descartados por error de protocolo |
| `TELEMETRIA_PERDIDA_EST` | Datagramas perdidos estimados (suma de todos los nodos) |
| `COMANDOS_TCP` | Comandos de operador atendidos |
| `ALERTAS_GENERADAS` | Alertas producidas desde el arranque |

### 4.9. `SET_THRESHOLD` — modificación de umbrales (TCP)

```
SET_THRESHOLD|<NODE_ID|*>|<VAR>|<MIN>|<MAX>
```

`*` aplica el umbral a **todos** los nodos; un `NODE_ID` concreto crea una
excepción que tiene prioridad sobre el umbral global.

**Respuesta:**

```
OK|SET_THRESHOLD|<DESTINO>|<VAR>|<MIN>|<MAX>
```

Este comando es el que permite provocar una alerta en vivo durante la
sustentación sin modificar el código de los nodos.

### 4.10. `SUBSCRIBE` / `UNSUBSCRIBE` — alertas en tiempo real (TCP)

```
SUBSCRIBE|ALERTS
UNSUBSCRIBE|ALERTS
```

**Respuesta:** `OK|SUBSCRIBE|ALERTS` / `OK|UNSUBSCRIBE|ALERTS`.

Mientras la suscripción esté activa, el servidor **empuja** mensajes `ALERT`
por esa conexión sin que medie petición:

```
ALERT|<NODE_ID>|<TIPO_ALERTA>|<VALOR>|<TIMESTAMP>|<SEVERIDAD>
```

> El cliente debe estar preparado para recibir un `ALERT` **en cualquier
> momento**, incluso intercalado entre el comando que acaba de enviar y su
> respuesta. Por eso el operador de referencia lee la conexión en un hilo
> aparte y encamina cada línea según su tipo.

### 4.11. `PING` y `BYE` (TCP)

```
PING            →  PONG|<TIMESTAMP>
BYE             →  OK|BYE       (y el servidor cierra el socket)
```

---

## 5. Códigos de error

Todo error se responde con una línea:

```
ERR|<CODIGO>|<SIMBOLO>|<DESCRIPCION>
```

| Código | Símbolo | Cuándo se produce |
|---|---|---|
| `400` | `BAD_REQUEST` | Mensaje mal formado: vacío, sin tipo o con campos inválidos |
| `401` | `UNKNOWN_COMMAND` | El tipo de mensaje no pertenece a TSP/1.0 o no es válido en ese transporte |
| `402` | `MISSING_PARAM` | Faltan parámetros obligatorios para el comando |
| `403` | `INVALID_PARAM` | Un parámetro tiene formato o rango inválido (valor no numérico, `MIN > MAX`) |
| `404` | `NODE_NOT_FOUND` | Se consultó un `NODE_ID` que no está registrado |
| `405` | `NO_DATA` | El nodo existe pero aún no ha reportado ninguna medición |
| `406` | `NOT_REGISTERED` | Llegó `TELEMETRY` de un nodo que no hizo `REGISTER` |
| `409` | `LIMIT_REACHED` | Se alcanzó el máximo de nodos o de variables por nodo |
| `413` | `MESSAGE_TOO_LONG` | El mensaje supera los 1024 bytes |
| `500` | `INTERNAL_ERROR` | Fallo interno del servidor |
| `503` | `SERVER_FULL` | Se alcanzó el máximo de conexiones TCP simultáneas |

### 5.1. Recuperación ante errores

| Situación | Comportamiento esperado |
|---|---|
| El nodo recibe `ERR\|406\|NOT_REGISTERED` | Vuelve a ejecutar `REGISTER` por TCP y continúa enviando telemetría. Es el mecanismo que permite que los nodos se recuperen solos si el servidor se reinicia. |
| El nodo no recibe `ACK` | **No retransmite.** Contabiliza el envío como no confirmado y sigue con la siguiente medición. |
| El nodo no puede resolver el DNS o conectar por TCP | Reintenta con espera incremental, sin abortar el proceso. |
| El operador recibe un `ERR` | Lo muestra y mantiene la sesión abierta; solo `BYE` o un fallo de socket cierran la conexión. |
| El servidor recibe un mensaje inválido | Responde `ERR`, incrementa el contador de rechazos y **mantiene viva la conexión** y el resto del sistema. |

---

## 6. Detección de anomalías y alertas

El servidor compara cada valor recibido contra un umbral `[MIN, MAX]`. La
búsqueda del umbral es: primero una excepción para ese `NODE_ID` y variable, y
si no existe, el umbral global de la variable.

Umbrales por defecto:

| Variable | Unidad | MIN | MAX | Alerta por exceso | Alerta por defecto |
|---|---|---|---|---|---|
| `TEMP` | `C` | -10.0 | 40.0 | `TEMP_HIGH` | `TEMP_LOW` |
| `HUM` | `%` | 10.0 | 85.0 | `HUM_HIGH` | `HUM_LOW` |
| `PWR` | `W` | 0.0 | 2000.0 | `PWR_HIGH` | `PWR_LOW` |
| `VIB` | `mm/s` | 0.0 | 5.0 | `VIB_HIGH` | `VIB_LOW` |
| `STATUS` | `-` | 1.0 | 1.0 | `STATUS_FAIL` | `STATUS_FAIL` |

`STATUS` es un estado operativo, no una magnitud: `1` = operativo y `0` =
fallo. Su rango `[1.0, 1.0]` hace que **cualquier valor distinto de 1** se
considere anómalo y produzca `STATUS_FAIL`.

El nombre de la alerta se deriva de la variable, así que una variable nueva
declarada por un nodo genera `<VARIABLE>_HIGH` o `<VARIABLE>_LOW` sin tocar el
servidor. Para una variable sin umbral definido no se genera alerta.

**Severidad:**

| Severidad | Criterio |
|---|---|
| `WARN` | El valor se sale del rango en menos del 20 % de la amplitud `MAX - MIN` |
| `CRITICAL` | El valor se sale en el 20 % o más de la amplitud, o el nodo pasa a `OFFLINE` |
| `INFO` | El nodo vuelve a estar disponible (`NODE_ONLINE`) |

**Alerta de disponibilidad:** un hilo monitor del servidor marca como `OFFLINE`
todo nodo del que no se reciba telemetría durante más de 15 segundos y emite
una única alerta `NODE_OFFLINE` con severidad `CRITICAL` en la transición. Si el
nodo vuelve, se emite `NODE_ONLINE` con severidad `INFO`.

---

## 7. Ejemplos de intercambio

### 7.1. Ciclo de vida de un nodo de telemetría

```
   NODO01                                            SERVIDOR
     |                                                   |
     |--- TCP connect (puerto 6000) --------------------->|
     |                                                   |
     |--- REGISTER|NODO01|SENSOR_AMBIENTAL|PLANTA_A|TEMP|C|HUM|%|PWR|W|VIB|mm/s
     |                                                   |
     |<-- OK|REGISTER|NODO01|5000|3 ---------------------|
     |--- BYE ------------------------------------------>|
     |<-- OK|BYE ----------------------------------------|
     |--- TCP close ------------------------------------>|
     |                                                   |
     |=== UDP (puerto 5000) ============================>|
     |--- TELEMETRY|NODO01|1|TEMP|24.8|HUM|58.2|PWR|1180.5|VIB|1.4
     |<-- ACK|NODO01|1|0 --------------------------------|
     |                                                   |
     |        ... 3 segundos ...                         |
     |                                                   |
     |--- TELEMETRY|NODO01|2|TEMP|25.1|HUM|58.9|PWR|1195.0|VIB|1.5
     |<-- ACK|NODO01|2|0 --------------------------------|
     |                                                   |
     |        ... el sensor se dispara ...               |
     |                                                   |
     |--- TELEMETRY|NODO01|3|TEMP|42.1|HUM|59.0|PWR|1190.0|VIB|1.5
     |<-- ACK|NODO01|3|1 --------------------------------|   (1 alerta generada)
     |                                                   |
```

### 7.2. Sesión de un operador

```
OPERADOR → HELLO|sala-control-1
SERVIDOR ← OK|HELLO|TSP-SERVER-1|TSP/1.0|412

OPERADOR → LIST_NODES
SERVIDOR ← OK|LIST_NODES|3
SERVIDOR ← NODE|NODO01|ONLINE|SENSOR_AMBIENTAL|PLANTA_A|2|137|0
SERVIDOR ← NODE|NODO02|ONLINE|SENSOR_AMBIENTAL|PLANTA_A|1|136|2
SERVIDOR ← NODE|NODO03|OFFLINE|SENSOR_VIBRACION|PLANTA_B|48|91|1
SERVIDOR ← END|LIST_NODES

OPERADOR → GET_STATUS|NODO01
SERVIDOR ← OK|GET_STATUS|NODO01|ONLINE|2|4
SERVIDOR ← VAR|TEMP|42.10|C|1774900812
SERVIDOR ← VAR|HUM|59.00|%|1774900812
SERVIDOR ← VAR|PWR|1190.00|W|1774900812
SERVIDOR ← VAR|VIB|1.50|mm/s|1774900812
SERVIDOR ← END|GET_STATUS

OPERADOR → GET_ALERTS|2
SERVIDOR ← OK|GET_ALERTS|2
SERVIDOR ← EVENT|NODO01|TEMP_HIGH|42.10|1774900812|CRITICAL
SERVIDOR ← EVENT|NODO03|NODE_OFFLINE|18.00|1774900790|CRITICAL
SERVIDOR ← END|GET_ALERTS

OPERADOR → GET_SYSTEM
SERVIDOR ← OK|GET_SYSTEM|9
SERVIDOR ← STAT|UPTIME_SEG|412
SERVIDOR ← STAT|NODOS_REGISTRADOS|3
SERVIDOR ← STAT|NODOS_ACTIVOS|2
SERVIDOR ← STAT|OPERADORES_CONECTADOS|1
SERVIDOR ← STAT|TELEMETRIA_RECIBIDA|364
SERVIDOR ← STAT|TELEMETRIA_RECHAZADA|1
SERVIDOR ← STAT|TELEMETRIA_PERDIDA_EST|3
SERVIDOR ← STAT|COMANDOS_TCP|12
SERVIDOR ← STAT|ALERTAS_GENERADAS|2
SERVIDOR ← END|GET_SYSTEM

OPERADOR → BYE
SERVIDOR ← OK|BYE
```

### 7.3. Alerta provocada en vivo mediante `SET_THRESHOLD`

```
OPERADOR → SUBSCRIBE|ALERTS
SERVIDOR ← OK|SUBSCRIBE|ALERTS

OPERADOR → SET_THRESHOLD|*|TEMP|-10.0|20.0
SERVIDOR ← OK|SET_THRESHOLD|*|TEMP|-10.00|20.00

   (el siguiente TELEMETRY de cualquier nodo con TEMP > 20 dispara la alerta;
    el servidor la empuja sin que el operador pida nada)

SERVIDOR ← ALERT|NODO02|TEMP_HIGH|25.30|1774900851|CRITICAL
SERVIDOR ← ALERT|NODO01|TEMP_HIGH|24.90|1774900853|CRITICAL
```

### 7.4. Casos de error

```
OPERADOR → GET_STATUS|NODO99
SERVIDOR ← ERR|404|NODE_NOT_FOUND|El nodo NODO99 no esta registrado

OPERADOR → GET_STATUS
SERVIDOR ← ERR|402|MISSING_PARAM|GET_STATUS requiere el identificador del nodo

OPERADOR → DAME_TODO|AHORA
SERVIDOR ← ERR|401|UNKNOWN_COMMAND|Comando no reconocido en TSP/1.0

OPERADOR → SET_THRESHOLD|*|TEMP|50|10
SERVIDOR ← ERR|403|INVALID_PARAM|El umbral minimo no puede ser mayor que el maximo

OPERADOR → (línea vacía)
SERVIDOR ← ERR|400|BAD_REQUEST|Mensaje vacio o sin tipo

NODO07   → TELEMETRY|NODO07|1|TEMP|22.0          (por UDP, sin REGISTER previo)
SERVIDOR ← ERR|406|NOT_REGISTERED|El nodo debe registrarse por TCP antes de enviar telemetria
   (el nodo reacciona re-registrándose por TCP y reanuda el envío)
```

En **ninguno** de estos casos el servidor cierra la conexión ni finaliza: la
sesión sigue disponible para el siguiente comando.

---

## 8. Máquina de estados

### 8.1. Conexión TCP vista por el servidor

```
        [NUEVA CONEXION]
               |
               | primera línea recibida
       +-------+--------+---------------------+
       |                |                     |
   HELLO|...       REGISTER|...        cualquier otra cosa
       |                |                     |
       v                v                     v
  [OPERADOR]        [NODO]              ERR|401 y sigue en
       |                |               [NUEVA CONEXION]
       | comandos       | OK|REGISTER
       | GET_*, SET_*   |
       | SUBSCRIBE      v
       |            [CIERRE]
       v
   BYE / EOF / error de socket
       |
       v
   [CIERRE]  → se libera el slot y se cancela la suscripción
```

### 8.2. Nodo de telemetría

```
[INICIO] → resolver DNS → [REGISTRANDO] → OK|REGISTER → [ENVIANDO]
              ^                 |                            |
              |    fallo        | fallo TCP                  | ERR|406
              +-----------------+----------------------------+
                        (reintento con espera incremental)
```

---

## 9. Implementaciones de referencia

| Componente | Lenguaje | Archivo |
|---|---|---|
| Analizador y generador de mensajes (servidor) | C | [`server/protocol.c`](../server/protocol.c), [`server/protocol.h`](../server/protocol.h) |
| Despacho de comandos (servidor) | C | [`server/handlers.c`](../server/handlers.c) |
| Registro de nodos, alertas y estadísticas | C | [`server/registry.c`](../server/registry.c) |
| Biblioteca TSP para clientes | Python | [`clients/tsp.py`](../clients/tsp.py) |
| Nodo de telemetría | Python | [`clients/telemetry_node.py`](../clients/telemetry_node.py) |
| Cliente operador (CLI y GUI) | Python | [`clients/operator_cli.py`](../clients/operator_cli.py), [`clients/operator_gui.py`](../clients/operator_gui.py) |
