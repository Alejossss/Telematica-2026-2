#!/usr/bin/env python3
"""Lanzador de varios nodos de telemetria simultaneos - punto 3.1.

El enunciado exige ejecutar 5 nodos o mas a la vez. Este script arranca
cada nodo como un proceso independiente, les reparte identificador, tipo
y ubicacion, y los detiene a todos de forma ordenada con Ctrl-C.

Ejemplos:

    python3 run_nodes.py
    python3 run_nodes.py --count 8 --host telemetria.ejemplo.com
    python3 run_nodes.py --count 5 --anomaly-every 12
"""

import argparse
import os
import signal
import subprocess
import sys
import time

import tsp

# Perfiles que se reparten ciclicamente entre los nodos, para que el
# sistema no sea una fila de dispositivos identicos.
PERFILES = [
    ("SENSOR_AMBIENTAL",  "PLANTA_A"),
    ("SENSOR_AMBIENTAL",  "PLANTA_B"),
    ("SENSOR_VIBRACION",  "PLANTA_A"),
    ("MEDIDOR_ENERGIA",   "SUBESTACION_1"),
    ("SENSOR_AMBIENTAL",  "BODEGA_NORTE"),
    ("SENSOR_VIBRACION",  "SUBESTACION_1"),
    ("MEDIDOR_ENERGIA",   "PLANTA_B"),
    ("SENSOR_AMBIENTAL",  "SALA_SERVIDORES"),
]


def construir_parser():
    parser = argparse.ArgumentParser(
        description="Arranca varios nodos de telemetria a la vez",
    )

    parser.add_argument(
        "--count",
        type=int,
        default=5,
        help="cuantos nodos arrancar (minimo exigido: 5)",
    )

    parser.add_argument(
        "--host",
        default=os.environ.get("TSP_SERVER_HOST", "localhost"),
        help="nombre DNS del servidor (o variable TSP_SERVER_HOST)",
    )

    parser.add_argument(
        "--tcp-port",
        type=int,
        default=int(os.environ.get("TSP_TCP_PORT", tsp.PUERTO_TCP_DEFECTO)),
    )

    parser.add_argument(
        "--udp-port",
        type=int,
        default=int(os.environ.get("TSP_UDP_PORT", tsp.PUERTO_UDP_DEFECTO)),
    )

    parser.add_argument(
        "--interval",
        type=float,
        default=3.0,
        help="segundos entre mediciones de cada nodo",
    )

    parser.add_argument(
        "--prefix",
        default="NODO",
        help="prefijo de los identificadores",
    )

    parser.add_argument(
        "--anomaly-every",
        type=int,
        default=0,
        metavar="N",
        help="cada nodo inyecta una anomalia cada N ciclos (0 = nunca)",
    )

    parser.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="segundos de ejecucion (0 = indefinido)",
    )

    parser.add_argument(
        "--stagger",
        type=float,
        default=0.4,
        help="retardo entre arranques, para no registrarlos todos a la vez",
    )

    parser.add_argument(
        "--quiet",
        action="store_true",
        help="los nodos no imprimen cada medicion",
    )

    return parser


def _detener_con_sigterm(_senal, _marco):
    """Convierte SIGTERM en la misma parada ordenada que Ctrl-C.

    Con Ctrl-C la senal llega a todo el grupo de procesos y los nodos se
    enteran solos, pero con 'kill' solo la recibe el lanzador: sin esto,
    los nodos quedarian huerfanos y siguiendo en marcha.
    """
    raise KeyboardInterrupt


def main():
    args = construir_parser().parse_args()

    signal.signal(signal.SIGTERM, _detener_con_sigterm)

    if args.count < 1:
        print("El numero de nodos debe ser al menos 1", file=sys.stderr)
        return 1

    if args.count < 5:
        print(
            f"[LANZADOR] Aviso: el enunciado exige 5 nodos o mas "
            f"(se van a arrancar {args.count})"
        )

    guion = os.path.join(os.path.dirname(os.path.abspath(__file__)), "telemetry_node.py")

    procesos = []

    print(f"[LANZADOR] Arrancando {args.count} nodos contra '{args.host}'")

    try:
        for i in range(args.count):
            identificador = f"{args.prefix}{i + 1:02d}"
            tipo, ubicacion = PERFILES[i % len(PERFILES)]

            comando = [
                sys.executable,
                guion,
                "--id", identificador,
                "--host", args.host,
                "--tcp-port", str(args.tcp_port),
                "--udp-port", str(args.udp_port),
                "--interval", str(args.interval),
                "--type", tipo,
                "--location", ubicacion,
                "--anomaly-every", str(args.anomaly_every),
                "--duration", str(args.duration),
                "--seed", str(1000 + i),
            ]

            if args.quiet:
                comando.append("--quiet")

            proceso = subprocess.Popen(comando)

            procesos.append((identificador, proceso))

            print(f"[LANZADOR] {identificador} ({tipo} / {ubicacion}) pid={proceso.pid}")

            time.sleep(args.stagger)

        print("[LANZADOR] Todos los nodos en marcha. Ctrl-C para detenerlos.")

        # Se espera a que terminen (o a que el usuario interrumpa)
        for _, proceso in procesos:
            proceso.wait()

    except KeyboardInterrupt:
        print("\n[LANZADOR] Deteniendo los nodos...")

        for identificador, proceso in procesos:
            if proceso.poll() is not None:
                continue

            try:
                # En Windows no existe SIGTERM para procesos hijos del
                # mismo modo: terminate() hace lo correcto en ambos casos.
                if os.name == "nt":
                    proceso.terminate()
                else:
                    proceso.send_signal(signal.SIGTERM)

            except OSError as exc:
                print(f"[LANZADOR] No se pudo detener {identificador}: {exc}")

        for identificador, proceso in procesos:
            try:
                proceso.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print(f"[LANZADOR] {identificador} no respondio, se fuerza el cierre")
                proceso.kill()

        print("[LANZADOR] Nodos detenidos")

    return 0


if __name__ == "__main__":
    sys.exit(main())
