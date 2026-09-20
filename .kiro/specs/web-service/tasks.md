# Implementation Plan: Servicio Web (Punto 7)

## Overview

El plan implementa el **Servicio_Web** en el módulo `web/servicio_web.py` usando únicamente la
biblioteca estándar de Python y reutilizando `clients/tsp.py` (sin reimplementar el protocolo TSP).
El desarrollo es incremental y guiado por pruebas: primero el andamiaje de importación de `tsp` y el
esqueleto de pruebas, luego el cargador de configuración, el modelo de datos, la capa de obtención de
datos TSP, el renderizador HTML y, por último, el manejador HTTP y el arranque concurrente. Cada
tarea construye sobre la anterior y termina cableando el código en el flujo de la petición, sin dejar
código huérfano. Las pruebas basadas en propiedades (Hypothesis, mínimo 100 iteraciones) cubren las 8
propiedades de corrección del diseño; las pruebas de ejemplo e integración cubren rutas/métodos,
valores por defecto, mensajes de error, cableado de comandos, DNS, concurrencia y restricciones
tecnológicas.

## Tasks

- [x] 1. Preparar la estructura del módulo y el andamiaje de pruebas
  - Crear la carpeta `web/` con `web/servicio_web.py` y `web/__init__.py` vacío para importación.
  - Añadir la inserción en `sys.path` relativa al archivo (`os.path.dirname(__file__)/../clients`)
    **antes** de `import tsp`, de modo que `tsp.py` se importe sin reimplementar el protocolo.
  - Definir la excepción `ConfigError(Exception)` y los esqueletos (firmas + `pass`/`NotImplementedError`)
    de `parsear_puerto`, `cargar_config`, `obtener_panel`, `render_pagina`, `ManejadorWeb`, `main`.
  - Crear la carpeta de pruebas `web/tests/` con `__init__.py` y un `conftest.py`/helper que añada
    `web/` y `clients/` al `sys.path` para poder importar `servicio_web` y `tsp` en los tests.
  - Añadir `web/requirements-dev.txt` (o sección equivalente) declarando solo `hypothesis` como
    dependencia de desarrollo para PBT; el código de producción no la usa.
  - _Requirements: 9.1, 9.2, 9.3_

- [x] 2. Implementar el cargador de configuración
  - [x] 2.1 Implementar `parsear_puerto` y `Config` / `cargar_config`
    - Definir `@dataclass(frozen=True) Config` con `tsp_host: str`, `tsp_port: int`, `web_port: int`.
    - Implementar `parsear_puerto(nombre_var, valor, defecto)` como función total y pura: `None` →
      `defecto`; entero válido en 1–65535 → ese entero; en otro caso lanzar `ConfigError` con mensaje
      que incluya el nombre de la variable y el rango permitido (p. ej. `TSP_TCP_PORT debe ser un
      entero en el rango 1-65535 (recibido: 'abc')`).
    - Implementar `cargar_config(entorno)` leyendo `TSP_SERVER_HOST` (defecto `localhost`),
      `TSP_TCP_PORT` (defecto 6000) y `WEB_PORT` (defecto 8080) desde el mapping recibido.
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8_

  - [ ]* 2.2 Escribir prueba de propiedad para la validación de puertos
    - **Feature: web-service, Property 5: Validación de puerto total sobre las entradas**
    - Generar cadenas arbitrarias, enteros dentro/fuera de rango, `None`, negativos, `0`, `65536`,
      no numéricos; verificar que `parsear_puerto` devuelve un entero en 1–65535 o lanza `ConfigError`,
      nunca un valor fuera de rango ni otra excepción; con `None` devuelve el defecto; el mensaje de
      `ConfigError` incluye el nombre de variable y el rango. Mínimo 100 iteraciones.
    - **Validates: Requirements 2.3, 2.5, 2.6, 2.8**

  - [ ]* 2.3 Escribir pruebas de ejemplo para valores por defecto y mensajes de error
    - Sin variables definidas → `Config(localhost, 6000, 8080)`; host presente se lee correctamente.
    - `TSP_TCP_PORT` / `WEB_PORT` inválidos → `ConfigError` cuyo texto contiene el nombre de la
      variable y el rango `1-65535`.
    - _Requirements: 2.1, 2.2, 2.4, 2.7, 2.5, 2.8_

