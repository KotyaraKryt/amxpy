// Встроенный CPython: запуск, GIL и вызовы точек входа amxpy._entry.
#pragma once

#include <string>
#include <vector>

typedef struct _object PyObject;

// Аргумент события на границе C++ ↔ Python
struct EventValue {
    enum class Kind { Int, Float, Str };
    Kind kind = Kind::Int;
    long i = 0;
    double f = 0.0;
    std::string s;

    static EventValue Int(long value) {
        EventValue v;
        v.i = value;
        return v;
    }
    static EventValue Float(double value) {
        EventValue v;
        v.kind = Kind::Float;
        v.f = value;
        return v;
    }
    static EventValue Str(std::string value) {
        EventValue v;
        v.kind = Kind::Str;
        v.s = std::move(value);
        return v;
    }
};

// Ответ рантайма на pre-событие
struct EventAnswer {
    bool blocked = false;     // игре действие не выполнять
    bool has_result = false;  // плагин ответил за игру
    long result = 0;
    bool changed = false;  // args — изменённые аргументы
    std::vector<EventValue> args;
};

class PythonHost {
public:
    bool Start(const std::string& game_dir);
    void Shutdown();
    bool Running() const { return running_; }

    void OnFrame();
    void OnMapStart(const char* map);
    void OnMapEnd();
    std::string OnClientConnect(int index, const char* name, const char* ip);  // причина отказа или ""
    void OnClientPutInServer(int index);
    void OnClientDisconnect(int index);
    // true — команда обработана; handled — её уже обработал другой плагин Metamod (AMXX)
    bool OnClientCommand(int index, bool handled);
    void OnServerCommand();
    EventAnswer OnEvent(const char* hook, bool post, const std::vector<EventValue>& args, long result = 0);
    // Pawn-форвард пришёл в плагин-приёмник: номер public и сырые ячейки аргументов
    long OnPawnForward(int id, void* amx, const std::vector<long>& args);

    // Вызывающий уже держит GIL
    PyObject* NativeSpecs();
    PyObject* CallNative(const char* name, PyObject* args);  // забирает ссылку на args

private:
    PyObject* Call(PyObject* fn, std::vector<PyObject*> args);  // забирает ссылки на args

    bool running_ = false;
    PyObject* fn_frame_ = nullptr;
    PyObject* fn_map_start_ = nullptr;
    PyObject* fn_map_end_ = nullptr;
    PyObject* fn_connect_ = nullptr;
    PyObject* fn_putinserver_ = nullptr;
    PyObject* fn_disconnect_ = nullptr;
    PyObject* fn_client_command_ = nullptr;
    PyObject* fn_server_command_ = nullptr;
    PyObject* fn_event_ = nullptr;
    PyObject* fn_natives_ = nullptr;
    PyObject* fn_call_native_ = nullptr;
    PyObject* fn_shutdown_ = nullptr;
    PyObject* fn_pawn_forward_ = nullptr;
};

extern PythonHost g_python;

// GIL на время вызова Python. Повторный вход из того же (игрового) потока безопасен:
// Python → движок → снова Python (форвард → натив и т.п.).
class Gil {
public:
    Gil();
    ~Gil();
    Gil(const Gil&) = delete;
    Gil& operator=(const Gil&) = delete;
};

PyObject* PyStr(const char* text);  // UTF-8 с заменой битых байтов (ники в cp1251 и т.п.)
