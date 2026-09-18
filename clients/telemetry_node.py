#!/usr/bin/env python3
"""Nodo de telemetria simulado - punto 3.1 del proyecto.

Cada nodo:
  * tiene un identificador unico;
  * simula 5 variables (TEMP, HUM, PWR, VIB, STATUS);
  * localiza el servidor mediante DNS, nunca por IP fija;
  * se da de alta por TCP (informacion critica) y envia las mediciones
    periodicamente por UDP (perdida tolerable);
  * maneja los errores de comunicacion sin caerse.

Ejemplos:

    python3 telemetry_node.py --id NODO01
    python3 telemetry_node.py --id NODO03 --host telemetria.ejemplo.com
    python3 telemetry_node.py --id NODO02 --anomaly-every 10
"""

import argparse
import os
import random
import signal
import socket
import sys
import time

import tsp

# ----------------------------------------------------------------------
# Modelo de las variables simuladas
#
# Cada variable hace un paseo aleatorio alrededor de un valor base, para
# que las mediciones se muevan de forma creible en lugar de saltar.
# ----------------------------------------------------------------------

VARIABLES = {
    # nombre:  (unidad, base, deriva, minimo, maximo, anomalia)
    "TEMP":   ("C",    22.0, 0.45,  15.0,  32.0, 47.5),
    "HUM":    ("%",    55.0, 1.20,  35.0,  75.0, 94.0),
    "PWR":    ("W",  1150.0, 35.0, 700.0, 1700.0, 2450.0),
    "VIB":    ("mm/s",  1.3, 0.22,   0.2,   3.5, 8.7),
    "STATUS": ("-",     1.0, 0.0,    1.0,   1.0, 0.0),
}

ORDEN_VARIABLES = ["TEMP", "HUM", "PWR", "VIB", "STATUS"]


class SimuladorSensor:
    """Genera lecturas plausibles para una variable."""

    def __init__(self, nombre, aleatorio):
        unidad, base, deriva, minimo, maximo, anomalo = VARIABLES[nombre]

        self.nombre = nombre
        self.unidad = unidad
        self.deriva = deriva
        self.minimo = minimo
        self.maximo = maximo
        self.anomalo = anomalo
        self.aleatorio = aleatorio

        # Cada nodo arranca en un punto distinto del rango
        self.valor = aleatorio.uniform(
            base - (maximo - minimo) * 0.15,
            base + (maximo - minimo) * 0.15,
        )

        self.valor = max(minimo, min(maximo, self.valor))

    def siguiente(self, forzar_anomalia=False):
        if forzar_anomalia:
            return self.anomalo

        if self.deriva == 0.0:
            return self.valor

        self.valor += self.aleatorio.gauss(0.0, self.deriva)

        # El paseo se mantiene dentro del rango normal de operacion
        self.valor = max(self.minimo, min(self.maximo, self.valor))

        return self.valor


# ----------------------------------------------------------------------
# Nodo
# ----------------------------------------------------------------------


