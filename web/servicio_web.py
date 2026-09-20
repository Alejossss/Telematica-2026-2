"""Servicio_Web (Punto 7): interfaz HTTP básica para el sistema de telemetría.

Este proceso Python expone una página HTML que muestra el estado del
Servidor_Central, los nodos registrados/activos, las últimas mediciones y las
alertas recientes. Actúa como un cliente operador TSP más: reutiliza la
Biblioteca_TSP ``clients/tsp.py`` para toda la comunicación y **no reimplementa
el protocolo** (Req. 9.2).

Usa únicamente la biblioteca estándar de Python (Req. 9.1) y vive en la carpeta
``web/`` (Req. 9.3). Hypothesis es solo una dependencia de desarrollo para las
pruebas basadas en propiedades; el código de producción no la usa.

Este archivo contiene por ahora el andamiaje (Tarea 1): la inserción en
``sys.path`` para importar ``tsp``, la excepción de configuración y los
esqueletos de las funciones y clases que se implementarán en tareas posteriores.
"""

import html
import os
import socket
import sys
import urllib.parse
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional

# ----------------------------------------------------------------------
# Estrategia de importación de la Biblioteca_TSP (Req. 9.2)
# ----------------------------------------------------------------------
#
# ``web/`` y ``clients/`` son carpetas hermanas, así que ``import tsp`` no
# funciona directamente. Se añade ``clients/`` al sys.path de forma relativa al
# propio archivo (no al directorio de trabajo) para que funcione igual
# ejecutándose a mano o dentro de un contenedor. La inserción va ANTES de
# ``import tsp``.
_DIR_CLIENTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "clients")
sys.path.insert(0, os.path.abspath(_DIR_CLIENTS))

import tsp  # noqa: E402  (import tras ajustar sys.path)


# ----------------------------------------------------------------------
# Excepciones
# ----------------------------------------------------------------------


class ConfigError(Exception):
    """Error de configuración al arrancar (p. ej. puerto inválido).

    ``main`` la captura, imprime el mensaje en stderr y aborta el arranque con
    un código de salida distinto de cero (Req. 2.5, 2.8).
    """


# ----------------------------------------------------------------------
# Modelo de datos (Tarea 3)
# ----------------------------------------------------------------------
#
# Se usan ``dataclasses`` de la biblioteca estándar. Todos los campos textuales
# se guardan como ``str`` crudo tal como llega del Servidor_Central; la
# conversión a número solo se hace en los contadores derivados de nodos.


@dataclass(frozen=True)
class EstadoSistema:
    """Los 9 indicadores STAT de ``GET_SYSTEM`` (sección 4.8 del protocolo).

    Claves esperadas: ``UPTIME_SEG``, ``NODOS_REGISTRADOS``, ``NODOS_ACTIVOS``,
    ``OPERADORES_CONECTADOS``, ``TELEMETRIA_RECIBIDA``, ``TELEMETRIA_RECHAZADA``,
    ``TELEMETRIA_PERDIDA_EST``, ``COMANDOS_TCP`` y ``ALERTAS_GENERADAS``
    (Req. 3.2).
    """

    valores: Dict[str, str]          # clave STAT -> valor crudo


@dataclass(frozen=True)
class NodoInfo:
    """Registro ``NODE`` de ``LIST_NODES`` (sección 4.4 del protocolo)."""

    id: str
    estado: str          # ONLINE | OFFLINE
    tipo: str
    ubicacion: str
    hace_seg: str
    msgs: str
    perdidos: str


@dataclass(frozen=True)
class Medicion:
    """Registro ``MEAS`` de ``GET_LAST`` (sección 4.6 del protocolo)."""

    node_id: str
    variable: str
    valor: str
    unidad: str
    timestamp: str


@dataclass(frozen=True)
class Alerta:
    """Registro ``EVENT`` de ``GET_ALERTS`` (sección 4.7 del protocolo)."""

    node_id: str
    tipo_alerta: str
    valor: str
    timestamp: str
    severidad: str


@dataclass(frozen=True)
class SeccionError:
    """Error TSP de una sección concreta (Req. 7.2)."""

    codigo: int
    descripcion: str


# Estado del nodo que cuenta como "activo" (Req. 4.4). La comparación es
# insensible a mayúsculas según la regla R7 del protocolo.
_ESTADO_ACTIVO = "ONLINE"


def _contar_activos(nodos):
    """Cuenta los nodos cuyo ``estado`` es ONLINE (insensible a mayúsculas).

    Función auxiliar pura usada para derivar ``nodos_activos`` garantizando la
    invariante ``0 <= nodos_activos <= len(nodos)`` (Req. 4.4).
    """
    return sum(1 for n in nodos if n.estado.upper() == _ESTADO_ACTIVO)


