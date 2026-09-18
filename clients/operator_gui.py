#!/usr/bin/env python3
"""Cliente operador con interfaz grafica sencilla - punto 3.3.

Muestra en una sola ventana:
  * el estado general del servidor;
  * los nodos activos y su estado;
  * las ultimas mediciones del nodo seleccionado;
  * las alertas, tanto el historial como las que llegan en vivo.

La ventana no habla nunca directamente con el socket: un hilo trabajador
mantiene la conexion TCP, consulta al servidor cada pocos segundos y deja
los resultados en una cola que la interfaz vacia con ``after()``. Asi la
ventana no se congela esperando a la red.

Requiere tkinter (viene con Python en Windows y macOS; en Debian/Ubuntu
se instala con: sudo apt install python3-tk).

Ejemplos:

    python3 operator_gui.py
    python3 operator_gui.py --host telemetria.ejemplo.com
"""

import argparse
import os
import queue
import sys
import threading
import time

import tsp

# ----------------------------------------------------------------------
# Capa de datos: no depende de tkinter y por eso se puede probar sola
# ----------------------------------------------------------------------


class TrabajadorTelemetria:
    """Mantiene la sesion TCP y consulta al servidor periodicamente."""

    def __init__(self, host, puerto, nombre, intervalo=2.0):
        self.host = host
        self.puerto = puerto
        self.nombre = nombre
        self.intervalo = intervalo

        self.eventos = queue.Queue()     # trabajador -> interfaz
        self.peticiones = queue.Queue()  # interfaz -> trabajador

        self.nodo_seleccionado = None
        self.activo = False

        self._hilo = None
        self._conexion = None

    # -- control -------------------------------------------------------

    def iniciar(self):
        self.activo = True

        self._hilo = threading.Thread(target=self._bucle, daemon=True)
        self._hilo.start()

    def detener(self):
        self.activo = False

    def seleccionar_nodo(self, node_id):
        self.nodo_seleccionado = node_id

    def pedir_umbral(self, destino, variable, minimo, maximo):
        self.peticiones.put(("SET_THRESHOLD", destino, variable, minimo, maximo))

    # -- hilo trabajador -----------------------------------------------

    def _emitir(self, tipo, datos):
        self.eventos.put((tipo, datos))

    def _bucle(self):
        espera = 1.0

        while self.activo:
            try:
                self._conectar()

                espera = 1.0

                while self.activo:
                    self._atender_peticiones()
                    self._consultar()

                    # Espera troceada: reacciona rapido al cierre
                    fin = time.time() + self.intervalo

                    while self.activo and time.time() < fin:
                        time.sleep(0.1)

            except (OSError, ConnectionError, tsp.TspError, tsp.TspProtocolError) as exc:
                if not self.activo:
                    break

                self._emitir("desconectado", str(exc))
                self._cerrar()

                # Reintento con espera incremental
                fin = time.time() + espera

                while self.activo and time.time() < fin:
                    time.sleep(0.1)

                espera = min(espera * 2, 15.0)

        self._cerrar()

    def _conectar(self):
        self._conexion = tsp.TspConexion(
            self.host, self.puerto, timeout=8.0, verbose=False)

        self._conexion.conectar()

        cabecera, _ = self._conexion.comando("HELLO", self.nombre)

        self._conexion.comando("SUBSCRIBE", "ALERTS")

        self._emitir("conectado", {
            "servidor": cabecera[2] if len(cabecera) > 2 else "?",
            "version": cabecera[3] if len(cabecera) > 3 else "?",
            "ip": self._conexion.ip_servidor,
        })

    def _cerrar(self):
        if self._conexion is not None:
            try:
                self._conexion.cerrar(despedirse=False)
            except OSError:
                pass

            self._conexion = None

    def _alerta_en_vivo(self, campos):
        self._emitir("alerta_nueva", campos)

    def _atender_peticiones(self):
        """Ejecuta los comandos que pidio la interfaz."""
        while True:
            try:
                peticion = self.peticiones.get_nowait()
            except queue.Empty:
                return

            try:
                cabecera, _ = self._conexion.comando(
                    *peticion, al_recibir_alerta=self._alerta_en_vivo)

                self._emitir("aviso", "Umbral aplicado: " + "|".join(cabecera[2:]))

            except tsp.TspError as exc:
                self._emitir("aviso", f"El servidor rechazo la peticion: {exc}")

    def _consultar(self):
        """Una ronda completa de consultas al servidor."""
        _, nodos = self._conexion.comando(
            "LIST_NODES", al_recibir_alerta=self._alerta_en_vivo)

        self._emitir("nodos", nodos)

        _, sistema = self._conexion.comando(
            "GET_SYSTEM", al_recibir_alerta=self._alerta_en_vivo)

        self._emitir("sistema", sistema)

        _, alertas = self._conexion.comando(
            "GET_ALERTS", "25", al_recibir_alerta=self._alerta_en_vivo)

        self._emitir("alertas", alertas)

        if self.nodo_seleccionado:
            try:
                cabecera, variables = self._conexion.comando(
                    "GET_STATUS",
                    self.nodo_seleccionado,
                    al_recibir_alerta=self._alerta_en_vivo,
                )

                self._emitir("detalle", (cabecera, variables))

            except tsp.TspError as exc:
                # 404 o 405 son respuestas normales, no un fallo de red
                self._emitir("detalle_vacio", str(exc))


