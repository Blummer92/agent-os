"""Launcher run AS ROOT by supervisor.spawn_isolated_worker, then replaced by the worker.

Order matters: unshare the network namespace and set no_new_privs while still
privileged, then drop to an unprivileged uid, PROVE root cannot be regained,
and only then exec the worker. Any failure exits 97 before the worker starts.
"""
import ctypes
import os
import sys

uid = int(sys.argv[1])
argv = sys.argv[sys.argv.index("--") + 1:]
try:
    if os.geteuid() != 0 or uid == 0:
        raise PermissionError("needs root to isolate")
    os.unshare(os.CLONE_NEWNET)  # empty network namespace: no route to any provider
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
        raise OSError("no_new_privs")
    os.setgroups([])
    os.setgid(uid)
    os.setuid(uid)
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
except Exception:
    sys.stderr.write("isolation-unavailable\n")
    os._exit(97)
os.execv(argv[0], argv)