@dataclass(frozen=True)
class PanelDatos:
    """Resultado completo de una petición.

    En Estado_Degradado ``disponible`` es ``False`` y ``mensaje_degradado``
    lleva el texto del banner de indisponibilidad (Req. 1.4, 7.1). Cada sección
    puede llevar su propio ``SeccionError`` cuando el comando correspondiente
    respondió con un ``TspError`` (Req. 7.2).

    Los contadores ``nodos_registrados`` y ``nodos_activos`` son campos
    derivados de ``nodos``. Como la dataclass es ``frozen``, no se pueden
    calcular en ``__post_init__`` sin ``object.__setattr__``; en su lugar se
    ofrece la fábrica :meth:`crear`, que computa ambos contadores a partir de la
    lista de nodos y garantiza ``nodos_registrados == len(nodos)`` y
    ``0 <= nodos_activos <= nodos_registrados`` (Req. 4.3, 4.4). Construir
    ``PanelDatos`` directamente sigue siendo posible, pero es responsabilidad de
    quien llama pasar contadores coherentes; usar :meth:`crear` es la vía
    recomendada.
    """

    disponible: bool                          # False -> Servidor_Central inalcanzable
    mensaje_degradado: Optional[str]          # texto del banner cuando disponible=False
    server_id: Optional[str]                  # de OK|HELLO|<SERVER_ID>|...
    sistema: Optional[EstadoSistema]
    error_sistema: Optional[SeccionError]
    nodos: List[NodoInfo]
    error_nodos: Optional[SeccionError]
    nodos_registrados: int                    # derivado: len(nodos)
    nodos_activos: int                        # derivado: nodos con estado == ONLINE
    mediciones: List[Medicion]
    error_mediciones: Optional[SeccionError]
    alertas: List[Alerta]
    error_alertas: Optional[SeccionError]

    @classmethod
    def crear(
        cls,
        *,
        disponible=True,
        mensaje_degradado=None,
        server_id=None,
        sistema=None,
        error_sistema=None,
        nodos=None,
        error_nodos=None,
        mediciones=None,
        error_mediciones=None,
        alertas=None,
        error_alertas=None,
    ):
        """Construye un ``PanelDatos`` derivando los contadores de nodos.

        ``nodos_registrados`` se fija a ``len(nodos)`` y ``nodos_activos`` al
        número de nodos ONLINE (insensible a mayúsculas), garantizando la
        invariante ``0 <= nodos_activos <= nodos_registrados`` (Req. 4.3, 4.4).
        El resto de campos se pasan tal cual; las listas ``None`` se normalizan
        a listas vacías para no compartir estado mutable por defecto.
        """
        nodos_lista = list(nodos) if nodos is not None else []
        mediciones_lista = list(mediciones) if mediciones is not None else []
        alertas_lista = list(alertas) if alertas is not None else []
        return cls(
            disponible=disponible,
            mensaje_degradado=mensaje_degradado,
            server_id=server_id,
            sistema=sistema,
            error_sistema=error_sistema,
            nodos=nodos_lista,
            error_nodos=error_nodos,
            nodos_registrados=len(nodos_lista),
            nodos_activos=_contar_activos(nodos_lista),
            mediciones=mediciones_lista,
            error_mediciones=error_mediciones,
            alertas=alertas_lista,
            error_alertas=error_alertas,
        )

    @classmethod
    def degradado(cls, mensaje):
        """Construye un ``PanelDatos`` en Estado_Degradado (Req. 1.4, 7.1).

        Atajo para el caso en que el Servidor_Central es inalcanzable: no hay
        datos, ``disponible=False`` y ``mensaje_degradado`` lleva el texto de
        indisponibilidad. Los contadores derivados quedan en 0.
        """
        return cls.crear(disponible=False, mensaje_degradado=mensaje)


# ----------------------------------------------------------------------
# Parseo tolerante de registros crudos al modelo (Tarea 4)
# ----------------------------------------------------------------------
#
# ``conexion.comando(...)`` devuelve ``(cabecera, registros)`` donde
# ``registros`` es una ``list[list[str]]``: cada registro ya viene separado por
# ``|`` por ``tsp.decodificar``, así que la posición 0 es el tipo (``STAT``,
# ``NODE``, ``MEAS``, ``EVENT``) y los datos empiezan en la posición 1.
#
# Estas funciones son puras y NO lanzan ante entrada malformada: replican la
# tolerancia de ``clients/operator_cli.py`` (``cmd_system``, ``cmd_nodes``,
# ``cmd_last``, ``cmd_alerts``). Los registros con menos campos de los
# requeridos se descartan; de los más largos solo se leen las posiciones
# conocidas (Req. 3.2, 4.2, 5.2, 6.2).


def parsear_sistema(registros):
    """Convierte los registros ``STAT|CLAVE|VALOR`` en un ``EstadoSistema``.

    Replica ``cmd_system`` de ``operator_cli.py``: descarta los registros con
    ``len(r) < 3`` y lee solo ``r[1]`` (clave) y ``r[2]`` (valor). Las claves
    repetidas conservan el último valor visto. Devuelve siempre un
    ``EstadoSistema`` (con ``valores`` vacío si no hay registros válidos), nunca
    lanza (Req. 3.2).
    """
    valores = {}
    for r in registros:
        if len(r) < 3:
            continue
        valores[r[1]] = r[2]
    return EstadoSistema(valores=valores)


def parsear_nodos(registros):
    """Convierte los registros ``NODE`` en una ``list[NodoInfo]``.

    Layout: ``NODE|ID|ESTADO|TIPO|UBICACION|HACE_SEG|MSGS|PERDIDOS``. Replica
    ``cmd_nodes`` de ``operator_cli.py``: descarta los registros con
    ``len(r) < 8`` y lee solo ``r[1..7]`` (posiciones conocidas), ignorando
    cualquier campo extra de los registros más largos. Nunca lanza (Req. 4.2).
    """
    nodos = []
    for r in registros:
        if len(r) < 8:
            continue
        nodos.append(
            NodoInfo(
                id=r[1],
                estado=r[2],
                tipo=r[3],
                ubicacion=r[4],
                hace_seg=r[5],
                msgs=r[6],
                perdidos=r[7],
            )
        )
    return nodos


def parsear_mediciones(registros):
    """Convierte los registros ``MEAS`` en una ``list[Medicion]``.

    Layout: ``MEAS|NODE_ID|VAR|VALOR|UNIDAD|TIMESTAMP``. Replica ``cmd_last`` de
    ``operator_cli.py``: descarta los registros con ``len(r) < 6`` y lee solo
    ``r[1..5]``, ignorando campos extra. Preserva el orden recibido del servidor
    (Req. 5.2, 5.3). Nunca lanza.
    """
    mediciones = []
    for r in registros:
        if len(r) < 6:
            continue
        mediciones.append(
            Medicion(
                node_id=r[1],
                variable=r[2],
                valor=r[3],
                unidad=r[4],
                timestamp=r[5],
            )
        )
    return mediciones


