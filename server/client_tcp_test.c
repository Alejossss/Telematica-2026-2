#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <arpa/inet.h>
#include <sys/socket.h>

#define TCP_PORT 6000
#define SERVER_IP "127.0.0.1"
#define BUFFER_SIZE 1024

int main(void) {
    int sock_fd;
    struct sockaddr_in server_addr;

    char buffer[BUFFER_SIZE];

    // 1. Crear socket TCP
    sock_fd = socket(AF_INET, SOCK_STREAM, 0);

    if (sock_fd < 0) {
        perror("Error creando socket TCP");
        return 1;
    }

    printf("[CLIENTE] Socket creado correctamente\n");

    // 2. Configurar direccion del servidor
    memset(&server_addr, 0, sizeof(server_addr));

    server_addr.sin_family = AF_INET;
    server_addr.sin_port = htons(TCP_PORT);

    if (inet_pton(
            AF_INET,
            SERVER_IP,
            &server_addr.sin_addr
        ) <= 0) {

        perror("Direccion IP invalida");
        close(sock_fd);
        return 1;
    }

    // 3. Conectarse al servidor
    if (connect(
            sock_fd,
            (struct sockaddr *)&server_addr,
            sizeof(server_addr)
        ) < 0) {

        perror("Error conectando al servidor");
        close(sock_fd);
        return 1;
    }

    printf("[CLIENTE] Conectado al servidor\n");
    printf("[CLIENTE] Escribe EXIT para cerrar la conexion\n\n");

    // 4. Mantener conexion activa
    while (1) {
        memset(buffer, 0, sizeof(buffer));

        printf("Mensaje: ");

        if (fgets(buffer, sizeof(buffer), stdin) == NULL) {
            printf("\nError leyendo entrada\n");
            break;
        }

        // Eliminar salto de linea
        buffer[strcspn(buffer, "\n")] = '\0';

        // No enviar mensajes vacios
        if (strlen(buffer) == 0) {
            continue;
        }

        // 5. Enviar mensaje
        if (send(
                sock_fd,
                buffer,
                strlen(buffer),
                0
            ) < 0) {

            perror("Error enviando mensaje");
            break;
        }

        // Guardamos si el usuario pidio salir
        int exit_requested = strcmp(buffer, "EXIT") == 0;

        // 6. Esperar respuesta del servidor
        memset(buffer, 0, sizeof(buffer));

        ssize_t bytes_received = recv(
            sock_fd,
            buffer,
            sizeof(buffer) - 1,
            0
        );

        if (bytes_received < 0) {
            perror("Error recibiendo respuesta");
            break;
        }

        if (bytes_received == 0) {
            printf("[CLIENTE] El servidor cerro la conexion\n");
            break;
        }

        buffer[bytes_received] = '\0';

        printf("[SERVIDOR] %s\n\n", buffer);

        if (exit_requested) {
            printf("[CLIENTE] Conexion finalizada\n");
            break;
        }
    }

    // 7. Cerrar socket
    close(sock_fd);

    return 0;
}