// Жизненный цикл модуля и DLL-хуки: события движка → рантайм amxpy.
#include <time.h>
#include <unistd.h>

#include <cstdarg>
#include <cstdio>

#include "amxx_api.h"
#include "hooks.h"
#include "module.h"
#include "natives.h"
#include "python_host.h"

PlayerSlot g_slots[kMaxClients + 1];
int g_msg_saytext = 0;
int g_msg_money = 0;
bool g_plugins_loaded = false;

constexpr double kReconnectTimeout = 120.0;  // сколько ждать игрока после смены карты, с

double MonotonicNow() {
    timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec * 1e-9;
}

void ServerPrintf(const char* fmt, ...) {
    char buffer[1024];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buffer, sizeof buffer, fmt, ap);
    va_end(ap);
    g_engfuncs.pfnServerPrint(buffer);
}

edict_t* EdictOf(int index) {
    if (index < 0 || !gpGlobals || index >= gpGlobals->maxEntities)
        return nullptr;
    edict_t* e = g_engfuncs.pfnPEntityOfEntIndex(index);
    return (e && !e->free) ? e : nullptr;
}

edict_t* PlayerEdict(int index) {
    if (index < 1 || index > kMaxClients || !gpGlobals || index > gpGlobals->maxClients || !g_slots[index].connected)
        return nullptr;
    return g_engfuncs.pfnPEntityOfEntIndex(index);
}

int IndexOf(const edict_t* e) {
    return e ? g_engfuncs.pfnIndexOfEdict(e) : 0;
}

int IndexOf(const entvars_t* pev) {
    return pev ? IndexOf(pev->pContainingEntity) : 0;
}

int PlayerIndexOf(const entvars_t* pev) {
    int index = IndexOf(pev);
    return (index >= 1 && index <= gpGlobals->maxClients) ? index : 0;
}

CBasePlayer* PlayerOf(int index) {
    if (!Hooks_ReGameAvailable())
        return nullptr;
    edict_t* e = PlayerEdict(index);
    return (e && e->pvPrivateData) ? static_cast<CBasePlayer*>(e->pvPrivateData) : nullptr;
}

static std::string GameDir() {
    char game[256] = {};
    g_engfuncs.pfnGetGameDir(game);
    if (game[0] == '/')
        return game;
    char cwd[4096];
    if (!getcwd(cwd, sizeof cwd))
        return game;
    return std::string(cwd) + "/" + game;
}

static std::string StripPort(const char* address) {
    std::string ip = address ? address : "";
    auto colon = ip.rfind(':');
    return colon == std::string::npos ? ip : ip.substr(0, colon);
}

// ---------------------------------------------------------------- AMXX

bool OnAmxxAttach() {
    if (!gpGlobals || !g_engfuncs.pfnServerPrint || !gpMetaUtilFuncs) {
        fprintf(stderr, "[amxpy] the module must be loaded by AMX Mod X under Metamod\n");
        return false;
    }
    Hooks_Init();  // до загрузки плагинов: они спрашивают, доступны ли хуки
    if (!g_python.Start(GameDir())) {
        ServerPrintf("[amxpy] the Python runtime did not start; the module is disabled\n");
        return true;  // без Python модуль просто ничего не делает
    }
    Natives_RegisterAll();
    Bridge_RegisterNatives();  // __amxpy_forward: Pawn-форварды → Python
    return true;
}

void OnPluginsLoaded() {
    g_plugins_loaded = true;
    Forwards_Reset();
    g_python.OnMapStart(STRING(gpGlobals->mapname));
}

void OnPluginsUnloaded() {
    g_plugins_loaded = false;
    Forwards_Reset();
}

void OnAmxxDetach() {
    g_python.Shutdown();
}

// ---------------------------------------------------------------- DLL-хуки

void EXT_FUNC Hook_StartFrame() {
    double now = MonotonicNow();
    for (int i = 1; i <= kMaxClients; ++i) {
        PlayerSlot& slot = g_slots[i];
        if (slot.connected && slot.pending_since > 0 && now - slot.pending_since > kReconnectTimeout) {
            slot.connected = false;  // не вернулся после смены карты
            slot.pending_since = 0;
        }
    }
    g_python.OnFrame();
    RETURN_META(MRES_IGNORED);
}

qboolean EXT_FUNC Hook_ClientConnect(edict_t* e, const char* name, const char* address, char reject[128]) {
    int index = IndexOf(e);
    if (index >= 1 && index <= kMaxClients) {
        PlayerSlot& slot = g_slots[index];
        slot.connected = true;
        slot.pending_since = 0;
        slot.ip = StripPort(address);
        std::string reason = g_python.OnClientConnect(index, name ? name : "", slot.ip.c_str());
        if (!reason.empty()) {
            slot.connected = false;
            snprintf(reject, 128, "%s", reason.c_str());
            RETURN_META_VALUE(MRES_SUPERCEDE, static_cast<qboolean>(0));
        }
    }
    RETURN_META_VALUE(MRES_IGNORED, static_cast<qboolean>(1));
}

void EXT_FUNC Hook_ClientPutInServer_Post(edict_t* e) {
    int index = IndexOf(e);
    if (index >= 1 && index <= kMaxClients && g_slots[index].connected)
        g_python.OnClientPutInServer(index);
    RETURN_META(MRES_IGNORED);
}

// Боты подключаются в обход ClientConnect: узнаём их по первому setinfo
void EXT_FUNC Hook_ClientUserInfoChanged_Post(edict_t* e, char* /*infobuffer*/) {
    int index = IndexOf(e);
    if (index >= 1 && index <= kMaxClients && !g_slots[index].connected && (e->v.flags & FL_FAKECLIENT)) {
        g_slots[index].connected = true;
        g_slots[index].ip = "127.0.0.1";
        g_python.OnClientConnect(index, STRING(e->v.netname), "127.0.0.1");
        g_python.OnClientPutInServer(index);
    }
    RETURN_META(MRES_IGNORED);
}

void EXT_FUNC Hook_ClientDisconnect(edict_t* e) {
    int index = IndexOf(e);
    if (index >= 1 && index <= kMaxClients && g_slots[index].connected) {
        g_python.OnClientDisconnect(index);
        g_slots[index].connected = false;
        g_slots[index].pending_since = 0;
    }
    RETURN_META(MRES_IGNORED);
}

void EXT_FUNC Hook_ClientCommand(edict_t* e) {
    int index = IndexOf(e);
    // AMXX стоит в Metamod раньше: если он уже забрал команду (например, menuselect своего меню), видно по status
    bool handled = gpMetaGlobals && gpMetaGlobals->status >= MRES_SUPERCEDE;
    if (index >= 1 && index <= kMaxClients && g_slots[index].connected && g_python.OnClientCommand(index, handled))
        RETURN_META(MRES_SUPERCEDE);
    RETURN_META(MRES_IGNORED);
}

void EXT_FUNC Hook_ServerActivate_Post(edict_t* /*edicts*/, int /*count*/, int /*max_clients*/) {
    g_msg_saytext = GET_USER_MSG_ID(PLID, "SayText", nullptr);
    g_msg_money = GET_USER_MSG_ID(PLID, "Money", nullptr);
    RETURN_META(MRES_IGNORED);
}

void EXT_FUNC Hook_ServerDeactivate() {
    g_python.OnMapEnd();
    double now = MonotonicNow();
    for (int i = 1; i <= kMaxClients; ++i) {
        if (g_slots[i].connected)
            g_slots[i].pending_since = now;  // при смене карты игроки переподключаются
    }
    RETURN_META(MRES_IGNORED);
}