def parsear_alertas(registros):
    """Convierte los registros ``EVENT`` en una ``list[Alerta]``.

    Layout: ``EVENT|NODE_ID|TIPO_ALERTA|VALOR|TIMESTAMP|SEVERIDAD``. Replica
    ``cmd_alerts`` de ``operator_cli.py``: descarta los registros con
    ``len(r) < 6`` y lee solo ``r[1..5]`` (``r[4]`` es el timestamp y ``r[5]``
    la severidad), ignorando campos extra. Preserva el orden recibido del
    servidor (Req. 6.2, 6.3). Nunca lanza.
    """
    alertas = []
    for r in registros:
        if len(r) < 6:
            continue
        alertas.append(
            Alerta(
                node_id=r[1],
                tipo_alerta=r[2],
                valor=r[3],
                timestamp=r[4],
                severidad=r[5],
            )
        )
    return alertas


# ----------------------------------------------------------------------
# Cargador de configuración (Tarea 2) — esqueletos
# ----------------------------------------------------------------------


_PUERTO_MIN = 1
_PUERTO_MAX = 65535


@dataclass(frozen=True)
class Config:
    """Configuración del Servicio_Web leída del entorno (Req. 2).

    - ``tsp_host``: nombre DNS del Servidor_Central (``TSP_SERVER_HOST``,
      defecto ``localhost``).
    - ``tsp_port``: puerto TCP del Servidor_Central (``TSP_TCP_PORT``, defecto
      6000, rango 1–65535).
    - ``web_port``: puerto HTTP de escucha (``WEB_PORT``, defecto 8080, rango
      1–65535).
    """

    tsp_host: str
    tsp_port: int
    web_port: int


def parsear_puerto(nombre_var, valor, defecto):
    """Devuelve un puerto válido o lanza ``ConfigError``.

    Función total y pura sobre ``(nombre_var, valor, defecto)``:
    ``None`` -> ``defecto``; entero en 1–65535 -> ese entero; en otro caso
    lanza ``ConfigError`` con un mensaje que incluye el nombre de la variable y
    el rango permitido (Req. 2.3, 2.5, 2.6, 2.8).

    Nunca devuelve un valor fuera del rango 1–65535 y nunca propaga una
    excepción distinta de ``ConfigError``.
    """
    if valor is None:
        return defecto

    def _invalido():
        return ConfigError(
            "{nombre} debe ser un entero en el rango {lo}-{hi} (recibido: {valor!r})".format(
                nombre=nombre_var,
                lo=_PUERTO_MIN,
                hi=_PUERTO_MAX,
                valor=valor,
            )
        )

    # ``int()`` solo debe aceptar enteros en base 10 escritos de forma canónica;
    # rechazamos flotantes, notación con prefijos o texto no numérico. Se acota
    # con ``strip`` para tolerar espacios en los valores de entorno.
    texto = valor.strip() if isinstance(valor, str) else valor
    try:
        numero = int(texto)
    except (TypeError, ValueError):
        raise _invalido()

    if numero < _PUERTO_MIN or numero > _PUERTO_MAX:
        raise _invalido()

    return numero


def cargar_config(entorno):
    """Construye la configuración desde un mapping de entorno.

    Lee ``TSP_SERVER_HOST`` (defecto ``localhost``), ``TSP_TCP_PORT`` (defecto
    6000) y ``WEB_PORT`` (defecto 8080) (Req. 2.1, 2.2, 2.4, 2.7). Los puertos
    se validan con ``parsear_puerto``, que lanza ``ConfigError`` ante un valor
    fuera de rango o no entero (Req. 2.5, 2.8).
    """
    tsp_host = entorno.get("TSP_SERVER_HOST", "localhost")
    tsp_port = parsear_puerto("TSP_TCP_PORT", entorno.get("TSP_TCP_PORT"), 6000)
    web_port = parsear_puerto("WEB_PORT", entorno.get("WEB_PORT"), 8080)
    return Config(tsp_host=tsp_host, tsp_port=tsp_port, web_port=web_port)


# ----------------------------------------------------------------------
# Capa de obtención de datos TSP (Tarea 6) — esqueleto
# ----------------------------------------------------------------------


def _server_id_de_cabecera(cabecera):
    """Extrae el ``SERVER_ID`` de la cabecera de ``HELLO``.

    La respuesta a ``HELLO`` es ``OK|HELLO|<SERVER_ID>|TSP/1.0|<UPTIME_SEG>``
    (sección 4.3 del protocolo), así que el identificador está en la posición 2.
    Devuelve ``None`` si la cabecera es más corta de lo esperado.
    """
    if cabecera is not None and len(cabecera) >= 3:
        return cabecera[2]
    return None


# Mensaje del banner de Estado_Degradado cuando el Servidor_Central es
# inalcanzable al conectar (Req. 1.4, 7.1).
_MSG_DEGRADADO = (
    "El Servidor_Central no está disponible en este momento. "
    "La interfaz sigue activa; vuelve a intentarlo más tarde."
)

# Código sintético para las secciones marcadas por un fallo de red o de
# protocolo a mitad de sesión (Req. 7.3). No proviene de un ``ERR`` del
# servidor: usa 500 (error interno) para reflejar que la respuesta no pudo
# obtenerse de forma fiable.
_COD_SECCION_FALLIDA = 500

