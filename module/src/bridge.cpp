// Вызов нативов AMX Mod X и других модулей из Python.
//
// Python собирает крошечный .amxx, в таблице нативов которого перечислены нужные
// имена, и просит ядро AMXX загрузить его (LoadAmxScript): ядро само привязывает
// нативы модулей, ядра и Pawn-плагинов. Отсюда берутся адреса функций и память
// AMX под строки, массивы и ссылки на время вызова.
#include <Python.h>

#include <cstring>
#include <string>
#include <vector>

#include "amxx_api.h"
#include "bridge.h"
#include "python_host.h"

namespace {

#pragma pack(push, 1)
// tagAMX из AMX Mod X SDK (public/sdk/amxxmodule.h), i386
struct AmxVm {
    unsigned char* base;
    unsigned char* data;
    void* callback;
    void* debug;
    cell cip, frm, hea, hlw, stk, stp;
    int flags;
    long usertags[4];
    void* userdata[4];
    int error;
    int paramcount;
    cell pri, alt, reset_stk, reset_hea, sysreq_d;
    int reloc_size;
    long code_size;
};

// AMX_HEADER (amx.h)
struct AmxHeader {
    int32_t size;
    uint16_t magic;
    char file_version;
    char amx_version;
    int16_t flags;
    int16_t defsize;
    int32_t cod, dat, hea, stp, cip, publics, natives, libraries, pubvars, tags, nametable;
};

struct AmxFuncStub {  // AMX_FUNCSTUBNT
    uint32_t address;
    uint32_t nameofs;
};
#pragma pack(pop)

static_assert(sizeof(AmxHeader) == 56, "AMX_HEADER layout");
constexpr int kUtNative = 3;  // amx->usertags[UT_NATIVE]: номер натива для сообщений об ошибках

std::vector<AmxVm*> g_bridges;

AmxVm* BridgeAt(int id) {
    if (id < 0 || id >= static_cast<int>(g_bridges.size())) {
        PyErr_SetString(PyExc_ValueError, "unknown bridge");
        return nullptr;
    }
    return g_bridges[id];
}

// Аргумент, который после вызова нужно прочитать обратно
struct Output {
    char kind;
    cell* cells;
    int count;
};

PyObject* ReadOutput(const Output& out) {
    switch (out.kind) {
    case 'b': {
        std::string text;
        for (int i = 0; i < out.count && out.cells[i] != 0; ++i)
            text.push_back(static_cast<char>(out.cells[i] & 0xFF));
        return PyUnicode_DecodeUTF8(text.data(), static_cast<Py_ssize_t>(text.size()), "replace");
    }
    case 'r':
        return PyLong_FromLong(out.cells[0]);
    case 'q':
        return PyFloat_FromDouble(amx_ctof(out.cells[0]));
    case 'a':
    case 'v': {
        PyObject* list = PyList_New(out.count);
        if (!list)
            return nullptr;
        for (int i = 0; i < out.count; ++i) {
            PyObject* item = out.kind == 'a' ? PyLong_FromLong(out.cells[i]) : PyFloat_FromDouble(amx_ctof(out.cells[i]));
            if (!item) {
                Py_DECREF(list);
                return nullptr;
            }
            PyList_SET_ITEM(list, i, item);
        }
        return list;
    }
    default:
        Py_RETURN_NONE;
    }
}

// Данные AMX: amx->data или сегмент данных образа
unsigned char* AmxData(AmxVm* vm) {
    return vm->data ? vm->data : vm->base + reinterpret_cast<AmxHeader*>(vm->base)->dat;
}

// Адрес AMX → ячейки с проверкой границ (данные, куча и стек: [0, stp])
cell* AmxCells(AmxVm* vm, long addr, long count) {
    if (!vm || addr < 0 || count < 0 || addr % static_cast<long>(sizeof(cell)) != 0 ||
        addr + count * static_cast<long>(sizeof(cell)) > static_cast<long>(vm->stp) + static_cast<long>(sizeof(cell)))
        return nullptr;
    return reinterpret_cast<cell*>(AmxData(vm) + addr);
}

AmxVm* AmxFromPython(PyObject* object) {
    void* ptr = PyLong_AsVoidPtr(object);
    if (!ptr && !PyErr_Occurred())
        PyErr_SetString(PyExc_ValueError, "null AMX");
    return static_cast<AmxVm*>(ptr);
}

// __amxpy_forward(номер) из public плагина-приёмника: аргументы public — в его кадре, как у getarg
cell PawnForward(AMX* amx, cell* params) {
    AmxVm* vm = reinterpret_cast<AmxVm*>(amx);
    auto* frame = reinterpret_cast<cell*>(AmxData(vm) + vm->frm);  // [frm]: frm, cip, байты аргументов, аргументы
    const int count = frame[2] / static_cast<int>(sizeof(cell));
    std::vector<long> args(frame + 3, frame + 3 + (count > 0 ? count : 0));
    return static_cast<cell>(g_python.OnPawnForward(params[1], amx, args));
}

const AMX_NATIVE_INFO kBridgeNatives[] = {{"__amxpy_forward", PawnForward}, {nullptr, nullptr}};

}  // namespace

