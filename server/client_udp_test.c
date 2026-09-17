#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <arpa/inet.h>
#include <sys/socket.h>

#define UDP_PORT 5000
#define SERVER_IP "127.0.0.1"
#define BUFFER_SIZE 1024

int main(void) {
    int sock_fd;

    struct sockaddr_in server_addr;
    socklen_t server_addr_len = sizeof(server_addr);

    char buffer[BUFFER_SIZE];

    // 1. Crear socket UDP
    sock_fd = socket(AF_INET, SOCK_DGRAM, 0);

    if (sock_fd < 0) {
        perror("Error creando socket UDP");
        return 1;
    }

    printf("[CLIENTE UDP] Socket creado correctamente\n");

    // 2. Configurar dirección del servidor
    memset(&server_addr, 0, sizeof(server_addr));

    server_addr.sin_family = AF_INET;
    server_addr.sin_port = htons(UDP_PORT);

    if (inet_pton(AF_INET, SERVER_IP, &server_addr.sin_addr) <= 0) {
        perror("Dirección IP inválida");
        close(sock_fd);
        return 1;
    }

    // 3. Mensaje temporal de prueba
    const char *message = "Hola servidor UDP";

    // 4. Enviar datagrama
    if (sendto(
            sock_fd,
            message,
            strlen(message),
            0,
            (struct sockaddr *)&server_addr,
            sizeof(server_addr)
        ) < 0) {

        perror("Error enviando datagrama");
        close(sock_fd);
        return 1;
    }

    printf("[CLIENTE UDP] Datagrama enviado: %s\n", message);

    // 5. Esperar respuesta
    memset(buffer, 0, sizeof(buffer));

    ssize_t bytes_received = recvfrom(
        sock_fd,
        buffer,
        sizeof(buffer) - 1,
        0,
        (struct sockaddr *)&server_addr,
        &server_addr_len
    );

    if (bytes_received < 0) {
        perror("Error recibiendo respuesta");
        close(sock_fd);
        return 1;
    }

    buffer[bytes_received] = '\0';

    printf("[CLIENTE UDP] Respuesta: %s\n", buffer);

    // 6. Cerrar socket
    close(sock_fd);

    printf("[CLIENTE UDP] Socket cerrado\n");

    return 0;
}