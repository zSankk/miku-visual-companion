# 🎤 Miku Visual Companion

> ⚠️ **Projeto Não-Comercial de Fã (Fan-Made / Non-Profit Open Source):**
> Este é um projeto de código aberto sem fins lucrativos, desenvolvido exclusivamente por fãs para fins de estudo, aprendizado e entretenimento pessoal. Este software **não é oficial** e não possui nenhuma afiliação, patrocínio ou endosso da **Crypton Future Media, INC.**, **SEGA Corporation** ou **Colorful Palette Inc.**.

---

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
  - Banco SQLite com diretório configurável e migração automática de pasta, extração de preferências via tags ocultas `[MEMORIA: ...]`, pílula visual de feedback no chat, CRUD visual de fatos, fixação de memórias, backups em JSON e gerenciador de chaves de API no app.
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

#### 2. Instalação com 1 Clique (`setup.bat`)
Dê um duplo clique no arquivo **`setup.bat`** (ou execute no terminal):
```bat
setup.bat
```
O script irá automaticamente:
- Verificar sua instalação do Python.
- Criar o ambiente virtual isolado (`.venv`).
- Atualizar o `pip` e instalar todas as dependências (`requirements.txt`).
- Baixar os pesos da voz da Miku (RVC local, ~930 MB, só na primeira vez) em `data/models/miku_rvc/`.
- Gerar o arquivo de configuração `.env` inicial.

> 🎤 **Voz da Miku:** sem esses pesos o app funciona, mas fala com a voz reserva do Edge-TTS (`pt-BR-FranciscaNeural`). Se o download falhar ou for interrompido, rode o `setup.bat` de novo, ou apenas:
> ```bat
> .venv\Scripts\python.exe scripts\download_miku_models.py
> ```
> O script baixa **somente pesos** (nenhum código), em versões fixas, e confere o SHA-256 de cada arquivo antes de instalar. Em PCs sem GPU NVIDIA a voz é gerada pela CPU e cada frase pode levar alguns segundos.

#### 3. Iniciar a Aplicação (`run.bat`)
Dê um duplo clique em **`run.bat`**:
```bat
run.bat
```
A Miku iniciará na sua tela imediatamente! Caso seja a primeira vez e você ainda não tenha uma chave configurada, ela iniciará em **Modo Offline (Simulado)** para você testar a interface, o avatar, a voz e os controles sem custo.

#### 4. Configurar a Chave de API Diretamente no Aplicativo (Sem Editar Arquivos!)
Você pode ativar a IA do Gemini em segundos direto pela interface gráfica:
1. No menu lateral esquerdo, clique no botão **🔑 Chave de API** (ou no rodapé).
2. Acesse o **[Google AI Studio (aistudio.google.com/apikey)](https://aistudio.google.com/apikey)** para obter sua chave:
   > 💡 **Como gerar a chave 100% gratuita (Free Tier):**
   > No Google AI Studio, clique no botão azul **"Create API key"** (Criar chave de API) e selecione a opção **"Create API key in new project"** (Criar chave de API em novo projeto). Isso cria a chave instantaneamente no plano gratuito do Google, **sem pedir cartão de crédito nem dados de cobrança**!
3. Cole a sua chave gerada (`AIzaSy...`) no campo do aplicativo.
4. Escolha o modelo desejado (recomendado: `gemini-3.5-flash-lite` ou `gemini-flash-lite-latest`).
5. Clique em **💾 Salvar e Aplicar** (ou simplesmente pressione **Enter**).
6. O aplicativo salva a chave automaticamente no `.env` e ativa as respostas inteligentes na mesma hora, sem precisar reiniciar!

> *(Opcional)* Se preferir o método manual tradicional por arquivo de texto, você também pode abrir o arquivo `.env` gerado na raiz e preencher `GEMINI_API_KEY=sua_chave`.

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

---

## ⚖️ Aviso Legal & Propriedade Intelectual (Disclaimer)

- **Hatsune Miku (初音ミク)** é uma personagem e software de síntese vocal de titularidade de **Crypton Future Media, INC.** (札幌市中央区). Este projeto é uma obra derivada não comercial criada por fãs em conformidade com as diretrizes da [Piapro Character License (PCL)](https://piapro.jp/license/pcl/summary) e os termos de uso de personagens para fins não lucrativos da Crypton.
- **Modelos e Assets Visuais (Project SEKAI: Colorful Stage!)**: Todos os designs de personagens, malhas de modelos Live2D Cubism e elementos visuais pertencem a **SEGA Corporation**, **Colorful Palette Inc.** e **Crypton Future Media, INC.**. O uso aqui tem finalidade exclusivamente recreativa, educacional e sem fins comerciais.
- **Gratuidade Absoluta**: Este software é e sempre será 100% gratuito e de código aberto. É expressamente proibida qualquer comercialização, venda, inclusão de anúncios monetizados ou cobrança de qualquer natureza associada a este projeto.
