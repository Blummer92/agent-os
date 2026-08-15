/*
 * WSC-AUTO1C -- minimal clone3(CLONE_INTO_CGROUP) launcher.
 *
 * This extension exists solely because a race-free way to place a child
 * process directly into a target cgroup v2 subtree does not exist through
 * plain subprocess.Popen()/posix_spawn() plus a later "cgroup.procs"
 * migration (the child can exec or fork before migration completes -- a
 * real race), and because CPython documents its own C API as unsafe to call
 * from a child produced by a raw fork-like operation in a threaded process.
 * The Linux kernel documents CLONE_INTO_CGROUP as the supported way to
 * create a child directly inside a target cgroup v2 directory (see
 * clone3(2), cgroups(7)).
 *
 * Everything up to and including the clone3() syscall itself runs with the
 * ordinary CPython C API and the GIL held, exactly like any other
 * extension function. The moment the syscall returns 0 (we are the new
 * child), execution drops onto a narrow, pre-computed, async-signal-safe
 * path: dup2 the three standard streams, chdir, setsid, execve -- using
 * only plain libc wrappers around those specific POSIX async-signal-safe
 * calls, on buffers already built by the parent before the clone (argv,
 * envp, and cwd are plain C arrays/strings, not any live Python object
 * access). No Py_* call, no heap allocation, and no return into Python
 * happens on this path. If any step fails, the child reports the phase and
 * errno through a dedicated O_CLOEXEC self-pipe and exits -- it never
 * falls back to any other launch mechanism.
 *
 * This module exposes exactly two entry points: spawn() and probe(). It has
 * no shell, no arbitrary runner API, no networking, no credential handling,
 * no persistence, no scheduler/workflow surface, and no other cgroup
 * operation.
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <errno.h>
#include <fcntl.h>
#include <sched.h>
#include <signal.h>
#include <stdint.h>
#include <string.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;

#ifndef CLONE_INTO_CGROUP
#define CLONE_INTO_CGROUP 0x200000000ULL
#endif

#ifndef SYS_clone3
/* clone3 is syscall 435 on every architecture that has it (x86_64, i386,
 * aarch64, arm, and every other architecture sharing the "generic" table
 * clone3 was introduced under). Kernel headers on the build host may not
 * define SYS_clone3 even when the running kernel supports the syscall, so
 * this fallback keeps the build working; the real availability check is
 * the runtime probe() below, not this macro. */
#define SYS_clone3 435
#endif

/* Mirrors the kernel's struct clone_args (linux/sched.h) ABI exactly --
 * defined locally instead of included so the build does not depend on a
 * particular kernel-headers package providing it. */
struct agentos_clone_args {
    uint64_t flags;
    uint64_t pidfd;
    uint64_t child_tid;
    uint64_t parent_tid;
    uint64_t exit_signal;
    uint64_t stack;
    uint64_t stack_size;
    uint64_t tls;
    uint64_t set_tid;
    uint64_t set_tid_size;
    uint64_t cgroup;
};

enum agentos_launch_phase {
    AGENTOS_PHASE_DUP2 = 1,
    AGENTOS_PHASE_CHDIR = 2,
    AGENTOS_PHASE_SETSID = 3,
    AGENTOS_PHASE_EXECVE = 4,
};

struct agentos_error_record {
    int32_t phase;
    int32_t err;
};

/* Async-signal-safe: write() only, fixed-size record, no allocation. */
static void
agentos_child_report_and_die(int errpipe_write_fd, enum agentos_launch_phase phase, int err)
{
    struct agentos_error_record rec;
    rec.phase = (int32_t)phase;
    rec.err = (int32_t)err;
    /* Best-effort: if this write itself fails there is nothing further that
     * can be safely done from here. */
    (void)write(errpipe_write_fd, &rec, sizeof(rec));
    _exit(127);
}

/* Runs only in the child, only on the narrow post-clone3 path. Every
 * argument is a plain C pointer already materialized by the parent before
 * the clone -- no Python object is touched from here on. */
