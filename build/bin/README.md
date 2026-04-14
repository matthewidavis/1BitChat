# Prebuilt BitNet.cpp binaries

The files in this directory are redistributed **unmodified** from builds of
[Microsoft/BitNet](https://github.com/microsoft/BitNet), which is licensed
under the MIT License.

## Files

| File | Purpose |
|---|---|
| `llama-server.exe` | OpenAI-compatible HTTP inference server (spawned by 1BitChat) |
| `llama.dll` | Core llama.cpp runtime (required by `llama-server.exe`) |
| `ggml.dll` | GGML tensor library (required by `llama.dll`) |
| `llava_shared.dll` | LLaVA support library (dependency of the server binary) |
| `libomp.dll` | LLVM OpenMP runtime — ships here so users don't need LLVM installed |

## Rebuilding

To rebuild these from source, follow the BitNet.cpp build instructions:
<https://github.com/microsoft/BitNet#installation>

## License

MIT, inherited from the upstream project. See that repo for the full license
and attribution.