# Errores que, al conectar, significan que el Servidor_Central es inalcanzable
# y obligan a devolver un panel en Estado_Degradado (Req. 7.1). ``socket.gaierror``
# (DNS) y ``socket.timeout`` son subclases de ``OSError``, pero se listan de
# forma explícita para dejar clara la intención.
_ERRORES_CONEXION = (
    ConnectionError,
    socket.gaierror,
    socket.timeout,
    TimeoutError,
    OSError,
)

# Errores de red o de protocolo que, a mitad de sesión, invalidan el socket:
# la sección en curso y todas las restantes quedan marcadas y no se emiten más
# comandos (Req. 7.3).
_ERRORES_SESION = (
    tsp.TspProtocolError,
    ConnectionError,
    socket.timeout,
    TimeoutError,
    OSError,
)


def obtener_panel(host, puerto, timeout=5.0, n_ultimas=20, n_alertas=20):
    """Abre una conexión TSP, ejecuta los comandos y devuelve un ``PanelDatos``.

    Envía ``HELLO`` y luego ``GET_SYSTEM``, ``LIST_NODES``, ``GET_LAST`` y
    ``GET_ALERTS`` reutilizando ``tsp.TspConexion``; parsea cada
    ``(cabecera, registros)`` al modelo y cierra con ``BYE``. Nunca propaga
    excepciones de red: traduce los fallos a Estado_Degradado o parcial
    (Req. 3.1, 4.1, 5.1, 6.1, 7.1–7.4, 8.2, 9.2).

    Manejo de errores por capas (tabla "Error Handling" del diseño):

    - Fallo al **conectar** (``ConnectionError``, ``OSError``,
      ``socket.gaierror``, ``socket.timeout``/``TimeoutError``) → panel en
      Estado_Degradado (``disponible=False``) con mensaje de indisponibilidad y
      sin ejecutar ningún comando (Req. 1.4, 7.1).
    - ``tsp.TspError`` en un comando → ``SeccionError(codigo, descripcion)`` solo
      en esa sección; el resto de comandos continúa y ``disponible=True``
      (Req. 7.2). La conexión sigue viva.
    - ``tsp.TspProtocolError`` o error de red a mitad de sesión → la sección en
      curso y todas las no ejecutadas quedan marcadas como fallidas; no se emiten
      más comandos, ``disponible=True`` (respondió, aunque parcial) y nunca se
      propaga la excepción (Req. 7.3).
    """
    # Cada petición usa su propia conexión TSP (Req. 8.2), con timeout de 5 s
    # (Req. 7.4) y sin trazas por consola. La resolución DNS del host ocurre
    # dentro de ``conectar()`` vía ``tsp.resolver`` (Req. 2.9).
    conexion = tsp.TspConexion(host, puerto, timeout=timeout, verbose=False)

    # --- Paso de conexión, aislado del resto (Req. 1.4, 7.1) ---
    # Si falla aquí no hay socket vivo, así que se devuelve Estado_Degradado sin
    # ejecutar comandos. ``cerrar()`` sobre una conexión sin socket es un no-op
    # (``sock`` es ``None``), de modo que no hace falta ``finally`` en este tramo.
    try:
        conexion.conectar()
    except _ERRORES_CONEXION:
        return PanelDatos.degradado(_MSG_DEGRADADO)

    # A partir de aquí hay socket abierto: se cierra siempre con ``BYE`` en el
    # ``finally`` (Req. 8.2), incluso ante error a mitad de sesión.
    try:
        # HELLO como primer mensaje (sección 4.3). Un fallo de red/protocolo aquí
        # implica que ninguna sección podrá obtenerse: se degradan todas.
        server_id = None
        try:
            cabecera_hello, _ = conexion.comando("HELLO", "servicio-web")
            server_id = _server_id_de_cabecera(cabecera_hello)
        except tsp.TspError:
            # HELLO no tiene sección propia; un TspError aquí no debe tumbar la
            # sesión, así que se ignora el id y se siguen intentando los datos.
            server_id = None
        except _ERRORES_SESION:
            # Socket roto antes de pedir datos: todas las secciones fallan.
            fallo = SeccionError(_COD_SECCION_FALLIDA, "El Servidor_Central cortó la sesión")
            return PanelDatos.crear(
                disponible=True,
                server_id=None,
                sistema=None,
                error_sistema=fallo,
                nodos=[],
                error_nodos=fallo,
                mediciones=[],
                error_mediciones=fallo,
                alertas=[],
                error_alertas=fallo,
            )

        # Los cuatro comandos de datos, cada uno con su propio manejo de errores.
        # ``comando`` devuelve ``(cabecera, registros)`` tal y como los consume
        # ``operator_cli.py``; se parsea con las funciones de la Tarea 4, que
        # preservan el orden recibido.
        #
        # ``_ejecutar_comandos`` recorre los comandos en orden y, ante un error de
        # red/protocolo (socket roto), marca el actual y todos los restantes sin
        # emitir más comandos; ante un ``TspError`` marca solo esa sección y sigue.
        return _ejecutar_comandos(conexion, server_id, n_ultimas, n_alertas)
    finally:
        # Siempre se cierra la sesión con ``BYE`` (Req. 8.2), incluso ante error.
        conexion.cerrar()