static void
agentos_child_exec(
    int errpipe_write_fd,
    int stdin_fd,
    int stdout_fd,
    int stderr_fd,
    const char *cwd,
    char *const *argv,
    char *const *envp
) {
    if (stdin_fd != STDIN_FILENO && dup2(stdin_fd, STDIN_FILENO) < 0) {
        agentos_child_report_and_die(errpipe_write_fd, AGENTOS_PHASE_DUP2, errno);
    }
    if (stdout_fd != STDOUT_FILENO && dup2(stdout_fd, STDOUT_FILENO) < 0) {
        agentos_child_report_and_die(errpipe_write_fd, AGENTOS_PHASE_DUP2, errno);
    }
    if (stderr_fd != STDERR_FILENO && dup2(stderr_fd, STDERR_FILENO) < 0) {
        agentos_child_report_and_die(errpipe_write_fd, AGENTOS_PHASE_DUP2, errno);
    }
    if (cwd != NULL && chdir(cwd) < 0) {
        agentos_child_report_and_die(errpipe_write_fd, AGENTOS_PHASE_CHDIR, errno);
    }
    if (setsid() < 0) {
        agentos_child_report_and_die(errpipe_write_fd, AGENTOS_PHASE_SETSID, errno);
    }
    execve(argv[0], argv, envp);
    /* Only reached when execve() itself failed. */
    agentos_child_report_and_die(errpipe_write_fd, AGENTOS_PHASE_EXECVE, errno);
}

static const char *
agentos_phase_name(int32_t phase)
{
    switch (phase) {
        case AGENTOS_PHASE_DUP2:
            return "dup2";
        case AGENTOS_PHASE_CHDIR:
            return "chdir";
        case AGENTOS_PHASE_SETSID:
            return "setsid";
        case AGENTOS_PHASE_EXECVE:
            return "execve";
        default:
            return "unknown";
    }
}

static PyObject *
clone3_cgroup_spawn(PyObject *self, PyObject *args, PyObject *kwargs)
{
    (void)self;
    static char *kwlist[] = {
        "argv", "cwd", "env", "cgroup_fd", "stdin_fd", "stdout_fd", "stderr_fd", NULL
    };

    PyObject *argv_obj = NULL;
    PyObject *cwd_obj = Py_None;
    PyObject *env_obj = Py_None;
    int cgroup_fd = -1;
    int stdin_fd = -1;
    int stdout_fd = -1;
    int stderr_fd = -1;

    if (!PyArg_ParseTupleAndKeywords(
            args, kwargs, "O|OOiiii", kwlist,
            &argv_obj, &cwd_obj, &env_obj,
            &cgroup_fd, &stdin_fd, &stdout_fd, &stderr_fd)) {
        return NULL;
    }

    if (!PyList_Check(argv_obj) || PyList_Size(argv_obj) < 1) {
        PyErr_SetString(PyExc_ValueError, "argv must be a non-empty list of strings");
        return NULL;
    }
    if (cgroup_fd < 0 || stdin_fd < 0 || stdout_fd < 0 || stderr_fd < 0) {
        PyErr_SetString(PyExc_ValueError, "cgroup_fd/stdin_fd/stdout_fd/stderr_fd are required");
        return NULL;
    }

    Py_ssize_t argc = PyList_Size(argv_obj);
    char **argv_c = PyMem_RawMalloc((size_t)(argc + 1) * sizeof(char *));
    if (argv_c == NULL) {
        return PyErr_NoMemory();
    }
    for (Py_ssize_t i = 0; i < argc; i++) {
        PyObject *item = PyList_GetItem(argv_obj, i); /* borrowed */
        const char *s = PyUnicode_AsUTF8(item);
        if (s == NULL) {
            PyMem_RawFree(argv_c);
            return NULL;
        }
        argv_c[i] = (char *)s;
    }
    argv_c[argc] = NULL;

    char **envp_c = environ;
    char **envp_owned = NULL;
    if (env_obj != Py_None) {
        if (!PyList_Check(env_obj)) {
            PyMem_RawFree(argv_c);
            PyErr_SetString(PyExc_ValueError, "env must be a list of 'KEY=VALUE' strings or None");
            return NULL;
        }
        Py_ssize_t envc = PyList_Size(env_obj);
        envp_owned = PyMem_RawMalloc((size_t)(envc + 1) * sizeof(char *));
        if (envp_owned == NULL) {
            PyMem_RawFree(argv_c);
            return PyErr_NoMemory();
        }
        for (Py_ssize_t i = 0; i < envc; i++) {
            PyObject *item = PyList_GetItem(env_obj, i); /* borrowed */
            const char *s = PyUnicode_AsUTF8(item);
            if (s == NULL) {
                PyMem_RawFree(argv_c);
                PyMem_RawFree(envp_owned);
                return NULL;
            }
            envp_owned[i] = (char *)s;
        }
        envp_owned[envc] = NULL;
        envp_c = envp_owned;
    }

    const char *cwd_c = NULL;
    if (cwd_obj != Py_None) {
        cwd_c = PyUnicode_AsUTF8(cwd_obj);
        if (cwd_c == NULL) {
            PyMem_RawFree(argv_c);
            if (envp_owned) PyMem_RawFree(envp_owned);
            return NULL;
        }
    }

    int errpipe[2];
    if (pipe2(errpipe, O_CLOEXEC) < 0) {
        PyMem_RawFree(argv_c);
        if (envp_owned) PyMem_RawFree(envp_owned);
        return PyErr_SetFromErrno(PyExc_OSError);
    }

    struct agentos_clone_args ca;
    memset(&ca, 0, sizeof(ca));
    ca.flags = CLONE_INTO_CGROUP;
    ca.exit_signal = SIGCHLD;
    ca.cgroup = (uint64_t)cgroup_fd;

    /* Everything the child needs (argv_c, envp_c, cwd_c, the fd numbers,
     * the errpipe write end) is already fully materialized above -- this
     * is the "prepared in the parent before clone" buffer set. */
    long pid = syscall(SYS_clone3, &ca, sizeof(ca));

    if (pid < 0) {
        int saved_errno = errno;
        close(errpipe[0]);
        close(errpipe[1]);
        PyMem_RawFree(argv_c);
        if (envp_owned) PyMem_RawFree(envp_owned);
        errno = saved_errno;
        return PyErr_SetFromErrno(PyExc_OSError);
    }

    if (pid == 0) {
        /* Child: narrow async-signal-safe path only, no Py_* calls below
         * this point, no heap allocation, no return to Python. */
        close(errpipe[0]);
        agentos_child_exec(
            errpipe[1], stdin_fd, stdout_fd, stderr_fd, cwd_c, argv_c, envp_c
        );
        _exit(127); /* unreachable */
    }

    /* Parent. */
    close(errpipe[1]);
    PyMem_RawFree(argv_c);
    if (envp_owned) PyMem_RawFree(envp_owned);

    struct agentos_error_record rec;
    memset(&rec, 0, sizeof(rec));
    ssize_t n = read(errpipe[0], &rec, sizeof(rec));
    close(errpipe[0]);

    if (n == (ssize_t)sizeof(rec)) {
        return Py_BuildValue("(isi)", (int)pid, agentos_phase_name(rec.phase), (int)rec.err);
    }
    return Py_BuildValue("(iOi)", (int)pid, Py_None, 0);
}

