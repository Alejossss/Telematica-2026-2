# ======================================================
# Plataforma Distribuida de Telemetria
#
#   make            compila el servidor
#   make clients    compila los clientes de prueba en C
#   make all        compila todo
#   make run        compila y arranca el servidor
#   make clean      borra los binarios
# ======================================================

CC      = gcc
CFLAGS  = -Wall -Wextra -O2
LDFLAGS = -pthread

SRV_DIR = server

# El servidor central: sockets y concurrencia (puntos 4 y 6) mas la
# logica de aplicacion y el protocolo TSP/1.0 (puntos 3 y 5)
SERVER_SRC = $(SRV_DIR)/server_concurrent.c \
             $(SRV_DIR)/protocol.c \
             $(SRV_DIR)/registry.c \
             $(SRV_DIR)/handlers.c

SERVER_HDR = $(SRV_DIR)/protocol.h \
             $(SRV_DIR)/registry.h \
             $(SRV_DIR)/handlers.h

SERVER_BIN = $(SRV_DIR)/server_concurrent

# Clientes de prueba en C (sockets crudos, utiles para demostrar el
# protocolo a mano)
CLIENT_BINS = $(SRV_DIR)/client_tcp_test $(SRV_DIR)/client_udp_test

.PHONY: all server clients run clean

server: $(SERVER_BIN)

all: server clients

$(SERVER_BIN): $(SERVER_SRC) $(SERVER_HDR)
	$(CC) $(CFLAGS) -o $@ $(SERVER_SRC) $(LDFLAGS)

clients: $(CLIENT_BINS)

$(SRV_DIR)/client_tcp_test: $(SRV_DIR)/client_tcp_test.c
	$(CC) $(CFLAGS) -o $@ $<

$(SRV_DIR)/client_udp_test: $(SRV_DIR)/client_udp_test.c
	$(CC) $(CFLAGS) -o $@ $<

run: $(SERVER_BIN)
	./$(SERVER_BIN)

clean:
	rm -f $(SERVER_BIN) $(CLIENT_BINS) $(SRV_DIR)/*.o