def _ejecutar_comandos(conexion, server_id, n_ultimas, n_alertas):
    """Ejecuta los cuatro comandos de datos y construye el ``PanelDatos`` parcial.

    Recorre ``GET_SYSTEM``, ``LIST_NODES``, ``GET_LAST`` y ``GET_ALERTS`` en
    orden. Para cada uno:

    - Éxito → guarda los datos parseados en su sección.
    - ``tsp.TspError`` → guarda ``SeccionError(codigo, descripcion)`` solo en esa
      sección y continúa con el resto (Req. 7.2).
    - Error de red/protocolo (socket roto) → marca esa sección y todas las que
      aún no se han ejecutado como fallidas, deja de emitir comandos y devuelve
      el panel parcial (Req. 7.3).

    ``disponible`` siempre es ``True`` aquí: el servidor respondió, aunque el
    resultado sea parcial. Nunca propaga una excepción.
    """
    # Estado acumulado de cada sección: (datos, error). ``datos`` toma su valor
    # por defecto "vacío" cuando la sección no se pudo obtener.
    resultado = {
        "sistema": (None, None),
        "nodos": ([], None),
        "mediciones": ([], None),
        "alertas": ([], None),
    }

    # Orden de ejecución: (clave, comando, argumentos, parser).
    pasos = (
        ("sistema", ("GET_SYSTEM",), parsear_sistema),
        ("nodos", ("LIST_NODES",), parsear_nodos),
        ("mediciones", ("GET_LAST", str(n_ultimas)), parsear_mediciones),
        ("alertas", ("GET_ALERTS", str(n_alertas)), parsear_alertas),
    )

    fallo_sesion = None
    for indice, (clave, comando, parser) in enumerate(pasos):
        if fallo_sesion is not None:
            # Ya hubo un fallo de red/protocolo: no se emiten más comandos; esta
            # sección (y las siguientes) quedan marcadas como fallidas (Req. 7.3).
            resultado[clave] = (resultado[clave][0], fallo_sesion)
            continue

        try:
            _, registros = conexion.comando(*comando)
            resultado[clave] = (parser(registros), None)
        except tsp.TspError as exc:
            # Error TSP por comando: solo esa sección se marca; el resto sigue
            # (Req. 7.2). La conexión sigue viva.
            resultado[clave] = (resultado[clave][0], SeccionError(exc.codigo, exc.descripcion))
        except _ERRORES_SESION:
            # Fallo de red/protocolo a mitad de sesión: el socket ya no es fiable.
            # Se marca esta sección y se degradarán las restantes (Req. 7.3).
            fallo_sesion = SeccionError(
                _COD_SECCION_FALLIDA, "El Servidor_Central cortó la sesión"
            )
            resultado[clave] = (resultado[clave][0], fallo_sesion)

    return PanelDatos.crear(
        disponible=True,
        server_id=server_id,
        sistema=resultado["sistema"][0],
        error_sistema=resultado["sistema"][1],
        nodos=resultado["nodos"][0],
        error_nodos=resultado["nodos"][1],
        mediciones=resultado["mediciones"][0],
        error_mediciones=resultado["mediciones"][1],
        alertas=resultado["alertas"][0],
        error_alertas=resultado["alertas"][1],
    )


# ----------------------------------------------------------------------
# Renderizador HTML (Tarea 7) — esqueleto
# ----------------------------------------------------------------------


# Títulos de las cuatro secciones. Se declaran como constantes porque las
# propiedades de corrección (Property 1) exigen que aparezcan SIEMPRE en el HTML,
# incluso en Estado_Degradado o con errores por sección.
_TITULO_ESTADO = "Estado del servidor"
_TITULO_NODOS = "Nodos"
_TITULO_MEDICIONES = "Últimas mediciones"
_TITULO_ALERTAS = "Alertas recientes"

# Claves STAT esperadas de GET_SYSTEM en el orden en que se presentan (Req. 3.2).
_CLAVES_STAT = (
    "UPTIME_SEG",
    "NODOS_REGISTRADOS",
    "NODOS_ACTIVOS",
    "OPERADORES_CONECTADOS",
    "TELEMETRIA_RECIBIDA",
    "TELEMETRIA_RECHAZADA",
    "TELEMETRIA_PERDIDA_EST",
    "COMANDOS_TCP",
    "ALERTAS_GENERADAS",
)

# Marcador para un valor STAT ausente. Es texto estático (no dato no confiable),
# así que puede insertarse tal cual.
_SIN_VALOR = "—"

# CSS en línea (Req. 1.1: página autocontenida, sin recursos externos ni JS).
_CSS = """
* { box-sizing: border-box; }
body {
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  margin: 0; padding: 1.5rem; background: #0f172a; color: #e2e8f0;
  line-height: 1.5;
}
h1 { font-size: 1.5rem; margin: 0 0 1rem; }
h2 { font-size: 1.15rem; margin: 0 0 0.75rem; color: #93c5fd; }
section {
  background: #1e293b; border: 1px solid #334155; border-radius: 8px;
  padding: 1rem 1.25rem; margin-bottom: 1.25rem;
}
table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
th, td { text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid #334155; }
th { color: #cbd5e1; font-weight: 600; }
tr:last-child td { border-bottom: none; }
.stats { list-style: none; margin: 0; padding: 0;
  display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 0.5rem; }
.stats li { background: #0f172a; border: 1px solid #334155; border-radius: 6px; padding: 0.5rem 0.75rem; }
.stats .clave { display: block; font-size: 0.75rem; color: #94a3b8; text-transform: uppercase; }
.stats .valor { font-size: 1.05rem; font-weight: 600; }
.banner {
  background: #7f1d1d; border: 1px solid #b91c1c; color: #fecaca;
  padding: 1rem 1.25rem; border-radius: 8px; margin-bottom: 1.25rem; font-weight: 600;
}
.error {
  background: #78350f; border: 1px solid #b45309; color: #fed7aa;
  padding: 0.6rem 0.9rem; border-radius: 6px; margin-bottom: 0.75rem;
}
.vacio { color: #94a3b8; font-style: italic; }
.meta { color: #94a3b8; font-size: 0.85rem; margin-bottom: 0.5rem; }
.contadores { margin-bottom: 0.75rem; }
.contadores strong { color: #f8fafc; }
"""


