// ======================================================
// handlers.h - Semantica del protocolo TSP/1.0
//
// Une la sintaxis (protocol.c) con el estado del
// servidor central (registry.c): decide que significa
// cada mensaje y construye la respuesta.
// ======================================================

#ifndef HANDLERS_H
#define HANDLERS_H

#include <stddef.h>

// Rol que toma una conexion TCP segun su primer mensaje
typedef enum {
    TSP_ROLE_UNKNOWN = 0,
    TSP_ROLE_OPERATOR,
    TSP_ROLE_NODE
} tsp_role_t;

typedef struct {
    int         fd;
    int         slot;          // slot en la tabla de sesiones, -1 si no hay
    tsp_role_t  rol;
    int         cerrar;        // el servidor debe cerrar tras responder (BYE)
    char        direccion[64];
    char       *respuesta;     // buffer de respuesta (heap, TSP_RESPONSE_MAX)
} tsp_session_t;

// Devuelve TSP_OK, o TSP_ERR_SERVER_FULL si no quedan slots
int  handlers_session_init(tsp_session_t *s, int fd, const char *direccion);
void handlers_session_end(tsp_session_t *s);

// Procesa una linea recibida por TCP y deja la respuesta en s->respuesta.
// Devuelve cuantos bytes hay que enviar (0 = no responder).
size_t handlers_process_tcp_line(tsp_session_t *s, const char *linea);

// Construye la respuesta a un error detectado antes de analizar
// el mensaje (por ejemplo, linea demasiado larga).
size_t handlers_build_error(tsp_session_t *s, int codigo, const char *desc);

// Procesa un datagrama UDP y deja la respuesta en out.
// Devuelve cuantos bytes hay que enviar (0 = no responder).
size_t handlers_process_udp(const char *datagrama,
                            const char *direccion,
                            char *out,
                            size_t cap);

#endif // HANDLERS_H
