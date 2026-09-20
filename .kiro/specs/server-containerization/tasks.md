# Implementation Plan: Contenerización del Servidor_Central (Punto 9)

## Overview

Este plan traduce el diseño aprobado en pasos de configuración declarativa de contenedores e infraestructura (IaC) sobre el código C y Python **existente y sin modificar**. El servidor ya lee sus puertos del entorno y enlaza a `INADDR_ANY`, por lo que **ninguna tarea toca `server_concurrent.c`, `protocol.c`, `registry.c`, `handlers.c` ni la lógica del `servicio_web.py`**. El trabajo se centra en `server/Dockerfile`, `.dockerignore`, `docker-compose.yml` y la documentación de despliegue, con verificación de humo/integración (no PBT, por ser configuración declarativa, ver "Testing Strategy" del diseño).

Cada tarea construye sobre la anterior y termina cableando el sistema completo: primero la imagen del servidor, luego el contexto de build magro, luego la orquestación conjunta, y finalmente la verificación y la documentación de despliegue.

## Tasks

- [x] 1. Crear el `server/Dockerfile` multi-etapa del Servidor_Central
  - Crear el archivo `server/Dockerfile` con construcción multi-etapa siguiendo la estructura del diseño (sección "Components and Interfaces > 1").
  - Etapa_Compilacion: `FROM gcc:14-bookworm AS builder`, `WORKDIR /src`, `COPY Makefile ./Makefile`, `COPY server/ ./server/`, `RUN make server` (única fuente de verdad de flags `-Wall -Wextra -O2 -pthread`; un código de salida distinto de cero aborta el build sin imagen final).
  - Etapa_Ejecucion: `FROM debian:bookworm-slim AS runtime` (glibc + pthread, sin compilador ni gestor de paquetes de compilación), `WORKDIR /app`, `COPY --from=builder /src/server/server_concurrent /app/server_concurrent`.
  - Declarar `ENV TSP_TCP_PORT=6000` y `ENV TSP_UDP_PORT=5000`, `EXPOSE 6000/tcp` y `EXPOSE 5000/udp`, y `CMD ["/app/server_concurrent"]` para dejar el proceso en primer plano.
  - Redactar todos los comentarios en español referenciando el Punto 9.
  - _Requisitos: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 2.5, 7.1, 7.5, 7.6_

- [x] 2. Crear el `.dockerignore` en la raíz para un contexto de build magro
  - Crear `.dockerignore` en la raíz del repositorio con las entradas del diseño (sección "Components and Interfaces > 4"): `.git`, `**/__pycache__`, `server/server_concurrent`, `server/*.o`, `server/client_tcp_test`, `server/client_udp_test`.
  - Objetivo: reducir el contexto enviado al demonio Docker y evitar filtrar binarios/artefactos locales dentro de la imagen (el binario se recompila en el builder).
  - _Requisitos: 7.4_

- [x] 3. Ampliar `docker-compose.yml` con el Servicio_Servidor y conservar el Servicio_Web
  - Añadir el servicio `servidor-central` con `build.context: .` y `build.dockerfile: server/Dockerfile`, `environment` `TSP_TCP_PORT=6000` y `TSP_UDP_PORT=5000`, y `ports` `"6000:6000"` (TCP) y `"5000:5000/udp"` (UDP).
  - Conservar el servicio `servicio-web` existente con su publicación `"8080:8080"`; añadirle `depends_on: [servidor-central]` para arranque ordenado.
  - Asegurar `TSP_SERVER_HOST=servidor-central` en `servicio-web` para localización por DNS interno de compose (nunca IP fija); ambos servicios en la misma Red_Compose por defecto.
  - Redactar todos los comentarios en español referenciando el Punto 9.
  - _Requisitos: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.9, 4.1, 4.2, 4.3, 7.2_

