// Состояние модуля, общее для обвязки движка, рантайма и хуков.
#pragma once

#include <string>

#include "sdk.h"

constexpr int kMaxClients = 32;

// То, что движок не сообщает напрямую: подключён ли слот и с какого IP
struct PlayerSlot {
    bool connected = false;
    double pending_since = 0.0;  // смена карты: ждём, переподключится ли игрок
    std::string ip;
};

extern PlayerSlot g_slots[kMaxClients + 1];
extern int g_msg_saytext;
extern int g_msg_money;
extern bool g_plugins_loaded;

edict_t* EdictOf(int index);              // nullptr — нет такой сущности
edict_t* PlayerEdict(int index);          // nullptr — слот не подключён
int IndexOf(const edict_t* e);
int IndexOf(const entvars_t* pev);        // 0 для nullptr
int PlayerIndexOf(const entvars_t* pev);  // 0 — не игрок
CBasePlayer* PlayerOf(int index);         // nullptr без ReGameDLL или без игрока
double MonotonicNow();
void ServerPrintf(const char* fmt, ...);

// DLL-хуки: meta_glue.cpp отдаёт их Metamod
void Hook_StartFrame();
qboolean Hook_ClientConnect(edict_t* e, const char* name, const char* address, char reject[128]);
void Hook_ClientDisconnect(edict_t* e);
void Hook_ClientCommand(edict_t* e);
void Hook_ServerDeactivate();
void Hook_ClientPutInServer_Post(edict_t* e);
void Hook_ClientUserInfoChanged_Post(edict_t* e, char* infobuffer);
void Hook_ServerActivate_Post(edict_t* edicts, int count, int max_clients);
