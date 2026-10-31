// Нативы Python-плагинов для Pawn и форварды из Python в Pawn.
#include <Python.h>

#include <array>
#include <map>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include "amxx_api.h"
#include "module.h"
#include "natives.h"
#include "python_host.h"

namespace {

constexpr size_t kMaxNatives = 512;
constexpr size_t kMaxForwardParams = 12;

struct NativeEntry {
    std::string name;
    std::string params;  // коды типов: i f b s p
    char returns;        // i f b s p v
};

// Всё ниже живёт до конца процесса: AMXX хранит указатели на имена и таблицу
std::vector<NativeEntry> g_natives;
std::vector<AMX_NATIVE_INFO> g_table;
std::vector<std::string> g_libraries;
bool g_registered = false;

std::map<std::string, int> g_forwards;  // имя → id форварда на текущую карту

cell CallNative(size_t slot, AMX* amx, cell* params);

// AMX_NATIVE не передаёт контекст, поэтому у каждого слота своя функция-заглушка
template <size_t N>
cell EXT_FUNC NativeStub(AMX* amx, cell* params) {
    return CallNative(N, amx, params);
}

template <size_t... I>
constexpr std::array<AMX_NATIVE, sizeof...(I)> MakeStubs(std::index_sequence<I...>) {
    return {{&NativeStub<I>...}};
}

const std::array<AMX_NATIVE, kMaxNatives> kStubs = MakeStubs(std::make_index_sequence<kMaxNatives>{});

PyObject* ParamToPython(char code, AMX* amx, cell value) {
    switch (code) {
    case 'f':
        return PyFloat_FromDouble(amx_ctof(value));
    case 'b':
        return PyBool_FromLong(value != 0);
    case 's': {
        int length = 0;
        const char* text = g_amxx.GetAmxString(amx, value, 0, &length);
        return PyUnicode_DecodeUTF8(text ? text : "", text ? length : 0, "replace");
    }
    default:
        return PyLong_FromLong(value);
    }
}

cell CallNative(size_t slot, AMX* amx, cell* params) {
    const NativeEntry& native = g_natives[slot];
    const size_t given = static_cast<size_t>(params[0]) / sizeof(cell);
    const size_t needed = native.params.size() + (native.returns == 's' ? 2 : 0);
    if (given < needed) {
        g_amxx.LogError(amx, AMX_ERR_NATIVE, "[amxpy] %s: expected %u parameters, got %u", native.name.c_str(),
                        static_cast<unsigned>(needed), static_cast<unsigned>(given));
        return 0;
    }

    Gil gil;
    PyObject* args = PyList_New(static_cast<Py_ssize_t>(native.params.size()));
    if (!args) {
        PyErr_Print();
        return 0;
    }
    for (size_t i = 0; i < native.params.size(); ++i)
        PyList_SET_ITEM(args, static_cast<Py_ssize_t>(i), ParamToPython(native.params[i], amx, params[i + 1]));

    PyObject* result = g_python.CallNative(native.name.c_str(), args);
    if (!result)
        return 0;
    cell ret = 0;
    switch (native.returns) {
    case 'f':
        ret = amx_ftoc(static_cast<float>(PyFloat_AsDouble(result)));
        break;
    case 's': {
        // строка — в буфер Pawn (output[], maxlen), результат — длина
        Py_ssize_t length = 0;
        const char* text = PyUnicode_Check(result) ? PyUnicode_AsUTF8AndSize(result, &length) : "";
        const size_t base = native.params.size() + 1;
        ret = g_amxx.SetAmxString(amx, params[base], text ? text : "", params[base + 1]);
        break;
    }
    case 'v':
        break;
    default:
        ret = static_cast<cell>(PyLong_AsLong(result));
        break;
    }
    if (PyErr_Occurred())
        PyErr_Print();
    Py_DECREF(result);
    return ret;
}

int RegisterForward(const char* name, const int* t, size_t n) {
    // параметры передаются как varargs, поэтому вызов разворачивается по числу параметров
    switch (n) {
    case 0: return g_amxx.RegisterForward(name, ET_IGNORE, FP_DONE);
    case 1: return g_amxx.RegisterForward(name, ET_IGNORE, t[0], FP_DONE);
    case 2: return g_amxx.RegisterForward(name, ET_IGNORE, t[0], t[1], FP_DONE);
    case 3: return g_amxx.RegisterForward(name, ET_IGNORE, t[0], t[1], t[2], FP_DONE);
    case 4: return g_amxx.RegisterForward(name, ET_IGNORE, t[0], t[1], t[2], t[3], FP_DONE);
    case 5: return g_amxx.RegisterForward(name, ET_IGNORE, t[0], t[1], t[2], t[3], t[4], FP_DONE);
    case 6: return g_amxx.RegisterForward(name, ET_IGNORE, t[0], t[1], t[2], t[3], t[4], t[5], FP_DONE);
    case 7: return g_amxx.RegisterForward(name, ET_IGNORE, t[0], t[1], t[2], t[3], t[4], t[5], t[6], FP_DONE);
    case 8: return g_amxx.RegisterForward(name, ET_IGNORE, t[0], t[1], t[2], t[3], t[4], t[5], t[6], t[7], FP_DONE);
    case 9:
        return g_amxx.RegisterForward(name, ET_IGNORE, t[0], t[1], t[2], t[3], t[4], t[5], t[6], t[7], t[8], FP_DONE);
    case 10:
        return g_amxx.RegisterForward(name, ET_IGNORE, t[0], t[1], t[2], t[3], t[4], t[5], t[6], t[7], t[8], t[9],
                                      FP_DONE);
    case 11:
        return g_amxx.RegisterForward(name, ET_IGNORE, t[0], t[1], t[2], t[3], t[4], t[5], t[6], t[7], t[8], t[9],
                                      t[10], FP_DONE);
    default:
        return g_amxx.RegisterForward(name, ET_IGNORE, t[0], t[1], t[2], t[3], t[4], t[5], t[6], t[7], t[8], t[9],
                                      t[10], t[11], FP_DONE);
    }
}

// Все аргументы — по 4 байта (cell или char*): на i386 так передаёт и AMXX
int ExecuteForward(int id, const intptr_t* a, size_t n) {
    switch (n) {
    case 0: return g_amxx.ExecuteForward(id);
    case 1: return g_amxx.ExecuteForward(id, a[0]);
    case 2: return g_amxx.ExecuteForward(id, a[0], a[1]);
    case 3: return g_amxx.ExecuteForward(id, a[0], a[1], a[2]);
    case 4: return g_amxx.ExecuteForward(id, a[0], a[1], a[2], a[3]);
    case 5: return g_amxx.ExecuteForward(id, a[0], a[1], a[2], a[3], a[4]);
    case 6: return g_amxx.ExecuteForward(id, a[0], a[1], a[2], a[3], a[4], a[5]);
    case 7: return g_amxx.ExecuteForward(id, a[0], a[1], a[2], a[3], a[4], a[5], a[6]);
    case 8: return g_amxx.ExecuteForward(id, a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7]);
    case 9: return g_amxx.ExecuteForward(id, a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7], a[8]);
    case 10: return g_amxx.ExecuteForward(id, a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7], a[8], a[9]);
    case 11: return g_amxx.ExecuteForward(id, a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7], a[8], a[9], a[10]);
    default:
        return g_amxx.ExecuteForward(id, a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7], a[8], a[9], a[10], a[11]);
    }
}

}  // namespace

