// Экспорт модуля для AMX Mod X: AMXX_Query/Attach/... (схема запроса функций — как в ReAPI).
#include "sdk.h"

#include "amxx_api.h"
#include "version.h"

AmxxApi g_amxx;

static amxx_module_info_s g_module_info = {
    "amxpy", "amxpy", AMXPY_VERSION, 0, "AMXPY", "amxpy", "",
};

#define AMXPY_REQUEST(name) {#name, offsetof(AmxxApi, name)}

static const struct {
    const char* name;
    size_t offset;
} kRequests[] = {
    AMXPY_REQUEST(AddNatives),
    AMXPY_REQUEST(AddLibraries),
    AMXPY_REQUEST(RemoveLibraries),
    AMXPY_REQUEST(GetAmxString),
    AMXPY_REQUEST(SetAmxString),
    AMXPY_REQUEST(Log),
    AMXPY_REQUEST(LogError),
    AMXPY_REQUEST(RegisterForward),
    AMXPY_REQUEST(ExecuteForward),
    AMXPY_REQUEST(GetPlayerFlags),
    AMXPY_REQUEST(GetPlayerTeamID),
    AMXPY_REQUEST(LoadAmxScript),
    AMXPY_REQUEST(amx_Allot),
};

C_DLLEXPORT int AMXX_Query(int* interface_version, amxx_module_info_s* module_info) {
    if (!interface_version || !module_info)
        return AMXX_PARAM;
    if (*interface_version != AMXX_INTERFACE_VERSION) {
        *interface_version = AMXX_INTERFACE_VERSION;
        return AMXX_IFVERS;
    }
    std::memcpy(module_info, &g_module_info, sizeof g_module_info);
    return AMXX_OK;
}

C_DLLEXPORT int AMXX_CheckGame(const char* /*game*/) {
    return AMXX_GAME_OK;
}

C_DLLEXPORT int AMXX_Attach(PFN_REQ_FNPTR request) {
    if (!request)
        return AMXX_PARAM;
    for (const auto& r : kRequests) {
        void* fn = request(r.name);
        if (!fn)
            return AMXX_FUNC_NOT_PRESENT;
        *reinterpret_cast<void**>(reinterpret_cast<char*>(&g_amxx) + r.offset) = fn;
    }
    return OnAmxxAttach() ? AMXX_OK : AMXX_FUNC_NOT_PRESENT;
}

C_DLLEXPORT int AMXX_Detach() {
    OnAmxxDetach();
    return AMXX_OK;
}

C_DLLEXPORT int AMXX_PluginsLoaded() {
    OnPluginsLoaded();
    return AMXX_OK;
}

C_DLLEXPORT void AMXX_PluginsUnloading() {
}

C_DLLEXPORT void AMXX_PluginsUnloaded() {
    OnPluginsUnloaded();
}
