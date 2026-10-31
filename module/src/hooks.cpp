// Игровые события через hookchain'ы ReGameDLL.
#include <cstring>
#include <string>
#include <vector>

#include "hooks.h"
#include "module.h"
#include "python_host.h"

namespace {

constexpr int kHitGroupHead = 1;  // HITGROUP_HEAD из monsters.h (сам заголовок конфликтует с cbase.h)

enum Hook {
    kSpawn, kTakeDamage, kKilled, kRoundStart, kRoundEnd,
    kTeamSelect, kMoneyChange, kBuyWeapon, kDropItem, kNameChange, kFreezeEnd,
    kGrenadeThrow, kBombPlanted, kBombDefuseStart, kBombDefuseEnd, kBombExploded,
    kHookCount
};
const char* const kHookNames[kHookCount] = {
    "player_spawn", "take_damage", "player_killed", "round_start", "round_end",
    "team_select", "money_change", "buy_weapon", "drop_item", "name_change", "freeze_end",
    "grenade_throw", "bomb_planted", "bomb_defuse_start", "bomb_defuse_end", "bomb_exploded",
};
// С какой минорной версии API 5.x есть хук: вызов отсутствующего в vtable хука уронит сервер
const int kMinMinor[kHookCount] = {0, 0, 0, 0, 0, 3, 3, 3, 3, 3, 3, 5, 5, 5, 5, 5};

// WeaponIdType → имя без weapon_
const char* const kWeaponNames[] = {
    "", "p228", "glock", "scout", "hegrenade", "xm1014", "c4", "mac10", "aug", "smokegrenade", "elite",
    "fiveseven", "ump45", "sg550", "galil", "famas", "usp", "glock18", "awp", "mp5navy", "m249", "m3",
    "m4a1", "tmp", "g3sg1", "flashbang", "deagle", "sg552", "ak47", "knife", "p90",
};

IReGameApi* g_api = nullptr;
bool g_available = false;
bool g_registered[kHookCount] = {};
bool g_enabled[kHookCount] = {};

bool InitApi() {
    const char* game_dll = GET_GAME_INFO(PLID, GINFO_DLL_FULLPATH);
    if (!game_dll)
        return false;
    CSysModule* module = Sys_GetModuleHandle(game_dll);
    CreateInterfaceFn factory = module ? Sys_GetFactory(module) : nullptr;
    if (!factory)
        return false;
    int code = 0;
    g_api = (IReGameApi*)factory(VRE_GAMEDLL_API_VERSION, &code);  // интерфейс не наследует IBaseInterface
    if (!g_api)
        return false;
    // используем только ранние хуки API 5.x, поэтому новые минорные версии не обязательны
    if (g_api->GetMajorVersion() != REGAMEDLL_API_VERSION_MAJOR) {
        ServerPrintf("[amxpy] ReGameDLL API %d.%d is not supported (need %d.x)\n", g_api->GetMajorVersion(),
                     g_api->GetMinorVersion(), REGAMEDLL_API_VERSION_MAJOR);
        return false;
    }
    return true;
}

std::string StripWeapon(const char* name) {
    if (!name)
        return "";
    return std::strncmp(name, "weapon_", 7) == 0 ? name + 7 : name;
}

std::string WeaponIdName(int id) {
    if (id == WEAPON_SHIELDGUN)
        return "shield";
    const int count = static_cast<int>(sizeof(kWeaponNames) / sizeof(kWeaponNames[0]));
    return id > 0 && id < count ? kWeaponNames[id] : "";
}

int EntityIndex(CBaseEntity* entity) {
    return entity ? IndexOf(entity->pev) : 0;
}

std::string WeaponName(int killer) {
    CBasePlayer* player = PlayerOf(killer);
    if (!player)
        return killer ? "" : "world";
    if (!player->m_pActiveItem || !player->m_pActiveItem->pev)
        return "";
    const char* name = STRING(player->m_pActiveItem->pev->classname);
    return std::strncmp(name, "weapon_", 7) == 0 ? name + 7 : name;
}

void EXT_FUNC OnSpawn(IReGameHook_CBasePlayer_Spawn* chain, CBasePlayer* player) {
    if (!g_enabled[kSpawn]) {
        chain->callNext(player);
        return;
    }
    std::vector<EventValue> args{EventValue::Int(IndexOf(player->pev))};
    if (g_python.OnEvent("player_spawn", false, args).blocked)
        return;
    chain->callNext(player);
    g_python.OnEvent("player_spawn", true, args);
}

BOOL EXT_FUNC OnTakeDamage(IReGameHook_CBasePlayer_TakeDamage* chain, CBasePlayer* victim, entvars_t* inflictor,
                           entvars_t* attacker, float& damage, int damage_type) {
    if (!g_enabled[kTakeDamage])
        return chain->callNext(victim, inflictor, attacker, damage, damage_type);
    std::vector<EventValue> args{
        EventValue::Int(IndexOf(victim->pev)), EventValue::Int(IndexOf(inflictor)),
        EventValue::Int(PlayerIndexOf(attacker)), EventValue::Float(damage), EventValue::Int(damage_type),
    };
    EventAnswer answer = g_python.OnEvent("take_damage", false, args);
    if (answer.blocked)
        return answer.has_result ? static_cast<BOOL>(answer.result) : FALSE;
    if (answer.changed) {
        damage = static_cast<float>(answer.args[3].f);
        damage_type = static_cast<int>(answer.args[4].i);
    }
    BOOL result = chain->callNext(victim, inflictor, attacker, damage, damage_type);
    args[3] = EventValue::Float(damage);
    args[4] = EventValue::Int(damage_type);
    g_python.OnEvent("take_damage", true, args, result);
    return result;
}

void EXT_FUNC OnKilled(IReGameHook_CBasePlayer_Killed* chain, CBasePlayer* victim, entvars_t* attacker, int gib) {
    if (!g_enabled[kKilled]) {
        chain->callNext(victim, attacker, gib);
        return;
    }
    const int killer = PlayerIndexOf(attacker);
    std::vector<EventValue> args{
        EventValue::Int(IndexOf(victim->pev)), EventValue::Int(killer),
        EventValue::Int(victim->m_LastHitGroup == kHitGroupHead), EventValue::Str(WeaponName(killer)),
    };
    if (g_python.OnEvent("player_killed", false, args).blocked)
        return;
    chain->callNext(victim, attacker, gib);
    args[2] = EventValue::Int(victim->m_bHeadshotKilled);
    g_python.OnEvent("player_killed", true, args);
}

bool EXT_FUNC OnRoundEnd(IReGameHook_RoundEnd* chain, int status, ScenarioEventEndRound event, float delay) {
    if (!g_enabled[kRoundEnd])
        return chain->callNext(status, event, delay);
    std::vector<EventValue> args{EventValue::Int(status), EventValue::Int(event), EventValue::Float(delay)};
    EventAnswer answer = g_python.OnEvent("round_end", false, args);
    if (answer.blocked)
        return answer.has_result && answer.result;
    if (answer.changed)
        delay = static_cast<float>(answer.args[2].f);
    bool result = chain->callNext(status, event, delay);
    args[2] = EventValue::Float(delay);
    g_python.OnEvent("round_end", true, args, result);
    return result;
}

void EXT_FUNC OnRestartRound(IReGameHook_CSGameRules_RestartRound* chain) {
    chain->callNext();
    if (g_enabled[kRoundStart])
        g_python.OnEvent("round_start", true, {});
}

BOOL EXT_FUNC OnChooseTeam(IReGameHook_HandleMenu_ChooseTeam* chain, CBasePlayer* player, int slot) {
    if (!g_enabled[kTeamSelect])
        return chain->callNext(player, slot);
    std::vector<EventValue> args{EventValue::Int(IndexOf(player->pev)), EventValue::Int(slot)};
    EventAnswer answer = g_python.OnEvent("team_select", false, args);
    if (answer.blocked)
        return answer.has_result ? static_cast<BOOL>(answer.result) : FALSE;
    if (answer.changed)
        slot = static_cast<int>(answer.args[1].i);
    BOOL result = chain->callNext(player, slot);
    args[1] = EventValue::Int(slot);
    g_python.OnEvent("team_select", true, args, result);
    return result;
}

void EXT_FUNC OnAddAccount(IReGameHook_CBasePlayer_AddAccount* chain, CBasePlayer* player, int amount, RewardType type,
                           bool track) {
    if (!g_enabled[kMoneyChange]) {
        chain->callNext(player, amount, type, track);
        return;
    }
    std::vector<EventValue> args{EventValue::Int(IndexOf(player->pev)), EventValue::Int(amount),
                                 EventValue::Int(type), EventValue::Int(track)};
    EventAnswer answer = g_python.OnEvent("money_change", false, args);
    if (answer.blocked)
        return;
    if (answer.changed)
        amount = static_cast<int>(answer.args[1].i);
    chain->callNext(player, amount, type, track);
    args[1] = EventValue::Int(amount);
    g_python.OnEvent("money_change", true, args);
}

CBaseEntity* EXT_FUNC OnBuyWeapon(IReGameHook_BuyWeaponByWeaponID* chain, CBasePlayer* player, WeaponIdType id) {
    if (!g_enabled[kBuyWeapon])
        return chain->callNext(player, id);
    std::vector<EventValue> args{EventValue::Int(IndexOf(player->pev)), EventValue::Str(WeaponIdName(id))};
    if (g_python.OnEvent("buy_weapon", false, args).blocked)
        return nullptr;  // не куплено: деньги не списываются
    CBaseEntity* item = chain->callNext(player, id);
    if (item)
        g_python.OnEvent("buy_weapon", true, args);
    return item;
}

CBaseEntity* EXT_FUNC OnDropItem(IReGameHook_CBasePlayer_DropPlayerItem* chain, CBasePlayer* player, const char* item) {
    if (!g_enabled[kDropItem])
        return chain->callNext(player, item);
    std::string name = StripWeapon(item);
    if (name.empty() && player->m_pActiveItem && player->m_pActiveItem->pev)
        name = StripWeapon(STRING(player->m_pActiveItem->pev->classname));  // пустое имя — оружие в руках
    std::vector<EventValue> args{EventValue::Int(IndexOf(player->pev)), EventValue::Str(name), EventValue::Int(0)};
    if (g_python.OnEvent("drop_item", false, args).blocked)
        return nullptr;
    CBaseEntity* box = chain->callNext(player, item);
    if (box) {
        args[2] = EventValue::Int(EntityIndex(box));
        g_python.OnEvent("drop_item", true, args);
    }
    return box;
}

bool EXT_FUNC OnNameChange(IReGameHook_CBasePlayer_SetClientUserInfoName* chain, CBasePlayer* player, char* infobuffer,
                           char* name) {
    if (!g_enabled[kNameChange])
        return chain->callNext(player, infobuffer, name);
    std::vector<EventValue> args{EventValue::Int(IndexOf(player->pev)),
                                 EventValue::Str(STRING(player->pev->netname)),
                                 EventValue::Str(name ? name : "")};
    if (g_python.OnEvent("name_change", false, args).blocked)
        return false;  // ReGameDLL вернёт старый ник в userinfo
    bool result = chain->callNext(player, infobuffer, name);
    if (result)
        g_python.OnEvent("name_change", true, args, result);
    return result;
}

void EXT_FUNC OnFreezeEnd(IReGameHook_CSGameRules_OnRoundFreezeEnd* chain) {
    chain->callNext();
    if (g_enabled[kFreezeEnd])
        g_python.OnEvent("freeze_end", true, {});
}

CGrenade* EXT_FUNC OnThrowGrenade(IReGameHook_CBasePlayer_ThrowGrenade* chain, CBasePlayer* player,
                                  CBasePlayerWeapon* weapon, Vector& src, Vector& velocity, float time,
                                  unsigned short event) {
    CGrenade* grenade = chain->callNext(player, weapon, src, velocity, time, event);
    if (g_enabled[kGrenadeThrow] && grenade) {
        std::string name = weapon && weapon->pev ? StripWeapon(STRING(weapon->pev->classname)) : "";
        g_python.OnEvent("grenade_throw", true,
                         {EventValue::Int(IndexOf(player->pev)), EventValue::Int(EntityIndex(grenade)), EventValue::Str(name)});
    }
    return grenade;
}

CGrenade* EXT_FUNC OnPlantBomb(IReGameHook_PlantBomb* chain, entvars_t* owner, Vector& origin, Vector& angles) {
    CGrenade* bomb = chain->callNext(owner, origin, angles);
    if (g_enabled[kBombPlanted] && bomb)
        g_python.OnEvent("bomb_planted", true, {EventValue::Int(PlayerIndexOf(owner)), EventValue::Int(EntityIndex(bomb))});
    return bomb;
}

void EXT_FUNC OnDefuseStart(IReGameHook_CGrenade_DefuseBombStart* chain, CGrenade* bomb, CBasePlayer* player) {
    if (!g_enabled[kBombDefuseStart]) {
        chain->callNext(bomb, player);
        return;
    }
    std::vector<EventValue> args{EventValue::Int(IndexOf(player->pev)), EventValue::Int(EntityIndex(bomb)),
                                 EventValue::Int(player->m_bHasDefuser)};
    if (g_python.OnEvent("bomb_defuse_start", false, args).blocked)
        return;
    chain->callNext(bomb, player);
    g_python.OnEvent("bomb_defuse_start", true, args);
}

void EXT_FUNC OnDefuseEnd(IReGameHook_CGrenade_DefuseBombEnd* chain, CGrenade* bomb, CBasePlayer* player, bool defused) {
    chain->callNext(bomb, player, defused);
    if (g_enabled[kBombDefuseEnd])
        g_python.OnEvent("bomb_defuse_end", true,
                         {EventValue::Int(player ? IndexOf(player->pev) : 0), EventValue::Int(EntityIndex(bomb)),
                          EventValue::Int(defused)});
}

void EXT_FUNC OnExplodeBomb(IReGameHook_CGrenade_ExplodeBomb* chain, CGrenade* bomb, TraceResult* trace, int bits) {
    const int planter = bomb && bomb->pev ? PlayerIndexOf(bomb->pev->owner ? &bomb->pev->owner->v : nullptr) : 0;
    const int index = EntityIndex(bomb);
    chain->callNext(bomb, trace, bits);
    if (g_enabled[kBombExploded])
        g_python.OnEvent("bomb_exploded", true, {EventValue::Int(planter), EventValue::Int(index)});
}

}  // namespace

