#!/usr/bin/env python3
"""Cliente operador - punto 3.3 del proyecto.

Permite:
  * consultar los nodos activos          (nodes)
  * visualizar las ultimas mediciones    (last)
  * consultar un dispositivo especifico  (node <ID>)
  * visualizar las alertas               (alerts)
  * consultar el estado general          (system)

Toda la comunicacion va por TCP, porque son consultas y comandos que
exigen entrega fiable y una respuesta asociada a cada peticion.

Ejemplos:

    python3 operator_cli.py
    python3 operator_cli.py --host telemetria.ejemplo.com --name sala-control
    python3 operator_cli.py --once system
"""

import argparse
import os
import queue
import sys
import threading
import time

import tsp

# ----------------------------------------------------------------------
# Presentacion
# ----------------------------------------------------------------------


def hora(ts):
    try:
        return time.strftime("%H:%M:%S", time.localtime(int(ts)))
    except (ValueError, TypeError, OSError):
        return "--:--:--"


def tabla(encabezados, filas, anchos=None):
    """Imprime una tabla de texto simple."""
    if not filas:
        print("  (sin datos)")
        return

    columnas = len(encabezados)

    if anchos is None:
        anchos = []

        for i in range(columnas):
            ancho = len(encabezados[i])

            for fila in filas:
                if i < len(fila):
                    ancho = max(ancho, len(str(fila[i])))

            anchos.append(ancho)

    linea = "  ".join(encabezados[i].ljust(anchos[i]) for i in range(columnas))

    print("  " + linea)
    print("  " + "-" * len(linea))

    for fila in filas:
        celdas = []

        for i in range(columnas):
            valor = str(fila[i]) if i < len(fila) else ""
            celdas.append(valor.ljust(anchos[i]))

        print("  " + "  ".join(celdas))


def mostrar_alerta(campos, prefijo="[ALERTA]"):
    # ALERT|<NODE_ID>|<TIPO>|<VALOR>|<TS>|<SEVERIDAD>
    nodo = campos[1] if len(campos) > 1 else "?"
    tipo = campos[2] if len(campos) > 2 else "?"
    valor = campos[3] if len(campos) > 3 else "?"
    ts = campos[4] if len(campos) > 4 else "0"
    severidad = campos[5] if len(campos) > 5 else "?"

    print(f"\n{prefijo} {hora(ts)}  {nodo}  {tipo}  valor={valor}  [{severidad}]")


# ----------------------------------------------------------------------
# Sesion del operador
#
# Un hilo lector es el unico que lee del socket: las alertas empujadas
# por el servidor se imprimen al instante y las respuestas a los comandos
# se encolan para el hilo principal (seccion 4.10 de docs/PROTOCOLO.md).
# ----------------------------------------------------------------------


class SesionOperador:
    def __init__(self, host, puerto, nombre, verbose=True):
        self.conexion = tsp.TspConexion(host, puerto, timeout=10.0, verbose=verbose)
        self.nombre = nombre

        self.cola = queue.Queue()
        self.lector = None
        self.activo = False
        self.suscrito = False
        self.error_lector = None

        # Solo se redibuja el prompt cuando de verdad hay uno en pantalla
        self.interactivo = False

    # -- ciclo de vida -------------------------------------------------

    def abrir(self):
        self.conexion.conectar()

        self.activo = True

        self.lector = threading.Thread(target=self._bucle_lector, daemon=True)
        self.lector.start()

        cabecera, _ = self.comando("HELLO", self.nombre)

        # OK|HELLO|<SERVER_ID>|<VERSION>|<UPTIME>
        if len(cabecera) >= 4:
            print(
                f"[OPERADOR] Conectado a {cabecera[2]} ({cabecera[3]}), "
                f"activo hace {cabecera[4] if len(cabecera) > 4 else '?'} s"
            )

    def cerrar(self):
        self.activo = False

        try:
            self.conexion.cerrar()
        except OSError:
            pass

    def _bucle_lector(self):
        """Unico punto de lectura del socket."""
        while self.activo:
            try:
                linea = self.conexion.leer_linea()

            except (OSError, ConnectionError) as exc:
                if self.activo:
                    self.error_lector = exc
                    self.cola.put(None)
                break

            campos = tsp.decodificar(linea)

            # Solo un ALERT es asincrono: el historial de GET_ALERTS llega
            # como registros EVENT y por eso no se confunde con un empuje
            # (seccion 3.3 de docs/PROTOCOLO.md)
            if campos and campos[0] == "ALERT":
                mostrar_alerta(campos)

                # Se redibuja el prompt que la alerta acaba de interrumpir
                if self.interactivo:
                    print("tsp> ", end="", flush=True)
                continue

            self.cola.put(linea)

    def _siguiente_linea(self, timeout=15.0):
        linea = self.cola.get(timeout=timeout)

        if linea is None:
            raise ConnectionError(
                f"Se perdio la conexion con el servidor: {self.error_lector}"
            )

        return linea

    # -- comandos ------------------------------------------------------

    def comando(self, *campos):
        self.conexion.enviar(*campos)

        return tsp.leer_respuesta(self._siguiente_linea)


