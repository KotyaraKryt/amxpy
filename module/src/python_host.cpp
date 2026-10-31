// Встроенный CPython: запуск, GIL и вызовы точек входа amxpy._entry.
#include <Python.h>

#include <dlfcn.h>

#include <cstring>

#include "module.h"
#include "python_host.h"

PyObject* PyInit__amxpy();  // core_module.cpp

PythonHost g_python;

static PyThreadState* g_saved_state = nullptr;  // состояние игрового потока, пока GIL отпущен
static int g_gil_depth = 0;

Gil::Gil() {
    if (g_gil_depth++ == 0 && g_saved_state)
        PyEval_RestoreThread(g_saved_state);
}

Gil::~Gil() {
    if (--g_gil_depth == 0 && g_saved_state)
        g_saved_state = PyEval_SaveThread();
}

PyObject* PyStr(const char* text) {
    if (!text)
        text = "";
    return PyUnicode_DecodeUTF8(text, static_cast<Py_ssize_t>(std::strlen(text)), "replace");
}

static bool CheckStatus(PyStatus status, const char* what) {
    if (!PyStatus_Exception(status))
        return true;
    ServerPrintf("[amxpy] %s failed: %s%s%s\n", what, status.func ? status.func : "", status.func ? ": " : "",
                 status.err_msg ? status.err_msg : "unknown error");
    return false;
}

static bool AppendPath(PyConfig* config, const std::string& path) {
    wchar_t* wide = Py_DecodeLocale(path.c_str(), nullptr);
    if (!wide)
        return false;
    PyStatus status = PyWideStringList_Append(&config->module_search_paths, wide);
    PyMem_RawFree(wide);
    return CheckStatus(status, "module search path");
}

bool PythonHost::Start(const std::string& game_dir) {
    const std::string base = game_dir + "/addons/amxpy";
    const std::string home = base + "/runtime";
    const std::string stdlib = home + "/lib/python3.14";

    // Модули расширений (_ssl, _sqlite3, ...) ищут символы libpython в глобальной области,
    // а AMXX грузит модуль с RTLD_LOCAL — поднимаем libpython в глобальную область.
    if (!dlopen(AMXPY_PYTHON_SONAME, RTLD_NOW | RTLD_NOLOAD | RTLD_GLOBAL))
        ServerPrintf("[amxpy] warning: cannot make %s global: %s\n", AMXPY_PYTHON_SONAME, dlerror());

    if (PyImport_AppendInittab("_amxpy", PyInit__amxpy) != 0) {
        ServerPrintf("[amxpy] cannot register the _amxpy module\n");
        return false;
    }

    PyPreConfig preconfig;
    PyPreConfig_InitIsolatedConfig(&preconfig);
    preconfig.utf8_mode = 1;  // UTF-8 независимо от локали сервера
    if (!CheckStatus(Py_PreInitialize(&preconfig), "Python pre-initialization"))
        return false;

    PyConfig config;
    PyConfig_InitIsolatedConfig(&config);
    config.install_signal_handlers = 0;  // сигналы — забота движка
    config.write_bytecode = 0;
    config.buffered_stdio = 0;
    bool ok = CheckStatus(PyConfig_SetBytesString(&config, &config.home, home.c_str()), "Python home");
    config.module_search_paths_set = 1;
    ok = ok && AppendPath(&config, stdlib) && AppendPath(&config, stdlib + "/lib-dynload") &&
         AppendPath(&config, base + "/python") && AppendPath(&config, base + "/site-packages");
    if (ok)
        ok = CheckStatus(Py_InitializeFromConfig(&config), "Python initialization");
    PyConfig_Clear(&config);
    if (!ok)
        return false;

    PyObject* entry = PyImport_ImportModule("amxpy._entry");
    if (!entry) {
        PyErr_Print();
        g_saved_state = PyEval_SaveThread();
        return false;
    }
    struct {
        PyObject** slot;
        const char* name;
    } functions[] = {
        {&fn_frame_, "on_frame"},
        {&fn_map_start_, "on_map_start"},
        {&fn_map_end_, "on_map_end"},
        {&fn_connect_, "on_client_connect"},
        {&fn_putinserver_, "on_client_putinserver"},
        {&fn_disconnect_, "on_client_disconnect"},
        {&fn_client_command_, "on_client_command"},
        {&fn_server_command_, "on_server_command"},
        {&fn_event_, "on_event"},
        {&fn_natives_, "natives"},
        {&fn_call_native_, "call_native"},
        {&fn_shutdown_, "shutdown"},
        {&fn_pawn_forward_, "on_pawn_forward"},
    };
    for (auto& f : functions) {
        *f.slot = PyObject_GetAttrString(entry, f.name);
        if (!*f.slot) {
            PyErr_Print();
            Py_DECREF(entry);
            g_saved_state = PyEval_SaveThread();
            return false;
        }
    }
    PyObject* booted = PyObject_CallMethod(entry, "boot", "s", game_dir.c_str());
    Py_DECREF(entry);
    if (!booted) {
        PyErr_Print();
        g_saved_state = PyEval_SaveThread();
        return false;
    }
    Py_DECREF(booted);
    running_ = true;
    g_saved_state = PyEval_SaveThread();  // отпускаем GIL между кадрами: потоки offload() работают
    return true;
}

