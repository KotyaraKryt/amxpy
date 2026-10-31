// Фейковый HLDS + Metamod + AMXX: грузит модуль amxpy как настоящий сервер и проверяет его.
// Запуск: amxpy_harness <корень HLDS> <путь к amxpy_amxx_i386.so>  (см. scripts/test-module.sh)
#include <dlfcn.h>
#include <unistd.h>

#include <chrono>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <map>
#include <string>
#include <thread>
#include <vector>

#include <zlib.h>

#include <extdll.h>
#include <eiface.h>
#include <meta_api.h>

#include "amxx_api.h"

namespace {

constexpr int kMsgSayText = 76;
constexpr int kMsgMoney = 77;
constexpr int kMsgShowMenu = 78;
constexpr int kSvcTempEntity = 23;

// ---------------------------------------------------------------- «движок»

globalvars_t globals;
edict_t edicts[64];
char infobuffers[33];
std::map<std::string, cvar_t*> cvars;
std::map<std::string, void (*)()> commands;
std::vector<std::string> cmd_argv;
std::string cmd_args;
std::string command_buffer;
std::vector<std::string> console;

struct Client {
    int userid = 0;
    int flags = 0;
    std::string auth;
    std::map<std::string, std::string> info;
    std::vector<std::string> chat;
    std::vector<std::string> hud;
    std::string menu, menu_buffer;
} clients[33];

struct Message {
    int type = 0;
    int to = 0;
    std::vector<int> bytes;
    std::vector<std::string> strings;
} current;

int Index(const edict_t* e) {
    return static_cast<int>(e - edicts);
}

string_t Alloc(const char* text) {
    return static_cast<string_t>(reinterpret_cast<intptr_t>(strdup(text)));  // pStringBase = 0
}

void ServerPrint(const char* text) {
    console.push_back(text);
    fputs(text, stdout);
}

void CVarRegister(cvar_t* cvar) {
    cvars[cvar->name] = cvar;
    cvar->value = static_cast<float>(atof(cvar->string));
}

cvar_t* CVarGetPointer(const char* name) {
    auto it = cvars.find(name);
    return it == cvars.end() ? nullptr : it->second;
}

void CVarSetString(const char* name, const char* value) {
    if (cvar_t* cvar = CVarGetPointer(name)) {
        cvar->string = strdup(value);
        cvar->value = static_cast<float>(atof(value));
    }
}

void AddServerCommand(char* name, void (*fn)()) {
    commands[name] = fn;
}

int CmdArgc() {
    return static_cast<int>(cmd_argv.size());
}

const char* CmdArgv(int i) {
    return i < static_cast<int>(cmd_argv.size()) ? cmd_argv[i].c_str() : "";
}

const char* CmdArgs() {
    return cmd_args.c_str();
}

std::vector<std::string> Tokenize(const std::string& line) {
    std::vector<std::string> out;
    std::string token;
    bool quoted = false, any = false;
    for (char c : line) {
        if (c == '"') {
            quoted = !quoted;
            any = true;
        } else if (!quoted && (c == ' ' || c == '\t')) {
            if (any)
                out.push_back(token);
            token.clear();
            any = false;
        } else {
            token += c;
            any = true;
        }
    }
    if (any)
        out.push_back(token);
    return out;
}

void Execute(const std::string& line) {
    std::vector<std::string> argv = Tokenize(line.substr(0, line.find("//")));
    if (argv.empty())
        return;
    if (argv[0] == "exec" && argv.size() > 1) {
        std::ifstream file("cstrike/" + argv[1]);
        for (std::string inner; std::getline(file, inner);)
            Execute(inner);
    } else if (commands.count(argv[0])) {
        cmd_argv = argv;
        commands[argv[0]]();
    } else if (argv.size() > 1 && CVarGetPointer(argv[0].c_str())) {
        CVarSetString(argv[0].c_str(), argv[1].c_str());
    }
}

void ServerCommand(char* text) {
    command_buffer += text;
}

void ServerExecute() {
    while (!command_buffer.empty()) {
        size_t end = command_buffer.find('\n');
        std::string line = command_buffer.substr(0, end);
        command_buffer.erase(0, end == std::string::npos ? std::string::npos : end + 1);
        Execute(line);
    }
}

edict_t* PEntityOfEntIndex(int index) {
    return &edicts[index];
}

int IndexOfEdict(const edict_t* e) {
    return Index(e);
}

int GetPlayerUserId(edict_t* e) {
    return clients[Index(e)].userid ? clients[Index(e)].userid : -1;
}

const char* GetPlayerAuthId(edict_t* e) {
    return clients[Index(e)].auth.c_str();
}

char* GetInfoKeyBuffer(edict_t* e) {
    return &infobuffers[Index(e)];
}

char* InfoKeyValue(char* buffer, const char* key) {
    static std::string value;
    value = clients[buffer - infobuffers].info[key];
    return const_cast<char*>(value.c_str());
}

void ClientPrintf(edict_t* e, PRINT_TYPE, const char* text) {
    clients[Index(e)].chat.push_back(text);
}

void ClientCommandFn(edict_t*, char*, ...) {
}

void MessageBegin(int, int type, const float*, edict_t* e) {
    current = Message{type, e ? Index(e) : 0, {}, {}};
}

void WriteByte(int value) {
    current.bytes.push_back(value);
}

void WriteChar(int) {
}

void WriteShort(int) {
}

void WriteAngle(float) {
}

void WriteCoord(float) {
}

void WriteEntity(int) {
}

void WriteLong(int) {
}

void WriteString(const char* text) {
    current.strings.push_back(text);
}

void MessageEnd() {
    if (current.type == kMsgSayText && !current.strings.empty()) {
        std::string text;
        for (char c : current.strings[0]) {
            if (c != '\x01' && c != '\x03' && c != '\x04')
                text += c;
        }
        clients[current.to].chat.push_back(text);
    } else if (current.type == kMsgShowMenu && !current.strings.empty()) {
        Client& client = clients[current.to];
        client.menu_buffer += current.strings[0];
        if (current.bytes.empty() || current.bytes.back() == 0) {  // последняя часть меню
            client.menu = client.menu_buffer;
            client.menu_buffer.clear();
        }
    } else if (current.type == kSvcTempEntity && !current.bytes.empty() && current.bytes[0] == 29) {
        clients[current.to].hud.push_back(current.strings.back());  // TE_TEXTMESSAGE
    }
}

void GetGameDir(char* out) {
    strcpy(out, "cstrike");
}

// ---------------------------------------------------------------- Metamod

meta_globals_t meta_globals;
gamedll_funcs_t gamedll;

int GetUserMsgID(plid_t, const char* name, int*) {
    return !strcmp(name, "SayText") ? kMsgSayText : !strcmp(name, "Money") ? kMsgMoney
         : !strcmp(name, "ShowMenu") ? kMsgShowMenu : 0;
}

const char* GetGameInfo(plid_t, ginfo_t) {
    return nullptr;  // игровой DLL нет — ReGameDLL API недоступен
}

// ---------------------------------------------------------------- AMXX

std::vector<const AMX_NATIVE_INFO*> native_lists;
std::vector<std::string> libraries;
cell amx_memory[256];

struct Forward {
    std::string name;
    std::vector<int> types;
};
std::vector<Forward> forwards;
std::vector<std::string> forward_calls;

int AddNatives(const AMX_NATIVE_INFO* list) {
    native_lists.push_back(list);
    return 1;
}

size_t AddLibraries(const char* name, LibType, void*) {
    libraries.push_back(name);
    return 1;
}

size_t RemoveLibraries(void*) {
    return 0;
}

char* GetAmxString(AMX*, cell addr, int, int* length) {
    static char buffer[256];
    int i = 0;
    for (; amx_memory[addr + i] && i < 255; ++i)
        buffer[i] = static_cast<char>(amx_memory[addr + i]);
    buffer[i] = 0;
    if (length)
        *length = i;
    return buffer;
}

int SetAmxString(AMX*, cell addr, const char* text, int max) {
    int i = 0;
    for (; text[i] && i < max; ++i)
        amx_memory[addr + i] = static_cast<unsigned char>(text[i]);
    amx_memory[addr + i] = 0;
    return i;
}

void LogFn(const char* fmt, ...) {
    char text[2048];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(text, sizeof text, fmt, ap);
    va_end(ap);
    console.push_back(text);
    printf("L %s\n", text);
}

void LogError(AMX*, int, const char* fmt, ...) {
    char text[2048];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(text, sizeof text, fmt, ap);
    va_end(ap);
    console.push_back(text);
    printf("E %s\n", text);
}

// Типы параметров приходят varargs после exec_type и заканчиваются FP_DONE
int RegisterForward(const char* name, int exec_type, ...) {
    Forward forward{name, {}};
    va_list ap;
    va_start(ap, exec_type);
    for (int type = va_arg(ap, int); type != FP_DONE; type = va_arg(ap, int))
        forward.types.push_back(type);
    va_end(ap);
    forwards.push_back(forward);
    return static_cast<int>(forwards.size() - 1);
}

int ExecuteForward(int id, ...) {
    const Forward& forward = forwards[id];
    std::string call = forward.name + "(";
    va_list ap;
    va_start(ap, id);
    for (size_t i = 0; i < forward.types.size(); ++i) {
        if (i)
            call += ", ";
        if (forward.types[i] == FP_STRING)
            call += std::string("\"") + va_arg(ap, const char*) + "\"";
        else
            call += std::to_string(va_arg(ap, cell));
    }
    va_end(ap);
    forward_calls.push_back(call + ")");
    return 0;
}

int GetPlayerFlags(int id) {
    return clients[id].flags;
}

int GetPlayerTeamID(int) {
    return 2;
}

// ---------------------------------------------------------------- мост к чужим нативам (amxpy.amxx)
// Фейковое ядро грузит .amxx моста как AMXX (LoadAmxScript) и привязывает нативы ниже по имени.

#pragma pack(push, 1)
struct AmxVm {  // tagAMX из AMX Mod X SDK, i386
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

struct AmxHeader {
    int32_t size;
    uint16_t magic;
    char file_version;
    char amx_version;
    int16_t flags;
    int16_t defsize;
    int32_t cod, dat, hea, stp, cip, publics, natives, libraries, pubvars, tags, nametable;
};
#pragma pack(pop)

AmxVm* Vm(AMX* amx) {
    return reinterpret_cast<AmxVm*>(amx);
}

cell* AmxCell(AMX* amx, cell addr) {
    AmxVm* vm = Vm(amx);
    return reinterpret_cast<cell*>(vm->base + reinterpret_cast<AmxHeader*>(vm->base)->dat + addr);
}

cell HarnessAdd(AMX*, cell* params) {
    return params[1] + params[2];
}

cell HarnessGetName(AMX* amx, cell* params) {  // (index, name[], len)
    const std::string name = reinterpret_cast<const char*>(static_cast<intptr_t>(edicts[params[1]].v.netname));
    cell* out = AmxCell(amx, params[2]);
    const int count = std::min<int>(static_cast<int>(name.size()), params[3]);
    for (int i = 0; i < count; ++i)
        out[i] = static_cast<unsigned char>(name[i]);
    out[count] = 0;
    return count;
}

cell HarnessScale(AMX* amx, cell* params) {  // (Float:x, &Float:out) -> Float:x*3, out *= 2
    cell* out = AmxCell(amx, params[2]);
    *out = amx_ftoc(amx_ctof(*out) * 2);
    return amx_ftoc(amx_ctof(params[1]) * 3);
}

cell HarnessDouble(AMX* amx, cell* params) {  // (arr[], n)
    cell* arr = AmxCell(amx, params[1]);
    for (int i = 0; i < params[2]; ++i)
        arr[i] *= 2;
    return 1;
}

cell HarnessStrlen(AMX* amx, cell* params) {  // (const s[]) — байты UTF-8 по ячейкам
    cell* text = AmxCell(amx, params[1]);
    int n = 0;
    while (text[n])
        ++n;
    return n;
}

cell HarnessFail(AMX* amx, cell*) {  // как LogError(amx, AMX_ERR_NATIVE, ...)
    Vm(amx)->error = AMX_ERR_NATIVE;
    return 0;
}

const std::map<std::string, AMX_NATIVE> bridge_natives = {
    {"harness_add", HarnessAdd}, {"harness_get_name", HarnessGetName}, {"harness_scale", HarnessScale},
    {"harness_double", HarnessDouble}, {"harness_strlen", HarnessStrlen}, {"harness_fail", HarnessFail},
};
int bridges_loaded = 0;

int LoadAmxScript(AMX* amx, void** program, const char* path, char error[64], int) {
    error[0] = 0;
    std::ifstream in(path, std::ios::binary);
    std::vector<unsigned char> file((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
    int32_t magic, disksize, imagesize, memsize, offset;
    if (file.size() < 24)
        return 19;
    std::memcpy(&magic, file.data(), 4);
    std::memcpy(&disksize, file.data() + 8, 4);
    std::memcpy(&imagesize, file.data() + 12, 4);
    std::memcpy(&memsize, file.data() + 16, 4);
    std::memcpy(&offset, file.data() + 20, 4);
    if (magic != 0x414D5858 || file[7] != 4) {
        std::snprintf(error, 64, "Invalid Plugin");
        return 19;
    }
    uLongf size = static_cast<uLongf>(std::max(imagesize, memsize) + 1);
    auto* image = new unsigned char[size]();
    if (uncompress(image, &size, file.data() + offset, static_cast<uLong>(disksize)) != Z_OK) {
        std::snprintf(error, 64, "Internal error: Decompress");
        return 19;
    }
    auto* hdr = reinterpret_cast<AmxHeader*>(image);
    if (hdr->magic != 0xF1E0 || hdr->defsize != 8 || hdr->size != hdr->hea || hdr->stp <= hdr->hea) {
        std::snprintf(error, 64, "Invalid Plugin");
        return 19;
    }
    AmxVm* vm = Vm(amx);  // как amx_Init
    std::memset(vm, 0, sizeof *vm);
    vm->base = image;
    vm->hlw = hdr->hea - hdr->dat;
    vm->stp = hdr->stp - hdr->dat - static_cast<cell>(sizeof(cell));
    vm->hea = vm->hlw;
    vm->stk = vm->stp;
    *program = image;
    ++bridges_loaded;
    for (int32_t at = hdr->natives; at < hdr->libraries; at += hdr->defsize) {
        auto* stub = reinterpret_cast<uint32_t*>(image + at);
        const char* name = reinterpret_cast<const char*>(image + stub[1]);
        auto it = bridge_natives.find(name);
        if (it != bridge_natives.end())
            stub[0] = static_cast<uint32_t>(reinterpret_cast<uintptr_t>(it->second));
        else if (!error[0])
            std::snprintf(error, 64, "Plugin uses an unknown function (name \"%s\")", name);
    }
    return error[0] ? 19 : 0;
}

int AmxAllot(AMX* amx, int cells, cell* addr, cell** phys) {
    AmxVm* vm = Vm(amx);
    if (vm->stk - vm->hea - cells * static_cast<int>(sizeof(cell)) < 16)
        return 1;  // AMX_ERR_MEMORY
    *addr = vm->hea;
    *phys = AmxCell(amx, vm->hea);
    vm->hea += cells * static_cast<int>(sizeof(cell));
    return 0;
}

void* RequestFunction(const char* name) {
    static const std::map<std::string, void*> table = {
        {"AddNatives", reinterpret_cast<void*>(AddNatives)},
        {"AddLibraries", reinterpret_cast<void*>(AddLibraries)},
        {"RemoveLibraries", reinterpret_cast<void*>(RemoveLibraries)},
        {"GetAmxString", reinterpret_cast<void*>(GetAmxString)},
        {"SetAmxString", reinterpret_cast<void*>(SetAmxString)},
        {"Log", reinterpret_cast<void*>(LogFn)},
        {"LogError", reinterpret_cast<void*>(LogError)},
        {"RegisterForward", reinterpret_cast<void*>(RegisterForward)},
        {"ExecuteForward", reinterpret_cast<void*>(ExecuteForward)},
        {"GetPlayerFlags", reinterpret_cast<void*>(GetPlayerFlags)},
        {"GetPlayerTeamID", reinterpret_cast<void*>(GetPlayerTeamID)},
        {"LoadAmxScript", reinterpret_cast<void*>(LoadAmxScript)},
        {"amx_Allot", reinterpret_cast<void*>(AmxAllot)},
    };
    auto it = table.find(name);
    return it == table.end() ? nullptr : it->second;
}

// ---------------------------------------------------------------- проверки

int g_checks = 0;
int g_failures = 0;

void Check(bool ok, const std::string& what) {
    ++g_checks;
    if (!ok)
        ++g_failures;
    printf("%s %s\n", ok ? "  ok  " : "  FAIL", what.c_str());
}

bool ConsoleHas(const std::string& needle) {
    for (const std::string& line : console) {
        if (line.find(needle) != std::string::npos)
            return true;
    }
    return false;
}

bool ChatHas(int index, const std::string& needle) {
    for (const std::string& line : clients[index].chat) {
        if (line.find(needle) != std::string::npos)
            return true;
    }
    return false;
}

AMX_NATIVE FindNative(const char* name) {
    for (const AMX_NATIVE_INFO* list : native_lists) {
        for (; list->name; ++list) {
            if (!strcmp(list->name, name))
                return list->func;
        }
    }
    return nullptr;
}

template <typename T>
T Symbol(void* lib, const char* name) {
    void* sym = dlsym(lib, name);
    if (!sym) {
        fprintf(stderr, "missing export %s\n", name);
        exit(2);
    }
    return reinterpret_cast<T>(sym);
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 3) {
        fprintf(stderr, "usage: %s <hlds root> <module.so>\n", argv[0]);
        return 2;
    }
    std::string module_path = argv[2];
    if (chdir(argv[1]) != 0) {
        perror("chdir");
        return 2;
    }
    void* lib = dlopen(module_path.c_str(), RTLD_NOW | RTLD_LOCAL);  // как Metamod/AMXX
    if (!lib) {
        fprintf(stderr, "dlopen: %s\n", dlerror());
        return 2;
    }

    enginefuncs_t engine{};
    engine.pfnServerPrint = ServerPrint;
    engine.pfnCVarRegister = CVarRegister;
    engine.pfnCVarGetPointer = CVarGetPointer;
    engine.pfnCVarSetString = CVarSetString;
    engine.pfnAddServerCommand = AddServerCommand;
    engine.pfnCmd_Argc = CmdArgc;
    engine.pfnCmd_Argv = CmdArgv;
    engine.pfnCmd_Args = CmdArgs;
    engine.pfnServerCommand = ServerCommand;
    engine.pfnServerExecute = ServerExecute;
    engine.pfnPEntityOfEntIndex = PEntityOfEntIndex;
    engine.pfnIndexOfEdict = IndexOfEdict;
    engine.pfnGetPlayerUserId = GetPlayerUserId;
    engine.pfnGetPlayerAuthId = GetPlayerAuthId;
    engine.pfnGetInfoKeyBuffer = GetInfoKeyBuffer;
    engine.pfnInfoKeyValue = InfoKeyValue;
    engine.pfnClientPrintf = ClientPrintf;
    engine.pfnClientCommand = ClientCommandFn;
    engine.pfnMessageBegin = MessageBegin;
    engine.pfnWriteByte = WriteByte;
    engine.pfnWriteChar = WriteChar;
    engine.pfnWriteShort = WriteShort;
    engine.pfnWriteAngle = WriteAngle;
    engine.pfnWriteCoord = WriteCoord;
    engine.pfnWriteEntity = WriteEntity;
    engine.pfnWriteLong = WriteLong;
    engine.pfnWriteString = WriteString;
    engine.pfnMessageEnd = MessageEnd;
    engine.pfnGetGameDir = GetGameDir;

    globals.maxClients = 32;
    globals.maxEntities = 64;
    globals.time = 1.0f;
    globals.mapname = Alloc("de_dust2");
    for (edict_t& e : edicts)
        e.v.pContainingEntity = &e;

    mutil_funcs_t mutil{};
    mutil.pfnGetUserMsgID = GetUserMsgID;
    mutil.pfnGetGameInfo = GetGameInfo;

    // --- порядок, как у AMXX: модуль сначала подключается к Metamod, потом к AMXX
    Symbol<void (*)(enginefuncs_t*, globalvars_t*)>(lib, "GiveFnptrsToDll")(&engine, &globals);
    plugin_info_t* info = nullptr;
    Symbol<int (*)(char*, plugin_info_t**, mutil_funcs_t*)>(lib, "Meta_Query")(
        const_cast<char*>(META_INTERFACE_VERSION), &info, &mutil);
    META_FUNCTIONS meta{};
    Check(Symbol<int (*)(PLUG_LOADTIME, META_FUNCTIONS*, meta_globals_t*, gamedll_funcs_t*)>(lib, "Meta_Attach")(
              PT_STARTUP, &meta, &meta_globals, &gamedll) == TRUE,
          "Meta_Attach");
    DLL_FUNCTIONS pre{}, post{};
    int version = INTERFACE_VERSION;
    meta.pfnGetEntityAPI2(&pre, &version);
    version = INTERFACE_VERSION;
    meta.pfnGetEntityAPI2_Post(&post, &version);

    int interface_version = AMXX_INTERFACE_VERSION;
    amxx_module_info_s module_info{};
    Check(Symbol<int (*)(int*, amxx_module_info_s*)>(lib, "AMXX_Query")(&interface_version, &module_info) == AMXX_OK,
          "AMXX_Query");
    Check(Symbol<int (*)(PFN_REQ_FNPTR)>(lib, "AMXX_Attach")(RequestFunction) == AMXX_OK,
          "AMXX_Attach: Python started, plugins loaded");
    AMX_NATIVE is_vip = FindNative("vip_is_user_vip");
    AMX_NATIVE days_left = FindNative("vip_days_left");
    Check(is_vip && days_left, "natives of the vip plugin are registered in AMXX");
    Check(libraries.size() == 1 && libraries[0] == "vip", "library vip for #pragma reqlib");
    if (!is_vip || !days_left) {
        printf("\n%d checks, %d failed\n", g_checks, g_failures);
        return 1;
    }

    // --- карта
    post.pfnServerActivate(edicts, 64, 32);
    Symbol<int (*)()>(lib, "AMXX_PluginsLoaded")();
    ServerExecute();

    auto frames = [&](double seconds) {
        auto end = std::chrono::steady_clock::now() + std::chrono::duration<double>(seconds);
        while (std::chrono::steady_clock::now() < end) {
            globals.time += 0.01f;
            pre.pfnStartFrame();
            ServerExecute();
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
    };
    auto connect = [&](int index, const char* name, const char* auth, int flags) {
        static int next_userid = 1;
        clients[index].userid = next_userid++;
        clients[index].auth = auth;
        clients[index].flags = flags;
        edicts[index].v.netname = Alloc(name);
        edicts[index].v.classname = Alloc("player");
        edicts[index].v.health = 100;
        edicts[index].v.flags = FL_CLIENT;
        char reject[128] = {};
        pre.pfnClientConnect(&edicts[index], name, "127.0.0.1:27005", reject);
        post.pfnClientPutInServer(&edicts[index]);
    };
    auto client_command = [&](int index, const std::string& line) {
        cmd_argv = Tokenize(line);
        cmd_args = line.size() > cmd_argv[0].size() ? line.substr(cmd_argv[0].size() + 1) : "";
        meta_globals.mres = MRES_UNSET;
        pre.pfnClientCommand(&edicts[index]);
        return meta_globals.mres == MRES_SUPERCEDE;
    };
    auto server_command = [&](const std::string& line) {
        cmd_argv = Tokenize(line);
        commands[cmd_argv[0]]();
    };

    connect(1, "Alice", "STEAM_0:1:42", 0);
    connect(2, "Admin", "STEAM_0:0:7", 1 << 11);  // флаг l (rcon)
    frames(0.4);
    Check(ChatHas(1, "Привет, Alice!"), "hello: greeting after hello_delay from the plugin cfg");

    Check(client_command(1, "say \"/hp\""), "say /hp is handled and hidden (MRES_SUPERCEDE)");
    Check(ChatHas(1, "HP: 100"), "hello: /hp answer via SayText");

    cell alice[] = {sizeof(cell), 1};
    Check(is_vip(nullptr, alice) == 0, "vip_is_user_vip(Alice) == 0 before the grant");
    client_command(2, "amx_vip_add Alice 7");
    for (int i = 0; i < 100 && is_vip(nullptr, alice) == 0; ++i)
        frames(0.03);  // запись в SQLite идёт в потоке offload()
    Check(is_vip(nullptr, alice) == 1, "vip_is_user_vip(Alice) == 1 after amx_vip_add (async SQLite)");
    Check(days_left(nullptr, alice) == 7, "vip_days_left(Alice) == 7");
    bool granted = false;
    for (const std::string& call : forward_calls)
        granted = granted || call == "vip_granted(1, 7)";
    Check(granted, "forward vip_granted(1, 7) reached AMXX");

    Check(client_command(1, "say \"/menu\""), "ui_demo: /menu is handled");
    Check(clients[1].menu.find("Магазин") != std::string::npos && clients[1].menu.find("1/2") != std::string::npos,
          "ui_demo: ShowMenu with title and page counter (UTF-8 split into parts)");
    Check(client_command(1, "menuselect 3"), "menuselect of an amxpy menu is handled (MRES_SUPERCEDE)");
    Check(ChatHas(1, "Вы — Alice"), "menu item callback ran");
    Check(!client_command(1, "menuselect 3"), "menuselect without an open menu is left to AMXX");
    client_command(1, "say \"/hud\"");
    Check(!clients[1].hud.empty() && clients[1].hud.back().find("Привет, Alice") != std::string::npos,
          "ui_demo: HUD via TE_TEXTMESSAGE");

    server_command("amxpy list");
    Check(ConsoleHas("vip") && ConsoleHas("1.2.0"), "amxpy list shows the loaded plugins");
    server_command("amxpy reload hello");
    Check(ConsoleHas("reloaded hello"), "amxpy reload hello: hot reload inside the server");
    Check(ConsoleHas("hook take_damage is not available"), "without ReGameDLL game hooks report unavailability");

    server_command("bridge_test");
    Check(ConsoleHas("bridge: Alice 5 42 7.5 2.5 [2, 4, 6] 12 yes False"),
          "amxx.call: string buffer, Float: ref, array, UTF-8 string, native error, missing native");
    Check(bridges_loaded == 7, "one bridge per newly resolved native, then the cache");

    // Pawn-форвард: кадр public плагина-приёмника, как его оставит заглушка, — и натив модуля
    {
        AMX_NATIVE forward = FindNative("__amxpy_forward");
        Check(forward != nullptr, "the __amxpy_forward native is registered in AMXX");
        std::ifstream ini("cstrike/addons/amxmodx/configs/plugins-amxpy.ini");
        std::string listed((std::istreambuf_iterator<char>(ini)), std::istreambuf_iterator<char>());
        Check(listed.find("amxpy_forwards.amxx") != std::string::npos &&
                  std::ifstream("cstrike/addons/amxmodx/plugins/amxpy_forwards.amxx").good(),
              "the Pawn forward receiver plugin is generated for AMXX");
        static unsigned char image[4096] = {};
        auto* hdr = reinterpret_cast<AmxHeader*>(image);
        hdr->dat = 64;
        static char amx_buffer[512] = {};
        AmxVm* vm = Vm(reinterpret_cast<AMX*>(amx_buffer));
        vm->base = image;
        vm->stp = 2048;
        vm->frm = 1024;
        cell* data = reinterpret_cast<cell*>(image + hdr->dat);
        const char* text = "Привет";
        for (int i = 0; text[i]; ++i)
            data[64 + i] = static_cast<unsigned char>(text[i]);
        data[96] = 5;  // &counter
        cell* frame = data + 1024 / 4;
        frame[2] = 3 * sizeof(cell);  // байты аргументов
        frame[3] = 7;
        frame[4] = 64 * sizeof(cell);
        frame[5] = 96 * sizeof(cell);
        cell params[] = {sizeof(cell), 0};  // __amxpy_forward(0)
        cell result = forward ? forward(reinterpret_cast<AMX*>(amx_buffer), params) : 0;
        Check(result == 3 && data[96] == 10 && ConsoleHas("harness_fwd: 7 Привет 10"),
              "Pawn forward reaches Python: int, UTF-8 string, by-ref cell written back, return value");
    }

    pre.pfnClientDisconnect(&edicts[1]);
    clients[1].userid = 0;
    Check(is_vip(nullptr, alice) == 0, "natives ignore a player who has left");

    pre.pfnServerDeactivate();
    Symbol<void (*)()>(lib, "AMXX_PluginsUnloaded")();
    Symbol<int (*)()>(lib, "AMXX_Detach")();
    Check(ConsoleHas("unloaded vip (shutdown)"), "shutdown unloads the plugins");

    printf("\n%d checks, %d failed\n", g_checks, g_failures);
    return g_failures ? 1 : 0;
}