# ----------------------------------------------------------------------
# Interfaz grafica
# ----------------------------------------------------------------------


def lanzar_interfaz(args):
    import tkinter as tk
    from tkinter import ttk

    trabajador = TrabajadorTelemetria(args.host, args.port, args.name, args.interval)

    raiz = tk.Tk()
    raiz.title(f"Panel de telemetria - {args.host}")
    raiz.geometry("1060x680")
    raiz.minsize(880, 560)

    def hora(ts):
        try:
            return time.strftime("%H:%M:%S", time.localtime(int(ts)))
        except (ValueError, TypeError, OSError):
            return "--:--:--"

    # -- barra de estado superior --------------------------------------

    cabecera = ttk.Frame(raiz, padding=(10, 8))
    cabecera.pack(fill="x")

    estado_var = tk.StringVar(value="Conectando...")

    ttk.Label(cabecera, textvariable=estado_var, font=("TkDefaultFont", 10, "bold")).pack(side="left")

    resumen_var = tk.StringVar(value="")

    ttk.Label(cabecera, textvariable=resumen_var).pack(side="right")

    # -- cuerpo: nodos a la izquierda, detalle a la derecha -------------

    cuerpo = ttk.Panedwindow(raiz, orient="horizontal")
    cuerpo.pack(fill="both", expand=True, padx=10, pady=(0, 8))

    marco_nodos = ttk.Labelframe(cuerpo, text="Nodos registrados", padding=6)
    marco_detalle = ttk.Labelframe(cuerpo, text="Ultimas mediciones", padding=6)

    cuerpo.add(marco_nodos, weight=3)
    cuerpo.add(marco_detalle, weight=2)

    columnas_nodos = ("nodo", "estado", "tipo", "ubicacion", "ultima", "msgs", "perdidos")

    tabla_nodos = ttk.Treeview(
        marco_nodos, columns=columnas_nodos, show="headings", height=12)

    anchos = {
        "nodo": 90, "estado": 75, "tipo": 145, "ubicacion": 130,
        "ultima": 70, "msgs": 60, "perdidos": 75,
    }

    for col in columnas_nodos:
        tabla_nodos.heading(col, text=col.upper())
        tabla_nodos.column(col, width=anchos[col], anchor="w")

    tabla_nodos.pack(fill="both", expand=True, side="left")

    barra_nodos = ttk.Scrollbar(marco_nodos, orient="vertical", command=tabla_nodos.yview)
    barra_nodos.pack(side="right", fill="y")

    tabla_nodos.configure(yscrollcommand=barra_nodos.set)

    tabla_nodos.tag_configure("offline", foreground="#b00020")

    columnas_detalle = ("variable", "valor", "unidad", "hora")

    tabla_detalle = ttk.Treeview(
        marco_detalle, columns=columnas_detalle, show="headings", height=12)

    for col in columnas_detalle:
        tabla_detalle.heading(col, text=col.upper())
        tabla_detalle.column(col, width=95, anchor="w")

    tabla_detalle.pack(fill="both", expand=True)

    # -- alertas --------------------------------------------------------

    marco_alertas = ttk.Labelframe(raiz, text="Alertas", padding=6)
    marco_alertas.pack(fill="both", expand=True, padx=10, pady=(0, 8))

    columnas_alertas = ("hora", "nodo", "tipo", "valor", "severidad")

    tabla_alertas = ttk.Treeview(
        marco_alertas, columns=columnas_alertas, show="headings", height=8)

    for col in columnas_alertas:
        tabla_alertas.heading(col, text=col.upper())
        tabla_alertas.column(col, width=110, anchor="w")

    tabla_alertas.pack(fill="both", expand=True, side="left")

    barra_alertas = ttk.Scrollbar(
        marco_alertas, orient="vertical", command=tabla_alertas.yview)
    barra_alertas.pack(side="right", fill="y")

    tabla_alertas.configure(yscrollcommand=barra_alertas.set)

    tabla_alertas.tag_configure("critical", foreground="#b00020")
    tabla_alertas.tag_configure("warn", foreground="#a86400")
    tabla_alertas.tag_configure("info", foreground="#00639c")

    # -- barra inferior: cambio de umbral en vivo -----------------------

    pie = ttk.Frame(raiz, padding=(10, 0, 10, 10))
    pie.pack(fill="x")

    ttk.Label(pie, text="Umbral  nodo:").pack(side="left")

    entrada_nodo = ttk.Entry(pie, width=10)
    entrada_nodo.insert(0, "*")
    entrada_nodo.pack(side="left", padx=(4, 10))

    ttk.Label(pie, text="variable:").pack(side="left")

    entrada_var = ttk.Entry(pie, width=8)
    entrada_var.insert(0, "TEMP")
    entrada_var.pack(side="left", padx=(4, 10))

    ttk.Label(pie, text="min:").pack(side="left")

    entrada_min = ttk.Entry(pie, width=8)
    entrada_min.insert(0, "-10")
    entrada_min.pack(side="left", padx=(4, 10))

    ttk.Label(pie, text="max:").pack(side="left")

    entrada_max = ttk.Entry(pie, width=8)
    entrada_max.insert(0, "40")
    entrada_max.pack(side="left", padx=(4, 10))

    aviso_var = tk.StringVar(value="")

    def aplicar_umbral():
        trabajador.pedir_umbral(
            entrada_nodo.get().strip() or "*",
            entrada_var.get().strip().upper() or "TEMP",
            entrada_min.get().strip(),
            entrada_max.get().strip(),
        )

        aviso_var.set("Enviando SET_THRESHOLD...")

    ttk.Button(pie, text="Aplicar umbral", command=aplicar_umbral).pack(side="left")

    ttk.Label(pie, textvariable=aviso_var).pack(side="left", padx=12)

    # -- seleccion de un nodo -------------------------------------------

    def al_seleccionar(_evento=None):
        seleccion = tabla_nodos.selection()

        if seleccion:
            trabajador.seleccionar_nodo(tabla_nodos.item(seleccion[0], "values")[0])

    tabla_nodos.bind("<<TreeviewSelect>>", al_seleccionar)

    # -- volcado de los eventos del trabajador a la ventana -------------

    def pintar_nodos(nodos):
        seleccion = tabla_nodos.selection()
        seleccionado = tabla_nodos.item(seleccion[0], "values")[0] if seleccion else None

        tabla_nodos.delete(*tabla_nodos.get_children())

        for r in nodos:
            # NODE|<ID>|<ESTADO>|<TIPO>|<UBICACION>|<HACE_SEG>|<MSGS>|<PERDIDOS>
            if len(r) < 8:
                continue

            etiquetas = () if r[2] == "ONLINE" else ("offline",)

            item = tabla_nodos.insert(
                "", "end",
                values=(r[1], r[2], r[3], r[4], f"{r[5]}s", r[6], r[7]),
                tags=etiquetas,
            )

            if r[1] == seleccionado:
                tabla_nodos.selection_set(item)

    def pintar_alertas(alertas):
        tabla_alertas.delete(*tabla_alertas.get_children())

        for r in alertas:
            # ALERT|<NODO>|<TIPO>|<VALOR>|<TS>|<SEVERIDAD>
            if len(r) < 6:
                continue

            tabla_alertas.insert(
                "", "end",
                values=(hora(r[4]), r[1], r[2], r[3], r[5]),
                tags=(r[5].lower(),),
            )

    def pintar_sistema(stats):
        datos = {r[1]: r[2] for r in stats if len(r) >= 3}

        resumen_var.set(
            f"activos {datos.get('NODOS_ACTIVOS', '?')}"
            f"/{datos.get('NODOS_REGISTRADOS', '?')}   "
            f"telemetria {datos.get('TELEMETRIA_RECIBIDA', '?')}   "
            f"perdidos {datos.get('TELEMETRIA_PERDIDA_EST', '?')}   "
            f"alertas {datos.get('ALERTAS_GENERADAS', '?')}   "
            f"operadores {datos.get('OPERADORES_CONECTADOS', '?')}   "
            f"uptime {datos.get('UPTIME_SEG', '?')}s"
        )

    def pintar_detalle(paquete):
        cabecera, variables = paquete

        marco_detalle.configure(
            text=f"Ultimas mediciones - {cabecera[2]} ({cabecera[3]})"
        )

        tabla_detalle.delete(*tabla_detalle.get_children())

        for r in variables:
            if len(r) >= 5:
                tabla_detalle.insert("", "end", values=(r[1], r[2], r[3], hora(r[4])))

    def procesar_cola():
        try:
            while True:
                tipo, datos = trabajador.eventos.get_nowait()

                if tipo == "conectado":
                    estado_var.set(
                        f"Conectado a {datos['servidor']} ({datos['version']}) "
                        f"en {datos['ip']}:{args.port}"
                    )

                elif tipo == "desconectado":
                    estado_var.set(f"Sin conexion: {datos} - reintentando...")

                elif tipo == "nodos":
                    pintar_nodos(datos)

                elif tipo == "sistema":
                    pintar_sistema(datos)

                elif tipo == "alertas":
                    pintar_alertas(datos)

                elif tipo == "detalle":
                    pintar_detalle(datos)

                elif tipo == "detalle_vacio":
                    tabla_detalle.delete(*tabla_detalle.get_children())
                    marco_detalle.configure(text=f"Ultimas mediciones - {datos}")

                elif tipo == "alerta_nueva":
                    aviso_var.set(
                        f"ALERTA {datos[1]} {datos[2]} = {datos[3]} [{datos[5]}]"
                    )

                elif tipo == "aviso":
                    aviso_var.set(datos)

        except queue.Empty:
            pass

        raiz.after(200, procesar_cola)

    def al_cerrar():
        trabajador.detener()
        raiz.destroy()

    raiz.protocol("WM_DELETE_WINDOW", al_cerrar)

    trabajador.iniciar()

    raiz.after(200, procesar_cola)
    raiz.mainloop()


# ----------------------------------------------------------------------


def construir_parser():
    parser = argparse.ArgumentParser(
        description="Cliente operador TSP/1.0 con interfaz grafica")

    parser.add_argument(
        "--host",
        default=os.environ.get("TSP_SERVER_HOST", "localhost"),
        help="nombre DNS del servidor (o variable TSP_SERVER_HOST)",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("TSP_TCP_PORT", tsp.PUERTO_TCP_DEFECTO)),
    )

    parser.add_argument(
        "--name",
        default=os.environ.get("TSP_OPERATOR_NAME", "operador-gui"),
    )

    parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="segundos entre refrescos de la pantalla",
    )

    return parser


def main():
    args = construir_parser().parse_args()

    try:
        lanzar_interfaz(args)

    except ImportError:
        print(
            "Esta interfaz necesita tkinter.\n"
            "  Debian/Ubuntu : sudo apt install python3-tk\n"
            "  Windows/macOS : viene incluido con Python\n"
            "Mientras tanto puedes usar el cliente de texto: "
            "python3 operator_cli.py",
            file=sys.stderr,
        )

        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
