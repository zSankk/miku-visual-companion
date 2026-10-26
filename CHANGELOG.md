# 📜 Registro de Atualizações (Changelog) · Miku Visual Companion

Todas as alterações notáveis deste projeto serão documentadas neste arquivo, seguindo as diretrizes do [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/) e [Semantic Versioning](https://semver.org/lang/pt-BR/).

---

## [v0.2.0] - 2026-10-26

### 🚀 Novas Funcionalidades
- **🧠 Sistema Avançado de Memória Persistente SQLite**:
  - Armazenamento portátil com caminho configurável salvo em `config/settings.json` (padrão: `data/miku_memory.db`).
  - **Migração Automática de Pasta**: Troca de diretório pela interface com cópia e reconexão segura do banco sem perda de dados.
  - Estrutura relacional com tabela `facts` (fatos pessoais, preferências, projetos e outros com suporte a fixação `is_pinned`) e tabela `summaries` (resumos compactos de sessões anteriores).
  - **Recuperação Contextual com Custo Zero de Tokens**: O prompt para o Gemini injeta apenas os fatos fixados, os top 5 fatos mais relevantes para a mensagem atual (via busca por palavras-chave) e os últimos 3 resumos de sessões anteriores.
  - **Aprendizado Ativo com Trava de Privacidade**: A IA gera automaticamente tags ocultas `[MEMORIA: categoria | fato | confirmado]` filtradas do chat e do TTS, com validação via Regex para bloquear senhas, chaves de API e dados sensíveis.
- **✨ Pílula de Memória no Chat (Estilo ChatGPT)**:
  - Exibição de um balão visual destacado `🧠 Memória salva: <fato>` acima da resposta da Miku sempre que uma nova informação for aprendida durante a conversa.
- **📋 Painel de Gerenciamento de Memória & Armazenamento**:
  - Interface dedicada com CRUD completo de memórias (adicionar, editar, excluir individualmente ou limpar tudo).
  - Botão para fixar memórias essenciais que ela nunca deve esquecer.
  - Exportação e importação de backups completos em formato `.json`.
  - Interruptor de modo privado (amnésia temporária) e botão "Nova Sessão" com resumo inteligente em 1 frase gerado pela IA.
- **🔑 Gerenciador de Chave de API no Aplicativo**:
  - Modal para visualizar, inserir ou alterar a `GEMINI_API_KEY` e selecionar o modelo ativo diretamente dentro do aplicativo, persistindo no arquivo `.env`.

---

### 🎨 Melhorias Visuais e UI/UX
- **📐 Layout Responsivo e Sem Quebras**:
  - Implementação de cálculo dinâmico de `wraplength` via evento `<Configure>` nos cartões e mensagens do chat, evitando cortes em diferentes resoluções.
  - Reorganização do painel *Studio de Modelos* em grade 2x2 para acomodar os botões sem esmagamento horizontal.
  - Eliminação de artefatos visuais e "fantasmas" no scroll rápido do CustomTkinter através de renderização forçada no `<MouseWheel>`.
- **📍 Posicionamento Preciso do Modo Mascote**:
  - Detecção da área útil de trabalho do Windows (`SPI_GETWORKAREA`), posicionando a mascote perfeitamente repousada acima da barra de tarefas sem cobrir o relógio ou a bandeja do sistema.
  - Centralização automática ao restaurar para o Modo Janela Completa.
- **🖐️ Controle de Navegação do Modelo Live2D**:
  - Agora é possível clicar e arrastar com o mouse para mover/panoramizar a Miku para cima, baixo e para os lados no modo janela.
  - Suporte a `Shift + Scroll` para ajuste fino de altura e `Scroll` para zoom.

---

### 🛠️ Correções de Bugs
- **Erro de Inicialização com CTkFont (`bad -weight value 'italic' / 'underline'`)**:
  - Correção na sintaxe de fontes do CustomTkinter/Tkinter onde estilos eram passados como terceiro argumento posicional em vez de argumentos nomeados (`slant="italic"`, `underline=True`).
- **Erro no Teste de Microfone (`paBadIODeviceCombination` -9993)**:
  - Correção na seleção de HostAPI do PortAudio no `stt.py` para sincronizar o host do dispositivo de gravação e reprodução durante o teste de loopback, com fallback gracioso para gravação direta.
- **Botões Ocultos no Modal de Chave de API**:
  - Ancoragem fixa da barra de botões no rodapé (`side="bottom"`) e área rolável superior, impedindo que a escala de DPI do Windows (125%/150%) empurre os botões para fora da tela.
  - Adição de salvamento direto ao pressionar a tecla `Enter`.

---

### 🔒 Segurança, Estabilidade e Resiliência
- **Resiliência a Erros HTTP 503 ("High Demand") do Gemini**:
  - Implementação de retry automático com espera de 1 segundo para erros transitórios de alta demanda na API gratuita do Google.
  - Mecanismo de fallback transparente para modelos irmãos ativos (`gemini-flash-lite-latest`, `gemini-3.5-flash`, `gemini-3.8-flash`, `gemini-flash-latest`), evitando que a Miku fique sem responder.
- **Suíte de Testes Automatizados**:
  - Cobertura expandida para 88 testes unitários passando (`pytest`), cobrindo roteamento, memória, persistência, voz e resiliência da IA.

---

## [v0.1.0] - 2026-10-26

### 🚀 Versão Inicial
- **Cérebro Gemini Flash-Lite**: Roteador com persona da Miku, tags de humor e prompts específicos para modo Casual e Dev.
- **Avatar Live2D Cubism 4 Embutido**: Palco WebGL com PixiJS embutido via WebView2 e modelos do Projeto Sekai.
- **Voz Vocaloid / Anime**: Síntese de voz com pipeline local MikuTTS (RVC) e fallback Edge-TTS.
- **STT 100% Local**: Reconhecimento de voz privado com Faster-Whisper e controle de mudo físico.
- **Modo Mascote Transparente**: Janela sem bordas Always-on-Top no canto da tela.
- **Scripts de Portabilidade**: Automação de setup e execução com `setup.bat` e `run.bat`.
- **Segurança de Repositório**: Configuração rigorosa de `.gitignore` e modelo `.env.example`.