# ----------------------------------------------------------------------
# Comandos del operador
# ----------------------------------------------------------------------


def cmd_nodes(sesion, _args):
    _, registros = sesion.comando("LIST_NODES")

    filas = []

    for r in registros:
        # NODE|<ID>|<ESTADO>|<TIPO>|<UBICACION>|<HACE_SEG>|<MSGS>|<PERDIDOS>
        if len(r) < 8:
            continue

        filas.append([r[1], r[2], r[3], r[4], f"{r[5]}s", r[6], r[7]])

    print(f"\n  Nodos registrados: {len(filas)}")

    tabla(
        ["NODO", "ESTADO", "TIPO", "UBICACION", "ULTIMA", "MSGS", "PERDIDOS"],
        filas,
    )


def cmd_node(sesion, args):
    if not args:
        print("  Uso: node <ID_NODO>")
        return

    cabecera, registros = sesion.comando("GET_STATUS", args[0])

    # OK|GET_STATUS|<ID>|<ESTADO>|<HACE_SEG>|<n>
    print(
        f"\n  Nodo {cabecera[2]}  estado={cabecera[3]}  "
        f"ultima medicion hace {cabecera[4]}s"
    )

    filas = [
        [r[1], r[2], r[3], hora(r[4])]
        for r in registros
        if len(r) >= 5
    ]

    tabla(["VARIABLE", "VALOR", "UNIDAD", "HORA"], filas)


def cmd_last(sesion, args):
    n = args[0] if args else "10"

    _, registros = sesion.comando("GET_LAST", n)

    filas = [
        [hora(r[5]), r[1], r[2], r[3], r[4]]
        for r in registros
        if len(r) >= 6
    ]

    print(f"\n  Ultimas {len(filas)} mediciones")

    tabla(["HORA", "NODO", "VARIABLE", "VALOR", "UNIDAD"], filas)


def cmd_alerts(sesion, args):
    n = args[0] if args else "10"

    _, registros = sesion.comando("GET_ALERTS", n)

    filas = [
        [hora(r[4]), r[1], r[2], r[3], r[5]]
        for r in registros
        if len(r) >= 6
    ]

    print(f"\n  Ultimas {len(filas)} alertas")

    tabla(["HORA", "NODO", "TIPO", "VALOR", "SEVERIDAD"], filas)


def cmd_system(sesion, _args):
    _, registros = sesion.comando("GET_SYSTEM")

    filas = [[r[1], r[2]] for r in registros if len(r) >= 3]

    print("\n  Estado general del sistema")

    tabla(["INDICADOR", "VALOR"], filas)


def cmd_threshold(sesion, args):
    if len(args) < 4:
        print("  Uso: threshold <NODO|*> <VARIABLE> <MIN> <MAX>")
        print("  Ejemplo: threshold * TEMP -10 20")
        return

    cabecera, _ = sesion.comando("SET_THRESHOLD", args[0], args[1], args[2], args[3])

    print(
        f"\n  Umbral aplicado: {cabecera[2]} / {cabecera[3]} "
        f"-> [{cabecera[4]}, {cabecera[5]}]"
    )


def cmd_subscribe(sesion, _args):
    sesion.comando("SUBSCRIBE", "ALERTS")

    sesion.suscrito = True

    print("\n  Suscrito: las alertas apareceran en cuanto el servidor las genere")


def cmd_unsubscribe(sesion, _args):
    sesion.comando("UNSUBSCRIBE", "ALERTS")

    sesion.suscrito = False

    print("\n  Suscripcion cancelada")


def cmd_ping(sesion, _args):
    inicio = time.time()

    campos = sesion.comando("PING")[0]

    tardanza = (time.time() - inicio) * 1000.0

    print(f"\n  {campos[0]} del servidor en {tardanza:.1f} ms")


