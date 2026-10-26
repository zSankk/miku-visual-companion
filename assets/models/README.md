# Modelos Live2D da Rin (`assets/models/`)

Coloque qualquer modelo **Live2D Cubism 4** (`.model3.json` + pastas de texturas `.2048/`, `.moc3`, `.physics3.json`, `expressions/`, `motion/`) dentro desta pasta.

## Como trocar para um modelo da Hatsune Miku
1. Copie a pasta do modelo (por exemplo `assets/models/miku/`) contendo o arquivo `.model3.json`.
2. Abra `config/persona.yaml` e altere `avatar_model_path`:
   ```yaml
   avatar_model_path: "assets/models/miku/miku.model3.json"
   ```
3. Clique em **+ Nova Sessão** na interface da Rin (ou reinicie o aplicativo) para carregar o novo modelo imediatamente!

## Modelo Padrão Incluso
- `assets/models/haru/haru_greeter_t03.model3.json` (Live2D Cubism 4 — Haru Greeter Oficial)
- CDN equivalente: `https://cdn.jsdelivr.net/gh/guansss/pixi-live2d-display/test/assets/haru/haru_greeter_t03.model3.json`
