// Минимальный интерфейс модуля AMX Mod X (AMXX_INTERFACE_VERSION 4).
// Типы, значения перечислений и имена функций — из AMX Mod X SDK (public/sdk/amxxmodule.h).
#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>

typedef int32_t cell;
typedef struct tagAMX AMX;
typedef cell (*AMX_NATIVE)(AMX* amx, cell* params);

struct AMX_NATIVE_INFO {
    const char* name;
    AMX_NATIVE func;
};

struct amxx_module_info_s {
    const char* name;
    const char* author;
    const char* version;
    int reload;
    const char* logtag;
    const char* library;
    const char* libclass;
};

enum { AMXX_OK = 0, AMXX_IFVERS = 1, AMXX_PARAM = 2, AMXX_FUNC_NOT_PRESENT = 3 };
enum { AMXX_GAME_OK = 0, AMXX_GAME_BAD = 1 };
constexpr int AMXX_INTERFACE_VERSION = 4;
constexpr int AMX_ERR_NATIVE = 10;

enum ForwardExecType { ET_IGNORE = 0, ET_STOP, ET_STOP2, ET_CONTINUE };
enum ForwardParam { FP_DONE = -1, FP_CELL, FP_FLOAT, FP_STRING, FP_STRINGEX, FP_ARRAY, FP_CELL_BYREF, FP_FLOAT_BYREF };
enum LibType { LibType_Library, LibType_Class };

typedef void* (*PFN_REQ_FNPTR)(const char* name);

// Функции ядра AMXX, которые модуль запрашивает при подключении
struct AmxxApi {
    int (*AddNatives)(const AMX_NATIVE_INFO* list);
    size_t (*AddLibraries)(const char* name, LibType type, void* parent);
    size_t (*RemoveLibraries)(void* parent);
    char* (*GetAmxString)(AMX* amx, cell amx_addr, int buffer_id, int* len);
    int (*SetAmxString)(AMX* amx, cell amx_addr, const char* source, int max);
    void (*Log)(const char* fmt, ...);
    void (*LogError)(AMX* amx, int err, const char* fmt, ...);
    int (*RegisterForward)(const char* name, ForwardExecType exec_type, ...);
    int (*ExecuteForward)(int id, ...);
    int (*GetPlayerFlags)(int id);
    int (*GetPlayerTeamID)(int id);
    int (*LoadAmxScript)(AMX* amx, void** program, const char* path, char error[64], int debug);
    int (*amx_Allot)(AMX* amx, int cells, cell* amx_addr, cell** phys_addr);
};

extern AmxxApi g_amxx;

inline float amx_ctof(cell value) {
    float f;
    std::memcpy(&f, &value, sizeof f);
    return f;
}

inline cell amx_ftoc(float value) {
    cell c;
    std::memcpy(&c, &value, sizeof c);
    return c;
}

// Колбэки модуля (module.cpp)
bool OnAmxxAttach();
void OnAmxxDetach();
void OnPluginsLoaded();
void OnPluginsUnloaded();