void Hooks_Init() {
    g_available = InitApi();
    if (!g_available) {
        ServerPrintf("[amxpy] ReGameDLL API not found: game events (spawn, damage, kills, rounds, buy, bomb...) are unavailable\n");
        return;
    }
    IReGameHookchains* chains = g_api->GetHookchains();
    const int minor = g_api->GetMinorVersion();
    auto want = [&](Hook hook) { return g_registered[hook] = minor >= kMinMinor[hook]; };
    if (want(kSpawn))
        chains->CBasePlayer_Spawn()->registerHook(&OnSpawn);
    if (want(kTakeDamage))
        chains->CBasePlayer_TakeDamage()->registerHook(&OnTakeDamage);
    if (want(kKilled))
        chains->CBasePlayer_Killed()->registerHook(&OnKilled);
    if (want(kRoundEnd))
        chains->RoundEnd()->registerHook(&OnRoundEnd);
    if (want(kRoundStart))
        chains->CSGameRules_RestartRound()->registerHook(&OnRestartRound);
    if (want(kTeamSelect))
        chains->HandleMenu_ChooseTeam()->registerHook(&OnChooseTeam);
    if (want(kMoneyChange))
        chains->CBasePlayer_AddAccount()->registerHook(&OnAddAccount);
    if (want(kBuyWeapon))
        chains->BuyWeaponByWeaponID()->registerHook(&OnBuyWeapon);
    if (want(kDropItem))
        chains->CBasePlayer_DropPlayerItem()->registerHook(&OnDropItem);
    if (want(kNameChange))
        chains->CBasePlayer_SetClientUserInfoName()->registerHook(&OnNameChange);
    if (want(kFreezeEnd))
        chains->CSGameRules_OnRoundFreezeEnd()->registerHook(&OnFreezeEnd);
    if (want(kGrenadeThrow))
        chains->CBasePlayer_ThrowGrenade()->registerHook(&OnThrowGrenade);
    if (want(kBombPlanted))
        chains->PlantBomb()->registerHook(&OnPlantBomb);
    if (want(kBombDefuseStart))
        chains->CGrenade_DefuseBombStart()->registerHook(&OnDefuseStart);
    if (want(kBombDefuseEnd))
        chains->CGrenade_DefuseBombEnd()->registerHook(&OnDefuseEnd);
    if (want(kBombExploded))
        chains->CGrenade_ExplodeBomb()->registerHook(&OnExplodeBomb);
}

bool Hooks_ReGameAvailable() {
    return g_available;
}

bool Hooks_Enable(const char* hook, bool enabled) {
    for (int i = 0; i < kHookCount; ++i) {
        if (std::strcmp(kHookNames[i], hook) == 0) {
            if (!g_available || !g_registered[i])
                return false;
            g_enabled[i] = enabled;
            return true;
        }
    }
    return false;
}
