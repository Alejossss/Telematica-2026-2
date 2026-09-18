// ======================================================
// protocol.c - Implementacion de la sintaxis TSP/1.0
// ======================================================

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <ctype.h>
#include <errno.h>

#include "protocol.h"

// ======================================================
// BUFFER DE SALIDA
// ======================================================

void tsp_sbuf_init(tsp_sbuf_t *sb, char *buf, size_t cap) {
    sb->buf      = buf;
    sb->cap      = cap;
    sb->len      = 0;
    sb->overflow = 0;

    if (cap > 0) {
        buf[0] = '\0';
    }
}

int tsp_sbuf_addf(tsp_sbuf_t *sb, const char *fmt, ...) {
    if (sb->overflow || sb->cap == 0) {
        return -1;
    }

    size_t disponible = sb->cap - sb->len;

    if (disponible <= 1) {
        sb->overflow = 1;
        return -1;
    }

    va_list args;
    va_start(args, fmt);

    int escritos = vsnprintf(sb->buf + sb->len, disponible, fmt, args);

    va_end(args);

    if (escritos < 0) {
        sb->overflow = 1;
        return -1;
    }

    // vsnprintf trunca: si no cabia, marcamos desbordamiento
    if ((size_t)escritos >= disponible) {
        sb->buf[sb->len] = '\0';
        sb->overflow = 1;
        return -1;
    }

    sb->len += (size_t)escritos;

    return 0;
}

// ======================================================
// SEPARACION DE MENSAJES EN EL FLUJO TCP
// ======================================================

void tsp_linebuf_init(tsp_linebuf_t *lb) {
    lb->len        = 0;
    lb->discarding = 0;
    lb->data[0]    = '\0';
}

int tsp_linebuf_push(tsp_linebuf_t *lb, const char *data, size_t n) {
    int resultado = TSP_OK;

    for (size_t i = 0; i < n; i++) {
        char c = data[i];

        // Estamos tirando los restos de una linea sobredimensionada
        if (lb->discarding) {
            if (c == TSP_TERMINATOR) {
                lb->discarding = 0;
            }
            continue;
        }

        // La linea supera el limite del protocolo (R5)
        if (lb->len + 1 >= sizeof(lb->data)) {
            lb->len        = 0;
            lb->discarding = (c != TSP_TERMINATOR);
            resultado      = TSP_ERR_MESSAGE_TOO_LONG;
            continue;
        }

        lb->data[lb->len++] = c;
    }

    return resultado;
}

int tsp_linebuf_next(tsp_linebuf_t *lb, char *out, size_t cap) {
    size_t fin = 0;
    int    encontrado = 0;

    for (size_t i = 0; i < lb->len; i++) {
        if (lb->data[i] == TSP_TERMINATOR) {
            fin        = i;
            encontrado = 1;
            break;
        }
    }

    if (!encontrado) {
        return 0;
    }

    size_t largo = fin;

    // R2: se tolera el fin de linea de Windows
    if (largo > 0 && lb->data[largo - 1] == '\r') {
        largo--;
    }

    // R5: la linea entra en el buffer pero excede el limite del
    // protocolo. Se avisa al llamador para que responda ERR|413 en
    // lugar de analizar un mensaje truncado.
    int demasiado_larga = (largo >= TSP_MAX_MESSAGE);

    if (largo >= cap) {
        largo = cap - 1;
    }

    memcpy(out, lb->data, largo);
    out[largo] = '\0';

    // Se descarta la linea consumida y se conserva el resto
    size_t restante = lb->len - (fin + 1);

    memmove(lb->data, lb->data + fin + 1, restante);

    lb->len = restante;

    return demasiado_larga ? 2 : 1;
}

// ======================================================
// ANALISIS DE MENSAJES
// ======================================================

void tsp_to_upper(char *s) {
    for (; *s; s++) {
        *s = (char)toupper((unsigned char)*s);
    }
}