void Bridge_RegisterNatives() {
    g_amxx.AddNatives(kBridgeNatives);
}

// amx_read(amx, адрес, ячеек) -> [ячейки]
PyObject* AmxRead(PyObject*, PyObject* args) {
    PyObject* object;
    long addr, count;
    if (!PyArg_ParseTuple(args, "Oll", &object, &addr, &count))
        return nullptr;
    AmxVm* vm = AmxFromPython(object);
    cell* cells = AmxCells(vm, addr, count);
    if (!cells) {
        if (!PyErr_Occurred())
            PyErr_SetString(PyExc_IndexError, "AMX address out of range");
        return nullptr;
    }
    PyObject* list = PyList_New(count);
    for (long i = 0; list && i < count; ++i)
        PyList_SET_ITEM(list, i, PyLong_FromLong(cells[i]));
    return list;
}

// amx_string(amx, адрес, максимум) -> str: строка Pawn (байт на ячейку) в UTF-8
PyObject* AmxString(PyObject*, PyObject* args) {
    PyObject* object;
    long addr, limit;
    if (!PyArg_ParseTuple(args, "Oll", &object, &addr, &limit))
        return nullptr;
    AmxVm* vm = AmxFromPython(object);
    std::string text;
    for (long i = 0; i < limit; ++i) {
        cell* c = AmxCells(vm, addr + i * static_cast<long>(sizeof(cell)), 1);
        if (!c) {
            if (!PyErr_Occurred())
                PyErr_SetString(PyExc_IndexError, "AMX address out of range");
            return nullptr;
        }
        if (*c == 0)
            break;
        text.push_back(static_cast<char>(*c & 0xFF));
    }
    return PyUnicode_DecodeUTF8(text.data(), static_cast<Py_ssize_t>(text.size()), "replace");
}

// amx_write(amx, адрес, [ячейки]) — значения параметров по ссылке обратно в Pawn
PyObject* AmxWrite(PyObject*, PyObject* args) {
    PyObject* object;
    long addr;
    PyObject* list;
    if (!PyArg_ParseTuple(args, "OlO!", &object, &addr, &PyList_Type, &list))
        return nullptr;
    AmxVm* vm = AmxFromPython(object);
    cell* cells = AmxCells(vm, addr, PyList_GET_SIZE(list));
    if (!cells) {
        if (!PyErr_Occurred())
            PyErr_SetString(PyExc_IndexError, "AMX address out of range");
        return nullptr;
    }
    for (Py_ssize_t i = 0; i < PyList_GET_SIZE(list); ++i) {
        cells[i] = static_cast<cell>(PyLong_AsLong(PyList_GET_ITEM(list, i)));
        if (PyErr_Occurred())
            return nullptr;
    }
    Py_RETURN_NONE;
}

// load_bridge(путь) -> (id или -1, [адрес натива или 0 по порядку таблицы], ошибка)
PyObject* BridgeLoad(PyObject*, PyObject* args) {
    const char* path;
    if (!PyArg_ParseTuple(args, "s", &path))
        return nullptr;
    // размер AMX у ядра совпадает с SDK; запас — на случай расхождений сборок
    auto* amx = reinterpret_cast<AmxVm*>(new char[512]());
    void* program = nullptr;
    char error[64] = {};
    g_amxx.LoadAmxScript(reinterpret_cast<AMX*>(amx), &program, path, error, 0);
    if (!amx->base)  // не дошло до amx_Init: образ не принят
        return Py_BuildValue("(iNs)", -1, PyList_New(0), error[0] ? error : "the bridge was not loaded");

    // Скрипт уже в списке загруженных ядром: AMX живёт до выключения сервера.
    // При «unknown function» привязаны все остальные нативы — читаем их адреса.
    g_bridges.push_back(amx);
    auto* hdr = reinterpret_cast<AmxHeader*>(amx->base);
    const int count = (hdr->libraries - hdr->natives) / hdr->defsize;
    PyObject* addresses = PyList_New(count);
    if (!addresses)
        return nullptr;
    for (int i = 0; i < count; ++i) {
        auto* stub = reinterpret_cast<AmxFuncStub*>(amx->base + hdr->natives + i * hdr->defsize);
        PyList_SET_ITEM(addresses, i, PyLong_FromUnsignedLong(stub->address));
    }
    return Py_BuildValue("(iNs)", static_cast<int>(g_bridges.size()) - 1, addresses, error);
}

