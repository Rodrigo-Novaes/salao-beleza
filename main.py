"""
Belle Salão — Backend v3
Instalar: pip install fastapi uvicorn python-dotenv
Rodar:    uvicorn main:app --reload
"""

import os, secrets, sqlite3, urllib.parse, smtplib, random, string, base64, mimetypes, hashlib
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ─── Carregar .env se existir ────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # sem python-dotenv, usa variáveis de ambiente do sistema

def env(key, default=""):
    return os.environ.get(key, default)

ADMIN_USER      = env("ADMIN_USER", "admin")
ADMIN_PASSWORD  = env("ADMIN_PASSWORD", "salao123")
SECRET_KEY      = env("SECRET_KEY", secrets.token_hex(32))
SALAO_NOME      = env("SALAO_NOME", "Belle Salão")
SALAO_WHATSAPP  = env("SALAO_WHATSAPP", "5511999990000")
SALAO_SLOGAN    = ""  # slogan gerenciado apenas pelo painel de configurações
SALAO_LOGO      = env("SALAO_LOGO", "")  # ex: /static/logo.png
EMAIL_ENABLED   = env("EMAIL_ENABLED", "false").lower() == "true"
EMAIL_HOST      = env("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT      = int(env("EMAIL_PORT", "587"))
EMAIL_USER      = env("EMAIL_USER", "")
EMAIL_PASSWORD  = env("EMAIL_PASSWORD", "")
EMAIL_FROM      = env("EMAIL_FROM", f"{SALAO_NOME} <{EMAIL_USER}>")

import os as _os
_BASE_DIR = _os.path.dirname(_os.path.abspath(__file__))
DB_PATH = env("DB_PATH", _os.path.join(_BASE_DIR, "salao.db"))
print(f"[DB] Usando banco: {DB_PATH}")

app = FastAPI(title=f"{SALAO_NOME} API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
security = HTTPBearer(auto_error=False)

# sessões admin em memória
sessions: dict = {}

# ─── BANCO DE DADOS ───────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS servicos (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            nome      TEXT NOT NULL,
            icone     TEXT DEFAULT '✨',
            preco     REAL NOT NULL,
            duracao   INTEGER NOT NULL,
            categoria TEXT DEFAULT 'Geral',
            descricao TEXT DEFAULT '',
            ativo     INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS profissionais (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            nome              TEXT NOT NULL,
            especialidade     TEXT NOT NULL,
            telefone          TEXT DEFAULT '',
            cor               TEXT DEFAULT '#c9a99a',
            horario_inicio    TEXT DEFAULT '09:00',
            horario_fim       TEXT DEFAULT '18:00',
            horario_intervalo TEXT DEFAULT '12:00',
            ativo             INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS profissional_servicos (
            profissional_id INTEGER REFERENCES profissionais(id) ON DELETE CASCADE,
            servico_id      INTEGER REFERENCES servicos(id) ON DELETE CASCADE,
            PRIMARY KEY (profissional_id, servico_id)
        );
        CREATE TABLE IF NOT EXISTS folgas (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            profissional_id INTEGER REFERENCES profissionais(id) ON DELETE CASCADE,
            data            TEXT NOT NULL,
            motivo          TEXT DEFAULT '',
            UNIQUE(profissional_id, data)
        );
        CREATE TABLE IF NOT EXISTS disponibilidade_semana (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            profissional_id INTEGER REFERENCES profissionais(id) ON DELETE CASCADE,
            dia_semana      INTEGER NOT NULL,
            ativo           INTEGER DEFAULT 1,
            hora_inicio     TEXT DEFAULT '09:00',
            hora_fim        TEXT DEFAULT '18:00',
            hora_intervalo  TEXT DEFAULT '12:00',
            UNIQUE(profissional_id, dia_semana)
        );
        CREATE TABLE IF NOT EXISTS configuracoes (
            chave TEXT PRIMARY KEY,
            valor TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS usuarios (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario   TEXT NOT NULL UNIQUE,
            senha     TEXT NOT NULL,
            nome      TEXT DEFAULT '',
            role      TEXT DEFAULT 'operador',
            ativo     INTEGER DEFAULT 1,
            criado_em TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS disponibilidade_excecao (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            profissional_id INTEGER REFERENCES profissionais(id) ON DELETE CASCADE,
            data            TEXT NOT NULL,
            ativo           INTEGER DEFAULT 1,
            hora_inicio     TEXT,
            hora_fim        TEXT,
            hora_intervalo  TEXT,
            motivo          TEXT DEFAULT '',
            UNIQUE(profissional_id, data)
        );
        CREATE TABLE IF NOT EXISTS agendamentos (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_nome    TEXT NOT NULL,
            cliente_tel     TEXT NOT NULL,
            cliente_email   TEXT DEFAULT '',
            servico_id      INTEGER REFERENCES servicos(id),
            profissional_id INTEGER REFERENCES profissionais(id),
            data            TEXT NOT NULL,
            hora            TEXT NOT NULL,
            status          TEXT DEFAULT 'confirmado',
            observacao      TEXT DEFAULT '',
            codigo_acesso   TEXT DEFAULT '',
            criado_em       TEXT DEFAULT (datetime('now','localtime'))
        );
    """)

    # REMOVIDO: Todo o bloco de inserção de dados de exemplo
    # O banco será criado apenas com as tabelas vazias

    conn.commit()
    conn.close()

init_db()
# ─── HELPERS ─────────────────────────────────────────────────────────────────
def t2m(t: str) -> int:
    h, m = map(int, t.split(':'))
    return h * 60 + m

def gerar_codigo() -> str:
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

def check_conflito(conn, profissional_id, data, hora, duracao, excluir_id=None):
    sql = """SELECT a.hora, s.duracao FROM agendamentos a
             JOIN servicos s ON s.id=a.servico_id
             WHERE a.profissional_id=? AND a.data=? AND a.status NOT IN ('cancelado')"""
    params = [profissional_id, data]
    if excluir_id:
        sql += " AND a.id != ?"
        params.append(excluir_id)
    ni, nf = t2m(hora), t2m(hora) + duracao
    for o in conn.execute(sql, params).fetchall():
        oi, of = t2m(o["hora"]), t2m(o["hora"]) + o["duracao"]
        if ni < of and nf > oi:
            return True
    return False

def get_disponibilidade(conn, profissional_id: int, data: str):
    from datetime import datetime as dt2
    exc = conn.execute(
        "SELECT * FROM disponibilidade_excecao WHERE profissional_id=? AND data=?",
        (profissional_id, data)).fetchone()
    if exc:
        return {"ativo": bool(exc["ativo"]), "hora_inicio": exc["hora_inicio"],
                "hora_fim": exc["hora_fim"], "hora_intervalo": exc["hora_intervalo"], "fonte": "excecao"}
    folga = conn.execute(
        "SELECT id FROM folgas WHERE profissional_id=? AND data=?",
        (profissional_id, data)).fetchone()
    if folga:
        return {"ativo": False, "hora_inicio": None, "hora_fim": None, "hora_intervalo": None, "fonte": "folga"}
    dia_semana = dt2.strptime(data, "%Y-%m-%d").weekday()
    reg = conn.execute(
        "SELECT * FROM disponibilidade_semana WHERE profissional_id=? AND dia_semana=?",
        (profissional_id, dia_semana)).fetchone()
    if reg:
        return {"ativo": bool(reg["ativo"]), "hora_inicio": reg["hora_inicio"],
                "hora_fim": reg["hora_fim"], "hora_intervalo": reg["hora_intervalo"], "fonte": "semana"}
    pro = conn.execute("SELECT * FROM profissionais WHERE id=?", (profissional_id,)).fetchone()
    if pro:
        return {"ativo": True, "hora_inicio": pro["horario_inicio"],
                "hora_fim": pro["horario_fim"], "hora_intervalo": pro["horario_intervalo"], "fonte": "padrao"}
    return {"ativo": False, "hora_inicio": None, "hora_fim": None, "hora_intervalo": None, "fonte": "nao_encontrado"}


def enviar_email(para: str, assunto: str, html: str):
    if not EMAIL_ENABLED or not para:
        return False
    try:
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        msg = MIMEMultipart("alternative")
        msg["Subject"] = assunto
        msg["From"] = EMAIL_FROM
        msg["To"] = para
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as s:
            s.starttls()
            s.login(EMAIL_USER, EMAIL_PASSWORD)
            s.sendmail(EMAIL_FROM, para, msg.as_string())
        return True
    except Exception as ex:
        print(f"Erro e-mail: {ex}")
        return False

def montar_wpp_link(tel: str, texto: str) -> str:
    num = ''.join(c for c in tel if c.isdigit())
    if len(num) <= 11:  # sem código do país
        num = "55" + num
    return f"https://wa.me/{num}?text={urllib.parse.quote(texto)}"
def fmt_moeda(valor: float) -> str:
    """Formata valor para padrão BR: 1.000,00"""
    return f"{valor:_.2f}".replace(".", ",").replace("_", ".")

def get_tolerancia(conn) -> int:
    """Retorna a tolerância em minutos configurada (padrão 30)"""
    row = conn.execute("SELECT valor FROM configuracoes WHERE chave='tolerancia_minutos'").fetchone()
    if row and row["valor"]:
        try:
            return int(row["valor"])
        except:
            return 30
    return 30  # valor padrão

# ─── AUTH ─────────────────────────────────────────────────────────────────────
def hash_senha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()

class LoginBody(BaseModel):
    usuario: str
    senha: str

def req_admin(creds: HTTPAuthorizationCredentials = Depends(security)):
    if not creds:
        raise HTTPException(401, "Token necessário")
    s = sessions.get(creds.credentials)
    if not s or s["exp"] < datetime.utcnow():
        sessions.pop(creds.credentials, None)
        raise HTTPException(401, "Sessão expirada")
    return s

def req_role_admin(s=Depends(req_admin)):
    if s["role"] != "admin":
        raise HTTPException(403, "Acesso restrito a administradores")
    return s["user"]

@app.post("/api/auth/login")
def login(b: LoginBody):
    conn = get_db()
    # Verifica primeiro no banco de usuários
    row = conn.execute(
        "SELECT id, usuario, senha, nome, role, ativo FROM usuarios WHERE usuario=? AND ativo=1",
        (b.usuario,)
    ).fetchone()
    if row and row["senha"] == hash_senha(b.senha):
        token = secrets.token_hex(32)
        sessions[token] = {"user": row["usuario"], "nome": row["nome"] or row["usuario"], "role": row["role"], "exp": datetime.utcnow() + timedelta(hours=8)}
        return {"token": token, "usuario": row["usuario"], "nome": row["nome"], "role": row["role"]}
    # Fallback: admin do .env (sempre role admin)
    if b.usuario == ADMIN_USER and b.senha == ADMIN_PASSWORD:
        token = secrets.token_hex(32)
        sessions[token] = {"user": b.usuario, "nome": b.usuario, "role": "admin", "exp": datetime.utcnow() + timedelta(hours=8)}
        return {"token": token, "usuario": b.usuario, "nome": b.usuario, "role": "admin"}
    raise HTTPException(401, "Usuário ou senha incorretos")

@app.post("/api/auth/logout")
def logout(creds: HTTPAuthorizationCredentials = Depends(security)):
    if creds: sessions.pop(creds.credentials, None)
    return {"ok": True}

@app.get("/api/auth/me")
def me(s=Depends(req_admin)):
    return {"usuario": s["user"], "nome": s["nome"], "role": s["role"]}

# ─── USUÁRIOS ─────────────────────────────────────────────────────────────────
class UsuarioIn(BaseModel):
    usuario: str
    senha: str = ""
    nome: str = ""
    role: str = "operador"
    ativo: int = 1

@app.get("/api/usuarios")
def listar_usuarios(s=Depends(req_admin)):
    if s["role"] != "admin": raise HTTPException(403, "Acesso negado")
    conn = get_db()
    rows = conn.execute("SELECT id,usuario,nome,role,ativo,criado_em FROM usuarios ORDER BY id").fetchall()
    return [dict(r) for r in rows]

@app.post("/api/usuarios")
def criar_usuario(b: UsuarioIn, s=Depends(req_admin)):
    if s["role"] != "admin": raise HTTPException(403, "Acesso negado")
    if not b.senha: raise HTTPException(400, "Senha obrigatória")
    conn = get_db()
    try:
        conn.execute("INSERT INTO usuarios (usuario,senha,nome,role,ativo) VALUES (?,?,?,?,?)",
                     (b.usuario.strip(), hash_senha(b.senha), b.nome.strip(), b.role, b.ativo))
        conn.commit()
    except Exception:
        raise HTTPException(400, "Usuário já existe")
    return {"ok": True}

@app.put("/api/usuarios/{uid}")
def editar_usuario(uid: int, b: UsuarioIn, s=Depends(req_admin)):
    if s["role"] != "admin": raise HTTPException(403, "Acesso negado")
    conn = get_db()
    if b.senha:
        conn.execute("UPDATE usuarios SET usuario=?,senha=?,nome=?,role=?,ativo=? WHERE id=?",
                     (b.usuario.strip(), hash_senha(b.senha), b.nome.strip(), b.role, b.ativo, uid))
    else:
        conn.execute("UPDATE usuarios SET usuario=?,nome=?,role=?,ativo=? WHERE id=?",
                     (b.usuario.strip(), b.nome.strip(), b.role, b.ativo, uid))
    conn.commit()
    return {"ok": True}

@app.delete("/api/usuarios/{uid}")
def excluir_usuario(uid: int, s=Depends(req_admin)):
    if s["role"] != "admin": raise HTTPException(403, "Acesso negado")
    conn = get_db()
    conn.execute("DELETE FROM usuarios WHERE id=?", (uid,))
    conn.commit()
    return {"ok": True}

# ─── SERVIÇOS ─────────────────────────────────────────────────────────────────
class ServicoIn(BaseModel):
    nome: str; icone: str = ""; preco: float; duracao: int
    categoria: str = "Geral"; descricao: str = ""

@app.get("/api/servicos")
def list_svcs(apenas_ativos: bool = True):
    conn = get_db()
    sql = "SELECT * FROM servicos" + (" WHERE ativo=1" if apenas_ativos else "")
    rows = conn.execute(sql + " ORDER BY categoria,nome").fetchall()
    conn.close(); return [dict(r) for r in rows]

@app.post("/api/servicos", status_code=201, dependencies=[Depends(req_admin)])
def create_svc(s: ServicoIn):
    conn = get_db()
    cur = conn.execute("INSERT INTO servicos (nome,icone,preco,duracao,categoria,descricao) VALUES (?,?,?,?,?,?)",
                       (s.nome,s.icone,s.preco,s.duracao,s.categoria,s.descricao))
    conn.commit()
    row = conn.execute("SELECT * FROM servicos WHERE id=?", (cur.lastrowid,)).fetchone()
    conn.close(); return dict(row)

@app.put("/api/servicos/{id}", dependencies=[Depends(req_admin)])
def update_svc(id: int, s: ServicoIn):
    conn = get_db()
    conn.execute("UPDATE servicos SET nome=?,icone=?,preco=?,duracao=?,categoria=?,descricao=? WHERE id=?",
                 (s.nome,s.icone,s.preco,s.duracao,s.categoria,s.descricao,id))
    conn.commit(); conn.close(); return {"ok": True}

@app.delete("/api/servicos/{id}", dependencies=[Depends(req_admin)])
def delete_svc(id: int):
    conn = get_db()
    conn.execute("UPDATE servicos SET ativo=0 WHERE id=?", (id,))
    conn.commit(); conn.close(); return {"ok": True}

# ─── PROFISSIONAIS ────────────────────────────────────────────────────────────
class ProfissionalIn(BaseModel):
    nome: str; especialidade: str; telefone: str = ""; cor: str = "#c9a99a"
    horario_inicio: str = "09:00"; horario_fim: str = "18:00"
    horario_intervalo: str = "12:00"; servicos: List[int] = []

@app.get("/api/profissionais")
def list_pros():
    conn = get_db()
    pros = [dict(r) for r in conn.execute("SELECT * FROM profissionais WHERE ativo=1 ORDER BY nome").fetchall()]
    for p in pros:
        p["servicos"] = [r["servico_id"] for r in conn.execute(
            "SELECT servico_id FROM profissional_servicos WHERE profissional_id=?", (p["id"],)).fetchall()]
    conn.close(); return pros

@app.post("/api/profissionais", status_code=201, dependencies=[Depends(req_admin)])
def create_pro(p: ProfissionalIn):
    conn = get_db()
    cur = conn.execute("INSERT INTO profissionais (nome,especialidade,telefone,cor,horario_inicio,horario_fim,horario_intervalo) VALUES (?,?,?,?,?,?,?)",
                       (p.nome,p.especialidade,p.telefone,p.cor,p.horario_inicio,p.horario_fim,p.horario_intervalo))
    pid = cur.lastrowid
    for sid in p.servicos:
        conn.execute("INSERT OR IGNORE INTO profissional_servicos VALUES (?,?)", (pid,sid))
    conn.commit()
    row = dict(conn.execute("SELECT * FROM profissionais WHERE id=?", (pid,)).fetchone())
    row["servicos"] = p.servicos; conn.close(); return row

@app.put("/api/profissionais/{id}", dependencies=[Depends(req_admin)])
def update_pro(id: int, p: ProfissionalIn):
    conn = get_db()
    conn.execute("UPDATE profissionais SET nome=?,especialidade=?,telefone=?,cor=?,horario_inicio=?,horario_fim=?,horario_intervalo=? WHERE id=?",
                 (p.nome,p.especialidade,p.telefone,p.cor,p.horario_inicio,p.horario_fim,p.horario_intervalo,id))
    conn.execute("DELETE FROM profissional_servicos WHERE profissional_id=?", (id,))
    for sid in p.servicos:
        conn.execute("INSERT OR IGNORE INTO profissional_servicos VALUES (?,?)", (id,sid))
    conn.commit(); conn.close(); return {"ok": True}

@app.delete("/api/profissionais/{id}", dependencies=[Depends(req_admin)])
def delete_pro(id: int):
    conn = get_db()
    conn.execute("UPDATE profissionais SET ativo=0 WHERE id=?", (id,))
    conn.commit(); conn.close(); return {"ok": True}

# ─── FOLGAS ───────────────────────────────────────────────────────────────────
class FolgaIn(BaseModel):
    profissional_id: int; data: str; motivo: str = ""

@app.get("/api/folgas")
def list_folgas(profissional_id: Optional[int] = None, mes: Optional[str] = None):
    conn = get_db()
    sql = """SELECT f.*, p.nome as profissional_nome, p.cor
             FROM folgas f JOIN profissionais p ON p.id=f.profissional_id WHERE 1=1"""
    params = []
    if profissional_id: sql += " AND f.profissional_id=?"; params.append(profissional_id)
    if mes: sql += " AND f.data LIKE ?"; params.append(mes+"%")
    rows = conn.execute(sql+" ORDER BY f.data", params).fetchall()
    conn.close(); return [dict(r) for r in rows]

@app.post("/api/folgas", status_code=201, dependencies=[Depends(req_admin)])
def create_folga(f: FolgaIn):
    conn = get_db()
    try:
        cur = conn.execute("INSERT INTO folgas (profissional_id,data,motivo) VALUES (?,?,?)",
                           (f.profissional_id, f.data, f.motivo))
        conn.commit()
        row = conn.execute("SELECT f.*,p.nome as profissional_nome,p.cor FROM folgas f JOIN profissionais p ON p.id=f.profissional_id WHERE f.id=?", (cur.lastrowid,)).fetchone()
        conn.close(); return dict(row)
    except Exception:
        conn.close(); raise HTTPException(409, "Folga já cadastrada para esta data")

@app.delete("/api/folgas/{id}", dependencies=[Depends(req_admin)])
def delete_folga(id: int):
    conn = get_db()
    conn.execute("DELETE FROM folgas WHERE id=?", (id,))
    conn.commit(); conn.close(); return {"ok": True}

@app.get("/api/folgas/check")
def check_folga(profissional_id: int, data: str):
    conn = get_db()
    row = conn.execute("SELECT id,motivo FROM folgas WHERE profissional_id=? AND data=?",
                       (profissional_id, data)).fetchone()
    conn.close()
    return {"folga": row is not None, "motivo": row["motivo"] if row else ""}

# ─── AGENDAMENTOS ─────────────────────────────────────────────────────────────
class AgendamentoIn(BaseModel):
    cliente_nome: str; cliente_tel: str; cliente_email: str = ""
    servico_id: int; profissional_id: int; data: str; hora: str; observacao: str = ""

class StatusIn(BaseModel):
    status: str

class CancelarClienteIn(BaseModel):
    codigo: str

class RemarcarIn(BaseModel):
    codigo: str; nova_data: str; nova_hora: str

@app.get("/api/agendamentos", dependencies=[Depends(req_admin)])
def list_appts(data: Optional[str] = None):
    conn = get_db()
    sql = """SELECT a.*, s.nome as servico_nome, s.icone as servico_icone, s.preco, s.duracao,
                    p.nome as profissional_nome, p.cor as profissional_cor
             FROM agendamentos a
             LEFT JOIN servicos s ON s.id=a.servico_id
             LEFT JOIN profissionais p ON p.id=a.profissional_id"""
    params = ()
    if data: sql += " WHERE a.data=?"; params=(data,)
    sql += " ORDER BY a.data,a.hora"
    rows = conn.execute(sql, params).fetchall()
    conn.close(); return [dict(r) for r in rows]

@app.get("/api/agendamentos/horarios-ocupados")
def horarios_ocupados(profissional_id: int, data: str):
    conn = get_db()
    disp = get_disponibilidade(conn, profissional_id, data)
    ocupados = [dict(r) for r in conn.execute(
        "SELECT a.hora,s.duracao FROM agendamentos a JOIN servicos s ON s.id=a.servico_id WHERE a.profissional_id=? AND a.data=? AND a.status!='cancelado'",
        (profissional_id, data)).fetchall()]
    conn.close()
    return {"disponivel": disp["ativo"], "hora_inicio": disp["hora_inicio"],
            "hora_fim": disp["hora_fim"], "hora_intervalo": disp["hora_intervalo"], "ocupados": ocupados}

@app.post("/api/agendamentos", status_code=201)
def create_appt(a: AgendamentoIn):
    conn = get_db()
    svc = conn.execute("SELECT * FROM servicos WHERE id=? AND ativo=1", (a.servico_id,)).fetchone()
    pro = conn.execute("SELECT * FROM profissionais WHERE id=? AND ativo=1", (a.profissional_id,)).fetchone()
    if not svc: raise HTTPException(400, "Serviço não encontrado")
    if not pro: raise HTTPException(400, "Profissional não encontrado")

    # checar disponibilidade
    disp = get_disponibilidade(conn, a.profissional_id, a.data)
    if not disp["ativo"]:
        raise HTTPException(409, f"{pro['nome']} não atende nesta data")

    if check_conflito(conn, a.profissional_id, a.data, a.hora, svc["duracao"]):
        raise HTTPException(409, "Este horário já está ocupado. Escolha outro.")

    codigo = gerar_codigo()
    cur = conn.execute(
        "INSERT INTO agendamentos (cliente_nome,cliente_tel,cliente_email,servico_id,profissional_id,data,hora,observacao,codigo_acesso) VALUES (?,?,?,?,?,?,?,?,?)",
        (a.cliente_nome,a.cliente_tel,a.cliente_email,a.servico_id,a.profissional_id,a.data,a.hora,a.observacao,codigo))
    conn.commit()
    appt_id = cur.lastrowid

    data_fmt = "/".join(reversed(a.data.split("-")))
    # WhatsApp de confirmação
    msg_conf = (
        f"Olá {a.cliente_nome}! 💇 Seu agendamento no {SALAO_NOME} foi confirmado!\n\n"
        f"📋 Serviço: {svc['nome']}\n"
        f"👩 Profissional: {pro['nome']}\n"
        f"📅 Data: {data_fmt} às {a.hora}\n"
        f"💰 Valor: R$ {fmt_moeda(svc['preco'])}\n\n"
        f"🔑 Código do seu agendamento: *{codigo}*\n"
        f"Guarde este código para cancelar ou remarcar.\n\n"
        f"Qualquer dúvida, entre em contato! ✨"
    )
    wpp_link = montar_wpp_link(a.cliente_tel, msg_conf)

    # E-mail
    obs_row = f"<tr><td style='padding:.5rem;color:#9a8070;font-size:.85rem'>Observação</td><td style='padding:.5rem'>{a.observacao}</td></tr>" if a.observacao else ""
    html_email = f"""<div style="font-family:sans-serif;max-width:500px;margin:auto;padding:2rem;background:#faf7f2;border-radius:12px">
      <h2 style="font-family:Georgia,serif;color:#2a1f1a">✦ Agendamento Confirmado!</h2>
      <p>Olá, <strong>{a.cliente_nome}</strong>!</p>
      <table style="width:100%;margin:1.5rem 0;border-collapse:collapse">
        <tr><td style="padding:.5rem;color:#9a8070;font-size:.85rem">Serviço</td><td style="padding:.5rem;font-weight:500">{svc['nome']}</td></tr>
        <tr style="background:#f0e8d8"><td style="padding:.5rem;color:#9a8070;font-size:.85rem">Profissional</td><td style="padding:.5rem">{pro['nome']}</td></tr>
        <tr><td style="padding:.5rem;color:#9a8070;font-size:.85rem">Data e Hora</td><td style="padding:.5rem">{data_fmt} às {a.hora}</td></tr>
        <tr style="background:#f0e8d8"><td style="padding:.5rem;color:#9a8070;font-size:.85rem">Valor</td><td style="padding:.5rem;color:#a07060;font-weight:600">R$ {fmt_moeda(svc['preco'])}</td></tr>
        {obs_row}
      </table>
      <div style="background:#2a1f1a;color:#fff;border-radius:10px;padding:1rem;text-align:center;margin:1.5rem 0">
        <div style="font-size:.8rem;color:rgba(255,255,255,.5);margin-bottom:.3rem">Código do agendamento</div>
        <div style="font-size:1.8rem;font-family:monospace;letter-spacing:.2em;color:#c8a96e">{codigo}</div>
        <div style="font-size:.75rem;color:rgba(255,255,255,.4);margin-top:.3rem">Use para cancelar ou remarcar</div>
      </div>
    </div>"""
    enviar_email(a.cliente_email, f"✦ Agendamento confirmado — {SALAO_NOME}", html_email)

    # Notificação para o admin/salão
    EMAIL_ADMIN = env("EMAIL_ADMIN", EMAIL_USER)
    if EMAIL_ADMIN:
        obs_admin = f"<tr style='background:#f0e8d8'><td style='padding:.5rem;color:#9a8070;font-size:.85rem'>Observação</td><td style='padding:.5rem'>{a.observacao}</td></tr>" if a.observacao else ""
        html_admin = f"""<div style="font-family:sans-serif;max-width:500px;margin:auto;padding:2rem;background:#faf7f2;border-radius:12px">
          <h2 style="font-family:Georgia,serif;color:#2a1f1a">🔔 Novo Agendamento!</h2>
          <table style="width:100%;margin:1.5rem 0;border-collapse:collapse">
            <tr><td style="padding:.5rem;color:#9a8070;font-size:.85rem">Cliente</td><td style="padding:.5rem;font-weight:500">{a.cliente_nome}</td></tr>
            <tr style="background:#f0e8d8"><td style="padding:.5rem;color:#9a8070;font-size:.85rem">WhatsApp</td><td style="padding:.5rem">{a.cliente_tel}</td></tr>
            <tr><td style="padding:.5rem;color:#9a8070;font-size:.85rem">E-mail</td><td style="padding:.5rem">{a.cliente_email or '—'}</td></tr>
            <tr style="background:#f0e8d8"><td style="padding:.5rem;color:#9a8070;font-size:.85rem">Serviço</td><td style="padding:.5rem">{svc['nome']}</td></tr>
            <tr><td style="padding:.5rem;color:#9a8070;font-size:.85rem">Profissional</td><td style="padding:.5rem">{pro['nome']}</td></tr>
            <tr style="background:#f0e8d8"><td style="padding:.5rem;color:#9a8070;font-size:.85rem">Data e Hora</td><td style="padding:.5rem">{data_fmt} às {a.hora}</td></tr>
            <tr><td style="padding:.5rem;color:#9a8070;font-size:.85rem">Valor</td><td style="padding:.5rem;color:#a07060;font-weight:600">R$ {fmt_moeda(svc['preco'])}</td></tr>
            <tr style="background:#f0e8d8"><td style="padding:.5rem;color:#9a8070;font-size:.85rem">Código</td><td style="padding:.5rem;font-family:monospace;font-weight:600;color:#c8a96e">{codigo}</td></tr>
            {obs_admin}
          </table>
        </div>"""
        enviar_email(EMAIL_ADMIN, f"🔔 Novo agendamento — {a.cliente_nome} ({data_fmt} às {a.hora})", html_admin)

    conn.close()
    return {"id": appt_id, "codigo": codigo, "whatsapp_link": wpp_link}

@app.patch("/api/agendamentos/{id}/status", dependencies=[Depends(req_admin)])
def update_status(id: int, b: StatusIn):
    conn = get_db()
    conn.execute("UPDATE agendamentos SET status=? WHERE id=?", (b.status, id))
    conn.commit(); conn.close(); return {"ok": True}

class AgendamentoEditIn(BaseModel):
    cliente_nome: str
    cliente_tel: str
    cliente_email: str = ""
    servico_id: int
    profissional_id: int
    data: str
    hora: str
    observacao: str = ""
    status: str = "confirmado"

@app.put("/api/agendamentos/{id}", dependencies=[Depends(req_admin)])
def edit_appt(id: int, b: AgendamentoEditIn):
    conn = get_db()
    svc = conn.execute("SELECT * FROM servicos WHERE id=?", (b.servico_id,)).fetchone()
    if not svc: raise HTTPException(400, "Serviço não encontrado")
    # Verifica conflito excluindo o próprio agendamento
    conflito = conn.execute(
        """SELECT COUNT(*) as n FROM agendamentos a JOIN servicos s ON s.id=a.servico_id
           WHERE a.profissional_id=? AND a.data=? AND a.id!=? AND a.status!='cancelado'
           AND a.hora < ? AND time(a.hora,'+'||s.duracao||' minutes') > ?""",
        (b.profissional_id, b.data, id, 
         f"{int(b.hora.split(':')[0]):02d}:{int(b.hora.split(':')[1]):02d}",
         f"{int(b.hora.split(':')[0]):02d}:{int(b.hora.split(':')[1]):02d}")
    ).fetchone()
    conn.execute("""UPDATE agendamentos SET cliente_nome=?,cliente_tel=?,cliente_email=?,
                    servico_id=?,profissional_id=?,data=?,hora=?,observacao=?,status=? WHERE id=?""",
                 (b.cliente_nome,b.cliente_tel,b.cliente_email,
                  b.servico_id,b.profissional_id,b.data,b.hora,b.observacao,b.status,id))
    conn.commit(); conn.close(); return {"ok": True}

@app.delete("/api/agendamentos/{id}", dependencies=[Depends(req_admin)])
def delete_appt(id: int):
    conn = get_db()
    conn.execute("DELETE FROM agendamentos WHERE id=?", (id,))
    conn.commit(); conn.close(); return {"ok": True}

# Cliente cancela via código
@app.post("/api/agendamentos/cancelar-cliente")
def cancelar_cliente(b: CancelarClienteIn):
    conn = get_db()
    appt = conn.execute("""SELECT a.*,s.nome as svc_nome,p.nome as pro_nome
                           FROM agendamentos a JOIN servicos s ON s.id=a.servico_id
                           JOIN profissionais p ON p.id=a.profissional_id
                           WHERE a.codigo_acesso=? AND a.status NOT IN ('cancelado','concluido')""",
                        (b.codigo.upper(),)).fetchone()
    if not appt:
        conn.close(); raise HTTPException(404, "Código não encontrado ou agendamento já finalizado")
    
    # PEGA A TOLERÂNCIA CONFIGURADA
    tolerancia = get_tolerancia(conn)
    
    # só pode cancelar com a tolerância configurada
    dt_appt = datetime.strptime(appt["data"]+" "+appt["hora"], "%Y-%m-%d %H:%M")
    if dt_appt - datetime.now() < timedelta(minutes=tolerancia):
        conn.close(); raise HTTPException(400, f"Cancelamento não permitido com menos de {tolerancia} minutos de antecedência. Entre em contato pelo WhatsApp.")
    
    conn.execute("UPDATE agendamentos SET status='cancelado' WHERE id=?", (appt["id"],))
    conn.commit()
    data_fmt = "/".join(reversed(appt["data"].split("-")))
    conn.close()
    return {"ok": True, "cliente": appt["cliente_nome"], "servico": appt["svc_nome"],
            "data": data_fmt, "hora": appt["hora"]}

# Cliente remarca via código
@app.post("/api/agendamentos/remarcar-cliente")
def remarcar_cliente(b: RemarcarIn):
    conn = get_db()
    appt = conn.execute("""SELECT a.*,s.duracao,s.nome as svc_nome,p.nome as pro_nome
                           FROM agendamentos a JOIN servicos s ON s.id=a.servico_id
                           JOIN profissionais p ON p.id=a.profissional_id
                           WHERE a.codigo_acesso=? AND a.status NOT IN ('cancelado','concluido')""",
                        (b.codigo.upper(),)).fetchone()
    if not appt:
        conn.close(); raise HTTPException(404, "Código não encontrado ou agendamento já finalizado")
    
    # PEGA A TOLERÂNCIA CONFIGURADA
    tolerancia = get_tolerancia(conn)
    
    dt_appt = datetime.strptime(appt["data"]+" "+appt["hora"], "%Y-%m-%d %H:%M")
    if dt_appt - datetime.now() < timedelta(minutes=tolerancia):
        conn.close(); raise HTTPException(400, f"Remarcação não permitida com menos de {tolerancia} minutos. Entre em contato pelo WhatsApp.")

    # checar disponibilidade na nova data
    disp2 = get_disponibilidade(conn, appt["profissional_id"], b.nova_data)
    if not disp2["ativo"]:
        conn.close(); raise HTTPException(409, "Profissional não atende nesta data")

    if check_conflito(conn, appt["profissional_id"], b.nova_data, b.nova_hora, appt["duracao"], appt["id"]):
        conn.close(); raise HTTPException(409, "Novo horário já está ocupado. Escolha outro.")

    conn.execute("UPDATE agendamentos SET data=?,hora=?,status='confirmado' WHERE id=?",
                 (b.nova_data, b.nova_hora, appt["id"]))
    conn.commit()
    data_fmt = "/".join(reversed(b.nova_data.split("-")))
    conn.close()
    return {"ok": True, "cliente": appt["cliente_nome"], "servico": appt["svc_nome"],
            "profissional": appt["pro_nome"], "nova_data": data_fmt, "nova_hora": b.nova_hora}

# Buscar agendamento por código (para mostrar detalhes)
@app.get("/api/agendamentos/por-codigo/{codigo}")
def appt_por_codigo(codigo: str):
    conn = get_db()
    row = conn.execute("""SELECT a.*,s.nome as svc_nome,s.icone,s.preco,s.duracao,
                                 p.nome as pro_nome,p.cor
                          FROM agendamentos a JOIN servicos s ON s.id=a.servico_id
                          JOIN profissionais p ON p.id=a.profissional_id
                          WHERE a.codigo_acesso=?""", (codigo.upper(),)).fetchone()
    conn.close()
    if not row: raise HTTPException(404, "Código não encontrado")
    return dict(row)

# ─── STATS & RELATÓRIO ────────────────────────────────────────────────────────
@app.get("/api/stats", dependencies=[Depends(req_admin)])
def stats():
    conn = get_db()
    hoje = datetime.today().strftime("%Y-%m-%d")
    r = {
        "total":    conn.execute("SELECT COUNT(*) FROM agendamentos").fetchone()[0],
        "confirmados": conn.execute("SELECT COUNT(*) FROM agendamentos WHERE status='confirmado'").fetchone()[0],
        "hoje":     conn.execute("SELECT COUNT(*) FROM agendamentos WHERE data=? AND status='confirmado'",(hoje,)).fetchone()[0],
        "profissionais": conn.execute("SELECT COUNT(*) FROM profissionais WHERE ativo=1").fetchone()[0],
        "servicos": conn.execute("SELECT COUNT(*) FROM servicos WHERE ativo=1").fetchone()[0],
        "receita":  conn.execute("SELECT COALESCE(SUM(s.preco),0) FROM agendamentos a JOIN servicos s ON s.id=a.servico_id WHERE a.status IN ('confirmado','concluido')").fetchone()[0],
    }
    conn.close(); return r

@app.get("/api/relatorio", dependencies=[Depends(req_admin)])
def relatorio(data_inicio: str, data_fim: str):
    conn = get_db()
    totais = dict(conn.execute("""
        SELECT COUNT(*) as qtd, COALESCE(SUM(s.preco),0) as receita,
               COUNT(CASE WHEN a.status='concluido' THEN 1 END) as concluidos,
               COUNT(CASE WHEN a.status='cancelado' THEN 1 END) as cancelados
        FROM agendamentos a LEFT JOIN servicos s ON s.id=a.servico_id
        WHERE a.data BETWEEN ? AND ?
    """, (data_inicio, data_fim)).fetchone())
    por_servico   = [dict(r) for r in conn.execute("""
        SELECT s.nome,s.icone,COUNT(*) as qtd,SUM(s.preco) as receita
        FROM agendamentos a JOIN servicos s ON s.id=a.servico_id
        WHERE a.data BETWEEN ? AND ? AND a.status IN ('confirmado','concluido')
        GROUP BY s.id ORDER BY receita DESC
    """, (data_inicio, data_fim)).fetchall()]
    por_profissional = [dict(r) for r in conn.execute("""
        SELECT p.nome,p.cor,COUNT(*) as qtd,SUM(s.preco) as receita
        FROM agendamentos a JOIN profissionais p ON p.id=a.profissional_id
        JOIN servicos s ON s.id=a.servico_id
        WHERE a.data BETWEEN ? AND ? AND a.status IN ('confirmado','concluido')
        GROUP BY p.id ORDER BY receita DESC
    """, (data_inicio, data_fim)).fetchall()]
    por_dia = [dict(r) for r in conn.execute("""
        SELECT a.data,COUNT(*) as qtd,SUM(s.preco) as receita
        FROM agendamentos a JOIN servicos s ON s.id=a.servico_id
        WHERE a.data BETWEEN ? AND ? AND a.status IN ('confirmado','concluido')
        GROUP BY a.data ORDER BY a.data
    """, (data_inicio, data_fim)).fetchall()]
    conn.close()
    return {"totais": totais, "por_servico": por_servico,
            "por_profissional": por_profissional, "por_dia": por_dia}

# ─── DISPONIBILIDADE ─────────────────────────────────────────────────────────

class DiaSemanaIn(BaseModel):
    dia_semana: int
    ativo: bool = True
    hora_inicio: str = "09:00"
    hora_fim: str = "18:00"
    hora_intervalo: str = "12:00"

class ExcecaoIn(BaseModel):
    profissional_id: int
    data: str
    ativo: bool = True
    hora_inicio: Optional[str] = None
    hora_fim: Optional[str] = None
    hora_intervalo: Optional[str] = None
    motivo: str = ""

@app.get("/api/disponibilidade/{profissional_id}/semana")
def get_disp_semana(profissional_id: int, _=Depends(req_admin)):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM disponibilidade_semana WHERE profissional_id=? ORDER BY dia_semana",
        (profissional_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/disponibilidade/{profissional_id}/semana", dependencies=[Depends(req_admin)])
def save_disp_semana(profissional_id: int, dias: List[DiaSemanaIn]):
    conn = get_db()
    conn.execute("DELETE FROM disponibilidade_semana WHERE profissional_id=?", (profissional_id,))
    for d in dias:
        conn.execute(
            "INSERT INTO disponibilidade_semana (profissional_id,dia_semana,ativo,hora_inicio,hora_fim,hora_intervalo) VALUES (?,?,?,?,?,?)",
            (profissional_id, d.dia_semana, int(d.ativo), d.hora_inicio, d.hora_fim, d.hora_intervalo))
    conn.commit(); conn.close()
    return {"ok": True}

@app.get("/api/disponibilidade/{profissional_id}/excecoes")
def get_excecoes(profissional_id: int, mes: Optional[str] = None, _=Depends(req_admin)):
    conn = get_db()
    sql = "SELECT * FROM disponibilidade_excecao WHERE profissional_id=?"
    params = [profissional_id]
    if mes:
        sql += " AND data LIKE ?"
        params.append(mes + "%")
    rows = conn.execute(sql + " ORDER BY data", params).fetchall()
    conn.close(); return [dict(r) for r in rows]

@app.post("/api/disponibilidade/excecao", status_code=201, dependencies=[Depends(req_admin)])
def save_excecao(e: ExcecaoIn):
    conn = get_db()
    pro = conn.execute("SELECT * FROM profissionais WHERE id=?", (e.profissional_id,)).fetchone()
    hi = e.hora_inicio or (pro["horario_inicio"] if pro else "09:00")
    hf = e.hora_fim or (pro["horario_fim"] if pro else "18:00")
    hv = e.hora_intervalo or (pro["horario_intervalo"] if pro else "12:00")
    conn.execute(
        "INSERT INTO disponibilidade_excecao (profissional_id,data,ativo,hora_inicio,hora_fim,hora_intervalo,motivo) VALUES (?,?,?,?,?,?,?) ON CONFLICT(profissional_id,data) DO UPDATE SET ativo=excluded.ativo, hora_inicio=excluded.hora_inicio, hora_fim=excluded.hora_fim, hora_intervalo=excluded.hora_intervalo, motivo=excluded.motivo",
        (e.profissional_id, e.data, int(e.ativo), hi, hf, hv, e.motivo))
    conn.commit()
    row = conn.execute("SELECT * FROM disponibilidade_excecao WHERE profissional_id=? AND data=?",
                       (e.profissional_id, e.data)).fetchone()
    conn.close(); return dict(row)

@app.delete("/api/disponibilidade/excecao/{id}", dependencies=[Depends(req_admin)])
def delete_excecao(id: int):
    conn = get_db()
    conn.execute("DELETE FROM disponibilidade_excecao WHERE id=?", (id,))
    conn.commit(); conn.close(); return {"ok": True}

@app.get("/api/disponibilidade/{profissional_id}/mes")
def get_disp_mes(profissional_id: int, mes: str, _=Depends(req_admin)):
    from datetime import datetime as dt3
    import calendar
    conn = get_db()
    ano, m = map(int, mes.split("-"))
    num_dias = calendar.monthrange(ano, m)[1]
    resultado = []
    for d in range(1, num_dias + 1):
        data_str = f"{ano:04d}-{m:02d}-{d:02d}"
        disp = get_disponibilidade(conn, profissional_id, data_str)
        resultado.append({"data": data_str, **disp})
    conn.close()
    return resultado

@app.get("/api/disponibilidade/check")
def check_disp_pub(profissional_id: int, data: str):
    conn = get_db()
    disp = get_disponibilidade(conn, profissional_id, data)
    conn.close(); return disp

def get_cfg(conn, chave, default=""):
    row = conn.execute("SELECT valor FROM configuracoes WHERE chave=?", (chave,)).fetchone()
    if row is None:
        return default  # nunca foi salvo → usa .env
    return row["valor"] if row["valor"] is not None else ""  # foi salvo (mesmo vazio) → usa o banco

def set_cfg(conn, chave, valor):
    conn.execute("INSERT INTO configuracoes (chave,valor) VALUES (?,?) ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor",
                 (chave, valor))

@app.get("/teste-slogan")
def teste_slogan():
    from fastapi.responses import HTMLResponse
    return HTMLResponse("""
<html><body style="font-family:sans-serif;padding:2rem">
<h2>Teste Slogan</h2>
<input id="s" value="Meu Slogan Teste" style="padding:.5rem;width:300px">
<button onclick="salvar()">Salvar</button>
<pre id="r"></pre>
<script>
async function salvar(){
  const token = localStorage.getItem('salon_token');
  const r = await fetch('/api/config', {
    method:'POST',
    headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},
    body: JSON.stringify({slogan: document.getElementById('s').value})
  });
  const j = await r.json();
  document.getElementById('r').textContent = JSON.stringify(j);
  const r2 = await fetch('/api/debug/config');
  const j2 = await r2.json();
  document.getElementById('r').textContent += '\\n\\nBanco: ' + JSON.stringify(j2.configuracoes.find(x=>x.chave==='slogan'));
}
</script>
</body></html>
""")

@app.get("/api/debug/config")
def debug_config():
    import os
    conn = get_db()
    rows = conn.execute("SELECT * FROM configuracoes").fetchall()
    dados = [dict(r) for r in rows]
    conn.close()
    return {
        "db_path": DB_PATH,
        "db_exists": os.path.exists(DB_PATH),
        "db_size": os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0,
        "configuracoes": dados
    }

@app.get("/api/config")
def get_config():
    from fastapi.responses import JSONResponse
    conn = get_db()
    nome   = get_cfg(conn, "nome",   SALAO_NOME)
    slogan_db = conn.execute("SELECT valor FROM configuracoes WHERE chave='slogan'").fetchone()
    slogan = slogan_db["valor"] if slogan_db else ""
    logo   = get_cfg(conn, "logo",   SALAO_LOGO)
    wpp    = get_cfg(conn, "whatsapp", SALAO_WHATSAPP)
    tema   = get_cfg(conn, "tema") or "rose"
    tolerancia = get_tolerancia(conn)  # <--- LINHA 1: ADICIONE AQUI
    conn.close()
    return JSONResponse(
        content={
            "nome": nome, 
            "slogan": slogan, 
            "logo": logo, 
            "whatsapp": wpp, 
            "tema": tema,
            "tolerancia_minutos": tolerancia  # <--- LINHA 2: ADICIONE AQUI (com vírgula no final da linha anterior)
        },
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"}
    )

@app.get("/tema.css")
def get_tema_css():
    from fastapi.responses import Response
    TEMAS_CSS = {
      "rose":        {"dark":"#2a1f1a","rose":"#c9a99a","cream":"#f5f0ea","gold":"#c8a96e","warm":"#f0e8d8","mid":"#6b4c3b","lt":"#a08070","dr":"#8b3a3a"},
      "sage":        {"dark":"#1a2a1f","rose":"#8fb8a8","cream":"#eaf2ee","gold":"#7ab87a","warm":"#e4f0e8","mid":"#2d6a4a","lt":"#6a9a7a","dr":"#2d6a2d"},
      "ocean":       {"dark":"#1a2030","rose":"#7ab3c8","cream":"#eaf3f7","gold":"#4a90b8","warm":"#e0eff8","mid":"#1a5a80","lt":"#5a90aa","dr":"#1a4a6a"},
      "plum":        {"dark":"#1f1a2a","rose":"#b09ac9","cream":"#f0eaf8","gold":"#9b7ec8","warm":"#ede8f5","mid":"#5a3a8a","lt":"#8a6aaa","dr":"#4a2a7a"},
      "gold":        {"dark":"#1a1510","rose":"#d4a843","cream":"#faf6ee","gold":"#c8a96e","warm":"#f5edda","mid":"#7a5a20","lt":"#aa8a50","dr":"#8a5a10"},
      "charcoal":    {"dark":"#1a1a1a","rose":"#888888","cream":"#f2f2f2","gold":"#555555","warm":"#e8e8e8","mid":"#333333","lt":"#777777","dr":"#222222"},
      "rose_sb":     {"dark":"#2a1f1a","rose":"#c9a99a","cream":"#f5f0ea","gold":"#c8a96e","warm":"#f0e8d8","mid":"#6b4c3b","lt":"#a08070","dr":"#8b3a3a"},
      "sage_sb":     {"dark":"#1a2a1f","rose":"#8fb8a8","cream":"#eaf2ee","gold":"#7ab87a","warm":"#e4f0e8","mid":"#2d6a4a","lt":"#6a9a7a","dr":"#2d6a2d"},
      "ocean_sb":    {"dark":"#1a2030","rose":"#7ab3c8","cream":"#eaf3f7","gold":"#4a90b8","warm":"#e0eff8","mid":"#1a5a80","lt":"#5a90aa","dr":"#1a4a6a"},
      "plum_sb":     {"dark":"#1f1a2a","rose":"#b09ac9","cream":"#f0eaf8","gold":"#9b7ec8","warm":"#ede8f5","mid":"#5a3a8a","lt":"#8a6aaa","dr":"#4a2a7a"},
      "light":       {"dark":"#2a1f1a","rose":"#c9a99a","cream":"#f5f0ea","gold":"#c8a96e","warm":"#f0e8d8","mid":"#6b4c3b","lt":"#a08070","dr":"#8b3a3a"},
      "light_sage":  {"dark":"#1a2a1f","rose":"#8fb8a8","cream":"#eaf2ee","gold":"#7ab87a","warm":"#e4f0e8","mid":"#2d6a4a","lt":"#6a9a7a","dr":"#2d6a2d"},
      "light_ocean": {"dark":"#1a2030","rose":"#7ab3c8","cream":"#eaf3f7","gold":"#4a90b8","warm":"#e0eff8","mid":"#1a5a80","lt":"#5a90aa","dr":"#1a4a6a"},
      "white_rose":  {"dark":"#2a1f1a","rose":"#c9a99a","cream":"#f5f0ea","gold":"#c8a96e","warm":"#f0e8d8","mid":"#6b4c3b","lt":"#a08070","dr":"#8b3a3a","brand":"#ffffff"},
      "white_sage":  {"dark":"#1a2a1f","rose":"#8fb8a8","cream":"#eaf2ee","gold":"#7ab87a","warm":"#e4f0e8","mid":"#2d6a4a","lt":"#6a9a7a","dr":"#2d6a2d","brand":"#ffffff"},
      "white_ocean": {"dark":"#1a2030","rose":"#7ab3c8","cream":"#eaf3f7","gold":"#4a90b8","warm":"#e0eff8","mid":"#1a5a80","lt":"#5a90aa","dr":"#1a4a6a","brand":"#ffffff"},
      "white_plum":  {"dark":"#1f1a2a","rose":"#b09ac9","cream":"#f0eaf8","gold":"#9b7ec8","warm":"#ede8f5","mid":"#5a3a8a","lt":"#8a6aaa","dr":"#4a2a7a","brand":"#ffffff"},
      "white_sb":    {"dark":"#2a1f1a","rose":"#c9a99a","cream":"#f5f0ea","gold":"#c8a96e","warm":"#f0e8d8","mid":"#6b4c3b","lt":"#a08070","dr":"#8b3a3a","brand":"#ffffff"},
    }
    conn = get_db()
    tema = get_cfg(conn, "tema") or "rose"
    conn.close()
    t = TEMAS_CSS.get(tema, TEMAS_CSS["rose"])
    brand = t.get('brand', t['gold'])
    css = f""":root{{
  --dark:{t['dark']};--rose:{t['rose']};--cream:{t['cream']};
  --gold:{t['gold']};--warm:{t['warm']};--mid:{t['mid']};
  --lt:{t['lt']};--dr:{t['dr']};--brand:{brand};
  --wh:#fff;--sh:0 4px 30px rgba(42,31,26,.08);--shl:0 8px 50px rgba(42,31,26,.15);
}}"""
    return Response(content=css, media_type="text/css", headers={"Cache-Control":"no-cache"})

class ConfigIn(BaseModel):
    nome: str = ""
    slogan: str = ""
    whatsapp: str = ""
    tema: str = ""
    tolerancia_minutos: Optional[int] = 30 

@app.post("/api/config", dependencies=[Depends(req_admin)])
def save_config(b: ConfigIn):
    conn = get_db()
    if b.nome:     set_cfg(conn, "nome",     b.nome)
    if b.whatsapp: set_cfg(conn, "whatsapp", b.whatsapp)
    if b.tema:     set_cfg(conn, "tema",     b.tema)
    if b.tolerancia_minutos is not None:
        set_cfg(conn, "tolerancia_minutos", str(b.tolerancia_minutos))
    conn.execute("INSERT INTO configuracoes (chave,valor) VALUES ('slogan',?) ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor", (b.slogan,))
    conn.commit()
    # Verificar se foi salvo
    check = conn.execute("SELECT valor FROM configuracoes WHERE chave='slogan'").fetchone()
    print(f"[CONFIG] Slogan salvo: '{b.slogan}' | Banco confirma: '{check['valor'] if check else 'NOT FOUND'}'")
    conn.close()
    return {"ok": True}

@app.post("/api/config/logo", dependencies=[Depends(req_admin)])
async def upload_logo(request: Request):
    import shutil
    body = await request.body()
    content_type = request.headers.get("content-type","image/png")
    ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ".png"
    if ext == ".jpe": ext = ".jpg"
    os.makedirs("static/uploads", exist_ok=True)
    filename = f"logo{ext}"
    path = f"static/uploads/{filename}"
    with open(path, "wb") as f:
        f.write(body)
    url = f"/static/uploads/{filename}"
    conn = get_db()
    set_cfg(conn, "logo", url)
    conn.commit(); conn.close()
    return {"ok": True, "url": url}

@app.delete("/api/config/logo", dependencies=[Depends(req_admin)])
def delete_logo():
    conn = get_db()
    set_cfg(conn, "logo", "")
    conn.commit(); conn.close()
    return {"ok": True}

@app.get("/api/config/public")
def get_public_config():
    conn = get_db()
    nome   = get_cfg(conn, "nome",   SALAO_NOME)
    slogan = get_cfg(conn, "slogan", "")
    logo   = get_cfg(conn, "logo",   SALAO_LOGO)
    tolerancia = get_tolerancia(conn)
    conn.close()
    return {
        "nome": nome,
        "slogan": slogan,
        "logo": logo,
        "tolerancia_minutos": tolerancia
    }
# ─── BACKUP ───────────────────────────────────────────────────────────────────
import json as json_mod
import shutil
import io
from fastapi.responses import StreamingResponse

@app.delete("/api/backup/{filename}", dependencies=[Depends(req_admin)])
def deletar_backup(filename: str):
    # Segurança: só permite deletar arquivos .db da pasta backups
    if not filename.endswith(".db") or "/" in filename or ".." in filename:
        raise HTTPException(400, "Arquivo inválido")
    path = f"backups/{filename}"
    if not os.path.exists(path):
        raise HTTPException(404, "Arquivo não encontrado")
    os.remove(path)
    backups = sorted([f for f in os.listdir("backups") if f.endswith(".db")], reverse=True)
    return {"ok": True, "backups": backups}

@app.get("/api/backup/listar", dependencies=[Depends(req_admin)])
def listar_backups():
    os.makedirs("backups", exist_ok=True)
    backups = sorted([f for f in os.listdir("backups") if f.endswith(".db")], reverse=True)
    return {"backups": backups}

@app.get("/api/backup/exportar-db", dependencies=[Depends(req_admin)])
def exportar_db():
    import datetime
    os.makedirs("backups", exist_ok=True)
    hoje = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    dest = f"backups/salao_{hoje}.db"
    shutil.copy2(DB_PATH, dest)
    # Lista todos os backups existentes
    backups = sorted(os.listdir("backups"), reverse=True)
    return {"ok": True, "arquivo": dest, "mensagem": f"Backup salvo em {dest}", "backups": backups}

@app.get("/api/backup/exportar", dependencies=[Depends(req_admin)])
def exportar_backup():
    conn = get_db()
    tabelas = ["servicos","profissionais","profissional_servicos","folgas",
               "agendamentos","disponibilidade_semana","disponibilidade_excecao","configuracoes","usuarios"]
    dados = {}
    for t in tabelas:
        try:
            rows = conn.execute(f"SELECT * FROM {t}").fetchall()
            dados[t] = [dict(r) for r in rows]
        except: dados[t] = []
    conn.close()
    import datetime
    dados["_meta"] = {"gerado_em": datetime.datetime.now().isoformat(), "versao": "1.0"}
    content = json_mod.dumps(dados, ensure_ascii=False, indent=2)
    return StreamingResponse(
        io.BytesIO(content.encode("utf-8")),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=backup_salao_{datetime.date.today()}.json"}
    )

@app.post("/api/backup/restaurar", dependencies=[Depends(req_admin)])
async def restaurar_backup(request: Request):
    try:
        dados = await request.json()
    except:
        raise HTTPException(400, "JSON inválido")
    conn = get_db()
    tabelas_ordem = ["configuracoes","profissionais","servicos","profissional_servicos",
                     "disponibilidade_semana","disponibilidade_excecao","folgas","agendamentos","usuarios"]
    try:
        for t in tabelas_ordem:
            if t not in dados: continue
            rows = dados[t]
            if not rows: continue
            conn.execute(f"DELETE FROM {t}")
            if rows:
                cols = ",".join(rows[0].keys())
                placeholders = ",".join(["?" for _ in rows[0]])
                for row in rows:
                    conn.execute(f"INSERT OR REPLACE INTO {t} ({cols}) VALUES ({placeholders})", list(row.values()))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"Erro ao restaurar: {str(e)}")
    finally:
        conn.close()
    return {"ok": True, "mensagem": "Backup restaurado com sucesso!"}

# ─── PÁGINAS ──────────────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def root(): return RedirectResponse("/static/cliente/index.html")

@app.get("/admin")
def admin(): return FileResponse("static/admin/index.html")

@app.get("/admin/login")
def admin_login(): return FileResponse("static/admin/login.html")


@app.get("/meu-agendamento")
def meu_agendamento(): return FileResponse("static/cliente/meu-agendamento.html")