- [x] 4. Checkpoint — Artefactos de contenerización creados
  - Revisar que `server/Dockerfile`, `.dockerignore` y `docker-compose.yml` sean coherentes con el diseño y que ninguna fuente C ni la lógica del servicio web haya sido modificada.
  - Asegurar que todo esté listo para las verificaciones; consultar al usuario si surgen dudas.

- [x]* 5. Verificar la construcción de la imagen del servidor y la ausencia de compilador en runtime
  - Construir la imagen: `docker build -f server/Dockerfile -t servidor-central .` desde la raíz; debe finalizar sin error y producir imagen etiquetada.
  - Confirmar que `make server` compila con código de salida cero dentro del builder y que un build con una fuente inválida aborta sin imagen final (cobertura de error 1.4/7.7).
  - Verificar ausencia de toolchain en runtime: `docker run --rm servidor-central sh -c "gcc --version"` (o `which gcc`) debe fallar.
  - _Requisitos: 1.4, 1.5, 1.7, 5.1_

- [x]* 6. Verificar la ejecución del contenedor y el alcance de los puertos
  - Ejecutar `docker run --rm -p 6000:6000 -p 5000:5000/udp servidor-central` y confirmar con `docker ps` que el proceso queda vivo en primer plano.
  - TCP 6000: probar con `server/client_tcp_test` (o `nc`) un registro/comando TSP desde fuera del contenedor.
  - UDP 5000: probar con `server/client_udp_test` (o `clients/telemetry_node.py`) enviando un datagrama.
  - HTTP 8080: `curl` al `servicio-web` responde.
  - _Requisitos: 5.2, 5.4, 5.5, 5.6_

- [x]* 7. Verificar la orquestación conjunta y la resolución DNS interna
  - Ejecutar `docker compose up` y confirmar que `servidor-central` y `servicio-web` quedan en estado de ejecución.
  - Verificar resolución DNS interna desde `servicio-web`: `getent hosts servidor-central` (o el flujo del operador web) resuelve al servidor por nombre, no por IP fija.
  - Comprobar el conflicto de puertos (cobertura de error 3.8): ocupar `8080` en el host y verificar que `docker compose up` aborta el servicio afectado con mensaje del puerto en conflicto.
  - _Requisitos: 3.7, 4.2_

- [x]* 8. Documentar las instrucciones de build/run/compose y el despliegue en AWS EC2
  - Añadir al `README.md` (o a `docs/`) los comandos reproducibles: build de la imagen desde la raíz con `server/Dockerfile`, ejecución del contenedor publicando `6000/tcp` y `5000/udp`, y `docker compose up` para levantar ambos servicios.
  - Documentar el despliegue en AWS EC2: instalar Docker (verificar con `docker --version`), instalar el complemento Compose (verificar con `docker compose version`), y reglas de entrada del Grupo_Seguridad `6000/tcp`, `5000/udp`, `8080/tcp` con origen `0.0.0.0/0`.
  - Aclarar que la localización interna es por nombre DNS de compose (sin IP fija embebida) y añadir la verificación post-despliegue desde un equipo externo para el alcance de los tres puertos contra la IP/DNS pública de la instancia.
  - _Requisitos: 5.3, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_

## Notes

- Las tareas marcadas con `*` corresponden a verificación de humo/integración y a la documentación de despliegue; pueden ejecutarse tras completar la configuración base.
- No se incluyen tareas de pruebas basadas en propiedades (PBT): un `Dockerfile` y un `docker-compose.yml` son configuración declarativa sin relación entrada/salida sobre la que formular propiedades universales (ver "Testing Strategy" del diseño). La verificación es de build, humo e integración con ejemplos representativos.
- Ninguna tarea modifica el código C del servidor ni la lógica del `servicio_web.py`; la configurabilidad por variables de entorno ya existe en el binario.
- Cada tarea referencia criterios de aceptación específicos para trazabilidad.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1", "2"] },
    { "id": 1, "tasks": ["3"] },
    { "id": 2, "tasks": ["5"] },
    { "id": 3, "tasks": ["6", "7"] },
    { "id": 4, "tasks": ["8"] }
  ]
}
```