- [x] 3. Implementar el modelo de datos
  - [x] 3.1 Definir las dataclasses del panel
    - Definir `@dataclass(frozen=True)` para `EstadoSistema`, `NodoInfo`, `Medicion`, `Alerta`,
      `SeccionError` y `PanelDatos` con los campos del diseño (incluidos los errores por sección y el
      estado degradado).
    - Implementar los campos derivados `nodos_registrados` (= longitud de la lista de nodos) y
      `nodos_activos` (= nodos con `estado == "ONLINE"`, comparación insensible a mayúsculas),
      garantizando `0 <= nodos_activos <= nodos_registrados`.
    - _Requirements: 3.2, 4.2, 4.3, 4.4, 5.2, 6.2_

  - [ ]* 3.2 Escribir prueba de propiedad para los conteos de nodos derivados
    - **Feature: web-service, Property 6: Conteos de nodos derivados correctamente**
    - Generar listas de `NodoInfo` con estados variados (ONLINE/OFFLINE y variaciones de mayúsculas);
      verificar `nodos_registrados == len(lista)`, `nodos_activos == nº ONLINE (case-insensitive)` y
      `0 <= nodos_activos <= nodos_registrados`. Mínimo 100 iteraciones.
    - **Validates: Requirements 4.3, 4.4**

- [x] 4. Implementar el parseo tolerante de registros
  - [x] 4.1 Implementar los parsers de registros crudos al modelo
    - Implementar funciones puras que conviertan `list[list[str]]` (cabecera + registros de
      `conexion.comando`) a `EstadoSistema` (STAT), `list[NodoInfo]` (NODE), `list[Medicion]` (MEAS) y
      `list[Alerta]` (EVENT), replicando la tolerancia de `operator_cli.py`: descartar registros con
      menos campos de los requeridos y recortar los más largos a las posiciones conocidas.
    - _Requirements: 4.2, 5.2, 6.2, 3.2_

  - [ ]* 4.2 Escribir prueba de propiedad para el parseo tolerante
    - **Feature: web-service, Property 8: Parseo tolerante de registros malformados**
    - Generar `list[list[str]]` con longitudes variables por registro; verificar que el parseo no
      lanza, descarta los cortos y recorta los largos de forma coherente con `operator_cli.py`.
      Mínimo 100 iteraciones.
    - **Validates: Requirements 4.2, 5.2, 6.2, 7.3**

- [x] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Implementar la capa de obtención de datos TSP (`obtener_panel`)
  - [x] 6.1 Implementar el flujo feliz de `obtener_panel`
    - Abrir `tsp.TspConexion(host, puerto, timeout=timeout, verbose=False)` con `timeout=5.0`; enviar
      `HELLO|servicio-web` y guardar `server_id` de la cabecera; ejecutar `GET_SYSTEM`, `LIST_NODES`,
      `GET_LAST` (n_ultimas), `GET_ALERTS` (n_alertas) vía `conexion.comando(...)`; parsear cada
      `(cabecera, registros)` con los parsers de la tarea 4 y construir un `PanelDatos` con
      `disponible=True`; cerrar siempre con `conexion.cerrar()` (`BYE`) en `finally`.
    - _Requirements: 3.1, 4.1, 5.1, 6.1, 5.3, 6.3, 7.4, 8.2, 9.2_

  - [x] 6.2 Implementar la traducción de errores a Estado Degradado y parcial
    - Al **conectar**: `ConnectionError`, `OSError`, `socket.gaierror`, `socket.timeout`/`TimeoutError`
      → `PanelDatos(disponible=False, mensaje_degradado=...)` sin ejecutar comandos.
    - `tsp.TspError` en un comando → `SeccionError(codigo, descripcion)` en esa sección, el resto de
      comandos continúan y `disponible=True`.
    - `tsp.TspProtocolError` o error de red a mitad de sesión → marcar la sección afectada y degradar
      las secciones no ejecutadas; nunca propagar la excepción; cerrar con `BYE` en `finally`.
    - _Requirements: 1.4, 7.1, 7.2, 7.3, 7.4, 8.2_

  - [ ]* 6.3 Escribir prueba de propiedad para la degradación segura
    - **Feature: web-service, Property 3: Degradación segura — obtener_panel nunca lanza**
    - Usar un doble de `TspConexion` parametrizado por el generador para lanzar `ConnectionError`,
      `socket.gaierror`, `socket.timeout`/`TimeoutError`, `tsp.TspProtocolError` o cierre a mitad;
      verificar que `obtener_panel` no propaga y devuelve un `PanelDatos`; si el fallo es al conectar,
      `disponible == False` con mensaje de indisponibilidad. Mínimo 100 iteraciones.
    - **Validates: Requirements 1.4, 7.1, 7.3**

  - [ ]* 6.4 Escribir prueba de propiedad para el error TSP parcial
    - **Feature: web-service, Property 4: Error TSP parcial preserva las secciones sanas**
    - Con un doble de `TspConexion`, elegir por el generador el subconjunto de comandos que responden
      con `tsp.TspError`; verificar `disponible == True`, `SeccionError` en las secciones afectadas y
      datos en las sanas, sin propagar excepción. Mínimo 100 iteraciones.
    - **Validates: Requirements 7.2, 7.3**

  - [ ]* 6.5 Escribir pruebas de integración de cableado de comandos y conexión por petición
    - Con un spy/doble de `TspConexion`, verificar que `obtener_panel` emite `HELLO`, `GET_SYSTEM`,
      `LIST_NODES`, `GET_LAST`, `GET_ALERTS`; construye una `TspConexion` nueva con `timeout=5.0` por
      llamada, invoca la resolución por DNS del host configurado y llama a `cerrar()` (`BYE`).
    - _Requirements: 3.1, 4.1, 5.1, 6.1, 2.9, 7.4, 8.2_

