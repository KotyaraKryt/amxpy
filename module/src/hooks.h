// Игровые события через hookchain'ы ReGameDLL: player_spawn, take_damage, player_killed,
// round_start, round_end. Хуки ставятся один раз и пропускают вызов, пока событие никому не нужно.
#pragma once

void Hooks_Init();
bool Hooks_ReGameAvailable();
bool Hooks_Enable(const char* hook, bool enabled);  // false — хука на этом сервере нет
