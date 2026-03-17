# ✦ Belle Salão — Sistema Completo v3

## Acesso rápido

| URL | Área |
|-----|------|
| `http://localhost:8000` | 👤 Clientes — agendar |
| `http://localhost:8000/meu-agendamento` | 🔑 Clientes — cancelar/remarcar |
| `http://localhost:8000/admin` | 🔐 Painel administrativo |
| `http://localhost:8000/docs` | 📖 Documentação da API |

---

## Rodar localmente

```bash
# 1. Copiar e configurar variáveis de ambiente
cp .env.example .env
# Edite o .env com suas configurações

# 2. Instalar dependências
pip install -r requirements.txt

# 3. Iniciar
uvicorn main:app --reload
```

Login padrão: `admin` / `salao123` (configure no `.env`)

---

## Configurar o .env

```env
ADMIN_USER=admin
ADMIN_PASSWORD=SuaSenhaForte@2025   ← TROQUE SEMPRE

SECRET_KEY=chave-aleatoria-longa    ← gere com: python -c "import secrets; print(secrets.token_hex(32))"

SALAO_NOME=Belle Salão
SALAO_WHATSAPP=5511999990000        ← DDI+DDD+número sem espaços

# E-mail (opcional)
EMAIL_ENABLED=false
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USER=seuemail@gmail.com
EMAIL_PASSWORD=senha_de_app_gmail
```

### Ativar e-mail com Gmail
1. Ative verificação em 2 etapas na conta Google
2. Conta Google → Segurança → **Senhas de app** → criar senha
3. Cole no `EMAIL_PASSWORD` e mude `EMAIL_ENABLED=true`

---

## Publicar online (gratuito)

### Opção 1 — Railway (recomendado, mais simples)

1. Crie conta em https://railway.app
2. Novo projeto → **Deploy from GitHub**
3. Faça upload ou conecte o repositório
4. Vá em **Variables** e adicione todas as variáveis do `.env`
5. Adicione um **Volume** montado em `/data` para persistir o banco
6. Deploy automático — Railway fornece uma URL pública com HTTPS ✅

### Opção 2 — Render (gratuito com limitações)

1. Crie conta em https://render.com
2. Novo serviço → **Web Service** → conecte o repositório
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Adicione as variáveis de ambiente no painel
6. ⚠️ No plano gratuito o banco não persiste — use um **Disk** pago ou migre para PostgreSQL

### Opção 3 — VPS (DigitalOcean, Contabo, etc.)

```bash
# No servidor Ubuntu
git clone <seu-repo>
cd salao
cp .env.example .env && nano .env    # configure as variáveis

pip install -r requirements.txt

# Rodar em background com systemd ou screen
uvicorn main:app --host 0.0.0.0 --port 8000

# HTTPS com Nginx + Certbot (recomendado para produção)
# sudo apt install nginx certbot python3-certbot-nginx
# sudo certbot --nginx -d seudominio.com.br
```

---

## Funcionalidades v3

### 👤 Área do Cliente
- Agendamento guiado em etapas
- Serviços por categoria
- Confirmação com **código único** de 6 dígitos
- Mensagem de confirmação pré-preenchida no **WhatsApp**
- Envio de **e-mail** de confirmação (se configurado)
- Botão "🔑 Meu Agendamento" no topo

### 🔑 Meu Agendamento (cliente)
- Busca pelo código recebido no WhatsApp/e-mail
- **Cancelar** próprio agendamento (até 2h antes)
- **Remarcar** para outra data/horário disponível (até 2h antes)
- Folgas do profissional já bloqueadas na remarcação

### 🔐 Painel Admin
- Login com sessão de 8h
- **Agenda** — filtro por data, atualização de status
- **Serviços** — cadastrar, editar, excluir
- **Profissionais** — cadastrar, editar, excluir
- **Folgas** — registrar dias de folga por profissional (com intervalo de datas)
- **Relatório** — receita por dia, ranking por serviço/profissional, gráficos, exportação CSV

### 🔐 Segurança
- Senhas em variável de ambiente (nunca no código)
- Token de sessão gerado com `secrets.token_hex`
- Rotas admin protegidas por Bearer token
- `.gitignore` configurado para nunca subir `.env` ou `.db`
- Dockerfile pronto para deploy seguro

### 🗃️ Banco SQLite
- Arquivo único `salao.db` (fácil de fazer backup)
- 5 tabelas: `servicos`, `profissionais`, `profissional_servicos`, `folgas`, `agendamentos`
- Validação de conflito de horário no backend
- Verificação de folga antes de confirmar ou remarcar