// call_bridge(id, номер натива, адрес, [(код, значение), ...]) -> (результат, [выходы], код ошибки AMX)
//   i — число, f — float, s — строка, b — буфер строки (значение — размер),
//   r/q — ссылка на число/float, a/v — массив чисел/float (читается обратно)
PyObject* BridgeCall(PyObject*, PyObject* args) {
    int id, index;
    unsigned long address;
    PyObject* list;
    if (!PyArg_ParseTuple(args, "iikO!", &id, &index, &address, &PyList_Type, &list))
        return nullptr;
    AmxVm* amx = BridgeAt(id);
    if (!amx)
        return nullptr;
    auto native = reinterpret_cast<AMX_NATIVE>(address);
    if (!native) {
        PyErr_SetString(PyExc_ValueError, "native is not bound");
        return nullptr;
    }

    const Py_ssize_t count = PyList_GET_SIZE(list);
    // Нули после аргументов: значения по умолчанию подставляет компилятор Pawn, а не натив, поэтому
    // натив читает все свои параметры — пропущенный из Python прочтётся как 0, а не как чужая память.
    constexpr size_t kPadding = 16;
    std::vector<cell> params(static_cast<size_t>(count) + 1 + kPadding, 0);
    std::vector<Output> outputs;
    const cell saved_hea = amx->hea;
    auto fail = [&](PyObject* type, const char* message) -> PyObject* {
        amx->hea = saved_hea;
        if (!PyErr_Occurred())
            PyErr_SetString(type, message);
        return nullptr;
    };
    auto allot = [&](int cells, cell* addr) -> cell* {
        cell* phys = nullptr;
        if (cells <= 0 || g_amxx.amx_Allot(reinterpret_cast<AMX*>(amx), cells, addr, &phys) != 0)
            return nullptr;
        return phys;
    };

    for (Py_ssize_t i = 0; i < count; ++i) {
        PyObject* item = PyList_GET_ITEM(list, i);
        const char* code;
        PyObject* value;
        if (!PyArg_ParseTuple(item, "sO", &code, &value))
            return fail(PyExc_TypeError, "bad argument spec");
        cell& param = params[static_cast<size_t>(i) + 1];
        switch (code[0]) {
        case 'i':
            param = static_cast<cell>(PyLong_AsLong(value));
            break;
        case 'f':
            param = amx_ftoc(static_cast<float>(PyFloat_AsDouble(value)));
            break;
        case 's': {
            Py_ssize_t size;
            const char* text = PyUnicode_AsUTF8AndSize(value, &size);
            if (!text)
                return fail(PyExc_TypeError, "string expected");
            cell* cells = allot(static_cast<int>(size) + 1, &param);
            if (!cells)
                return fail(PyExc_MemoryError, "AMX heap is full");
            for (Py_ssize_t c = 0; c < size; ++c)
                cells[c] = static_cast<unsigned char>(text[c]);
            cells[size] = 0;
            break;
        }
        case 'b': {
            const int size = static_cast<int>(PyLong_AsLong(value));
            cell* cells = allot(size, &param);
            if (!cells)
                return fail(PyExc_MemoryError, "AMX heap is full");
            std::memset(cells, 0, sizeof(cell) * static_cast<size_t>(size));
            outputs.push_back({'b', cells, size});
            break;
        }
        case 'r':
        case 'q': {
            cell* cells = allot(1, &param);
            if (!cells)
                return fail(PyExc_MemoryError, "AMX heap is full");
            cells[0] = code[0] == 'r' ? static_cast<cell>(PyLong_AsLong(value))
                                      : amx_ftoc(static_cast<float>(PyFloat_AsDouble(value)));
            outputs.push_back({code[0], cells, 1});
            break;
        }
        case 'a':
        case 'v': {
            PyObject* seq = PySequence_Fast(value, "sequence expected");
            if (!seq)
                return fail(PyExc_TypeError, "sequence expected");
            const int size = static_cast<int>(PySequence_Fast_GET_SIZE(seq));
            cell* cells = allot(size > 0 ? size : 1, &param);
            if (!cells) {
                Py_DECREF(seq);
                return fail(PyExc_MemoryError, "AMX heap is full");
            }
            for (int c = 0; c < size; ++c) {
                PyObject* v = PySequence_Fast_GET_ITEM(seq, c);
                cells[c] = code[0] == 'a' ? static_cast<cell>(PyLong_AsLong(v))
                                          : amx_ftoc(static_cast<float>(PyFloat_AsDouble(v)));
            }
            Py_DECREF(seq);
            outputs.push_back({code[0], cells, size});
            break;
        }
        default:
            return fail(PyExc_ValueError, "unknown argument code");
        }
        if (PyErr_Occurred())
            return fail(PyExc_TypeError, "bad argument value");
    }
    params[0] = static_cast<cell>(count * sizeof(cell));

    amx->error = 0;
    amx->usertags[kUtNative] = index;
    const cell result = native(reinterpret_cast<AMX*>(amx), params.data());
    const int error = amx->error;
    amx->error = 0;

    PyObject* outs = PyList_New(static_cast<Py_ssize_t>(outputs.size()));
    if (!outs)
        return fail(PyExc_MemoryError, "out of memory");
    for (size_t i = 0; i < outputs.size(); ++i) {
        PyObject* value = ReadOutput(outputs[i]);
        if (!value) {
            Py_DECREF(outs);
            return fail(PyExc_RuntimeError, "cannot read native output");
        }
        PyList_SET_ITEM(outs, static_cast<Py_ssize_t>(i), value);
    }
    amx->hea = saved_hea;
    return Py_BuildValue("(lNi)", static_cast<long>(result), outs, error);
}
