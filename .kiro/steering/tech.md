# Stack técnico

## Servidor (C)

- Lenguaje C sobre POSIX; concurrencia con hilos `pthread`.
- Modelo de hilos: un hilo para el socket UDP, un hilo por cliente TCP (modo
  *detached*) y un hilo monitor que marca nodos como `OFFLINE`.
- Sin dependencias externas más allá de la libc y `pthread`.
- Compilación: `gcc` con `-Wall -Wextra -O2` y enlace `-pthread`.

## Clientes (Python)

- Python 3 (usa `python3`), solo biblioteca estándar (`socket`, `threading`,
  `argparse`, etc.).
- La GUI del operador (`operator_gui.py`) requiere `tkinter`.
- `clients/tsp.py` es la biblioteca TSP compartida por nodos y operadores; toda
  lógica de codificación/decodificación de mensajes debe pasar por ahí.

## Servicio Web (Punto 7).

- Proporcionará una interfaz web básica HTTP.

- El propósito no es desarrollar una aplicación web compleja (no usar frameworks grandes como Django o React). Debe ser una integración sencilla (por ejemplo, usando http.server de Python o un micro-framework muy simple como Flask, interactuando con tsp.py para obtener datos del servidor central).

- Debe mostrar: estado del servidor, cantidad de nodos registrados, nodos activos, últimas mediciones y alertas recientes.

## Nube, DNS y Docker (Puntos 8 y 9)

- El servidor central en C debe ejecutarse dentro de un contenedor Docker.   

- Se requiere un Dockerfile para la imagen del servidor y un docker-compose.yml para orquestar la ejecución.   

- El despliegue final será en una instancia de computación en la nube (AWS EC2). Se deben generar scripts o instrucciones precisas para instalar Docker en la instancia y configurar las reglas de acceso (abrir puertos TCP 6000, UDP 5000, y el puerto HTTP del servicio web).

## Puertos y configuración

- TCP `6000` (registro, comandos, alertas) y UDP `5000` (telemetría).
- Configurables sin recompilar mediante variables de entorno:
  `TSP_TCP_PORT`, `TSP_UDP_PORT`, `TSP_SERVER_HOST`.

## Comandos comunes

### Compilar (Makefile)

```bash
make            # compila el servidor (server/server_concurrent)
make clients    # compila los clientes de prueba en C
make all        # compila todo
make run        # compila y arranca el servidor
make clean      # borra binarios y objetos
```

### Ejecutar

```bash
./server/server_concurrent                                   # servidor

cd clients
python3 run_nodes.py --count 5 --host <dns-servidor>         # varios nodos
python3 telemetry_node.py --id NODO01 --host <dns-servidor>  # un nodo
python3 operator_cli.py --host <dns-servidor>                # operador CLI
python3 operator_gui.py --host <dns-servidor>                # operador GUI
python3 operator_cli.py --once system                        # consulta puntual
```

### Probar el protocolo a mano

```bash
nc <servidor> 6000
LIST_NODES
GET_STATUS|NODO01
BYE
```

## Convenciones de código

- Constantes del protocolo (versión, separadores, códigos de error, límites)
  se declaran una vez y se reutilizan; en C viven en `server/protocol.h`, en
  Python en `clients/tsp.py`. No se replican con valores mágicos.
- Los códigos de error TSP (400–503) deben coincidir exactamente entre C y
  Python y con la sección 5 de `docs/PROTOCOLO.md`.
- Comentarios en español; muchos módulos referencian el punto del enunciado o
  la sección de `docs/PROTOCOLO.md` que implementan. Mantén esas referencias.
- Un mensaje TSP es una línea única, campos separados por `|`, terminada en
  `\n`, máximo 1024 bytes. Cualquier cambio de formato debe reflejarse a la vez
  en el servidor, la biblioteca cliente y `docs/PROTOCOLO.md`.
