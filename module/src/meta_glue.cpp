// Экспорт для движка и Metamod: GiveFnptrsToDll, Meta_*, таблицы DLL-хуков.
#include <cstring>

#include "module.h"
#include "version.h"

enginefuncs_t g_engfuncs;
globalvars_t* gpGlobals;
meta_globals_t* gpMetaGlobals;
gamedll_funcs_t* gpGamedllFuncs;
mutil_funcs_t* gpMetaUtilFuncs;

plugin_info_t Plugin_info = {
    META_INTERFACE_VERSION,
    "amxpy",
    AMXPY_VERSION,
    __DATE__,
    "amxpy",
    "",
    "AMXPY",
    PT_ANYTIME,
    PT_NEVER,  // встроенный интерпретатор Python не выгружается
};

C_DLLEXPORT void WINAPI GiveFnptrsToDll(enginefuncs_t* engine, globalvars_t* globals) {
    std::memcpy(&g_engfuncs, engine, sizeof g_engfuncs);
    gpGlobals = globals;
}

C_DLLEXPORT int GetEntityAPI2(DLL_FUNCTIONS* table, int* interface_version) {
    if (!table || !interface_version || *interface_version != INTERFACE_VERSION) {
        if (interface_version)
            *interface_version = INTERFACE_VERSION;
        return FALSE;
    }
    std::memset(table, 0, sizeof *table);
    table->pfnStartFrame = Hook_StartFrame;
    table->pfnClientConnect = Hook_ClientConnect;
    table->pfnClientDisconnect = Hook_ClientDisconnect;
    table->pfnClientCommand = Hook_ClientCommand;
    table->pfnServerDeactivate = Hook_ServerDeactivate;
    return TRUE;
}

C_DLLEXPORT int GetEntityAPI2_Post(DLL_FUNCTIONS* table, int* interface_version) {
    if (!table || !interface_version || *interface_version != INTERFACE_VERSION) {
        if (interface_version)
            *interface_version = INTERFACE_VERSION;
        return FALSE;
    }
    std::memset(table, 0, sizeof *table);
    table->pfnClientPutInServer = Hook_ClientPutInServer_Post;
    table->pfnClientUserInfoChanged = Hook_ClientUserInfoChanged_Post;
    table->pfnServerActivate = Hook_ServerActivate_Post;
    return TRUE;
}

static META_FUNCTIONS g_meta_functions = {
    nullptr,             // GetEntityAPI
    nullptr,             // GetEntityAPI_Post
    GetEntityAPI2,       // GetEntityAPI2
    GetEntityAPI2_Post,  // GetEntityAPI2_Post
    nullptr,             // GetNewDLLFunctions
    nullptr,             // GetNewDLLFunctions_Post
    nullptr,             // GetEngineFunctions
    nullptr,             // GetEngineFunctions_Post
};

C_DLLEXPORT int Meta_Query(char* /*interface_version*/, plugin_info_t** plinfo, mutil_funcs_t* mutil) {
    *plinfo = &Plugin_info;
    gpMetaUtilFuncs = mutil;
    return TRUE;
}

C_DLLEXPORT int Meta_Attach(PLUG_LOADTIME /*now*/, META_FUNCTIONS* table, meta_globals_t* globals,
                            gamedll_funcs_t* gamedll) {
    gpMetaGlobals = globals;
    gpGamedllFuncs = gamedll;
    std::memcpy(table, &g_meta_functions, sizeof g_meta_functions);
    return TRUE;
}

C_DLLEXPORT int Meta_Detach(PLUG_LOADTIME /*now*/, PL_UNLOAD_REASON /*reason*/) {
    return TRUE;
}
