# Regras de Desenvolvimento do Agente · Miku Visual Companion

Este documento define as diretrizes obrigatórias de desenvolvimento, controle de versão e boas práticas para o agente de IA neste repositório.

---

## 1. Convenção de Commits (Conventional Commits em Português)
Todo commit deve seguir o padrão Conventional Commits com mensagens claras em português:
- `feat:` Nova funcionalidade ou recurso para o usuário.
- `fix:` Correção de bug ou falha no sistema.
- `docs:` Alterações em documentação (`README.md`, `AGENT_RULES.md`, comentários).
- `refactor:` Refatoração de código sem alterar comportamento externo.
- `test:` Adição ou modificação de testes unitários (`pytest`).
- `chore:` Tarefas de manutenção, dependências ou scripts auxiliares.

Exemplo:
```bash
git commit -m "feat: adiciona persistencia de memoria no SQLite"
```

---

## 2. Fluxo de Branches e Entregas Atômicas
Para novas fases ou grandes funcionalidades:
1. **Criar branch dedicada**:
   ```bash
   git checkout -b feat/nome-da-feature
   ```
2. **Commits atômicos**:
   - Commitar cada etapa funcional e independente concluída.
3. **Validação Obrigatória**:
   - Rodar a suíte de testes antes de integrar:
     ```bash
     .\.venv\Scripts\python.exe -m pytest
     ```
   - Todos os testes devem passar (100% green).
4. **Integração na `main` e Push**:
   - Após teste e validação:
     ```bash
     git checkout main
     git merge feat/nome-da-feature
     git push origin main
     ```

---

## 3. Segurança e Privacidade Absoluta (Zero Secrets)
- **NUNCA** commitar arquivos `.env` ou expor chaves de API (`GEMINI_API_KEY`).
- **NUNCA** commitar bancos de dados locais (`*.db`, `*.sqlite*`) ou a pasta `data/`.
- **NUNCA** commitar pastas de ambientes virtuais (`.venv/`, `venv/`) ou caches (`__pycache__/`).
- Manter o [`.env.example`](.env.example) sempre atualizado com as variáveis necessárias sem valores sensíveis.
- Manter o [`.gitignore`](.gitignore) rigorosamente atualizado.
