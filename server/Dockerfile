# server/Dockerfile — Contenerizacion del Servidor_Central (Punto 9 del enunciado).
# Construccion multi-etapa: se compila con la cadena de herramientas en la
# Etapa_Compilacion y se ejecuta un binario minimo en la Etapa_Ejecucion, de
# modo que la imagen final no arrastre el compilador ni las utilidades de build.

# --- Etapa_Compilacion (builder): compila server_concurrent con el Makefile ---
# Se usa la familia Debian/glibc para que el binario enlace contra la misma
# implementacion de libc/pthread que la Etapa_Ejecucion (Punto 9).
FROM gcc:14-bookworm AS builder
WORKDIR /src
# Se copian el Makefile y las fuentes del servidor (contexto de build = raiz del repo).
COPY Makefile ./Makefile
COPY server/ ./server/
# Se invoca el objetivo `server` del Makefile: unica fuente de verdad de los flags
# de compilacion (-Wall -Wextra -O2) y del enlace (-pthread). Si `make server`
# finaliza con codigo distinto de cero, este RUN falla y Docker aborta el build
# sin producir imagen final (Punto 9).
RUN make server

# --- Etapa_Ejecucion (runtime): imagen minima con glibc + pthread, sin compilador ---
# debian:bookworm-slim aporta glibc y libpthread de tiempo de ejecucion, pero no
# incluye el compilador de C ni un gestor de paquetes de compilacion, de modo que
# un intento de invocar el compilador dentro del contenedor falla (Punto 9).
FROM debian:bookworm-slim AS runtime
WORKDIR /app
# Solo se copia el binario ya compilado desde el builder, sin la cadena de herramientas (Punto 9).
COPY --from=builder /src/server/server_concurrent /app/server_concurrent
# Puertos por defecto configurables por entorno, sin recompilar el servidor (Punto 9).
ENV TSP_TCP_PORT=6000
ENV TSP_UDP_PORT=5000
# Exposicion de los puertos usados por el proceso server_concurrent (Punto 9).
EXPOSE 6000/tcp
EXPOSE 5000/udp
# El binario queda como proceso principal en primer plano del contenedor (Punto 9).
CMD ["/app/server_concurrent"]
