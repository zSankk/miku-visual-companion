# 🎤 Miku Visual Companion

Assistente Virtual Inteligente de Desktop com **Hatsune Miku**, combinando **IA Generativa Gemini Flash-Lite**, **Avatar Live2D Cubism 4 (Projeto Sekai)** embutido, **Voz Vocaloid/Anime (RVC Local + Fallback Edge-TTS)**, **Reconhecimento de Voz 100% Local (Faster-Whisper)**, **Memória Persistente SQLite** e **Modo Mascote Transparente** no canto da tela.

---

## 🌟 Principais Recursos

- **🧠 Cérebro Inteligente (Gemini Flash-Lite)**: Respostas rápidas, naturais e concisas em português brasileiro com tags dinâmicas de emoção, ação e resiliência com fallback automático.
- **💾 Memória de Longo Prazo (SQLite Persistente)**: Gravação contínua de preferências e fatos com aprendizado automático, pílula de memória estilo ChatGPT no chat, busca contextual (zero custo de tokens) e portabilidade com migração de pasta e backups JSON.
- **🎭 Avatar Live2D Cubism 4 Embutido**: Palco WebGL transparente com PixiJS renderizando modelos oficiais da Hatsune Miku do Projeto Sekai com física de cabelo, piscar de olhos, respiração natural, arraste com mouse e zoom.
- **🎙️ Voz Vocaloid / Anime**: Síntese de voz com pipeline local Miku RVC e fallback automático resiliente para Microsoft Edge-TTS (`pt-BR-FranciscaNeural`).
- **🎧 Reconhecimento de Voz 100% Local**: Transcrição contínua com Faster-Whisper e VAD (Voice Activity Detection), sem enviar áudio para a nuvem.
- **👄 LipSync a 60 FPS**: Movimentação labial perfeitamente sincronizada em tempo real com a saída de áudio.
- **📌 Modo Mascote PNG no Canto da Tela**: Fixa a Miku no desktop sem fundo e sempre no topo (*Always on Top*), posicionada com precisão sobre a barra de tarefas sem cobrir o relógio do Windows.

---

## 🗺️ Roadmap de Desenvolvimento

- [x] **Fase 1: Arquitetura Base, Router e Personalidade**
  - Roteador de conversa inteligente, prompt da persona Miku em `config/persona.yaml` e estados de humor.
- [x] **Fase 2: STT Faster-Whisper Local e Voz MikuTTS**
  - Reconhecimento de voz privado local via Faster-Whisper, controle de Hard Mute físico e síntese MikuTTS RVC com fallback Edge-TTS.
- [x] **Fase 3: Avatar Live2D Embutido, Emotes e Modo Mascote**
  - Palco PixiJS + Cubism 4 embutido via WebView2, modelos Project Sekai (Normal, Idol, Night, Wonder), articulação simétrica de braços, aceno e Modo Mascote com transparência real.
- [x] **Fase 4: Memória de Longo Prazo SQLite & Menu de Configurações**
  - Banco SQLite com diretório configurável e migração automática de pasta, extração de preferências via tags ocultas `[MEMORIA: ...]`, pílula visual de feedback no chat, CRUD visual de fatos, fixação de memórias, backups em JSON e gerenciador de chaves de API.
- [ ] **Fase 5: Integração Antigravity MCP Bridge**
  - Conexão MCP para execução de tarefas de desenvolvimento e comandos autônomos no ambiente.

Para conferir o histórico detalhado de cada versão e suas mudanças, veja o [**`CHANGELOG.md`**](CHANGELOG.md).

---

## 🚀 Como Rodar em um Novo PC (Windows)

### Pré-requisitos
1. **Python 3.10 ou superior** instalado ([python.org](https://www.python.org/downloads/)) — marque a opção *"Add Python to PATH"*.
2. **Git** instalado ([git-scm.com](https://git-scm.com/)).
3. **Microsoft Edge WebView2 Runtime** (já incluído no Windows 10/11 por padrão).

---

### Passo a Passo Rápido

#### 1. Clonar o Repositório
```bash
git clone https://github.com/zSankk/miku-visual-companion.git
cd miku-visual-companion
```

#### 2. Configurar o Ambiente com 1 Clique (`setup.bat`)
Dê um duplo clique no arquivo **`setup.bat`** (ou execute no terminal):
```bat
setup.bat
```
O script irá automaticamente:
- Verificar sua instalação do Python.
- Criar o ambiente virtual `.venv`.
- Atualizar o `pip` e instalar todas as dependências (`requirements.txt`).
- Gerar o arquivo `.env` a partir de `.env.example`.

#### 3. Configurar a Chave de API
Abra o arquivo `.env` criado na raiz do projeto e insira sua chave gratuita do Google AI Studio (ou configure diretamente pela interface do aplicativo no botão 🔑):
```env
GEMINI_API_KEY=sua_chave_aqui
```
> *Obtenha sua chave gratuita em: [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey)*

#### 4. Iniciar a Aplicação (`run.bat`)
Dê um duplo clique em **`run.bat`**:
```bat
run.bat
```
A Miku iniciará na sua tela pronta para interagir!

---

## ⌨️ Atalhos Úteis

- **`Ctrl + M`**: Mutar / desmutar microfone instantaneamente.
- **`Ctrl + N`**: Iniciar uma nova sessão de conversa.
- **`Ctrl + D`**: Alternar entre o modo *Casual* e modo *Dev*.
- **`Esc`**: Sair do Modo Mascote e voltar à janela principal.
- **Scroll na Miku (Modo Mascote)**: Aumentar ou diminuir o tamanho dela na tela.
- **Clique e Arraste (Modo Janela)**: Mover e reposicionar o modelo Live2D no palco.
- **Shift + Scroll (Modo Janela)**: Mover o modelo verticalmente.

---

## 🔒 Segurança e Privacidade

- **Chaves de API e Segredos**: Arquivos `.env` e chaves privadas nunca são versionados no repositório ([`.gitignore`](.gitignore)).
- **Privacidade de Áudio**: A voz do seu microfone é transcrita 100% localmente pelo Faster-Whisper na sua CPU/GPU, sem upload de áudio para servidores externos.
- **Código Aberto e Modular**: Arquitetura desacoplada em `src/core`, `src/avatar`, `src/voice`, `src/memory` e `src/ui`.
