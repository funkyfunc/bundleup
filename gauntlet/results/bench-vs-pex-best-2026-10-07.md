| Tool | Project | Python | Build (ms) | First run (ms) | Warm start (ms) |
|---|---|---|---|---|---|
| venv | 03-pure-deps | 3.12 | – | – | 29 |
| bundleup | 03-pure-deps | 3.12 | 208 | 48 | 28 |
| pex | 03-pure-deps | 3.12 | 1,472 | 589 | 203 |
| pex-pylock | 03-pure-deps | 3.12 | 3,595 | 711 | 78 |
| pex-venv | 03-pure-deps | 3.12 | 496 | 711 | 84 |
| venv | 13-native-bundled-libs | 3.12 | – | – | 38 |
| bundleup | 13-native-bundled-libs | 3.12 | 486 | 562 | 38 |
| pex | 13-native-bundled-libs | 3.12 | 1,858 | 1,165 | 228 |
| pex-pylock | 13-native-bundled-libs | 3.12 | 5,155 | 1,372 | 88 |
| pex-venv | 13-native-bundled-libs | 3.12 | 807 | 1,318 | 88 |
| venv | 21-large-pure-python | 3.12 | – | – | 340 |
| bundleup | 21-large-pure-python | 3.12 | 2,838 | 1,370 | 341 |
| pex | 21-large-pure-python | 3.12 | 4,783 | 3,173 | 726 |
| pex-pylock | 21-large-pure-python | 3.12 | can't build (see findings) | | |
| pex-venv | 21-large-pure-python | 3.12 | 3,082 | 3,591 | 422 |