- [x] 7. Implementar el renderizador HTML (`render_pagina`)
  - [x] 7.1 Implementar la página autocontenida con escapado y secciones
    - Generar HTML completo con CSS en línea, sin JS ni recursos externos; renderizar las cuatro
      secciones (Estado del servidor con los 9 STAT, Nodos con registrados/activos + tabla, Últimas
      mediciones, Alertas recientes) preservando el orden recibido; pasar **todo** dato por
      `html.escape`; soportar `<meta http-equiv="refresh" content="N">` opcional.
    - Renderizar el **banner degradado** cuando `panel.disponible` es `False` y el **error por sección**
      (código y descripción) cuando una sección tiene `SeccionError`, renderizando el resto con normalidad.
    - _Requirements: 1.1, 1.4, 3.2, 4.2, 4.3, 4.4, 5.2, 5.3, 6.2, 6.3, 7.1, 7.2_

  - [ ]* 7.2 Escribir prueba de propiedad para HTML bien formado
    - **Feature: web-service, Property 1: HTML bien formado para cualquier panel**
    - Generar `PanelDatos` (disponible, degradado y con errores por sección); parsear el HTML con
      `html.parser.HTMLParser` sin que lance y comprobar que están las cuatro secciones esperadas.
      Mínimo 100 iteraciones.
    - **Validates: Requirements 1.1**

  - [ ]* 7.3 Escribir prueba de propiedad para el escapado total de datos
    - **Feature: web-service, Property 2: Escapado total de datos no confiables**
    - Generar `PanelDatos` con campos que contengan `<`, `>`, `&`, `"`, `'`; comprobar que ningún dato
      aparece sin escapar en el contenido y que todo pasa por `html.escape`. Mínimo 100 iteraciones.
    - **Validates: Requirements 1.1, 3.2, 4.2, 5.2, 6.2**

  - [ ]* 7.4 Escribir prueba de propiedad para la preservación del orden en tablas
    - **Feature: web-service, Property 7: Preservación del orden en tablas**
    - Generar listas de `Medicion` y `Alerta`; verificar que los índices de aparición de las filas en
      el HTML son monótonos respecto al orden de la lista de entrada. Mínimo 100 iteraciones.
    - **Validates: Requirements 5.3, 6.3**