int tsp_parse(const char *line, tsp_message_t *msg) {
    msg->count = 0;

    if (line == NULL) {
        return TSP_ERR_BAD_REQUEST;
    }

    size_t largo = strlen(line);

    if (largo == 0) {
        return TSP_ERR_BAD_REQUEST;
    }

    if (largo >= TSP_MAX_MESSAGE) {
        return TSP_ERR_MESSAGE_TOO_LONG;
    }

    size_t pos_campo = 0;
    int    indice    = 0;

    msg->field[0][0] = '\0';

    for (size_t i = 0; i <= largo; i++) {
        char c = line[i];

        if (c == TSP_SEPARATOR || c == '\0') {

            msg->field[indice][pos_campo] = '\0';

            indice++;
            pos_campo = 0;

            if (c == '\0') {
                break;
            }

            if (indice >= TSP_MAX_FIELDS) {
                return TSP_ERR_BAD_REQUEST;
            }

            msg->field[indice][0] = '\0';
            continue;
        }

        // R4: dentro de un campo no puede haber caracteres de control
        if ((unsigned char)c < 0x20) {
            return TSP_ERR_BAD_REQUEST;
        }

        if (pos_campo + 1 >= TSP_FIELD_LEN) {
            return TSP_ERR_BAD_REQUEST;
        }

        msg->field[indice][pos_campo++] = c;
    }

    msg->count = indice;

    // R3: el primer campo es el tipo y no puede estar vacio
    if (msg->count == 0 || msg->field[0][0] == '\0') {
        return TSP_ERR_BAD_REQUEST;
    }

    tsp_to_upper(msg->field[0]);

    return TSP_OK;
}

int tsp_valid_identifier(const char *s) {
    if (s == NULL || *s == '\0') {
        return 0;
    }

    for (const char *p = s; *p; p++) {
        unsigned char c = (unsigned char)*p;

        if (!isalnum(c) && c != '_' && c != '-' && c != '.') {
            return 0;
        }
    }

    return 1;
}

int tsp_parse_double(const char *s, double *out) {
    if (s == NULL || *s == '\0') {
        return 0;
    }

    char  *fin = NULL;
    errno = 0;

    double valor = strtod(s, &fin);

    // R8: debe consumirse todo el campo y ser un numero valido
    if (errno != 0 || fin == s || *fin != '\0') {
        return 0;
    }

    *out = valor;

    return 1;
}

int tsp_parse_long(const char *s, long *out) {
    if (s == NULL || *s == '\0') {
        return 0;
    }

    char *fin = NULL;
    errno = 0;

    long valor = strtol(s, &fin, 10);

    if (errno != 0 || fin == s || *fin != '\0') {
        return 0;
    }

    *out = valor;

    return 1;
}

// ======================================================
// CONSTRUCCION DE ERRORES
// ======================================================

const char *tsp_error_symbol(int code) {
    switch (code) {
        case TSP_ERR_BAD_REQUEST:      return "BAD_REQUEST";
        case TSP_ERR_UNKNOWN_COMMAND:  return "UNKNOWN_COMMAND";
        case TSP_ERR_MISSING_PARAM:    return "MISSING_PARAM";
        case TSP_ERR_INVALID_PARAM:    return "INVALID_PARAM";
        case TSP_ERR_NODE_NOT_FOUND:   return "NODE_NOT_FOUND";
        case TSP_ERR_NO_DATA:          return "NO_DATA";
        case TSP_ERR_NOT_REGISTERED:   return "NOT_REGISTERED";
        case TSP_ERR_LIMIT_REACHED:    return "LIMIT_REACHED";
        case TSP_ERR_MESSAGE_TOO_LONG: return "MESSAGE_TOO_LONG";
        case TSP_ERR_SERVER_FULL:      return "SERVER_FULL";
        case TSP_ERR_INTERNAL:         return "INTERNAL_ERROR";
        default:                       return "INTERNAL_ERROR";
    }
}

int tsp_format_error(char *out, size_t cap, int code, const char *desc) {
    int escritos = snprintf(
        out,
        cap,
        "ERR|%d|%s|%s\n",
        code,
        tsp_error_symbol(code),
        desc != NULL ? desc : "Error"
    );

    if (escritos < 0 || (size_t)escritos >= cap) {
        return 0;
    }

    return escritos;
}