def _esc(valor):
    """Escapa un valor no confiable con ``html.escape(..., quote=True)``.

    Convierte a ``str`` primero (los campos derivados como los contadores son
    ``int``) y escapa ``<``, ``>``, ``&``, ``"`` y ``'``. TODO dato que provenga
    de la red pasa por aquí antes de insertarse en el HTML (Property 2).
    """
    return html.escape(str(valor), quote=True)


def _seccion_error_html(error):
    """Devuelve el bloque HTML del ``SeccionError`` (código + descripción).

    Devuelve cadena vacía si no hay error. El código es un ``int`` y la
    descripción es texto no confiable del servidor: ambos se escapan (Req. 7.2).
    """
    if error is None:
        return ""
    return (
        '<div class="error">Error {codigo}: {descripcion}</div>'.format(
            codigo=_esc(error.codigo),
            descripcion=_esc(error.descripcion),
        )
    )


def _tabla_html(encabezados, filas):
    """Construye una ``<table>`` con los encabezados dados y las filas escapadas.

    ``encabezados`` es una tupla de títulos estáticos (no datos). ``filas`` es
    una lista de tuplas de valores no confiables; cada celda se pasa por
    ``_esc``. El orden de ``filas`` se preserva tal cual (Property 7). Si no hay
    filas, devuelve un mensaje de "sin datos" en lugar de una tabla vacía.
    """
    if not filas:
        return '<p class="vacio">Sin datos.</p>'
    ths = "".join("<th>{0}</th>".format(_esc(h)) for h in encabezados)
    cuerpo = []
    for fila in filas:
        celdas = "".join("<td>{0}</td>".format(_esc(c)) for c in fila)
        cuerpo.append("<tr>{0}</tr>".format(celdas))
    return "<table><thead><tr>{ths}</tr></thead><tbody>{cuerpo}</tbody></table>".format(
        ths=ths, cuerpo="".join(cuerpo)
    )


def _seccion_estado_html(panel):
    """Sección "Estado del servidor": los 9 STAT o su error (Req. 3.2, 7.2)."""
    partes = ["<section>", "<h2>{0}</h2>".format(_esc(_TITULO_ESTADO))]
    if panel.server_id is not None:
        partes.append('<p class="meta">Servidor: {0}</p>'.format(_esc(panel.server_id)))
    partes.append(_seccion_error_html(panel.error_sistema))
    if not panel.disponible:
        partes.append('<p class="vacio">No disponible.</p>')
    else:
        valores = panel.sistema.valores if panel.sistema is not None else {}
        items = []
        for clave in _CLAVES_STAT:
            crudo = valores.get(clave)
            valor = _esc(crudo) if crudo is not None else _SIN_VALOR
            items.append(
                '<li><span class="clave">{clave}</span>'
                '<span class="valor">{valor}</span></li>'.format(
                    clave=_esc(clave), valor=valor
                )
            )
        partes.append('<ul class="stats">{0}</ul>'.format("".join(items)))
    partes.append("</section>")
    return "".join(partes)


def _seccion_nodos_html(panel):
    """Sección "Nodos": registrados/activos + tabla, o su error (Req. 4.2–4.4)."""
    partes = ["<section>", "<h2>{0}</h2>".format(_esc(_TITULO_NODOS))]
    partes.append(_seccion_error_html(panel.error_nodos))
    if not panel.disponible:
        partes.append('<p class="vacio">No disponible.</p>')
    else:
        partes.append(
            '<p class="contadores">Registrados: <strong>{reg}</strong> · '
            'Activos: <strong>{act}</strong></p>'.format(
                reg=_esc(panel.nodos_registrados),
                act=_esc(panel.nodos_activos),
            )
        )
        encabezados = (
            "ID", "Estado", "Tipo", "Ubicación", "Hace (s)", "Msgs", "Perdidos",
        )
        filas = [
            (n.id, n.estado, n.tipo, n.ubicacion, n.hace_seg, n.msgs, n.perdidos)
            for n in panel.nodos
        ]
        partes.append(_tabla_html(encabezados, filas))
    partes.append("</section>")
    return "".join(partes)


def _seccion_mediciones_html(panel):
    """Sección "Últimas mediciones": tabla en orden recibido (Req. 5.2, 5.3)."""
    partes = ["<section>", "<h2>{0}</h2>".format(_esc(_TITULO_MEDICIONES))]
    partes.append(_seccion_error_html(panel.error_mediciones))
    if not panel.disponible:
        partes.append('<p class="vacio">No disponible.</p>')
    else:
        encabezados = ("Nodo", "Variable", "Valor", "Unidad", "Timestamp")
        filas = [
            (m.node_id, m.variable, m.valor, m.unidad, m.timestamp)
            for m in panel.mediciones
        ]
        partes.append(_tabla_html(encabezados, filas))
    partes.append("</section>")
    return "".join(partes)


def _seccion_alertas_html(panel):
    """Sección "Alertas recientes": tabla en orden recibido (Req. 6.2, 6.3)."""
    partes = ["<section>", "<h2>{0}</h2>".format(_esc(_TITULO_ALERTAS))]
    partes.append(_seccion_error_html(panel.error_alertas))
    if not panel.disponible:
        partes.append('<p class="vacio">No disponible.</p>')
    else:
        encabezados = ("Nodo", "Tipo", "Valor", "Timestamp", "Severidad")
        filas = [
            (a.node_id, a.tipo_alerta, a.valor, a.timestamp, a.severidad)
            for a in panel.alertas
        ]
        partes.append(_tabla_html(encabezados, filas))
    partes.append("</section>")
    return "".join(partes)