static PyObject *
clone3_cgroup_probe(PyObject *self, PyObject *Py_UNUSED(ignored))
{
    (void)self;
    /* A NULL/zero-size clone3 call fails fast (EFAULT/EINVAL) on any
     * kernel that recognizes the syscall at all, and fails with ENOSYS on
     * one that does not -- with no process created either way. */
    long rc = syscall(SYS_clone3, NULL, (size_t)0);
    if (rc < 0 && errno == ENOSYS) {
        Py_RETURN_FALSE;
    }
    Py_RETURN_TRUE;
}

static PyMethodDef clone3_cgroup_methods[] = {
    {
        "spawn",
        (PyCFunction)clone3_cgroup_spawn,
        METH_VARARGS | METH_KEYWORDS,
        "spawn(argv, cwd=None, env=None, *, cgroup_fd, stdin_fd, stdout_fd, stderr_fd)\n"
        "-> (pid, exec_failure_phase_or_None, errno)\n\n"
        "Launches argv[0] directly inside the cgroup identified by "
        "cgroup_fd via clone3(CLONE_INTO_CGROUP). Raises OSError if the "
        "clone3() syscall itself fails (no process created). On success "
        "the pid is always returned; exec_failure_phase is None on a "
        "clean handoff to execve, or a phase name ('dup2'|'chdir'|"
        "'setsid'|'execve') plus the child's errno if the already-cloned "
        "child could not reach the target program -- the caller is "
        "responsible for reaping that pid.",
    },
    {
        "probe",
        clone3_cgroup_probe,
        METH_NOARGS,
        "probe() -> bool\n\n"
        "True if this kernel implements the clone3() syscall at all "
        "(CLONE_INTO_CGROUP support still requires a cgroup v2 target). "
        "Spawns no process.",
    },
    {NULL, NULL, 0, NULL},
};

static struct PyModuleDef clone3_cgroup_module = {
    PyModuleDef_HEAD_INIT,
    "_clone3_cgroup",
    "Minimal clone3(CLONE_INTO_CGROUP) launcher backing WSC-AUTO1C process-tree containment.",
    -1,
    clone3_cgroup_methods,
};

PyMODINIT_FUNC
PyInit__clone3_cgroup(void)
{
    return PyModule_Create(&clone3_cgroup_module);
}
