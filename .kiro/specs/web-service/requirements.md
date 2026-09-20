# Requirements Document

## Introduction

Este documento especifica los requisitos del **Servicio Web** (Punto 7 del enunciado del proyecto),
una interfaz HTTP básica en Python ubicada en la carpeta `web/`. El servicio permite consultar desde
un navegador el estado general del servidor central, la cantidad de nodos registrados, los nodos
activos, las últimas mediciones y las alertas recientes.

El Servicio Web NO es una aplicación web compleja: no emplea frameworks grandes (Django, React) y se
limita a la biblioteca estándar de Python (`http.server`, `socket`, `threading`). Actúa como un
**cliente operador TSP más**: se conecta por TCP al servidor central escrito en C y consume los
comandos `GET_SYSTEM`, `LIST_NODES`, `GET_LAST` y `GET_ALERTS` definidos en `docs/PROTOCOLO.md`
(secciones 4.4, 4.6, 4.7 y 4.8). Toda la comunicación TSP se realiza reutilizando la biblioteca
`clients/tsp.py`; el Servicio Web no reimplementa el protocolo.

El servidor central se localiza siempre por nombre DNS (nunca por IP fija) y los puertos son
configurables por variables de entorno, de modo que el servicio encaje con el despliegue en Docker y
en la nube (Puntos 8 y 9). El Servicio Web debe ser robusto ante la caída o indisponibilidad del
servidor central y atender varias peticiones de navegador de forma concurrente.

## Glossary

- **Servicio_Web**: Proceso Python del Punto 7 que expone una interfaz HTTP básica y traduce las
  peticiones del navegador en consultas TSP contra el servidor central.
- **Servidor_Central**: Servidor concurrente en C que mantiene el estado del sistema (nodos,
  mediciones, umbrales, alertas y estadísticas) y responde comandos TSP por TCP.
- **Navegador**: Cliente HTTP (navegador web) que consume la interfaz expuesta por el Servicio_Web.
- **TSP/1.0**: Telemetry Simple Protocol, protocolo de aplicación propio definido en `docs/PROTOCOLO.md`.
- **Biblioteca_TSP**: Módulo `clients/tsp.py` que codifica, decodifica y transporta mensajes TSP por TCP.
- **Comando_TSP**: Petición dirigida al Servidor_Central; para este servicio son `GET_SYSTEM`,
  `LIST_NODES`, `GET_LAST` y `GET_ALERTS`.
- **Estado_Degradado**: Modo de operación del Servicio_Web en el que el Servidor_Central no está
  disponible; la interfaz sigue respondiendo peticiones HTTP y muestra un mensaje de indisponibilidad
  en lugar de datos.
- **TSP_SERVER_HOST**: Variable de entorno con el nombre DNS del Servidor_Central (valor por defecto `localhost`).
- **TSP_TCP_PORT**: Variable de entorno con el puerto TCP del Servidor_Central (valor por defecto 6000).
- **WEB_PORT**: Variable de entorno con el puerto HTTP en el que escucha el Servicio_Web (valor por defecto 8080).
- **Medicion**: Registro `MEAS|NODE_ID|VAR|VALOR|UNIDAD|TIMESTAMP` devuelto por `GET_LAST`.
- **Alerta_Reciente**: Registro `EVENT|NODE_ID|TIPO_ALERTA|VALOR|TIMESTAMP|SEVERIDAD` devuelto por `GET_ALERTS`.
- **Indicador_Sistema**: Registro `STAT|CLAVE|VALOR` devuelto por `GET_SYSTEM`.

## Requirements

### Requisito 1: Servir la interfaz web por HTTP

**Historia de usuario:** Como operador, quiero abrir una página web en mi navegador, para consultar el
estado del sistema de telemetría sin usar la línea de comandos.

#### Criterios de aceptación

1. WHEN el Servicio_Web recibe una petición HTTP GET a la ruta raíz "/" (con o sin cadena de consulta),
   THE Servicio_Web SHALL responder con código de estado HTTP 200 y una página HTML renderizable por el
   Navegador que presenta el estado del servidor, la cantidad de nodos registrados, los nodos activos, las
   últimas mediciones y las alertas recientes.
2. WHEN el Servicio_Web recibe una petición HTTP GET a una ruta distinta de "/", THE Servicio_Web SHALL
   responder con código de estado HTTP 404 y un cuerpo que indica que el recurso no existe.
3. WHEN el Servicio_Web recibe una petición HTTP con un método distinto de GET a cualquier ruta,
   THE Servicio_Web SHALL responder con código de estado HTTP 405 y un cuerpo que indica que el método no
   está permitido.
