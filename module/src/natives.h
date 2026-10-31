// Нативы Python-плагинов для Pawn и форварды из Python в Pawn.
#pragma once

typedef struct _object PyObject;

// AMXX принимает нативы модуля только в AMXX_Attach — регистрируем всё, что объявили плагины
void Natives_RegisterAll();
// Доступен ли натив Pawn-плагинам (вызов из рантайма при загрузке плагина)
bool Natives_Declare(const char* name, const char* params, const char* returns);

// Форварды AMXX живут одну карту: id сбрасываются вместе с плагинами
void Forwards_Reset();
// Вызывающий держит GIL. -1 и исключение Python — при ошибке аргументов
int Forwards_Execute(const char* name, const char* types, PyObject* args);

// Натив __amxpy_forward для Pawn-форвардов в Python (bridge.cpp)
void Bridge_RegisterNatives();