void PythonHost::Shutdown() {
    if (!running_)
        return;
    {
        Gil gil;
        Py_XDECREF(Call(fn_shutdown_, {}));
    }
    running_ = false;
    // Py_FinalizeEx не вызываем: процесс сервера завершается, а финализация с живыми
    // потоками и модулями расширений может уронить его на выходе.
}

PyObject* PythonHost::Call(PyObject* fn, std::vector<PyObject*> args) {
    for (PyObject* arg : args) {
        if (!arg) {
            for (PyObject* other : args)
                Py_XDECREF(other);
            PyErr_Print();
            return nullptr;
        }
    }
    PyObject* result = PyObject_Vectorcall(fn, args.data(), args.size(), nullptr);
    for (PyObject* arg : args)
        Py_DECREF(arg);
    if (!result)
        PyErr_Print();
    return result;
}

void PythonHost::OnFrame() {
    if (!running_)
        return;
    Gil gil;
    Py_XDECREF(Call(fn_frame_, {}));
}

void PythonHost::OnMapStart(const char* map) {
    if (!running_)
        return;
    Gil gil;
    Py_XDECREF(Call(fn_map_start_, {PyStr(map)}));
}

void PythonHost::OnMapEnd() {
    if (!running_)
        return;
    Gil gil;
    Py_XDECREF(Call(fn_map_end_, {}));
}

std::string PythonHost::OnClientConnect(int index, const char* name, const char* ip) {
    if (!running_)
        return {};
    Gil gil;
    PyObject* result = Call(fn_connect_, {PyLong_FromLong(index), PyStr(name), PyStr(ip)});
    std::string reason;
    if (result && PyUnicode_Check(result)) {
        const char* text = PyUnicode_AsUTF8(result);
        if (text)
            reason = text;
        else
            PyErr_Clear();
    }
    Py_XDECREF(result);
    return reason;
}

void PythonHost::OnClientPutInServer(int index) {
    if (!running_)
        return;
    Gil gil;
    Py_XDECREF(Call(fn_putinserver_, {PyLong_FromLong(index)}));
}

void PythonHost::OnClientDisconnect(int index) {
    if (!running_)
        return;
    Gil gil;
    Py_XDECREF(Call(fn_disconnect_, {PyLong_FromLong(index)}));
}

bool PythonHost::OnClientCommand(int index, bool handled) {
    if (!running_)
        return false;
    Gil gil;
    int argc = g_engfuncs.pfnCmd_Argc();
    PyObject* argv = PyList_New(argc);
    if (!argv) {
        PyErr_Print();
        return false;
    }
    for (int i = 0; i < argc; ++i)
        PyList_SET_ITEM(argv, i, PyStr(g_engfuncs.pfnCmd_Argv(i)));
    PyObject* result = Call(fn_client_command_,
                            {PyLong_FromLong(index), argv, PyStr(g_engfuncs.pfnCmd_Args()), PyBool_FromLong(handled)});
    bool taken = result && PyObject_IsTrue(result) == 1;
    Py_XDECREF(result);
    return taken;
}

