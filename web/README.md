# krach Web REPL

Browser-based interactive REPL for krach, powered by JupyterLite + Pyodide.

## Build

```bash
pip install jupyterlite-core jupyterlite-pyodide-kernel
cd web
jupyter lite build --output-dir ../docs/site/try
```

## Development

```bash
jupyter lite serve
```

Opens at http://localhost:8000 with the welcome notebook.

## Architecture

- JupyterLite provides the IPython REPL in the browser
- Pyodide runs CPython compiled to WASM
- krach Python package loaded via micropip
- Web Audio API provides synthesis (built-in oscillators, not FAUST)
- pattern-engine-py (future) will provide Rust pattern evaluation in WASM
