// ======================================================
// protocol.h - Capa de protocolo TSP/1.0
//
// Punto 5 del proyecto: protocolo propio de capa de
// aplicacion, basado en texto.
//
// Este modulo solo se ocupa de la SINTAXIS del protocolo:
// analizar una linea, validarla, construir errores y
// separar el flujo TCP en mensajes. La semantica vive en
// handlers.c y el estado del sistema en registry.c
//
// Especificacion completa: docs/PROTOCOLO.md
// ======================================================

#ifndef PROTOCOL_H
#define PROTOCOL_H

#include <stddef.h>

// ------------------------------------------------------
// Constantes del protocolo
// ------------------------------------------------------

#define TSP_VERSION        "TSP/1.0"
#define TSP_SERVER_ID      "TSP-SERVER-1"

#define TSP_SEPARATOR      '|'
#define TSP_TERMINATOR     '\n'

#define TSP_MAX_MESSAGE    1024   // R5: tamano maximo de un mensaje
#define TSP_MAX_FIELDS       24   // campos maximos por mensaje
#define TSP_FIELD_LEN       128   // longitud maxima de un campo

#define TSP_RESPONSE_MAX  32768   // respuestas multiples (LIST_NODES, GET_LAST...)

// ------------------------------------------------------
// Codigos de error (seccion 5 de docs/PROTOCOLO.md)
// ------------------------------------------------------

#define TSP_OK                    0
#define TSP_ERR_BAD_REQUEST     400
#define TSP_ERR_UNKNOWN_COMMAND 401
#define TSP_ERR_MISSING_PARAM   402
#define TSP_ERR_INVALID_PARAM   403
#define TSP_ERR_NODE_NOT_FOUND  404
#define TSP_ERR_NO_DATA         405
#define TSP_ERR_NOT_REGISTERED  406
#define TSP_ERR_LIMIT_REACHED   409
#define TSP_ERR_MESSAGE_TOO_LONG 413
#define TSP_ERR_INTERNAL        500
#define TSP_ERR_SERVER_FULL     503

// ------------------------------------------------------
// Mensaje analizado
// ------------------------------------------------------

typedef struct {
    int  count;                                  // numero de campos
    char field[TSP_MAX_FIELDS][TSP_FIELD_LEN];   // field[0] es el tipo
} tsp_message_t;

// ------------------------------------------------------
// Buffer de salida con control de capacidad
//
// Evita desbordar la respuesta cuando hay muchos nodos,
// mediciones o alertas.
// ------------------------------------------------------

typedef struct {
    char   *buf;
    size_t  cap;
    size_t  len;
    int     overflow;
} tsp_sbuf_t;

void tsp_sbuf_init(tsp_sbuf_t *sb, char *buf, size_t cap);
int  tsp_sbuf_addf(tsp_sbuf_t *sb, const char *fmt, ...);

// ------------------------------------------------------
// Separacion de mensajes en el flujo TCP
//
// TCP no conserva fronteras de mensaje: un recv() puede
// traer medio mensaje o tres mensajes juntos. Este buffer
// acumula bytes y entrega lineas completas.
// ------------------------------------------------------

typedef struct {
    char   data[TSP_MAX_MESSAGE * 2];
    size_t len;
    int    discarding;   // descartando una linea demasiado larga
} tsp_linebuf_t;

void tsp_linebuf_init(tsp_linebuf_t *lb);

// Devuelve 0 o TSP_ERR_MESSAGE_TOO_LONG si hubo que descartar
int  tsp_linebuf_push(tsp_linebuf_t *lb, const char *data, size_t n);

// Extrae la siguiente linea completa. Devuelve:
//   0 = todavia no hay una linea entera en el buffer
//   1 = linea extraida correctamente
//   2 = la linea superaba el limite del protocolo; se consume igual
//       y en "out" queda solo el principio, para responder ERR|413
int  tsp_linebuf_next(tsp_linebuf_t *lb, char *out, size_t cap);

// ------------------------------------------------------
// Analisis y construccion de mensajes
// ------------------------------------------------------

// Analiza una linea (sin '\n'). Devuelve TSP_OK o un codigo de error.
int tsp_parse(const char *line, tsp_message_t *msg);

// Nombre simbolico de un codigo de error: 404 -> "NODE_NOT_FOUND"
const char *tsp_error_symbol(int code);

// Construye "ERR|<codigo>|<SIMBOLO>|<descripcion>\n"
int tsp_format_error(char *out, size_t cap, int code, const char *desc);

// Utilidades de validacion
void tsp_to_upper(char *s);
int  tsp_parse_double(const char *s, double *out);
int  tsp_parse_long(const char *s, long *out);
int  tsp_valid_identifier(const char *s);

#endif // PROTOCOL_H
