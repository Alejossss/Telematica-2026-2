"""Biblioteca TSP/1.0 (Telemetry Simple Protocol) para los clientes Python.

Implementa el lado cliente del protocolo definido en docs/PROTOCOLO.md:
codificacion y decodificacion de mensajes, resolucion del servidor por DNS
y lectura de respuestas simples y multiples sobre TCP.

La usan tanto los nodos de telemetria (punto 3.1) como el cliente
operador (punto 3.3).
"""

import socket

# ----------------------------------------------------------------------
# Constantes del protocolo
# ----------------------------------------------------------------------

VERSION = "TSP/1.0"

SEPARADOR = "|"
TERMINADOR = "\n"

MAX_MENSAJE = 1024

PUERTO_TCP_DEFECTO = 6000
PUERTO_UDP_DEFECTO = 5000

# Comandos cuya respuesta es multiple: cabecera + registros + END
# (seccion 3.2 de docs/PROTOCOLO.md)
RESPUESTAS_MULTIPLES = {
    "LIST_NODES",
    "GET_STATUS",
    "GET_LAST",
    "GET_ALERTS",
    "GET_SYSTEM",
}

# Codigos de error de la seccion 5 de docs/PROTOCOLO.md
ERR_BAD_REQUEST = 400
ERR_UNKNOWN_COMMAND = 401
ERR_MISSING_PARAM = 402
ERR_INVALID_PARAM = 403
ERR_NODE_NOT_FOUND = 404
ERR_NO_DATA = 405
ERR_NOT_REGISTERED = 406
ERR_LIMIT_REACHED = 409
ERR_MESSAGE_TOO_LONG = 413
ERR_INTERNAL = 500
ERR_SERVER_FULL = 503


class TspError(Exception):
    """Un mensaje ERR|<codigo>|<simbolo>|<descripcion> devuelto por el servidor."""

    def __init__(self, codigo, simbolo, descripcion):
        super().__init__(f"{codigo} {simbolo}: {descripcion}")

        self.codigo = codigo
        self.simbolo = simbolo
        self.descripcion = descripcion


class TspProtocolError(Exception):
    """El servidor respondio algo que no encaja con TSP/1.0."""


# ----------------------------------------------------------------------
# Codificacion y decodificacion
# ----------------------------------------------------------------------


def codificar(*campos):
    """Construye un mensaje TSP a partir de sus campos.

    Valida la regla R4 (ningun campo puede contener el separador ni un
    salto de linea) y la R5 (tamano maximo del mensaje).
    """
    partes = []

    for campo in campos:
        texto = str(campo)

        if SEPARADOR in texto or "\n" in texto or "\r" in texto:
            raise ValueError(f"Campo invalido para TSP: {texto!r}")

        partes.append(texto)

    mensaje = SEPARADOR.join(partes) + TERMINADOR

    if len(mensaje.encode("utf-8")) > MAX_MENSAJE:
        raise ValueError("El mensaje supera los 1024 bytes permitidos")

    return mensaje.encode("utf-8")


def decodificar(linea):
    """Separa una linea TSP en su lista de campos."""
    if isinstance(linea, bytes):
        linea = linea.decode("utf-8", errors="replace")

    return linea.rstrip("\r\n").split(SEPARADOR)


def formatear_numero(valor):
    """Formatea un valor con punto decimal, como exige la regla R8."""
    return f"{float(valor):.2f}"


# ----------------------------------------------------------------------
# Resolucion por DNS (punto 3.1 y punto 8)
# ----------------------------------------------------------------------


def resolver(host, puerto, tipo_socket=socket.SOCK_STREAM, verbose=True):
    """Resuelve el servidor por nombre y devuelve la lista de direcciones.

    El codigo nunca lleva una IP publica fija: el cliente parte siempre de
    un nombre DNS. Se imprime el resultado porque es la evidencia de que
    la resolucion ocurrio de verdad.
    """
    infos = socket.getaddrinfo(host, puerto, socket.AF_INET, tipo_socket)

    if verbose:
        direcciones = sorted({info[4][0] for info in infos})
        protocolo = "TCP" if tipo_socket == socket.SOCK_STREAM else "UDP"

        print(f"[DNS] {host} ({protocolo}/{puerto}) -> {', '.join(direcciones)}")

    return infos


# ----------------------------------------------------------------------
# Lectura de respuestas
# ----------------------------------------------------------------------


