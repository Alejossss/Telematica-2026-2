# Dockerfile del Servicio_Web (Punto 7).
#
# IMPORTANTE: el contexto de build DEBE ser la raíz del repositorio, porque este
# Dockerfile copia tanto `clients/` (la Biblioteca_TSP que se reutiliza) como
# `web/` (el propio servicio). Aunque el archivo vive en `web/`, las rutas de
# COPY son relativas al contexto de build, no a la ubicación del Dockerfile.
#
# Construir desde la raíz del repositorio:
#     docker build -f web/Dockerfile -t servicio-web .
#
# Ejecutar publicando el puerto HTTP:
#     docker run --rm -p 8080:8080 \
#         -e TSP_SERVER_HOST=servidor-central \
#         -e TSP_TCP_PORT=6000 \
#         -e WEB_PORT=8080 \
#         servicio-web
#
# El Servicio_Web usa SOLO la biblioteca estándar de Python (Req. 9.1), por lo
# que NO se ejecuta `pip install` de dependencias de producción. La imagen se
# basa en `python:3-slim`. Hypothesis (PBT) es solo dependencia de desarrollo y
# no forma parte de la imagen.
FROM python:3-slim

WORKDIR /app

# Se copia la Biblioteca_TSP y el Servicio_Web. `servicio_web.py` inserta
# `../clients` en sys.path de forma relativa a __file__, así que la estructura
# hermana clients/ + web/ dentro de /app basta para importar `tsp`. Además se
# fija PYTHONPATH=/app/clients como ruta preferida en contenedores (Req. 9.2).
COPY clients/ /app/clients/
COPY web/ /app/web/

# Localización por DNS y puertos por variable de entorno (Req. 2.1, 2.6, 2.9).
# WEB_PORT define el puerto HTTP de escucha (Req. 9.4). El servicio se enlaza a
# todas las interfaces ("") para ser accesible desde fuera del contenedor.
ENV PYTHONPATH=/app/clients
ENV WEB_PORT=8080

EXPOSE 8080

# El CMD ejecuta el Servicio_Web, que escucha en WEB_PORT.
CMD ["python", "/app/web/servicio_web.py"]
