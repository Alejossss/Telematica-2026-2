"""Configuración de pruebas del Servicio_Web.

Añade ``web/`` y ``clients/`` al ``sys.path`` para que los tests puedan importar
tanto ``servicio_web`` como la Biblioteca_TSP ``tsp`` sin depender del directorio
de trabajo desde el que se lance pytest. Las rutas se resuelven de forma relativa
a este archivo.
"""

import os
import sys

_DIR_TESTS = os.path.dirname(os.path.abspath(__file__))
_DIR_WEB = os.path.dirname(_DIR_TESTS)
_DIR_CLIENTS = os.path.join(_DIR_WEB, "..", "clients")

for _ruta in (_DIR_WEB, os.path.abspath(_DIR_CLIENTS)):
    if _ruta not in sys.path:
        sys.path.insert(0, _ruta)
