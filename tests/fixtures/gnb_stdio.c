#include <stdio.h>
#include <unistd.h>

int main(void)
{
    printf("N2: Connection to AMF on 192.168.3.201:38412 completed\n");
    printf("==== gNB started ===\nType <h> to view help\n");
    /* Signal startup completion independently of buffered stdout. */
    if (write(STDERR_FILENO, "1", 1) != 1) {
        return 1;
    }
    for (;;) {
        pause();
    }
}