def render_pagina(panel, refresh_seg=None):
    """Devuelve el HTML completo (str) a partir de un ``PanelDatos``.

    Página HTML5 autocontenida con CSS en línea, sin JS ni recursos externos.
    Renderiza las cuatro secciones (Estado del servidor, Nodos, Últimas
    mediciones, Alertas recientes) preservando el orden recibido y pasando TODO
    dato no confiable por ``html.escape`` (Req. 1.1, 3.2, 4.2, 5.2, 6.2;
    Property 1, 2, 7).

    - Si ``panel.disponible`` es ``False`` muestra un banner de indisponibilidad
      con ``mensaje_degradado``; las cuatro secciones siguen presentes con un
      marcador de "no disponible" (Req. 1.4, 7.1; Property 1).
    - Si una sección tiene un ``SeccionError`` muestra su código y descripción y
      renderiza el resto con normalidad (Req. 7.2).
    - Si ``refresh_seg`` no es ``None`` incluye
      ``<meta http-equiv="refresh" content="N">`` para auto-actualizar sin JS.
    """
    # Meta de auto-actualización opcional. ``int(refresh_seg)`` es un número, no
    # dato no confiable de la red, pero se normaliza a entero para no inyectar
    # nada arbitrario en el atributo ``content``.
    meta_refresh = ""
    if refresh_seg is not None:
        meta_refresh = '<meta http-equiv="refresh" content="{0}">'.format(int(refresh_seg))

    # Banner de Estado_Degradado (Req. 1.4, 7.1). El mensaje viene del panel y se
    # escapa aunque sea texto propio, por consistencia con la propiedad de
    # escapado total.
    banner = ""
    if not panel.disponible:
        mensaje = panel.mensaje_degradado if panel.mensaje_degradado is not None else (
            "El Servidor_Central no está disponible."
        )
        banner = '<div class="banner">{0}</div>'.format(_esc(mensaje))

    cuerpo = "".join(
        (
            banner,
            _seccion_estado_html(panel),
            _seccion_nodos_html(panel),
            _seccion_mediciones_html(panel),
            _seccion_alertas_html(panel),
        )
    )

    return (
        "<!DOCTYPE html>"
        '<html lang="es"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "{meta_refresh}"
        "<title>Servicio Web - Telemetría</title>"
        "<style>{css}</style>"
        "</head><body>"
        "<h1>Panel de telemetría</h1>"
        "{cuerpo}"
        "</body></html>"
    ).format(meta_refresh=meta_refresh, css=_CSS, cuerpo=cuerpo)


# ----------------------------------------------------------------------
# Manejador HTTP (Tarea 9) — esqueleto
# ----------------------------------------------------------------------

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402


# Cabecera Allow de las respuestas 405: solo se aceptan GET y HEAD (Req. 1.3).
_METODOS_PERMITIDOS = "GET, HEAD"

# HTML mínimo para las respuestas de error de cliente (404 / 405). Es texto
# estático propio, no dato no confiable de la red, así que se inserta tal cual.
_HTML_404 = (
    "<!DOCTYPE html>"
    '<html lang="es"><head><meta charset="utf-8">'
    "<title>404 - No encontrado</title></head><body>"
    "<h1>404 - Recurso no encontrado</h1>"
    "<p>El recurso solicitado no existe.</p>"
    "</body></html>"
)

_HTML_405 = (
    "<!DOCTYPE html>"
    '<html lang="es"><head><meta charset="utf-8">'
    "<title>405 - Método no permitido</title></head><body>"
    "<h1>405 - Método no permitido</h1>"
    "<p>Solo se admiten los métodos GET y HEAD.</p>"
    "</body></html>"
)

# Página degradada genérica de última línea: si algo inesperado falla al
# obtener el panel o renderizar, se responde 200 con esta página en lugar de un
# 500 (defensa en profundidad de Req. 7.3). Nunca depende de datos de la red.
_HTML_DEGRADADO_GENERICO = (
    "<!DOCTYPE html>"
    '<html lang="es"><head><meta charset="utf-8">'
    "<title>Servicio Web - Telemetría</title></head><body>"
    "<h1>Panel de telemetría</h1>"
    '<div style="background:#7f1d1d;border:1px solid #b91c1c;color:#fecaca;'
    'padding:1rem;border-radius:8px;font-weight:600;">'
    "El servicio no pudo generar la página en este momento. "
    "La interfaz sigue activa; vuelve a intentarlo más tarde."
    "</div>"
    "</body></html>"
)