class NodoTelemetria:
    def __init__(self, args):
        self.id = args.id.upper()
        self.host = args.host
        self.puerto_tcp = args.tcp_port
        self.puerto_udp = args.udp_port
        self.intervalo = args.interval
        self.tipo = args.type
        self.ubicacion = args.location
        self.anomalia_cada = args.anomaly_every
        self.duracion = args.duration
        self.verbose = not args.quiet

        self.aleatorio = random.Random(args.seed if args.seed is not None else None)

        self.sensores = {
            nombre: SimuladorSensor(nombre, self.aleatorio)
            for nombre in ORDEN_VARIABLES
        }

        self.sock_udp = None
        self.direccion_udp = None

        self.seq = 0
        self.registrado = False
        self.ejecutando = True

        # Contadores para la prueba del punto 11
        self.enviados = 0
        self.confirmados = 0
        self.sin_confirmar = 0
        self.errores_envio = 0
        self.alertas_reportadas = 0
        self.registros = 0

    # -- registro por TCP ----------------------------------------------

    def registrar(self):
        """Da de alta el nodo por TCP. Reintenta con espera incremental."""
        espera = 1.0

        while self.ejecutando:
            try:
                conexion = tsp.TspConexion(
                    self.host,
                    self.puerto_tcp,
                    timeout=10.0,
                    verbose=self.verbose,
                )

                conexion.conectar()

                # REGISTER|<ID>|<TIPO>|<UBICACION>|<VAR>|<UNIDAD>...
                campos = ["REGISTER", self.id, self.tipo, self.ubicacion]

                for nombre in ORDEN_VARIABLES:
                    campos.append(nombre)
                    campos.append(self.sensores[nombre].unidad)

                cabecera, _ = conexion.comando(*campos)

                # OK|REGISTER|<ID>|<UDP_PORT>|<INTERVALO_SUGERIDO>
                if len(cabecera) >= 4:
                    puerto_sugerido = int(cabecera[3])

                    if puerto_sugerido != self.puerto_udp:
                        self.log(
                            f"el servidor indica el puerto UDP {puerto_sugerido}"
                        )
                        self.puerto_udp = puerto_sugerido
                        self.direccion_udp = None

                conexion.cerrar()

                self.registrado = True
                self.registros += 1

                self.log(f"registrado en {self.host} como {self.tipo} / {self.ubicacion}")

                return True

            except (OSError, tsp.TspError, tsp.TspProtocolError) as exc:
                self.log(f"fallo el registro ({exc}); reintento en {espera:.0f}s")

                self.dormir(espera)

                # Espera incremental, con tope, para no golpear al servidor
                espera = min(espera * 2, 30.0)

        return False

    # -- envio por UDP -------------------------------------------------

    def abrir_socket_udp(self):
        if self.sock_udp is not None:
            return

        self.sock_udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # El ACK es informativo: si no llega, el nodo sigue adelante
        self.sock_udp.settimeout(1.0)

    def resolver_destino(self):
        """Resuelve el destino UDP por DNS, cacheando el resultado."""
        if self.direccion_udp is not None:
            return self.direccion_udp

        infos = tsp.resolver(
            self.host,
            self.puerto_udp,
            socket.SOCK_DGRAM,
            self.verbose,
        )

        self.direccion_udp = infos[0][4]

        return self.direccion_udp

    def medir(self, forzar_anomalia):
        """Genera una lectura de cada variable."""
        lecturas = []

        # La anomalia se inyecta en una sola variable por ciclo
        variable_anomala = None

        if forzar_anomalia:
            candidatas = [n for n in ORDEN_VARIABLES if n != "STATUS"]
            variable_anomala = self.aleatorio.choice(candidatas)

        for nombre in ORDEN_VARIABLES:
            valor = self.sensores[nombre].siguiente(
                forzar_anomalia=(nombre == variable_anomala)
            )

            lecturas.append((nombre, valor))

        return lecturas, variable_anomala

    def enviar_medicion(self, lecturas):
        """Envia un TELEMETRY y espera el ACK. Devuelve True si se envio."""
        self.seq += 1

        campos = ["TELEMETRY", self.id, self.seq]

        for nombre, valor in lecturas:
            campos.append(nombre)
            campos.append(tsp.formatear_numero(valor))

        try:
            destino = self.resolver_destino()

            self.abrir_socket_udp()
            self.sock_udp.sendto(tsp.codificar(*campos), destino)

            self.enviados += 1

        except (OSError, ValueError) as exc:
            self.errores_envio += 1

            self.log(f"error enviando telemetria: {exc}")

            # Puede haber cambiado la IP del servidor: se fuerza otra
            # resolucion DNS en el proximo ciclo
            self.direccion_udp = None

            return False

        # -- espera del ACK (no es fiable, es diagnostico) --------------

        try:
            datos, _ = self.sock_udp.recvfrom(tsp.MAX_MENSAJE)

        except socket.timeout:
            self.sin_confirmar += 1

            self.log(f"sin ACK para seq={self.seq}")

            return True

        except OSError as exc:
            self.sin_confirmar += 1

            self.log(f"error esperando ACK: {exc}")

            return True

        campos_ack = tsp.decodificar(datos)

        if campos_ack[0] == "ACK":
            self.confirmados += 1

            alertas = int(campos_ack[3]) if len(campos_ack) > 3 and campos_ack[3].isdigit() else 0

            if alertas > 0:
                self.alertas_reportadas += alertas

                self.log(f"el servidor genero {alertas} alerta(s) con seq={self.seq}")

            return True

        if campos_ack[0] == "ERR":
            codigo = int(campos_ack[1]) if len(campos_ack) > 1 and campos_ack[1].isdigit() else 0

            self.log(f"el servidor respondio {' '.join(campos_ack[1:])}")

            # El servidor no conoce este nodo (se reinicio, por ejemplo):
            # el nodo se recupera solo volviendo a registrarse.
            if codigo == tsp.ERR_NOT_REGISTERED:
                self.registrado = False

        return True

    # -- bucle principal -----------------------------------------------

    def ejecutar(self):
        self.log(f"iniciando (servidor '{self.host}', intervalo {self.intervalo}s)")

        inicio = time.time()
        ciclo = 0

        while self.ejecutando:
            if not self.registrado:
                if not self.registrar():
                    break

            ciclo += 1

            forzar = (
                self.anomalia_cada > 0
                and ciclo % self.anomalia_cada == 0
            )

            lecturas, variable_anomala = self.medir(forzar)

            if variable_anomala is not None:
                self.log(f"inyectando anomalia en {variable_anomala}")

            self.enviar_medicion(lecturas)

            if self.verbose:
                resumen = "  ".join(
                    f"{nombre}={tsp.formatear_numero(valor)}"
                    for nombre, valor in lecturas
                )

                print(f"[{self.id}] seq={self.seq}  {resumen}")

            if self.duracion > 0 and (time.time() - inicio) >= self.duracion:
                break

            self.dormir(self.intervalo)

        self.finalizar()

    def dormir(self, segundos):
        """Espera troceada para reaccionar rapido a Ctrl-C."""
        fin = time.time() + segundos

        while self.ejecutando and time.time() < fin:
            time.sleep(min(0.2, max(0.0, fin - time.time())))

    def detener(self, *_):
        self.ejecutando = False

    def finalizar(self):
        if self.sock_udp is not None:
            try:
                self.sock_udp.close()
            except OSError:
                pass

            self.sock_udp = None

        print(
            f"\n[{self.id}] --- Resumen de la sesion ---\n"
            f"[{self.id}] Registros TCP realizados : {self.registros}\n"
            f"[{self.id}] Datagramas enviados      : {self.enviados}\n"
            f"[{self.id}] ACK recibidos            : {self.confirmados}\n"
            f"[{self.id}] Sin ACK (timeout)        : {self.sin_confirmar}\n"
            f"[{self.id}] Errores de envio         : {self.errores_envio}\n"
            f"[{self.id}] Alertas notificadas      : {self.alertas_reportadas}"
        )

    def log(self, mensaje):
        if self.verbose:
            print(f"[{self.id}] {mensaje}")


