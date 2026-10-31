"""Плагин харнесса: вызывает подставные нативы фейкового ядра через amxpy.amxx."""

from amxpy import Plugin, amxx, server

plugin = Plugin("Bridge probe")


@plugin.server_command("bridge_test")
def bridge_test() -> None:
    name = amxx.String(32)
    written = amxx.call("harness_get_name", 1, name, 31)
    total = amxx.call("harness_add", 40, 2)
    out = amxx.FloatRef(1.25)
    scaled = amxx.call_float("harness_scale", 2.5, out)
    values = amxx.Array([1, 2, 3])
    amxx.call("harness_double", values, 3)
    length = amxx.call("harness_strlen", "Привет")
    try:
        amxx.call("harness_fail")
        failed = "no"
    except amxx.NativeError:
        failed = "yes"
    missing = amxx.available("harness_missing")
    total = amxx.call("harness_add", total, 0)  # из кеша, без нового моста
    server.console(f"bridge: {name.value} {written} {total} {scaled} {out.value} {values.values} {length} {failed} {missing}")


@plugin.on_forward("harness_fwd")
def harness_fwd(number: int, text: str, counter: amxx.Ref) -> int:
    counter.value *= 2
    server.console(f"harness_fwd: {number} {text} {counter.value}")
    return 3
