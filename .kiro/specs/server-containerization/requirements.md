# Requirements Document

## Introduction

Esta funcionalidad cubre el **Punto 9 del enunciado**: contenerizar el sistema de la Plataforma Distribuida de Telemetría. El objetivo es ejecutar el **Servidor_Central** en C (binario `server/server_concurrent`) dentro de un contenedor Docker y orquestar el sistema completo mediante `docker-compose`, exponiendo los puertos requeridos: TCP `6000` (registro, comandos y alertas), UDP `5000` (telemetría) y el puerto HTTP del **Servicio_Web** (Punto 7).

El alcance incluye:

- Un `Dockerfile` optimizado (multi-etapa) que **compila** y **ejecuta** el Servidor_Central en C, ubicado en `server/Dockerfile` según la convención de `structure.md`.
- La ampliación del `docker-compose.yml` existente para añadir el servicio `servidor-central` como hermano del servicio `servicio-web` ya definido, en la misma red de compose y con resolución por nombre DNS interno.
- Instrucciones de despliegue en AWS EC2 (instalación de Docker y apertura de puertos en el grupo de seguridad).

Este trabajo se integra con artefactos existentes verificados en el repositorio: `web/Dockerfile` (imagen del Servicio_Web) y `docker-compose.yml` (que ya define `servicio-web` y anticipa el servicio hermano `servidor-central`). El Servidor_Central lee sus puertos de las variables de entorno `TSP_TCP_PORT` y `TSP_UDP_PORT` (con valores por defecto `6000` y `5000`), por lo que los puertos deben ser configurables sin recompilar. La localización entre servicios se realiza por nombre DNS de compose (`TSP_SERVER_HOST=servidor-central`), nunca por IP fija.

## Glossary

- **Servidor_Central**: Servidor concurrente en C cuyo binario desplegable es `server/server_concurrent`, compilado a partir de `server_concurrent.c`, `protocol.c`, `registry.c` y `handlers.c`. Depende solo de la libc y `pthread`.
- **Servicio_Web**: Servicio HTTP en Python (Punto 7) empaquetado por `web/Dockerfile`, que escucha en el puerto definido por `WEB_PORT` (por defecto `8080`) y localiza al Servidor_Central por nombre DNS.
- **Dockerfile_Servidor**: Archivo `server/Dockerfile` que define la imagen del Servidor_Central mediante una construcción multi-etapa.
- **Etapa_Compilacion**: Primera etapa (builder) del Dockerfile_Servidor que contiene la cadena de herramientas de compilación (compilador de C y utilidades de construcción) y produce el binario.
- **Etapa_Ejecucion**: Etapa final del Dockerfile_Servidor, basada en una imagen mínima, que contiene únicamente el binario y las bibliotecas de tiempo de ejecución necesarias.
- **Compose_Orquestador**: Archivo `docker-compose.yml` en la raíz del repositorio que orquesta los servicios `servidor-central` y `servicio-web`.
- **Servicio_Servidor**: Servicio de compose llamado `servidor-central` que ejecuta la imagen del Servidor_Central.
- **Red_Compose**: Red interna de Docker Compose que conecta el Servicio_Servidor y el Servicio_Web y provee resolución de nombres DNS entre servicios.
- **Puerto_TCP**: Puerto TCP del Servidor_Central, `6000` por defecto, configurable con `TSP_TCP_PORT`.
- **Puerto_UDP**: Puerto UDP del Servidor_Central, `5000` por defecto, configurable con `TSP_UDP_PORT`.
- **Puerto_Web**: Puerto HTTP del Servicio_Web, `8080` por defecto, configurable con `WEB_PORT`.
- **Grupo_Seguridad**: Conjunto de reglas de acceso de red de una instancia AWS EC2 que controla qué puertos son alcanzables desde Internet.
- **Documentacion_Despliegue**: Contenido que describe la construcción, ejecución y despliegue del sistema contenerizado, incluyendo pasos para AWS EC2.

## Requirements

### Requisito 1: Imagen del Servidor_Central mediante construcción multi-etapa

**Historia de usuario:** Como desarrollador del proyecto, quiero un Dockerfile optimizado que compile y ejecute el Servidor_Central en C, para obtener una imagen final pequeña que no incluya la cadena de herramientas de compilación.

#### Criterios de Aceptación