def cmd_raw(sesion, args):
    """Envia un mensaje TSP tal cual, util para demostrar el protocolo."""
    if not args:
        print("  Uso: raw <TIPO> [campo...]      Ejemplo: raw GET_STATUS NODO01")
        return

    cabecera, registros = sesion.comando(*args)

    print("\n  " + "|".join(cabecera))

    for r in registros:
        print("  " + "|".join(r))


COMANDOS = {
    "nodes": (cmd_nodes, "lista los nodos registrados y su estado"),
    "node": (cmd_node, "consulta un dispositivo: node NODO01"),
    "last": (cmd_last, "ultimas mediciones del sistema: last 15"),
    "alerts": (cmd_alerts, "alertas recientes: alerts 20"),
    "system": (cmd_system, "estado general del servidor"),
    "threshold": (cmd_threshold, "cambia un umbral: threshold * TEMP -10 20"),
    "subscribe": (cmd_subscribe, "recibe las alertas en tiempo real"),
    "unsubscribe": (cmd_unsubscribe, "deja de recibir alertas"),
    "ping": (cmd_ping, "comprueba la conexion con el servidor"),
    "raw": (cmd_raw, "envia un mensaje TSP literal"),
}


def cmd_help(*_):
    print("\n  Comandos disponibles\n")

    for nombre, (_, descripcion) in COMANDOS.items():
        print(f"    {nombre:<12} {descripcion}")

    print(f"    {'help':<12} muestra esta ayuda")
    print(f"    {'quit':<12} cierra la sesion\n")


# ----------------------------------------------------------------------
# Bucle interactivo
# ----------------------------------------------------------------------


def ejecutar_comando(sesion, entrada):
    partes = entrada.split()

    if not partes:
        return True

    nombre = partes[0].lower()
    argumentos = partes[1:]

    if nombre in ("quit", "exit", "salir"):
        return False

    if nombre in ("help", "ayuda", "?"):
        cmd_help()
        return True

    if nombre not in COMANDOS:
        print(f"  Comando desconocido: {nombre}. Escribe 'help'.")
        return True

    try:
        COMANDOS[nombre][0](sesion, argumentos)

    except tsp.TspError as exc:
        # Un error del protocolo no cierra la sesion (seccion 5.1)
        print(f"\n  El servidor rechazo la peticion: {exc}")

    except (ValueError, IndexError) as exc:
        print(f"\n  Respuesta inesperada del servidor: {exc}")

    except queue.Empty:
        print("\n  El servidor no respondio a tiempo")

    return True


def construir_parser():
    parser = argparse.ArgumentParser(description="Cliente operador TSP/1.0")

    parser.add_argument(
        "--host",
        default=os.environ.get("TSP_SERVER_HOST", "localhost"),
        help="nombre DNS del servidor (o variable TSP_SERVER_HOST)",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("TSP_TCP_PORT", tsp.PUERTO_TCP_DEFECTO)),
        help="puerto TCP del servidor",
    )

    parser.add_argument(
        "--name",
        default=os.environ.get("TSP_OPERATOR_NAME", "operador"),
        help="nombre con el que el operador se identifica",
    )

    parser.add_argument(
        "--once",
        metavar="COMANDO",
        help="ejecuta un unico comando y termina, por ejemplo: --once system",
    )

    parser.add_argument(
        "--subscribe",
        action="store_true",
        help="suscribirse a las alertas al iniciar la sesion",
    )

    return parser


def main():
    args = construir_parser().parse_args()

    sesion = SesionOperador(args.host, args.port, args.name)

    try:
        sesion.abrir()

    except (OSError, ConnectionError) as exc:
        print(f"[OPERADOR] No fue posible conectar: {exc}", file=sys.stderr)
        return 1

    except tsp.TspError as exc:
        print(f"[OPERADOR] El servidor rechazo la sesion: {exc}", file=sys.stderr)
        sesion.cerrar()
        return 1

    try:
        if args.subscribe:
            cmd_subscribe(sesion, [])

        # Modo no interactivo: un comando y fuera
        if args.once:
            ejecutar_comando(sesion, args.once)
            return 0

        cmd_help()

        sesion.interactivo = True

        while True:
            try:
                entrada = input("tsp> ")

            except EOFError:
                print()
                break

            except KeyboardInterrupt:
                print()
                break

            if not ejecutar_comando(sesion, entrada):
                break

    except ConnectionError as exc:
        print(f"\n[OPERADOR] {exc}", file=sys.stderr)
        return 1

    finally:
        sesion.cerrar()

        print("[OPERADOR] Sesion cerrada")

    return 0


if __name__ == "__main__":
    sys.exit(main())
