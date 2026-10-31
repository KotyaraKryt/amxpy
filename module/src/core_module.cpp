// Встроенный модуль _amxpy — бэкенд рантайма на сервере (протокол amxpy/_backend.py).
#include <Python.h>

#include <unistd.h>

#include <cstring>
#include <string>
#include <vector>

#include "amxx_api.h"
#include "bridge.h"
#include "hooks.h"
#include "module.h"
#include "natives.h"
#include "python_host.h"

namespace {

enum { kPrintChat = 0, kPrintConsole = 1, kPrintCenter = 2 };
enum { kLogInfo = 0, kLogWarning = 1, kLogError = 2 };
constexpr size_t kMaxChatBytes = 189;  // длиннее SayText клиент не покажет

// Обрезать UTF-8 по границе символа
std::string Utf8Prefix(const char* text, size_t max_bytes) {
    size_t length = std::strlen(text);
    if (length <= max_bytes)
        return text;
    size_t cut = max_bytes;
    while (cut > 0 && (static_cast<unsigned char>(text[cut]) & 0xC0) == 0x80)
        --cut;
    return std::string(text, cut);
}

std::string StripColors(const std::string& text) {
    std::string out;
    for (char c : text) {
        if (c != '\x01' && c != '\x03' && c != '\x04')
            out += c;
    }
    return out;
}

void SendChat(int index, const std::string& text) {
    edict_t* e = PlayerEdict(index);
    if (!e || (e->v.flags & FL_FAKECLIENT))
        return;
    if (!g_msg_saytext) {
        g_engfuncs.pfnClientPrintf(e, print_chat, (StripColors(text) + "\n").c_str());
        return;
    }
    g_engfuncs.pfnMessageBegin(MSG_ONE, g_msg_saytext, nullptr, e);
    g_engfuncs.pfnWriteByte(index);  // «отправитель» задаёт цвет !t — команда получателя
    g_engfuncs.pfnWriteString(text.c_str());
    g_engfuncs.pfnMessageEnd();
}

void Print(int index, int kind, const char* text) {
    edict_t* e = PlayerEdict(index);
    if (!e || (e->v.flags & FL_FAKECLIENT))
        return;
    g_engfuncs.pfnClientPrintf(e, kind == kPrintCenter ? print_center : print_console, text);
}

PyObject* NoPlayer(int index) {
    PyErr_Format(PyExc_LookupError, "no player in slot %d", index);
    return nullptr;
}

#define PARSE(fmt, ...)                                  \
    if (!PyArg_ParseTuple(args, fmt, __VA_ARGS__))       \
        return nullptr

#define PLAYER_OR_RAISE(var, index)       \
    edict_t* var = PlayerEdict(index);    \
    if (!var)                             \
        return NoPlayer(index)

// ---------------------------------------------------------------- сервер

PyObject* ServerPrint(PyObject*, PyObject* args) {
    const char* text;
    PARSE("s", &text);
    g_engfuncs.pfnServerPrint(text);
    Py_RETURN_NONE;
}

PyObject* Log(PyObject*, PyObject* args) {
    int level;
    const char* text;
    PARSE("is", &level, &text);
    const char* prefix = level >= kLogError ? "[ERROR] " : level == kLogWarning ? "[WARNING] " : "";
    std::string all = text;
    size_t start = 0;
    while (start <= all.size()) {  // журнал AMXX построчный
        size_t end = all.find('\n', start);
        std::string line = all.substr(start, end == std::string::npos ? std::string::npos : end - start);
        if (!line.empty())
            g_amxx.Log("%s%s", prefix, line.c_str());
        if (end == std::string::npos)
            break;
        start = end + 1;
    }
    Py_RETURN_NONE;
}

PyObject* ServerCommand(PyObject*, PyObject* args) {
    const char* text;
    PARSE("s", &text);
    std::string command = text;
    if (command.empty() || command.back() != '\n')
        command += '\n';
    g_engfuncs.pfnServerCommand(const_cast<char*>(command.c_str()));
    Py_RETURN_NONE;
}

PyObject* ServerExecute(PyObject*, PyObject*) {
    g_engfuncs.pfnServerExecute();
    Py_RETURN_NONE;
}

PyObject* MapName(PyObject*, PyObject*) {
    return PyStr(STRING(gpGlobals->mapname));
}

PyObject* MaxPlayers(PyObject*, PyObject*) {
    return PyLong_FromLong(gpGlobals->maxClients);
}

PyObject* GameTime(PyObject*, PyObject*) {
    return PyFloat_FromDouble(gpGlobals->time);
}

PyObject* GameDirectory(PyObject*, PyObject*) {
    char game[256] = {};
    g_engfuncs.pfnGetGameDir(game);
    char cwd[4096];
    std::string path = (game[0] != '/' && getcwd(cwd, sizeof cwd)) ? std::string(cwd) + "/" + game : game;
    return PyStr(path.c_str());
}

// ---------------------------------------------------------------- игроки

PyObject* Userid(PyObject*, PyObject* args) {
    int index;
    PARSE("i", &index);
    edict_t* e = PlayerEdict(index);
    int userid = e ? g_engfuncs.pfnGetPlayerUserId(e) : 0;
    return PyLong_FromLong(userid > 0 ? userid : 0);
}

PyObject* PlayerName(PyObject*, PyObject* args) {
    int index;
    PARSE("i", &index);
    PLAYER_OR_RAISE(e, index);
    return PyStr(STRING(e->v.netname));
}

PyObject* PlayerAuth(PyObject*, PyObject* args) {
    int index;
    PARSE("i", &index);
    edict_t* e = PlayerEdict(index);
    return PyStr(e ? g_engfuncs.pfnGetPlayerAuthId(e) : "");
}

PyObject* PlayerIp(PyObject*, PyObject* args) {
    int index;
    PARSE("i", &index);
    PLAYER_OR_RAISE(e, index);
    return PyStr(g_slots[index].ip.c_str());
}

PyObject* PlayerInfo(PyObject*, PyObject* args) {
    int index;
    const char* key;
    PARSE("is", &index, &key);
    PLAYER_OR_RAISE(e, index);
    return PyStr(g_engfuncs.pfnInfoKeyValue(g_engfuncs.pfnGetInfoKeyBuffer(e), const_cast<char*>(key)));
}

PyObject* IsBot(PyObject*, PyObject* args) {
    int index;
    PARSE("i", &index);
    PLAYER_OR_RAISE(e, index);
    return PyBool_FromLong((e->v.flags & FL_FAKECLIENT) != 0);
}

PyObject* IsAlive(PyObject*, PyObject* args) {
    int index;
    PARSE("i", &index);
    PLAYER_OR_RAISE(e, index);
    return PyBool_FromLong(e->v.deadflag == DEAD_NO && e->v.health > 0);
}

PyObject* PlayerTeam(PyObject*, PyObject* args) {
    int index;
    PARSE("i", &index);
    PLAYER_OR_RAISE(e, index);
    CBasePlayer* player = PlayerOf(index);
    return PyLong_FromLong(player ? static_cast<long>(player->m_iTeam) : g_amxx.GetPlayerTeamID(index));
}

PyObject* PlayerFlags(PyObject*, PyObject* args) {
    int index;
    PARSE("i", &index);
    PLAYER_OR_RAISE(e, index);
    return PyLong_FromLong(g_amxx.GetPlayerFlags(index));
}

PyObject* GetProp(PyObject*, PyObject* args) {
    int index;
    const char* name;
    PARSE("is", &index, &name);
    PLAYER_OR_RAISE(e, index);
    CBasePlayer* player = PlayerOf(index);
    if (!std::strcmp(name, "health"))
        return PyFloat_FromDouble(e->v.health);
    if (!std::strcmp(name, "armor"))
        return PyFloat_FromDouble(e->v.armorvalue);
    if (!std::strcmp(name, "frags"))
        return PyFloat_FromDouble(e->v.frags);
    if (!std::strcmp(name, "deaths"))
        return PyFloat_FromDouble(player ? player->m_iDeaths : 0);
    if (!std::strcmp(name, "money"))
        return PyFloat_FromDouble(player ? player->m_iAccount : 0);
    return PyErr_Format(PyExc_KeyError, "unknown player property %s", name);
}

PyObject* SetProp(PyObject*, PyObject* args) {
    int index;
    const char* name;
    double value;
    PARSE("isd", &index, &name, &value);
    PLAYER_OR_RAISE(e, index);
    CBasePlayer* player = PlayerOf(index);
    if (!std::strcmp(name, "health")) {
        e->v.health = static_cast<float>(value);
    } else if (!std::strcmp(name, "armor")) {
        e->v.armorvalue = static_cast<float>(value);
    } else if (!std::strcmp(name, "frags")) {
        e->v.frags = static_cast<float>(value);
    } else if (!std::strcmp(name, "deaths") || !std::strcmp(name, "money")) {
        if (!player)
            return PyErr_Format(PyExc_RuntimeError, "%s needs ReGameDLL", name);
        if (name[0] == 'd') {
            player->m_iDeaths = static_cast<int>(value);
        } else {
            player->m_iAccount = static_cast<int>(value);
            if (g_msg_money) {  // обновить HUD денег
                g_engfuncs.pfnMessageBegin(MSG_ONE, g_msg_money, nullptr, e);
                g_engfuncs.pfnWriteLong(player->m_iAccount);
                g_engfuncs.pfnWriteByte(1);
                g_engfuncs.pfnMessageEnd();
            }
        }
    } else {
        return PyErr_Format(PyExc_KeyError, "unknown player property %s", name);
    }
    Py_RETURN_NONE;
}

PyObject* ClientPrint(PyObject*, PyObject* args) {
    int index, kind;
    const char* text;
    PARSE("iis", &index, &kind, &text);
    std::string message = kind == kPrintChat ? Utf8Prefix(text, kMaxChatBytes) : std::string(text);
    for (int i = index ? index : 1; i <= (index ? index : gpGlobals->maxClients); ++i) {
        if (kind == kPrintChat)
            SendChat(i, message);
        else
            Print(i, kind, message.c_str());
    }
    Py_RETURN_NONE;
}

PyObject* ClientCommand(PyObject*, PyObject* args) {
    int index;
    const char* command;
    PARSE("is", &index, &command);
    PLAYER_OR_RAISE(e, index);
    if (!(e->v.flags & FL_FAKECLIENT))
        g_engfuncs.pfnClientCommand(e, const_cast<char*>("%s\n"), command);
    Py_RETURN_NONE;
}

// ---------------------------------------------------------------- сущности, cvar'ы, команды

PyObject* EntityClassname(PyObject*, PyObject* args) {
    int index;
    PARSE("i", &index);
    edict_t* e = EdictOf(index);
    return PyStr(e ? STRING(e->v.classname) : "");
}

PyObject* CvarRegister(PyObject*, PyObject* args) {
    const char *name, *value;
    int flags;
    PARSE("ssi", &name, &value, &flags);
    if (g_engfuncs.pfnCVarGetPointer(name))
        Py_RETURN_NONE;  // уже есть (например, задан в командной строке)
    // движок хранит указатель на cvar_t и его имя до конца работы
    cvar_t* cvar = new cvar_t();
    cvar->name = strdup(name);
    cvar->string = strdup(value);
    cvar->flags = flags;
    g_engfuncs.pfnCVarRegister(cvar);
    Py_RETURN_NONE;
}

PyObject* CvarGet(PyObject*, PyObject* args) {
    const char* name;
    PARSE("s", &name);
    cvar_t* cvar = g_engfuncs.pfnCVarGetPointer(name);
    if (!cvar)
        Py_RETURN_NONE;
    return PyStr(cvar->string);
}

PyObject* CvarSet(PyObject*, PyObject* args) {
    const char *name, *value;
    PARSE("ss", &name, &value);
    g_engfuncs.pfnCVarSetString(name, value);
    Py_RETURN_NONE;
}

void EXT_FUNC ServerCommandHandler() {
    g_python.OnServerCommand();
}

PyObject* RegisterServerCommand(PyObject*, PyObject* args) {
    const char* name;
    PARSE("s", &name);
    g_engfuncs.pfnAddServerCommand(strdup(name), ServerCommandHandler);  // имя живёт до конца работы
    Py_RETURN_NONE;
}

// ---------------------------------------------------------------- сообщения

PyObject* UserMessage(PyObject*, PyObject* args) {
    const char* name;
    PARSE("s", &name);
    return PyLong_FromLong(GET_USER_MSG_ID(PLID, name, nullptr));
}

struct WriteOp {
    char code;
    long i = 0;
    double f = 0.0;
    std::string s;
};

// data — [(код, значение)]: b byte, c char, s short, l long, a angle, o coord, S string, e entity
PyObject* SendMessage(PyObject*, PyObject* args) {
    int dest, type, index;
    PyObject* data;
    PARSE("iiiO", &dest, &type, &index, &data);
    edict_t* e = nullptr;
    if (index) {
        e = PlayerEdict(index);
        if (!e)
            return NoPlayer(index);
        if (e->v.flags & FL_FAKECLIENT)
            Py_RETURN_NONE;  // ботам сообщения не нужны
    } else if (dest == MSG_ONE || dest == MSG_ONE_UNRELIABLE) {
        return PyErr_Format(PyExc_ValueError, "MSG_ONE needs a player");
    }
    // сначала разбираем всё: начатое сообщение прервать нельзя
    PyObject* items = PySequence_Fast(data, "message data must be a sequence");
    if (!items)
        return nullptr;
    std::vector<WriteOp> ops;
    Py_ssize_t count = PySequence_Fast_GET_SIZE(items);
    ops.reserve(static_cast<size_t>(count));
    for (Py_ssize_t i = 0; i < count; ++i) {
        const char* code;
        PyObject* value;
        if (!PyArg_ParseTuple(PySequence_Fast_GET_ITEM(items, i), "sO", &code, &value)) {
            Py_DECREF(items);
            return nullptr;
        }
        WriteOp op;
        op.code = code[0];
        if (op.code == 'S') {
            const char* text = PyUnicode_AsUTF8(value);
            if (text)
                op.s = text;
        } else if (op.code == 'a' || op.code == 'o') {
            op.f = PyFloat_AsDouble(value);
        } else {
            op.i = PyLong_AsLong(value);
        }
        if (PyErr_Occurred()) {
            Py_DECREF(items);
            return nullptr;
        }
        ops.push_back(std::move(op));
    }
    Py_DECREF(items);

    g_engfuncs.pfnMessageBegin(dest, type, nullptr, e);
    for (const WriteOp& op : ops) {
        switch (op.code) {
        case 'b': g_engfuncs.pfnWriteByte(static_cast<int>(op.i)); break;
        case 'c': g_engfuncs.pfnWriteChar(static_cast<int>(op.i)); break;
        case 's': g_engfuncs.pfnWriteShort(static_cast<int>(op.i)); break;
        case 'l': g_engfuncs.pfnWriteLong(static_cast<int>(op.i)); break;
        case 'a': g_engfuncs.pfnWriteAngle(static_cast<float>(op.f)); break;
        case 'o': g_engfuncs.pfnWriteCoord(static_cast<float>(op.f)); break;
        case 'S': g_engfuncs.pfnWriteString(op.s.c_str()); break;
        case 'e': g_engfuncs.pfnWriteEntity(static_cast<int>(op.i)); break;
        default: break;
        }
    }
    g_engfuncs.pfnMessageEnd();
    Py_RETURN_NONE;
}

// ---------------------------------------------------------------- хуки, нативы, форварды

PyObject* EnableHook(PyObject*, PyObject* args) {
    const char* hook;
    int enabled;
    PARSE("sp", &hook, &enabled);
    return PyBool_FromLong(Hooks_Enable(hook, enabled != 0));
}

PyObject* RegisterNative(PyObject*, PyObject* args) {
    const char *name, *params, *returns;
    PARSE("sss", &name, &params, &returns);
    return PyBool_FromLong(Natives_Declare(name, params, returns));
}

PyObject* ForwardExecute(PyObject*, PyObject* args) {
    const char *name, *types;
    PyObject* values;
    PARSE("ssO", &name, &types, &values);
    int result = Forwards_Execute(name, types, values);
    if (result < 0 && PyErr_Occurred())
        return nullptr;
    return PyLong_FromLong(result);
}

#undef PARSE
#undef PLAYER_OR_RAISE

PyMethodDef kMethods[] = {
    {"server_print", ServerPrint, METH_VARARGS, nullptr},
    {"log", Log, METH_VARARGS, nullptr},
    {"server_command", ServerCommand, METH_VARARGS, nullptr},
    {"server_execute", ServerExecute, METH_NOARGS, nullptr},
    {"map_name", MapName, METH_NOARGS, nullptr},
    {"max_players", MaxPlayers, METH_NOARGS, nullptr},
    {"game_time", GameTime, METH_NOARGS, nullptr},
    {"game_dir", GameDirectory, METH_NOARGS, nullptr},
    {"userid", Userid, METH_VARARGS, nullptr},
    {"player_name", PlayerName, METH_VARARGS, nullptr},
    {"player_auth", PlayerAuth, METH_VARARGS, nullptr},
    {"player_ip", PlayerIp, METH_VARARGS, nullptr},
    {"player_info", PlayerInfo, METH_VARARGS, nullptr},
    {"is_bot", IsBot, METH_VARARGS, nullptr},
    {"is_alive", IsAlive, METH_VARARGS, nullptr},
    {"player_team", PlayerTeam, METH_VARARGS, nullptr},
    {"player_flags", PlayerFlags, METH_VARARGS, nullptr},
    {"get_prop", GetProp, METH_VARARGS, nullptr},
    {"set_prop", SetProp, METH_VARARGS, nullptr},
    {"client_print", ClientPrint, METH_VARARGS, nullptr},
    {"client_command", ClientCommand, METH_VARARGS, nullptr},
    {"entity_classname", EntityClassname, METH_VARARGS, nullptr},
    {"cvar_register", CvarRegister, METH_VARARGS, nullptr},
    {"cvar_get", CvarGet, METH_VARARGS, nullptr},
    {"cvar_set", CvarSet, METH_VARARGS, nullptr},
    {"register_server_command", RegisterServerCommand, METH_VARARGS, nullptr},
    {"user_message", UserMessage, METH_VARARGS, nullptr},
    {"send_message", SendMessage, METH_VARARGS, nullptr},
    {"enable_hook", EnableHook, METH_VARARGS, nullptr},
    {"register_native", RegisterNative, METH_VARARGS, nullptr},
    {"forward_execute", ForwardExecute, METH_VARARGS, nullptr},
    {"load_bridge", BridgeLoad, METH_VARARGS, nullptr},
    {"call_bridge", BridgeCall, METH_VARARGS, nullptr},
    {"amx_read", AmxRead, METH_VARARGS, nullptr},
    {"amx_string", AmxString, METH_VARARGS, nullptr},
    {"amx_write", AmxWrite, METH_VARARGS, nullptr},
    {nullptr, nullptr, 0, nullptr},
};

PyModuleDef kModule = {
    PyModuleDef_HEAD_INIT, "_amxpy", "amxpy backend for HLDS (C++ part of the AMXX module)", -1, kMethods,
};

}  // namespace

PyObject* PyInit__amxpy() {
    return PyModule_Create(&kModule);
}