1. THE Dockerfile_Servidor SHALL residir en la ruta `server/Dockerfile`.
2. THE Dockerfile_Servidor SHALL definir una Etapa_Compilacion que contenga el compilador de C y las utilidades de construcción necesarias.
3. WHEN la Etapa_Compilacion se ejecuta, THE Etapa_Compilacion SHALL compilar el binario `server_concurrent` a partir de `server_concurrent.c`, `protocol.c`, `registry.c` y `handlers.c` usando las opciones `-Wall -Wextra -O2` y el enlace `-pthread`.
4. IF la compilación del binario `server_concurrent` en la Etapa_Compilacion finaliza con un código de salida distinto de cero, THEN THE Dockerfile_Servidor SHALL abortar la construcción sin producir una imagen final.
5. THE Etapa_Ejecucion SHALL basarse en una imagen que no contenga el compilador de C ni un gestor de paquetes de compilación.
6. THE Etapa_Ejecucion SHALL contener el binario `server_concurrent` y las bibliotecas de tiempo de ejecución `libc` y `pthread`.
7. THE Etapa_Ejecucion SHALL excluir de la imagen final el compilador de C y las utilidades de construcción, de modo que un intento de invocar el compilador de C dentro del contenedor falle.
8. THE Etapa_Ejecucion SHALL declarar la exposición del puerto TCP 6000 y del puerto UDP 5000 utilizados por el proceso `server_concurrent`.
9. WHEN el contenedor de la Etapa_Ejecucion arranca, THE Etapa_Ejecucion SHALL iniciar el proceso `server_concurrent` como comando por defecto y mantenerlo como proceso en ejecución del contenedor.
10. THE Dockerfile_Servidor SHALL incluir comentarios en español que referencien el Punto 9 del enunciado.

### Requisito 2: Configuración de puertos y host por variables de entorno

**Historia de usuario:** Como operador del sistema, quiero configurar los puertos y el host mediante variables de entorno, para desplegar el sistema en distintos entornos sin recompilar el Servidor_Central.

#### Criterios de Aceptación

1. WHEN el Servidor_Central arranca dentro del contenedor, THE Servidor_Central SHALL leer el Puerto_TCP de la variable de entorno `TSP_TCP_PORT`.
2. WHEN el Servidor_Central arranca dentro del contenedor, THE Servidor_Central SHALL leer el Puerto_UDP de la variable de entorno `TSP_UDP_PORT`.
3. IF la variable `TSP_TCP_PORT` no está definida, está vacía, no es un entero, o está fuera del rango de 1024 a 65535, THEN THE Servidor_Central SHALL usar el Puerto_TCP `6000`.
4. IF la variable `TSP_UDP_PORT` no está definida, está vacía, no es un entero, o está fuera del rango de 1024 a 65535, THEN THE Servidor_Central SHALL usar el Puerto_UDP `5000`.
5. THE Dockerfile_Servidor SHALL declarar la exposición del Puerto_TCP y del Puerto_UDP mediante instrucciones `EXPOSE`.
6. THE Servidor_Central SHALL enlazar sus sockets a todas las interfaces de red del contenedor para ser alcanzable desde fuera del contenedor.
7. IF el enlace del socket al Puerto_TCP o al Puerto_UDP falla durante el arranque, THEN THE Servidor_Central SHALL terminar el proceso de arranque y registrar un mensaje de error indicando el puerto que no pudo enlazarse.

### Requisito 3: Orquestación del Servicio_Servidor en docker-compose

**Historia de usuario:** Como desarrollador del proyecto, quiero que el Servidor_Central se orqueste como un servicio de compose, para levantar el sistema completo con un solo comando.

#### Criterios de Aceptación

1. THE Compose_Orquestador SHALL definir el Servicio_Servidor con el nombre exacto `servidor-central`.
2. THE Servicio_Servidor SHALL construir su imagen usando el contexto de build en la raíz del repositorio y el archivo `server/Dockerfile`.
3. THE Servicio_Servidor SHALL publicar el Puerto_TCP `6000` del contenedor hacia el puerto `6000` del host de forma que una conexión TCP entrante a `6000` del host sea aceptada por el Servicio_Servidor.
4. THE Servicio_Servidor SHALL publicar el Puerto_UDP `5000` del contenedor hacia el puerto `5000` del host mediante el protocolo `udp`, de forma que un datagrama UDP enviado a `5000` del host sea recibido por el Servicio_Servidor.
5. THE Compose_Orquestador SHALL conservar el Servicio_Web ya definido, que publica el Puerto_Web `8080` del contenedor hacia el puerto `8080` del host.
6. THE Servicio_Servidor y THE Servicio_Web SHALL pertenecer a la misma Red_Compose, de forma que el Servicio_Web resuelva al Servicio_Servidor por su nombre DNS `servidor-central` sin usar direcciones IP fijas.
7. WHEN el desarrollador ejecuta el comando único de arranque del Compose_Orquestador, THE Compose_Orquestador SHALL iniciar tanto el Servicio_Servidor como el Servicio_Web hasta que ambos estén en estado de ejecución.
8. IF la publicación de cualquiera de los puertos `6000/tcp`, `5000/udp` u `8080/tcp` no puede realizarse porque el puerto del host ya está en uso, THEN THE Compose_Orquestador SHALL abortar el arranque del servicio afectado y emitir un mensaje de error que indique el puerto en conflicto.
9. THE Compose_Orquestador SHALL incluir comentarios en español que referencien el Punto 9 del enunciado.

### Requisito 4: Localización entre servicios por nombre DNS interno

**Historia de usuario:** Como operador del sistema, quiero que el Servicio_Web localice al Servidor_Central por su nombre de servicio, para no depender de direcciones IP fijas al desplegar en la nube.

#### Criterios de Aceptación

