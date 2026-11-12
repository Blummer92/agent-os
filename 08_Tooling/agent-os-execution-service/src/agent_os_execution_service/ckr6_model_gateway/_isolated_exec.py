"""Launcher run AS ROOT by supervisor.spawn_isolated_worker, then replaced by the worker.

Order matters: unshare the network namespace and set no_new_privs while still
privileged, drop to the worker's UNIQUE unprivileged uid, PROVE root cannot be
regained and that the namespace holds no interface but loopback, signal
readiness on an inherited pipe, and only then exec the worker. Any failure
exits 97 before the worker starts (the supervisor turns that into a raise).
"""
import ctypes
import os
import socket
import sys

uid = int(sys.argv[1])
ready_fd = int(sys.argv[2])
argv = sys.argv[sys.argv.index("--") + 1:]
try:
    if os.geteuid() != 0 or uid == 0 or not argv:
        raise PermissionError("needs root, a non-root uid, and a command")
    os.unshare(os.CLONE_NEWNET)  # empty network namespace: no route to any provider
    if any(name != "lo" for _, name in socket.if_nameindex()):
        raise OSError("namespace is not empty")
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
        raise OSError("no_new_privs")
    os.setgroups([])
    os.setgid(uid)
    os.setuid(uid)
    if (os.getuid(), os.geteuid(), os.getgid(), os.getegid()) != (uid,) * 4:
        raise OSError("uid drop incomplete")
    try:
        os.setuid(0)
    except PermissionError:
        pass
    else:
        raise OSError("root was regained")
    try:
        os.unshare(os.CLONE_NEWNET)
    except PermissionError:
        pass
    else:
        raise OSError("namespace capability retained")
    os.write(ready_fd, b"R")  # readiness: every check above passed
    os.set_inheritable(ready_fd, False)  # closes at exec: the worker never sees it
except Exception:
    sys.stderr.write("isolation-unavailable\n")
    os._exit(97)
os.execv(argv[0], argv)
