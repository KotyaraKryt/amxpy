// Вызов чужих нативов AMXX из Python (bridge.cpp): методы модуля _amxpy.
#pragma once

#include <Python.h>

PyObject* BridgeLoad(PyObject* self, PyObject* args);
PyObject* BridgeCall(PyObject* self, PyObject* args);

// Pawn-форварды → Python: натив __amxpy_forward плагина-приёмника и доступ к памяти AMX
void Bridge_RegisterNatives();
PyObject* AmxRead(PyObject* self, PyObject* args);
PyObject* AmxString(PyObject* self, PyObject* args);
PyObject* AmxWrite(PyObject* self, PyObject* args);
