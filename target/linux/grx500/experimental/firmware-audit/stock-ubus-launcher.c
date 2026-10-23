/* SPDX-License-Identifier: GPL-2.0-only
 * Run only inside the test's private bubblewrap root/PID/network namespaces.
 * Supplies the real stock ubusd to the real stock nvrammanager under QEMU.
 * The existing /bin/sh capture fixture still prevents all flash/reboot commands.
 */
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <signal.h>
#include <stdio.h>
#include <unistd.h>

int main(void)
{
	pid_t server, checker;
	struct stat st;
	int i, status;
	if (mkdir("/tmp/run", 0700) != 0)
		return 90;
	server = fork();
	if (server < 0)
		return 91;
	if (!server) {
		execl("/qemu", "/qemu", "-strace", "/sbin/ubusd", (char *)0);
		_exit(92);
	}
	for (i = 0; i < 100; i++) {
		if (!stat("/var/run/ubus.sock", &st) && S_ISSOCK(st.st_mode))
			break;
		usleep(20000);
	}
	if (i == 100) {
		kill(server, SIGTERM);
		waitpid(server, 0, 0);
		return 93;
	}
	checker = fork();
	if (checker < 0) {
		kill(server, SIGTERM);
		waitpid(server, 0, 0);
		return 94;
	}
	if (!checker) {
		execl("/qemu", "/qemu", "-strace", "/usr/bin/nvrammanager",
		      "-u", "/work/input.bin", (char *)0);
		_exit(95);
	}
	if (waitpid(checker, &status, 0) != checker)
		status = -1;
	kill(server, SIGTERM);
	waitpid(server, 0, 0);
	if (status == -1 || !WIFEXITED(status))
		return 96;
	return WEXITSTATUS(status);
}