class ManejadorWeb(BaseHTTPRequestHandler):
    """Manejador HTTP del Servicio_Web (subclase de ``BaseHTTPRequestHandler``).

    Distingue la ruta ``/`` (200 + HTML), otras rutas (404) y métodos distintos
    de GET/HEAD (405 con cabecera ``Allow``) (Req. 1.1, 1.2, 1.3, 1.4).

    La ``Config`` se inyecta como atributo de clase ``_config`` mediante la
    fábrica :func:`fabricar_handler`, porque ``BaseHTTPRequestHandler`` se
    instancia una vez por petición y no se puede pasar estado por el
    constructor. El atributo base es ``None``; la subclase de la fábrica lo
    sobrescribe con la configuración real.
    """

    # Config inyectada por la fábrica (closure). La clase base no tiene config.
    _config = None

    # ------------------------------------------------------------------
    # Manejadores por método HTTP
    # ------------------------------------------------------------------

    def do_GET(self):
        """Enruta la petición GET: ``/`` -> 200 + HTML; otra ruta -> 404.

        Cualquier excepción inesperada al obtener el panel o renderizar se
        traduce en una página 200 degradada, nunca en un 500 (Req. 1.1, 1.2,
        1.4, 7.3).
        """
        self._despachar_get(con_cuerpo=True)

    def do_HEAD(self):
        """Igual enrutado y estado que GET pero sin cuerpo (solo cabeceras)."""
        self._despachar_get(con_cuerpo=False)

    # Métodos no permitidos -> 405 con cabecera ``Allow: GET, HEAD`` (Req. 1.3).
    def do_POST(self):
        self._metodo_no_permitido()

    def do_PUT(self):
        self._metodo_no_permitido()

    def do_DELETE(self):
        self._metodo_no_permitido()

    def do_PATCH(self):
        self._metodo_no_permitido()

    def do_OPTIONS(self):
        self._metodo_no_permitido()

    # ------------------------------------------------------------------
    # Lógica interna de enrutado y respuesta
    # ------------------------------------------------------------------

    def _despachar_get(self, con_cuerpo):
        """Enruta GET/HEAD según la ruta y responde con o sin cuerpo.

        Parsea la ruta con ``urllib.parse.urlsplit``; si el ``path`` es ``/``
        (con o sin query) sirve el panel (200), en otro caso responde 404.
        """
        ruta = urllib.parse.urlsplit(self.path).path
        if ruta == "/":
            self._responder_panel(con_cuerpo)
        else:
            self._responder_html(404, _HTML_404, con_cuerpo)

    def _responder_panel(self, con_cuerpo):
        """Obtiene el panel, lo renderiza y responde 200 con HTML.

        Envuelve ``obtener_panel``/``render_pagina`` en un ``try/except`` de
        última línea: aunque ``obtener_panel`` ya nunca lanza, cualquier
        excepción inesperada se degrada a una página 200 genérica en vez de un
        500 (defensa en profundidad de Req. 7.3).
        """
        try:
            config = self._config
            panel = obtener_panel(config.tsp_host, config.tsp_port)
            cuerpo = render_pagina(panel)
        except Exception:  # noqa: BLE001 (defensa de última línea, Req. 7.3)
            cuerpo = _HTML_DEGRADADO_GENERICO
        self._responder_html(200, cuerpo, con_cuerpo)

    def _responder_html(self, codigo, cuerpo_html, con_cuerpo):
        """Envía una respuesta HTML con el código dado.

        Siempre fija ``Content-Type: text/html; charset=utf-8`` y
        ``Content-Length`` sobre el cuerpo codificado en UTF-8. Cuando
        ``con_cuerpo`` es ``False`` (HEAD) se envían solo las cabeceras.
        """
        datos = cuerpo_html.encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        if con_cuerpo:
            self.wfile.write(datos)

    def _metodo_no_permitido(self):
        """Responde 405 con cabecera ``Allow: GET, HEAD`` y cuerpo mínimo (Req. 1.3)."""
        datos = _HTML_405.encode("utf-8")
        self.send_response(405)
        self.send_header("Allow", _METODOS_PERMITIDOS)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def log_message(self, formato, *args):
        """Log conciso y silencioso para no ensuciar la salida en pruebas."""
        # No-op: se sobreescribe el log por defecto de BaseHTTPRequestHandler,
        # que escribe en stderr una línea por petición.
        return


def fabricar_handler(config):
    """Devuelve una subclase de :class:`ManejadorWeb` con ``config`` inyectada.

    ``BaseHTTPRequestHandler`` se instancia una vez por petición, así que la
    ``Config`` no puede pasarse por el constructor. La fábrica crea una subclase
    con la configuración fijada como atributo de clase ``_config`` (patrón de
    closure) y esa subclase se pasa a ``ThreadingHTTPServer`` (Req. 2, sección
    "Arranque" del diseño).
    """

    class _Handler(ManejadorWeb):
        _config = config

    return _Handler


# ----------------------------------------------------------------------
# Arranque (Tarea 10) — esqueleto
# ----------------------------------------------------------------------


def main():
    """Carga la configuración y arranca el servidor HTTP concurrente.

    Carga ``Config`` desde ``os.environ``; ante ``ConfigError`` imprime en
    stderr y retorna un código distinto de cero (aborta el arranque). En caso
    contrario levanta un ``ThreadingHTTPServer`` (Req. 2.5–2.8, 8.1, 9.1, 9.4).

    - Único caso de aborto tras leer el entorno: puerto inválido (Req. 2.5,
      2.8). Ya en marcha, el servidor no cae por errores del Servidor_Central.
    - Se enlaza a ``""`` (todas las interfaces) para ser accesible dentro de un
      contenedor (Req. 9.4). El puerto de escucha es ``config.web_port``
      (Req. 2.6, 2.7).
    - ``ThreadingHTTPServer`` atiende cada petición en su propio hilo (Req. 8.1)
      y la ``Config`` se inyecta al handler con :func:`fabricar_handler`.
    - ``Ctrl-C`` (``KeyboardInterrupt``) cierra el servidor limpiamente y
      retorna 0.
    """
    try:
        config = cargar_config(os.environ)
    except ConfigError as exc:
        print("[web] {0}".format(exc), file=sys.stderr)
        return 2  # aborta el arranque (Req. 2.5, 2.8)

    # Enlaza a "" (todas las interfaces) para funcionar dentro de un contenedor
    # (Req. 9.4). Cada petición se atiende en un hilo propio (Req. 8.1).
    servidor = ThreadingHTTPServer(("", config.web_port), fabricar_handler(config))
    print(
        "[web] Servicio_Web escuchando en el puerto {0} "
        "(Servidor_Central: {1}:{2})".format(
            config.web_port, config.tsp_host, config.tsp_port
        ),
        file=sys.stderr,
    )
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("[web] Deteniendo el Servicio_Web…", file=sys.stderr)
    finally:
        servidor.shutdown()
        servidor.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
