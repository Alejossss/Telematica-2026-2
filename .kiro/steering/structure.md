# Estructura del proyecto

```
.
├── Makefile              # compilación del servidor y clientes en C
├── README.md             # visión general, arquitectura y guía de ejecución
├── docs/
│   └── PROTOCOLO.md      # especificación autoritativa de TSP/1.0
├── server/               # servidor central en C
└── clients/              # nodos y operadores en Python
├── docker-compose.yml    # Orquestación de contenedores (Punto 9)
├── Dockerfile            # Imagen del servidor C (Punto 9)
├── web/                  # Servicio web HTTP básico (Punto 7)
```

## `server/` (C)

Separación clara de responsabilidades por módulo; mantenerla al añadir código.

| Archivo | Responsabilidad |
|---|---|
| `server_concurrent.c` | Sockets, `bind`/`listen`/`accept`, hilos y ciclo de vida de conexiones. Es el binario que se despliega. |
| `protocol.c` / `protocol.h` | **Sintaxis** TSP: análisis de líneas, validación, construcción de errores y separación del flujo TCP en mensajes. |
| `handlers.c` / `handlers.h` | **Semántica**: qué hace el servidor con cada mensaje. |
| `registry.c` / `registry.h` | **Estado**: nodos, mediciones, umbrales, alertas y estadísticas. |
| `server_tcp.c`, `server_udp.c` | Versiones iniciales de cada socket por separado. Material de estudio, no se despliegan. |
| `client_tcp_test.c`, `client_udp_test.c` | Clientes de socket crudos para probar el protocolo a mano. |

Regla clave: sintaxis en `protocol.c`, semántica en `handlers.c`, estado en
`registry.c`. No mezclar parseo con lógica de negocio ni con almacenamiento.

## `clients/` (Python)

| Archivo | Responsabilidad |
|---|---|
| `tsp.py` | Biblioteca TSP compartida: constantes, codificación/decodificación, resolución DNS y lectura de respuestas simples/múltiples. |
| `telemetry_node.py` | Nodo de telemetría: `REGISTER` por TCP y envío periódico de `TELEMETRY` por UDP. |
| `run_nodes.py` | Lanza varios nodos simultáneos. |
| `operator_cli.py` | Cliente operador de línea de comandos (interactivo y `--once`). |
| `operator_gui.py` | Cliente operador con interfaz gráfica (`tkinter`). |

Los clientes no reimplementan el protocolo: dependen de `tsp.py`.

## Convenciones de organización

- Los binarios compilados y archivos objeto (`server/server_*`, `*.o`) están en
  `.gitignore`; no se versionan.
- Todo cambio en el formato o la semántica del protocolo debe mantenerse
  sincronizado entre `server/`, `clients/tsp.py` y `docs/PROTOCOLO.md`, que es
  la fuente de verdad.