4. IF la petición HTTP GET a la ruta raíz "/" no puede completarse porque el Servidor_Central no está
   disponible, THEN THE Servicio_Web SHALL responder con código de estado HTTP 200 y presentar la página
   HTML en Estado_Degradado con un mensaje de indisponibilidad del Servidor_Central en lugar de los datos.

### Requisito 2: Configuración por variables de entorno y localización por DNS

**Historia de usuario:** Como responsable de despliegue, quiero configurar los puertos y el host del
servidor central mediante variables de entorno, para desplegar el servicio en Docker y en la nube sin
modificar el código ni usar IPs fijas.

#### Criterios de aceptación

1. WHEN el Servicio_Web arranca, THE Servicio_Web SHALL leer el nombre DNS del Servidor_Central desde la
   variable de entorno `TSP_SERVER_HOST`.
2. IF la variable de entorno `TSP_SERVER_HOST` no está definida, THEN THE Servicio_Web SHALL usar el nombre
   `localhost` por defecto.
3. WHEN el Servicio_Web arranca, THE Servicio_Web SHALL leer el puerto TCP del Servidor_Central desde la
   variable de entorno `TSP_TCP_PORT` como entero en el rango 1–65535.
4. IF la variable de entorno `TSP_TCP_PORT` no está definida, THEN THE Servicio_Web SHALL usar el puerto
   TCP 6000 por defecto.
5. IF la variable de entorno `TSP_TCP_PORT` está definida con un valor que no es un entero en el rango
   1–65535, THEN THE Servicio_Web SHALL abortar el arranque y emitir un mensaje de error que indique el
   nombre de la variable y el rango permitido.
6. WHEN el Servicio_Web arranca, THE Servicio_Web SHALL leer el puerto HTTP de escucha desde la variable
   de entorno `WEB_PORT` como entero en el rango 1–65535.
7. IF la variable de entorno `WEB_PORT` no está definida, THEN THE Servicio_Web SHALL usar el puerto HTTP
   8080 por defecto.
8. IF la variable de entorno `WEB_PORT` está definida con un valor que no es un entero en el rango 1–65535,
   THEN THE Servicio_Web SHALL abortar el arranque y emitir un mensaje de error que indique el nombre de la
   variable y el rango permitido.
9. WHEN el Servicio_Web establece una conexión con el Servidor_Central, THE Servicio_Web SHALL resolver el
   Servidor_Central por su nombre DNS mediante la Biblioteca_TSP.

### Requisito 3: Consultar el estado general del servidor

**Historia de usuario:** Como operador, quiero ver el estado general del servidor central, para conocer el
tiempo de actividad, el volumen de telemetría procesada y el número de alertas generadas.

#### Criterios de aceptación

1. WHEN el Navegador solicita la interfaz web, THE Servicio_Web SHALL enviar el Comando_TSP `GET_SYSTEM`
   al Servidor_Central mediante la Biblioteca_TSP.
2. WHEN el Servidor_Central responde a `GET_SYSTEM`, THE Servicio_Web SHALL presentar los Indicador_Sistema
   `UPTIME_SEG`, `NODOS_REGISTRADOS`, `NODOS_ACTIVOS`, `OPERADORES_CONECTADOS`, `TELEMETRIA_RECIBIDA`,
   `TELEMETRIA_RECHAZADA`, `TELEMETRIA_PERDIDA_EST`, `COMANDOS_TCP` y `ALERTAS_GENERADAS` recibidos en la
   respuesta.

### Requisito 4: Consultar los nodos registrados y activos

**Historia de usuario:** Como operador, quiero ver la lista de nodos con su estado, para saber cuántos están
registrados y cuántos están en línea.

#### Criterios de aceptación

1. WHEN el Navegador solicita la interfaz web, THE Servicio_Web SHALL enviar el Comando_TSP `LIST_NODES` al
   Servidor_Central mediante la Biblioteca_TSP.
2. WHEN el Servidor_Central responde a `LIST_NODES`, THE Servicio_Web SHALL presentar, por cada registro
   `NODE`, el identificador del nodo, el estado (`ONLINE` u `OFFLINE`), el tipo, la ubicación, los segundos
   desde la última medición, los mensajes aceptados y los mensajes perdidos.
3. WHEN el Servidor_Central responde a `LIST_NODES`, THE Servicio_Web SHALL presentar la cantidad total de
   nodos registrados.
4. WHEN el Servidor_Central responde a `LIST_NODES`, THE Servicio_Web SHALL presentar la cantidad de nodos
   cuyo estado es `ONLINE` como nodos activos.

### Requisito 5: Consultar las últimas mediciones