1. THE Compose_Orquestador SHALL definir para el Servicio_Web la variable de entorno `TSP_SERVER_HOST` con el valor `servidor-central`.
2. WHEN el Servicio_Web resuelve el nombre `servidor-central`, THE Red_Compose SHALL proporcionar la dirección del Servicio_Servidor mediante su DNS interno.
3. THE Compose_Orquestador SHALL definir el host del Servidor_Central para el Servicio_Web mediante el nombre del Servicio_Servidor y no mediante una dirección IP literal.
4. IF la variable `TSP_SERVER_HOST` no está definida o está vacía en el Servicio_Web, THEN THE Servicio_Web SHALL registrar un error de configuración indicando la ausencia del host del Servidor_Central.
5. IF la resolución DNS interna del nombre `servidor-central` o la conexión al Servicio_Servidor falla, THEN THE Servicio_Web SHALL registrar el error y continuar en ejecución sin finalizar abruptamente.

### Requisito 5: Demostración de construcción y ejecución

**Historia de usuario:** Como evaluador del proyecto, quiero instrucciones reproducibles para construir la imagen y ejecutar el contenedor, para verificar que el Servidor_Central funciona contenerizado y es accesible desde la red.

#### Criterios de Aceptación

1. THE Documentacion_Despliegue SHALL incluir el comando para construir la imagen del Servidor_Central desde la raíz del repositorio usando `server/Dockerfile`, de modo que la construcción finalice sin error y produzca una imagen etiquetada.
2. THE Documentacion_Despliegue SHALL incluir el comando para ejecutar el contenedor del Servidor_Central publicando el Puerto_TCP y el Puerto_UDP, de modo que el contenedor quede en estado de ejecución.
3. THE Documentacion_Despliegue SHALL incluir el comando de `docker-compose` que levanta el Servicio_Servidor y el Servicio_Web de forma conjunta.
4. WHEN el Servicio_Servidor está en ejecución, THE Servicio_Servidor SHALL aceptar conexiones TCP en el Puerto_TCP `6000` desde clientes externos al contenedor.
5. WHEN el Servicio_Servidor está en ejecución, THE Servicio_Servidor SHALL recibir datagramas UDP en el Puerto_UDP `5000` desde clientes externos al contenedor.
6. WHEN el Servicio_Web está en ejecución, THE Servicio_Web SHALL responder solicitudes HTTP en el Puerto_Web `8080` desde clientes externos al contenedor.

### Requisito 6: Instrucciones de despliegue en AWS EC2

**Historia de usuario:** Como responsable del despliegue, quiero instrucciones precisas para desplegar el sistema en AWS EC2, para exponer el servicio a Internet con las reglas de acceso correctas.

#### Criterios de Aceptación

1. THE Documentacion_Despliegue SHALL incluir los pasos para instalar Docker en una instancia AWS EC2 y verificar la instalación mediante la comprobación de su versión.
2. THE Documentacion_Despliegue SHALL incluir los pasos para instalar `docker-compose` o el complemento `compose` de Docker en la instancia AWS EC2 y verificar la instalación mediante la comprobación de su versión.
3. THE Documentacion_Despliegue SHALL indicar la apertura del Puerto_TCP `6000` en el Grupo_Seguridad de la instancia para tráfico entrante desde Internet.
4. THE Documentacion_Despliegue SHALL indicar la apertura del Puerto_UDP `5000` en el Grupo_Seguridad de la instancia para tráfico entrante desde Internet.
5. THE Documentacion_Despliegue SHALL indicar la apertura del Puerto_Web `8080` en el Grupo_Seguridad de la instancia para tráfico entrante desde Internet.
6. THE Documentacion_Despliegue SHALL indicar que el host del Servidor_Central se localiza por nombre DNS y no por una dirección IP pública fija embebida.
7. THE Documentacion_Despliegue SHALL incluir una verificación posterior al despliegue que confirme la accesibilidad de los puertos `6000/tcp`, `5000/udp` y `8080/tcp` desde un equipo externo a la instancia.

### Requisito 7: Cumplimiento de convenciones del proyecto

**Historia de usuario:** Como mantenedor del proyecto, quiero que la contenerización respete las convenciones de los Steering Docs, para mantener la coherencia del repositorio.

#### Criterios de Aceptación

1. THE Dockerfile_Servidor SHALL redactar sus comentarios exclusivamente en español.
2. THE Compose_Orquestador SHALL redactar sus comentarios exclusivamente en español.
3. WHEN la Etapa_Compilacion compila los archivos fuente del Servidor_Central, THE Etapa_Compilacion SHALL finalizar con código de salida cero y producir el binario `server/server_concurrent`.
4. THE binario `server_concurrent` producido por la Etapa_Compilacion SHALL permanecer fuera del control de versiones del repositorio.
5. WHERE la construcción utilice el sistema de compilación existente, THE Etapa_Compilacion SHALL invocar el objetivo `server` del `Makefile` para producir `server/server_concurrent`.
6. THE Dockerfile_Servidor SHALL mantener la separación de responsabilidades del directorio `server/` sin modificar la lógica de los módulos `protocol.c`, `handlers.c` ni `registry.c`.
7. IF la compilación en la Etapa_Compilacion falla, THEN THE Dockerfile_Servidor SHALL detener la construcción, indicar el error y no producir una imagen final.