void PythonHost::OnServerCommand() {
    if (!running_)
        return;
    Gil gil;
    int argc = g_engfuncs.pfnCmd_Argc();
    PyObject* argv = PyList_New(argc);
    if (!argv) {
        PyErr_Print();
        return;
    }
    for (int i = 0; i < argc; ++i)
        PyList_SET_ITEM(argv, i, PyStr(g_engfuncs.pfnCmd_Argv(i)));
    Py_XDECREF(Call(fn_server_command_, {argv}));
}

static PyObject* ToPython(const EventValue& value) {
    switch (value.kind) {
    case EventValue::Kind::Float:
        return PyFloat_FromDouble(value.f);
    case EventValue::Kind::Str:
        return PyStr(value.s.c_str());
    default:
        return PyLong_FromLong(value.i);
    }
}

static long ToLong(PyObject* value) {
    long result = PyFloat_Check(value) ? static_cast<long>(PyFloat_AsDouble(value)) : PyLong_AsLong(value);
    if (PyErr_Occurred()) {
        PyErr_Clear();
        result = PyObject_IsTrue(value) == 1;
    }
    return result;
}

EventAnswer PythonHost::OnEvent(const char* hook, bool post, const std::vector<EventValue>& args, long result) {
    EventAnswer answer;
    if (!running_)
        return answer;
    Gil gil;
    PyObject* list = PyList_New(static_cast<Py_ssize_t>(args.size()));
    if (!list) {
        PyErr_Print();
        return answer;
    }
    for (size_t i = 0; i < args.size(); ++i)
        PyList_SET_ITEM(list, static_cast<Py_ssize_t>(i), ToPython(args[i]));
    PyObject* reply = Call(fn_event_, {PyStr(hook), PyBool_FromLong(post), list, PyLong_FromLong(result)});
    if (!reply)
        return answer;
    // None — продолжить как есть; (заблокировать, ответ, новые аргументы)
    if (PyTuple_Check(reply) && PyTuple_GET_SIZE(reply) == 3) {
        PyObject* value = PyTuple_GET_ITEM(reply, 1);
        PyObject* new_args = PyTuple_GET_ITEM(reply, 2);
        if (PyObject_IsTrue(PyTuple_GET_ITEM(reply, 0)) == 1) {
            answer.blocked = true;
            if (value != Py_None) {
                answer.has_result = true;
                answer.result = ToLong(value);
            }
        } else if (new_args != Py_None && PySequence_Check(new_args) &&
                   PySequence_Size(new_args) == static_cast<Py_ssize_t>(args.size())) {
            answer.changed = true;
            answer.args = args;
            for (size_t i = 0; i < args.size(); ++i) {
                PyObject* item = PySequence_GetItem(new_args, static_cast<Py_ssize_t>(i));
                if (!item)
                    continue;
                EventValue& out = answer.args[i];
                if (out.kind == EventValue::Kind::Float)
                    out.f = PyFloat_AsDouble(item);
                else if (out.kind == EventValue::Kind::Int)
                    out.i = ToLong(item);
                else if (const char* text = PyUnicode_AsUTF8(item))
                    out.s = text;
                Py_DECREF(item);
                if (PyErr_Occurred())
                    PyErr_Clear();
            }
        }
    }
    Py_DECREF(reply);
    return answer;
}

long PythonHost::OnPawnForward(int id, void* amx, const std::vector<long>& args) {
    if (!running_)
        return 0;
    Gil gil;
    PyObject* list = PyList_New(static_cast<Py_ssize_t>(args.size()));
    if (!list) {
        PyErr_Print();
        return 0;
    }
    for (size_t i = 0; i < args.size(); ++i)
        PyList_SET_ITEM(list, static_cast<Py_ssize_t>(i), PyLong_FromLong(args[i]));
    PyObject* result = Call(fn_pawn_forward_, {PyLong_FromLong(id), PyLong_FromVoidPtr(amx), list});
    long value = result ? ToLong(result) : 0;
    Py_XDECREF(result);
    return value;
}

PyObject* PythonHost::NativeSpecs() {
    return running_ ? Call(fn_natives_, {}) : nullptr;
}

PyObject* PythonHost::CallNative(const char* name, PyObject* args) {
    if (!running_) {
        Py_XDECREF(args);
        return nullptr;
    }
    return Call(fn_call_native_, {PyStr(name), args});
}