**Historia de usuario:** Como operador, quiero ver las mediciones más recientes del sistema, para verificar
los valores que reportan los nodos.

#### Criterios de aceptación

1. WHEN el Navegador solicita la interfaz web, THE Servicio_Web SHALL enviar el Comando_TSP `GET_LAST` al
   Servidor_Central mediante la Biblioteca_TSP.
2. WHEN el Servidor_Central responde a `GET_LAST`, THE Servicio_Web SHALL presentar, por cada Medicion, el
   identificador del nodo, la variable, el valor, la unidad y la marca de tiempo.
3. WHEN el Servidor_Central responde a `GET_LAST`, THE Servicio_Web SHALL presentar las mediciones ordenadas
   de la más reciente a la más antigua, en el orden recibido del Servidor_Central.

### Requisito 6: Consultar las alertas recientes

**Historia de usuario:** Como operador, quiero ver las alertas recientes, para detectar anomalías y nodos
caídos.

#### Criterios de aceptación

1. WHEN el Navegador solicita la interfaz web, THE Servicio_Web SHALL enviar el Comando_TSP `GET_ALERTS` al
   Servidor_Central mediante la Biblioteca_TSP.
2. WHEN el Servidor_Central responde a `GET_ALERTS`, THE Servicio_Web SHALL presentar, por cada
   Alerta_Reciente, el identificador del nodo, el tipo de alerta, el valor, la marca de tiempo y la severidad.
3. WHEN el Servidor_Central responde a `GET_ALERTS`, THE Servicio_Web SHALL presentar las alertas ordenadas
   de la más reciente a la más antigua, en el orden recibido del Servidor_Central.

### Requisito 7: Operación robusta en estado degradado

**Historia de usuario:** Como operador, quiero que la página web siga respondiendo cuando el servidor central
está caído, para distinguir un problema del servidor de un problema de la interfaz.

#### Criterios de aceptación

1. IF la conexión con el Servidor_Central falla por error de conexión, error de resolución DNS o expiración
   del tiempo de espera de 5 segundos, THEN THE Servicio_Web SHALL responder la petición HTTP con código de
   estado 200 y presentar la interfaz en Estado_Degradado con un mensaje que indica la indisponibilidad del
   Servidor_Central en lugar de los datos consultados.
2. IF el Servidor_Central devuelve un error TSP (`TspError`) ante un Comando_TSP, THEN THE Servicio_Web SHALL
   responder la petición HTTP con código de estado 200, presentar en la sección correspondiente el código de
   error y su descripción recibidos del Servidor_Central, y presentar el resto de las secciones de la interfaz
   cuyos comandos respondieron correctamente.
3. IF una consulta al Servidor_Central falla, THEN THE Servicio_Web SHALL continuar el proceso en ejecución y
   responder cada petición HTTP posterior con código de estado 200.
4. WHEN el Servicio_Web establece una conexión TCP con el Servidor_Central para atender una petición,
   THE Servicio_Web SHALL aplicar un tiempo de espera máximo de 5 segundos a la resolución DNS, al
   establecimiento de la conexión TCP y a la lectura de la respuesta TSP.

### Requisito 8: Atención concurrente de peticiones

**Historia de usuario:** Como operador, quiero que varios navegadores consulten la interfaz al mismo tiempo,
para que el servicio sea usable por más de una persona.

#### Criterios de aceptación

1. WHILE el Servicio_Web atiende una petición HTTP, THE Servicio_Web SHALL aceptar y procesar peticiones HTTP
   adicionales de otros Navegador de forma concurrente.
2. WHEN el Servicio_Web procesa una petición HTTP, THE Servicio_Web SHALL abrir una conexión TSP propia para
   esa petición y cerrarla al finalizar, de modo que las peticiones concurrentes no compartan la misma
   conexión TCP con el Servidor_Central.

### Requisito 9: Cumplimiento de restricciones tecnológicas y de despliegue

**Historia de usuario:** Como responsable del proyecto, quiero que el servicio use solo la biblioteca estándar
y reutilice la biblioteca TSP, para respetar las restricciones del enunciado y facilitar el despliegue en
contenedores.

#### Criterios de aceptación

1. THE Servicio_Web SHALL implementarse usando únicamente la biblioteca estándar de Python.
2. THE Servicio_Web SHALL realizar toda la comunicación TSP a través de la Biblioteca_TSP `clients/tsp.py`.
3. THE Servicio_Web SHALL ubicarse en la carpeta `web/` del repositorio.
4. WHERE el Servicio_Web se despliega en un contenedor o en la nube, THE Servicio_Web SHALL escuchar en el
   puerto HTTP indicado por la variable `WEB_PORT` sin requerir dependencias externas al intérprete de Python.