# ----------------------------------------------------------------------
# Linea de comandos
# ----------------------------------------------------------------------


def construir_parser():
    parser = argparse.ArgumentParser(
        description="Nodo de telemetria simulado (TSP/1.0)",
    )

    parser.add_argument(
        "--id",
        required=True,
        help="identificador unico del nodo, por ejemplo NODO01",
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
        help="puerto TCP para el registro",
    )

    parser.add_argument(
        "--udp-port",
        type=int,
        default=int(os.environ.get("TSP_UDP_PORT", tsp.PUERTO_UDP_DEFECTO)),
        help="puerto UDP para la telemetria",
    )

    parser.add_argument(
        "--interval",
        type=float,
        default=3.0,
        help="segundos entre mediciones",
    )

    parser.add_argument(
        "--type",
        default="SENSOR_AMBIENTAL",
        help="tipo de dispositivo",
    )

    parser.add_argument(
        "--location",
        default="PLANTA_A",
        help="instalacion donde esta desplegado el nodo",
    )

    parser.add_argument(
        "--anomaly-every",
        type=int,
        default=0,
        metavar="N",
        help="inyecta un valor anomalo cada N ciclos (0 = nunca)",
    )

    parser.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="segundos de ejecucion (0 = indefinido)",
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="semilla aleatoria, para obtener series reproducibles",
    )

    parser.add_argument(
        "--quiet",
        action="store_true",
        help="no imprimir cada medicion",
    )

    return parser


def main():
    args = construir_parser().parse_args()

    nodo = NodoTelemetria(args)

    signal.signal(signal.SIGINT, nodo.detener)
    signal.signal(signal.SIGTERM, nodo.detener)

    try:
        nodo.ejecutar()
    except KeyboardInterrupt:
        nodo.detener()
        nodo.finalizar()

    return 0


if __name__ == "__main__":
    sys.exit(main())
