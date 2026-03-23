# Auto-setup krach in Pyodide
import micropip
await micropip.install(["krach", "faust-dsl"])

from krach._web_audio import connect_web
kr = connect_web(bpm=120, master=0.7)
import krach.dsp as krs

print("krach ready!")
print("  kr  = audio graph (nodes, patterns, routing)")
print("  krs = DSP primitives (oscillators, filters, envelopes)")
print()
print("Try:")
print('  bass = kr.node("bass", "oscillator", gain=0.3)')
print('  bass @ kr.hit() * 4')