def leer_respuesta(siguiente_linea, al_recibir_alerta=None):
    """Lee una respuesta TSP completa.

    ``siguiente_linea`` es cualquier funcion que devuelva la siguiente linea
    del servidor: puede leer del socket directamente o de una cola, que es
    lo que hace el operador cuando tiene un hilo lector aparte.

    Devuelve la tupla ``(cabecera, registros)``, ambas listas de campos.

    Un ALERT puede llegar en cualquier momento, incluso entre el comando y
    su respuesta (seccion 4.10): se encamina al callback y se sigue leyendo.
    """
    while True:
        campos = decodificar(siguiente_linea())

        if not campos or not campos[0]:
            raise TspProtocolError("Linea vacia recibida del servidor")

        tipo = campos[0]

        if tipo == "ALERT":
            if al_recibir_alerta is not None:
                al_recibir_alerta(campos)
            continue

        if tipo == "ERR":
            codigo = int(campos[1]) if len(campos) > 1 and campos[1].isdigit() else 500
            simbolo = campos[2] if len(campos) > 2 else "INTERNAL_ERROR"
            descripcion = campos[3] if len(campos) > 3 else ""

            raise TspError(codigo, simbolo, descripcion)

        if tipo != "OK":
            # Respuestas simples que no empiezan por OK: PONG, ACK
            return campos, []

        comando = campos[1] if len(campos) > 1 else ""

        if comando not in RESPUESTAS_MULTIPLES:
            return campos, []

        # Respuesta multiple: registros hasta el centinela END
        registros = []

        while True:
            fila = decodificar(siguiente_linea())

            if not fila or not fila[0]:
                raise TspProtocolError("Linea vacia dentro de una respuesta multiple")

            if fila[0] == "ALERT":
                if al_recibir_alerta is not None:
                    al_recibir_alerta(fila)
                continue

            if fila[0] == "END":
                return campos, registros

            if fila[0] == "ERR":
                codigo = int(fila[1]) if len(fila) > 1 and fila[1].isdigit() else 500
                raise TspError(codigo, fila[2] if len(fila) > 2 else "", "")

            registros.append(fila)


# ----------------------------------------------------------------------
# Conexion TCP
# ----------------------------------------------------------------------


class TspConexion:
    """Conexion TCP con el servidor, con separacion de mensajes por linea.

    TCP entrega un flujo de bytes sin fronteras de mensaje: un recv() puede
    devolver media linea o varias juntas, asi que se acumula en un buffer
    y se extraen las lineas completas.
    """

    def __init__(self, host, puerto=PUERTO_TCP_DEFECTO, timeout=10.0, verbose=True):
        self.host = host
        self.puerto = puerto
        self.timeout = timeout
        self.verbose = verbose

        self.sock = None
        self._buffer = b""
        self.ip_servidor = None

    # -- ciclo de vida -------------------------------------------------

    def conectar(self):
        """Resuelve el nombre y abre el socket TCP.

        Se prueban todas las direcciones devueltas por DNS antes de darse
        por vencido.
        """
        infos = resolver(self.host, self.puerto, socket.SOCK_STREAM, self.verbose)

        ultimo_error = None

        for familia, tipo, proto, _, direccion in infos:
            try:
                sock = socket.socket(familia, tipo, proto)
                sock.settimeout(self.timeout)
                sock.connect(direccion)

                self.sock = sock
                self.ip_servidor = direccion[0]
                self._buffer = b""

                if self.verbose:
                    print(f"[TCP] Conectado a {direccion[0]}:{direccion[1]}")

                return

            except OSError as exc:
                ultimo_error = exc

                try:
                    sock.close()
                except OSError:
                    pass

        raise ConnectionError(
            f"No fue posible conectar con {self.host}:{self.puerto}: {ultimo_error}"
        )

    def cerrar(self, despedirse=True):
        """Cierra la sesion, enviando BYE si el socket sigue vivo."""
        if self.sock is None:
            return

        if despedirse:
            try:
                self.enviar("BYE")
                self.leer_linea()
            except (OSError, TspError, TspProtocolError):
                pass

        try:
            self.sock.close()
        except OSError:
            pass

        self.sock = None

    # -- envio y recepcion ---------------------------------------------

    def enviar(self, *campos):
        """Envia un mensaje TSP completo."""
        if self.sock is None:
            raise ConnectionError("La conexion no esta abierta")

        self.sock.sendall(codificar(*campos))

    def leer_linea(self):
        """Devuelve la siguiente linea completa recibida del servidor."""
        if self.sock is None:
            raise ConnectionError("La conexion no esta abierta")

        while b"\n" not in self._buffer:
            trozo = self.sock.recv(4096)

            if not trozo:
                raise ConnectionError("El servidor cerro la conexion")

            self._buffer += trozo

        linea, _, resto = self._buffer.partition(b"\n")

        self._buffer = resto

        return linea.decode("utf-8", errors="replace")

    def comando(self, *campos, al_recibir_alerta=None):
        """Envia un comando y devuelve ``(cabecera, registros)``."""
        self.enviar(*campos)

        return leer_respuesta(self.leer_linea, al_recibir_alerta)

    # -- uso con "with" -------------------------------------------------

    def __enter__(self):
        if self.sock is None:
            self.conectar()

        return self

    def __exit__(self, exc_type, exc, tb):
        self.cerrar(despedirse=exc_type is None)

        return False
