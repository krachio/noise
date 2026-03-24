"""Exported krach session."""
import json
from krach.patterns.ir import dict_to_ir
from krach.patterns.pattern import Pattern
import krach.dsp as krs


@kr.dsp
def acid_bass() -> krs.Signal:
    freq = krs.control("freq", 55.0, 20.0, 800.0)
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    cutoff = krs.control("cutoff", 800.0, 100.0, 4000.0)
    env = krs.adsr(0.005, 0.15, 0.3, 0.08, gate)
    return krs.lowpass(krs.saw(freq), cutoff) * env * 0.55

@kr.dsp
def kick() -> krs.Signal:
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    env = krs.adsr(0.001, 0.25, 0.0, 0.05, gate)
    return krs.sine_osc(55.0 + env * 200.0) * env * 0.9

@kr.dsp
def acid_bass() -> krs.Signal:
    freq = krs.control("freq", 55.0, 20.0, 800.0)
    gate = krs.control("gate", 0.0, 0.0, 1.0)
    cutoff = krs.control("cutoff", 800.0, 100.0, 4000.0)
    env = krs.adsr(0.005, 0.15, 0.3, 0.08, gate)
    return krs.lowpass(krs.saw(freq), cutoff) * env * 0.55

@kr.dsp
def reverb(inp: krs.Signal) -> krs.Signal:
    room = krs.control("room", 0.7, 0.0, 1.0)
    return krs.reverb(inp, room) * 0.8

with kr.batch():
    kr.node("bass", bass, gain=0.0)
    kr.node("kick", kick, gain=0.8)
    kr.node("pad", pad, gain=0.2, count=4)
    kr.node("verb", verb, gain=0.3)
kr.send("bass", "verb", level=0.4)
kr.tempo = 128.0
kr.master = 0.7

_patterns = json.loads('{"bass":{"op":"Slow","factor":[2,1],"child":{"op":"Cat","children":[{"op":"Freeze","child":{"op":"Cat","children":[{"op":"Stack","children":[{"op":"Atom","value":{"type":"Control","label":"freq","value":110.0}},{"op":"Atom","value":{"type":"Control","label":"gate","value":1.0}}]},{"op":"Atom","value":{"type":"Control","label":"gate","value":0.0}}]}},{"op":"Freeze","child":{"op":"Cat","children":[{"op":"Stack","children":[{"op":"Atom","value":{"type":"Control","label":"freq","value":146.8323839587038}},{"op":"Atom","value":{"type":"Control","label":"gate","value":1.0}}]},{"op":"Atom","value":{"type":"Control","label":"gate","value":0.0}}]}},{"op":"Silence"},{"op":"Freeze","child":{"op":"Cat","children":[{"op":"Stack","children":[{"op":"Atom","value":{"type":"Control","label":"freq","value":82.4068892282175}},{"op":"Atom","value":{"type":"Control","label":"gate","value":1.0}}]},{"op":"Atom","value":{"type":"Control","label":"gate","value":0.0}}]}}]}},"bass/cutoff":{"op":"Slow","factor":[4,1],"child":{"op":"Cat","children":[{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1100.0}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1188.2154262966046}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1275.5812898145155}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1361.2562095290161}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1444.4150891285808}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1524.257063143398}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1600.013209717642}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1670.953955747281}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1736.3961030678927}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1795.7094080264633}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1848.322651072291}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1893.7291379135195}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1931.491579260158}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1961.2463021589879}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1982.7067523629073}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1995.666254004977}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":2000.0}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1995.6662540049772}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1982.7067523629073}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1961.246302158988}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1931.491579260158}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1893.7291379135195}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1848.322651072291}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1795.7094080264635}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1736.3961030678927}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1670.953955747281}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1600.013209717642}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1524.2570631433982}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1444.4150891285808}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1361.2562095290164}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1275.5812898145157}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1188.2154262966048}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1100.0000000000002}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1011.7845737033955}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":924.4187101854844}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":838.7437904709841}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":755.5849108714193}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":675.742936856602}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":599.9867902823582}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":529.0460442527192}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":463.60389693210726}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":404.290591973537}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":351.6773489277093}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":306.2708620864805}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":268.5084207398421}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":238.75369784101207}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":217.29324763709272}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":204.33374599502275}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":200.0}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":204.33374599502275}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":217.2932476370926}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":238.75369784101196}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":268.50842073984205}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":306.27086208648046}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":351.6773489277091}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":404.29059197353683}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":463.6038969321071}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":529.0460442527187}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":599.986790282358}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":675.7429368566019}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":755.5849108714186}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":838.7437904709838}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":924.4187101854841}},{"op":"Atom","value":{"type":"Control","label":"ctrl","value":1011.7845737033955}}]}},"kick":{"op":"Freeze","child":{"op":"Cat","children":[{"op":"Atom","value":{"type":"Control","label":"gate","value":1.0}},{"op":"Atom","value":{"type":"Control","label":"gate","value":0.0}}]}},"pad":{"op":"Freeze","child":{"op":"Stack","children":[{"op":"Freeze","child":{"op":"Cat","children":[{"op":"Stack","children":[{"op":"Atom","value":{"type":"Control","label":"freq","value":440.0}},{"op":"Atom","value":{"type":"Control","label":"gate","value":1.0}}]},{"op":"Atom","value":{"type":"Control","label":"gate","value":0.0}}]}},{"op":"Freeze","child":{"op":"Cat","children":[{"op":"Stack","children":[{"op":"Atom","value":{"type":"Control","label":"freq","value":523.2511306011972}},{"op":"Atom","value":{"type":"Control","label":"gate","value":1.0}}]},{"op":"Atom","value":{"type":"Control","label":"gate","value":0.0}}]}},{"op":"Freeze","child":{"op":"Cat","children":[{"op":"Stack","children":[{"op":"Atom","value":{"type":"Control","label":"freq","value":659.2551138257398}},{"op":"Atom","value":{"type":"Control","label":"gate","value":1.0}}]},{"op":"Atom","value":{"type":"Control","label":"gate","value":0.0}}]}}]}}}')
for _slot, _ir in _patterns.items():
    kr.play(_slot, Pattern(dict_to_ir(_ir)))
kr.set("bass/cutoff", 1200)
kr.set("bass/gain", 0.0)