- [x] 8. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Implementar el manejador HTTP `ManejadorWeb`
  - [x] 9.1 Implementar el enrutado de rutas y métodos
    - Subclasear `BaseHTTPRequestHandler`; en `do_GET` parsear la ruta con `urllib.parse.urlsplit`: si
      `path == "/"` (con o sin query), llamar a `obtener_panel(...)` y `render_pagina(...)` y responder
      200 con `Content-Type: text/html; charset=utf-8`; ruta distinta → 404 con cuerpo HTML mínimo.
    - Responder 405 con cabecera `Allow: GET, HEAD` a métodos distintos de GET/HEAD; sobreescribir
      `log_message`; envolver el render en un `try/except` que responda 200 degradado ante cualquier
      excepción inesperada (defensa de Req. 7.3). Inyectar `Config` vía fábrica (closure/`partial`).
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 7.3_

  - [ ]* 9.2 Escribir pruebas de ejemplo de rutas y métodos
    - `GET /` → 200 con HTML; `GET /otra` → 404; `POST /` → 405 con cabecera `Allow`. Usar un doble de
      `obtener_panel` para aislar del servidor central.
    - _Requirements: 1.1, 1.2, 1.3_

- [x] 10. Implementar el arranque concurrente (`main`)
  - [x] 10.1 Cablear `main` con `ThreadingHTTPServer`
    - En `main`, cargar `Config` desde `os.environ`; si `ConfigError`, imprimir en `stderr` y retornar
      código distinto de cero (aborta el arranque); en caso contrario, crear
      `ThreadingHTTPServer(("", config.web_port), fabrica_handler(config))` y `serve_forever()`.
      Añadir el `if __name__ == "__main__": sys.exit(main())`.
    - _Requirements: 2.5, 2.6, 2.7, 2.8, 8.1, 9.1, 9.4_

  - [ ]* 10.2 Escribir pruebas de integración de concurrencia y restricciones tecnológicas
    - Arrancar un `ThreadingHTTPServer` de prueba con un doble/stub del servidor central que retarde la
      respuesta; lanzar varias peticiones simultáneas y verificar que todas responden 200.
    - Verificar que el módulo solo depende de la biblioteca estándar y de `tsp`, vive en `web/` y
      escucha en el `WEB_PORT` indicado.
    - _Requirements: 8.1, 8.2, 9.1, 9.2, 9.3, 9.4_

- [x] 11. Añadir el empaquetado de despliegue del servicio web (Punto 7 en Docker)
  - Crear `web/Dockerfile` basado en `python:3-slim` sin `pip install` de dependencias de producción,
    copiando `clients/` y `web/` y fijando `PYTHONPATH=/app/clients` (o usando la inserción en
    `sys.path`); el `CMD` ejecuta `servicio_web.py` escuchando en `WEB_PORT`.
    - Añadir una entrada de `docker-compose` para el servicio web con
      `TSP_SERVER_HOST=servidor-central`, `TSP_TCP_PORT=6000`, `WEB_PORT=8080` y `ports: 8080:8080`,
      alcanzando al servidor central por nombre DNS del compose (nunca IP fija).
    - Nota de alcance: solo se empaqueta el servicio web (Punto 7); el Docker del servidor central en C
      queda fuera del alcance de este spec.
    - _Requirements: 2.1, 2.6, 2.9, 9.1, 9.4_

- [x] 12. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Las tareas marcadas con `*` son opcionales (pruebas de propiedad, unitarias e integración) y pueden
  omitirse para un MVP más rápido; las tareas de implementación central no se marcan como opcionales.
- Cada tarea referencia los requisitos específicos que satisface para trazabilidad.
- Las pruebas de propiedad usan Hypothesis con mínimo 100 iteraciones y se etiquetan con el formato
  **Feature: web-service, Property N**; validan las 8 propiedades de corrección del diseño.
- Los checkpoints aseguran validación incremental.
- El servicio usa solo la biblioteca estándar y reutiliza `clients/tsp.py`; Hypothesis es solo una
  dependencia de desarrollo para pruebas.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2.1", "3.1", "4.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "3.2", "4.2", "6.1"] },
    { "id": 3, "tasks": ["6.2", "7.1"] },
    { "id": 4, "tasks": ["6.3", "6.4", "6.5", "7.2", "7.3", "7.4", "9.1"] },
    { "id": 5, "tasks": ["9.2", "10.1"] },
    { "id": 6, "tasks": ["10.2", "11"] }
  ]
}
```