void Natives_RegisterAll() {
    Gil gil;
    PyObject* specs = g_python.NativeSpecs();  // [(плагин, имя, параметры, результат), ...]
    if (!specs)
        return;
    std::set<std::string> libraries;
    Py_ssize_t count = PySequence_Size(specs);
    for (Py_ssize_t i = 0; i < count; ++i) {
        PyObject* item = PySequence_GetItem(specs, i);
        const char *plugin, *name, *params, *returns;
        if (item && PyArg_ParseTuple(item, "ssss", &plugin, &name, &params, &returns)) {
            if (g_natives.size() < kMaxNatives) {
                g_natives.push_back({name, params, returns[0]});
                libraries.insert(plugin);
            } else {
                ServerPrintf("[amxpy] too many natives, %s is not registered\n", name);
            }
        } else {
            PyErr_Print();
        }
        Py_XDECREF(item);
    }
    Py_DECREF(specs);

    g_table.reserve(g_natives.size() + 1);
    for (size_t i = 0; i < g_natives.size(); ++i)
        g_table.push_back({g_natives[i].name.c_str(), kStubs[i]});
    g_table.push_back({nullptr, nullptr});
    if (!g_natives.empty())
        g_amxx.AddNatives(g_table.data());

    // библиотека на каждый плагин с нативами: в Pawn работает #pragma reqlib <плагин>
    g_libraries.reserve(libraries.size());
    for (const std::string& library : libraries) {
        g_libraries.push_back(library);
        g_amxx.AddLibraries(g_libraries.back().c_str(), LibType_Library, &g_libraries);
    }
    g_registered = true;
}

bool Natives_Declare(const char* name, const char* params, const char* returns) {
    if (!g_registered)
        return true;  // загрузка при старте: натив попадёт в таблицу в Natives_RegisterAll
    for (const NativeEntry& native : g_natives) {
        if (native.name == name)
            return native.params == params && native.returns == returns[0];
    }
    return false;
}

void Forwards_Reset() {
    g_forwards.clear();
}

int Forwards_Execute(const char* name, const char* types, PyObject* args) {
    const size_t count = std::strlen(types);
    if (count > kMaxForwardParams) {
        PyErr_Format(PyExc_ValueError, "forward %s: at most %d parameters", name, static_cast<int>(kMaxForwardParams));
        return -1;
    }
    if (!PyTuple_Check(args) || static_cast<size_t>(PyTuple_GET_SIZE(args)) != count) {
        PyErr_Format(PyExc_TypeError, "forward %s: expected a tuple of %d values", name, static_cast<int>(count));
        return -1;
    }
    if (!g_plugins_loaded)
        return 0;  // Pawn-плагинов ещё нет

    auto found = g_forwards.find(name);
    int id;
    if (found == g_forwards.end()) {
        int param_types[kMaxForwardParams];
        for (size_t i = 0; i < count; ++i)
            param_types[i] = types[i] == 's' ? FP_STRING : FP_CELL;  // float идёт битами в cell
        id = RegisterForward(name, param_types, count);
        g_forwards.emplace(name, id);
    } else {
        id = found->second;
    }
    if (id < 0)
        return 0;

    intptr_t values[kMaxForwardParams];
    std::vector<std::string> strings;
    strings.reserve(count);
    for (size_t i = 0; i < count; ++i) {
        PyObject* value = PyTuple_GET_ITEM(args, static_cast<Py_ssize_t>(i));
        if (types[i] == 's') {
            const char* text = PyUnicode_AsUTF8(value);
            strings.emplace_back(text ? text : "");
            values[i] = reinterpret_cast<intptr_t>(strings.back().c_str());
        } else if (types[i] == 'f') {
            values[i] = amx_ftoc(static_cast<float>(PyFloat_AsDouble(value)));
        } else {
            values[i] = static_cast<cell>(PyLong_AsLong(value));
        }
        if (PyErr_Occurred())
            return -1;
    }
    return ExecuteForward(id, values, count);
}
