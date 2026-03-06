import os
import re
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
load_dotenv()  # carrega o arquivo .env automaticamente
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from authlib.integrations.flask_client import OAuth
from datetime import datetime, timedelta
from functools import wraps

app = Flask(__name__)
secret_key = os.environ.get("SECRET_KEY")
if not secret_key:
    raise RuntimeError("SECRET_KEY não definida! Configure a variável de ambiente.")
app.secret_key = secret_key

# ── Banco de dados (Supabase / PostgreSQL) ─────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "pool_recycle": 300,
    "pool_size": 5,
    "max_overflow": 2,
}
db = SQLAlchemy(app)

# ── Login ──────────────────────────────────────────────────────
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Faça login para continuar."

# ── Google OAuth ───────────────────────────────────────────────
oauth = OAuth(app)
google = oauth.register(
    name="google",
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

# E-mail do dono/admin da barbearia
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")
if not ADMIN_EMAIL:
    raise RuntimeError("ADMIN_EMAIL não definido! Configure a variável de ambiente.")

# ── Models ─────────────────────────────────────────────────────
class Usuario(UserMixin, db.Model):
    __tablename__ = "usuarios"
    id          = db.Column(db.Integer, primary_key=True)
    email       = db.Column(db.String(200), unique=True, nullable=False)
    nome        = db.Column(db.String(200), nullable=False)
    foto        = db.Column(db.String(500))
    criado_em   = db.Column(db.DateTime, default=datetime.utcnow)
    agendamentos = db.relationship("Agendamento", backref="usuario", lazy=True)


class Barbeiro(db.Model):
    """Cada barbeiro tem seu próprio login Google e controla sua disponibilidade."""
    __tablename__ = "barbeiros"
    id           = db.Column(db.Integer, primary_key=True)
    email        = db.Column(db.String(200), unique=True, nullable=False)
    nome         = db.Column(db.String(200), nullable=False)
    especialidade = db.Column(db.String(200), default="")
    nota         = db.Column(db.Float, default=5.0)
    disponivel   = db.Column(db.Boolean, default=True)
    foto         = db.Column(db.String(500))
    criado_em    = db.Column(db.DateTime, default=datetime.utcnow)


class Agendamento(db.Model):
    __tablename__ = "agendamentos"
    id            = db.Column(db.Integer, primary_key=True)
    usuario_id    = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    barbeiro_id   = db.Column(db.Integer, db.ForeignKey("barbeiros.id"), nullable=False)
    servico       = db.Column(db.String(100), nullable=False)
    servico_preco   = db.Column(db.Integer, nullable=False)
    servico_minutos = db.Column(db.Integer, nullable=False, default=30)
    data            = db.Column(db.String(20), nullable=False)
    horario       = db.Column(db.String(10), nullable=False)
    criado_em     = db.Column(db.DateTime, default=datetime.utcnow)
    status        = db.Column(db.String(20), default="pendente")
    barbeiro      = db.relationship("Barbeiro", backref="agendamentos")




class Avaliacao(db.Model):
    """Uma avaliação por agendamento concluído — o cliente não pode avaliar duas vezes."""
    __tablename__ = "avaliacoes"
    id            = db.Column(db.Integer, primary_key=True)
    agendamento_id = db.Column(db.Integer, db.ForeignKey("agendamentos.id"), unique=True, nullable=False)
    usuario_id    = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    barbeiro_id   = db.Column(db.Integer, db.ForeignKey("barbeiros.id"), nullable=False)
    estrelas      = db.Column(db.Integer, nullable=False)  # 1 a 5
    criado_em     = db.Column(db.DateTime, default=datetime.utcnow)
    agendamento   = db.relationship("Agendamento", backref=db.backref("avaliacao", uselist=False))
    barbeiro      = db.relationship("Barbeiro", backref="avaliacoes")
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Usuario, int(user_id))


# ── Helpers de papel (role) ────────────────────────────────────
def get_barbeiro_logado():
    """Retorna o Barbeiro do banco se o usuário atual for um barbeiro."""
    if current_user.is_authenticated:
        return Barbeiro.query.filter_by(email=current_user.email).first()
    return None

def is_admin():
    return current_user.is_authenticated and current_user.email == ADMIN_EMAIL

def is_barbeiro():
    return get_barbeiro_logado() is not None


# ── Decorators ─────────────────────────────────────────────────
def apenas_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not is_admin():
            flash("Acesso restrito ao administrador.", "erro")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated

def apenas_barbeiro_ou_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not is_barbeiro() and not is_admin():
            flash("Acesso restrito.", "erro")
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated


# ── Dados fixos ────────────────────────────────────────────────
SERVICOS = [
    {"nome": "Corte Clássico",  "duracao": "30 min", "preco": 35,  "icon": "✂️", "minutos": 30},
    {"nome": "Barba Completa",  "duracao": "20 min", "preco": 25,  "icon": "🪒", "minutos": 20},
    {"nome": "Corte + Barba",   "duracao": "50 min", "preco": 55,  "icon": "💈", "minutos": 50},
    {"nome": "Platinado",       "duracao": "90 min", "preco": 120, "icon": "🎨", "minutos": 90},
    {"nome": "Hidratação",      "duracao": "20 min", "preco": 30,  "icon": "💧", "minutos": 20},
    {"nome": "Sobrancelha",     "duracao": "15 min", "preco": 15,  "icon": "👁️", "minutos": 15},
]



def get_slots_bloqueados(barbeiro_id, data):
    """Retorna todos os horários bloqueados para um barbeiro numa data,
    levando em conta a duração de cada serviço agendado."""
    from datetime import datetime, timedelta
    agendamentos = Agendamento.query.filter_by(
        barbeiro_id=barbeiro_id, data=data, status="pendente").all()

    bloqueados = set()
    for ag in agendamentos:
        # Usa servico_minutos do banco; fallback pelo nome caso seja 0 ou nulo
        minutos = ag.servico_minutos if ag.servico_minutos and ag.servico_minutos > 0 else None
        if not minutos:
            servico = next((s for s in SERVICOS if s["nome"] == ag.servico), None)
            minutos = servico["minutos"] if servico else 30

        # Bloqueia todos os slots de 30 min que o serviço ocupa
        inicio = datetime.strptime(ag.horario, "%H:%M")
        num_slots = (minutos + 29) // 30  # ceil(minutos / 30)
        for i in range(num_slots):
            slot = inicio + timedelta(minutes=30 * i)
            bloqueados.add(slot.strftime("%H:%M"))

    return list(bloqueados)

def gerar_proximos_dias(quantidade=5):
    dias = []
    data = datetime.now(ZoneInfo("America/Sao_Paulo"))
    nomes = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    while len(dias) < quantidade:
        if data.weekday() < 6:
            dias.append({
                "label": nomes[data.weekday()],
                "valor": data.strftime("%Y-%m-%d"),
                "exibicao": data.strftime("%d/%m"),
            })
        data += timedelta(days=1)
    return dias


def gerar_horarios():
    horarios = []
    for hora in range(9, 18):
        for minuto in [0, 30]:
            horarios.append(f"{hora:02d}:{minuto:02d}")
    return horarios


# ── Injeta variáveis globais nos templates ─────────────────────
@app.context_processor
def inject_globals():
    return {
        "admin_email": ADMIN_EMAIL,
        "is_admin": is_admin(),
        "barbeiro_logado": get_barbeiro_logado(),
    }


# ── Autenticação ───────────────────────────────────────────────
@app.route("/login")
def login():
    return render_template("login.html")

@app.route("/login/google")
def login_google():
    redirect_uri = url_for("auth_callback", _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route("/auth/callback")
def auth_callback():
    token = google.authorize_access_token()
    info = token.get("userinfo")
    if not info:
        flash("Falha ao obter informações do Google.", "erro")
        return redirect(url_for("login"))

    # Cria/atualiza usuário
    usuario = Usuario.query.filter_by(email=info["email"]).first()
    if not usuario:
        usuario = Usuario(email=info["email"], nome=info.get("name", "Usuário"), foto=info.get("picture"))
        db.session.add(usuario)

    # Atualiza foto do barbeiro se ele já existir
    barbeiro = Barbeiro.query.filter_by(email=info["email"]).first()
    if barbeiro and not barbeiro.foto:
        barbeiro.foto = info.get("picture")

    db.session.commit()
    login_user(usuario)
    flash(f"Bem-vindo, {usuario.nome}! 👋", "sucesso")

    # Redireciona para o painel correto
    if info["email"] == ADMIN_EMAIL:
        return redirect(url_for("admin"))
    if barbeiro:
        return redirect(url_for("painel_barbeiro"))
    return redirect(url_for("index"))

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Você saiu. Até logo!", "sucesso")
    return redirect(url_for("login"))


# ── Rotas do cliente ───────────────────────────────────────────
@app.route("/")
@login_required
def index():
    return render_template("index.html", servicos=SERVICOS)

@app.route("/agendar", methods=["GET", "POST"])
@login_required
def agendar():
    barbeiros = Barbeiro.query.all()
    dias = gerar_proximos_dias()
    horarios = gerar_horarios()

    if request.method == "POST":
        servico_nome  = request.form.get("servico")
        barbeiro_id   = request.form.get("barbeiro_id", type=int)
        data          = request.form.get("data")
        horario       = request.form.get("horario")

        servico_sel = next((s for s in SERVICOS if s["nome"] == servico_nome), None)
        barbeiro_sel = db.session.get(Barbeiro, barbeiro_id) if barbeiro_id else None

        agora = datetime.now(ZoneInfo("America/Sao_Paulo"))
        # Valida formato de data e horário
        if not data or not re.match(r"^\d{4}-\d{2}-\d{2}$", data):
            flash("Data inválida.", "erro")
            return redirect(url_for("agendar"))
        if not horario or not re.match(r"^\d{2}:\d{2}$", horario):
            flash("Horário inválido.", "erro")
            return redirect(url_for("agendar"))
        if data == agora.strftime("%Y-%m-%d") and horario <= agora.strftime("%H:%M"):
            flash("Este horário já passou. Escolha um horário futuro.", "erro")
        elif not servico_sel or not barbeiro_sel or not data or not horario:
            flash("Preencha todos os campos.", "erro")
        elif not barbeiro_sel.disponivel:
            flash("Este barbeiro não está disponível no momento.", "erro")
        elif horario in get_slots_bloqueados(barbeiro_sel.id, data):
            flash("Este barbeiro já está ocupado neste horário. Escolha outro.", "erro")
        elif Agendamento.query.filter_by(usuario_id=current_user.id, data=data,
                                         horario=horario, status="pendente").first():
            flash("Você já tem um agendamento neste horário!", "erro")
        elif Agendamento.query.filter_by(usuario_id=current_user.id, data=data,
                                         horario=horario, status="pendente").first():
            flash("Você já tem um agendamento neste horário!", "erro")
        else:
            novo = Agendamento(
                usuario_id=current_user.id,
                barbeiro_id=barbeiro_sel.id,
                servico=servico_sel["nome"],
                servico_preco=servico_sel["preco"],
                servico_minutos=servico_sel["minutos"],
                data=data,
                horario=horario,
            )
            db.session.add(novo)
            db.session.commit()
            flash("✅ Agendamento confirmado!", "sucesso")
            return redirect(url_for("meus_agendamentos"))

    agora = datetime.now(ZoneInfo("America/Sao_Paulo"))
    return render_template("agendar.html",
                           servicos=SERVICOS, barbeiros=barbeiros,
                           dias=dias, horarios=horarios,
                           hoje=agora.strftime("%Y-%m-%d"),
                           hora_atual=agora.strftime("%H:%M"))

@app.route("/meus-agendamentos")
@login_required
def meus_agendamentos():
    agendamentos = Agendamento.query.filter_by(
        usuario_id=current_user.id).order_by(Agendamento.data, Agendamento.horario).all()
    return render_template("meus_agendamentos.html", agendamentos=agendamentos)

@app.route("/cancelar/<int:ag_id>")
@login_required
def cancelar(ag_id):
    ag = Agendamento.query.get_or_404(ag_id)
    if ag.usuario_id != current_user.id:
        flash("Acesso negado.", "erro")
        return redirect(url_for("meus_agendamentos"))
    ag.status = "cancelado"
    db.session.commit()
    flash("Agendamento cancelado.", "sucesso")
    return redirect(url_for("meus_agendamentos"))


# ── Painel do barbeiro (cada barbeiro vê só os dele) ───────────
@app.route("/meu-painel")
@login_required
@apenas_barbeiro_ou_admin
def painel_barbeiro():
    barbeiro = get_barbeiro_logado()
    if not barbeiro:
        return redirect(url_for("admin"))

    pendentes = Agendamento.query.filter_by(barbeiro_id=barbeiro.id, status="pendente")\
        .order_by(Agendamento.data, Agendamento.horario).all()
    total = sum(ag.servico_preco for ag in
                Agendamento.query.filter_by(barbeiro_id=barbeiro.id, status="concluido").all())
    return render_template("painel_barbeiro.html", barbeiro=barbeiro,
                           pendentes=pendentes, total=total)

@app.route("/meu-painel/disponibilidade")
@login_required
@apenas_barbeiro_ou_admin
def toggle_disponibilidade():
    barbeiro = get_barbeiro_logado()
    if not barbeiro:
        return redirect(url_for("admin"))
    barbeiro.disponivel = not barbeiro.disponivel
    db.session.commit()
    estado = "disponível ✅" if barbeiro.disponivel else "indisponível ⏸️"
    flash(f"Você agora está {estado}.", "sucesso")
    return redirect(url_for("painel_barbeiro"))

@app.route("/meu-painel/concluir/<int:ag_id>")
@login_required
@apenas_barbeiro_ou_admin
def barbeiro_concluir(ag_id):
    barbeiro = get_barbeiro_logado()
    ag = Agendamento.query.get_or_404(ag_id)
    if not barbeiro or ag.barbeiro_id != barbeiro.id:
        flash("Acesso negado.", "erro")
        return redirect(url_for("painel_barbeiro"))
    ag.status = "concluido"
    db.session.commit()
    flash(f"✅ Atendimento de {ag.usuario.nome} concluído.", "sucesso")
    return redirect(url_for("painel_barbeiro"))

@app.route("/meu-painel/cancelar/<int:ag_id>")
@login_required
@apenas_barbeiro_ou_admin
def barbeiro_cancelar(ag_id):
    barbeiro = get_barbeiro_logado()
    ag = Agendamento.query.get_or_404(ag_id)
    if not barbeiro or ag.barbeiro_id != barbeiro.id:
        flash("Acesso negado.", "erro")
        return redirect(url_for("painel_barbeiro"))
    ag.status = "cancelado"
    db.session.commit()
    flash("Agendamento cancelado.", "sucesso")
    return redirect(url_for("painel_barbeiro"))


# ── Painel do admin (visão geral + gerenciar barbeiros) ────────
@app.route("/admin")
@login_required
@apenas_admin
def admin():
    barbeiros  = Barbeiro.query.all()
    pendentes  = Agendamento.query.filter_by(status="pendente")\
        .order_by(Agendamento.data, Agendamento.horario).all()
    total      = sum(ag.servico_preco for ag in
                     Agendamento.query.filter_by(status="concluido").all())
    return render_template("admin.html", barbeiros=barbeiros, pendentes=pendentes, total=total)

@app.route("/admin/barbeiro/novo", methods=["POST"])
@login_required
@apenas_admin
def admin_novo_barbeiro():
    email        = request.form.get("email", "").strip().lower()
    nome         = request.form.get("nome", "").strip()
    especialidade = request.form.get("especialidade", "").strip()

    if not email or not nome:
        flash("Nome e e-mail são obrigatórios.", "erro")
        return redirect(url_for("admin"))
    if Barbeiro.query.filter_by(email=email).first():
        flash("Já existe um barbeiro com esse e-mail.", "erro")
        return redirect(url_for("admin"))

    b = Barbeiro(email=email, nome=nome, especialidade=especialidade)
    db.session.add(b)
    db.session.commit()
    flash(f"Barbeiro {nome} cadastrado! Ele pode fazer login agora. ✅", "sucesso")
    return redirect(url_for("admin"))

@app.route("/admin/barbeiro/remover/<int:b_id>")
@login_required
@apenas_admin
def admin_remover_barbeiro(b_id):
    b = Barbeiro.query.get_or_404(b_id)
    db.session.delete(b)
    db.session.commit()
    flash(f"Barbeiro {b.nome} removido.", "sucesso")
    return redirect(url_for("admin"))

@app.route("/admin/concluir/<int:ag_id>")
@login_required
@apenas_admin
def admin_concluir(ag_id):
    ag = Agendamento.query.get_or_404(ag_id)
    ag.status = "concluido"
    db.session.commit()
    flash(f"✅ Atendimento de {ag.usuario.nome} concluído.", "sucesso")
    return redirect(url_for("admin"))

@app.route("/admin/cancelar/<int:ag_id>")
@login_required
@apenas_admin
def admin_cancelar(ag_id):
    ag = Agendamento.query.get_or_404(ag_id)
    ag.status = "cancelado"
    db.session.commit()
    flash("Agendamento cancelado.", "sucesso")
    return redirect(url_for("admin"))




# ── API: barbeiros ocupados num horário (considera duração) ────
@app.route("/api/ocupados")
@login_required
def api_ocupados():
    data    = request.args.get("data", "")
    horario = request.args.get("horario", "")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", data):
        return jsonify([])
    if not re.match(r"^\d{2}:\d{2}$", horario):
        return jsonify([])

    # Para cada barbeiro, verifica se o horário solicitado cai dentro
    # de algum serviço já agendado (considerando duração)
    ocupados = []
    barbeiros = Barbeiro.query.all()
    for barbeiro in barbeiros:
        bloqueados = get_slots_bloqueados(barbeiro.id, data)
        if horario in bloqueados:
            ocupados.append(barbeiro.id)
    return jsonify(ocupados)


# ── API: todos os slots bloqueados de um barbeiro numa data ────
@app.route("/api/bloqueados")
@login_required
def api_bloqueados():
    barbeiro_id = request.args.get("barbeiro_id", type=int)
    data        = request.args.get("data", "")
    if not barbeiro_id or not re.match(r"^\d{4}-\d{2}-\d{2}$", data):
        return jsonify([])
    return jsonify(get_slots_bloqueados(barbeiro_id, data))


# ── API: barbeiros ocupados considerando duração (uma única chamada) ────
@app.route("/api/ocupados_duracao")
@login_required
def api_ocupados_duracao():
    data    = request.args.get("data", "")
    horario = request.args.get("horario", "")
    minutos = request.args.get("minutos", 30, type=int)
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", data):
        return jsonify([])
    if not re.match(r"^\d{2}:\d{2}$", horario):
        return jsonify([])

    from datetime import datetime, timedelta
    # Gera os slots que o novo serviço ocuparia
    base = datetime.strptime(horario, "%H:%M")
    slots_novos = set()
    for i in range(max(1, (minutos + 29) // 30)):
        slots_novos.add((base + timedelta(minutes=30 * i)).strftime("%H:%M"))

    # Verifica quais barbeiros têm conflito em qualquer desses slots
    ocupados = []
    barbeiros = Barbeiro.query.all()
    for barbeiro in barbeiros:
        bloqueados = set(get_slots_bloqueados(barbeiro.id, data))
        if slots_novos & bloqueados:  # interseção
            ocupados.append(barbeiro.id)
    return jsonify(ocupados)

# ── Avaliação ──────────────────────────────────────────────────
@app.route("/avaliar/<int:ag_id>", methods=["POST"])
@login_required
def avaliar(ag_id):
    ag = Agendamento.query.get_or_404(ag_id)

    # Validações de segurança
    if ag.usuario_id != current_user.id:
        flash("Acesso negado.", "erro")
        return redirect(url_for("meus_agendamentos"))
    if ag.status != "concluido":
        flash("Só é possível avaliar atendimentos concluídos.", "erro")
        return redirect(url_for("meus_agendamentos"))
    if ag.avaliacao:
        flash("Você já avaliou este atendimento.", "erro")
        return redirect(url_for("meus_agendamentos"))

    estrelas = request.form.get("estrelas", type=int)
    if not estrelas or not (1 <= estrelas <= 5):
        flash("Selecione entre 1 e 5 estrelas.", "erro")
        return redirect(url_for("meus_agendamentos"))

    # Salva a avaliação
    nova = Avaliacao(
        agendamento_id=ag.id,
        usuario_id=current_user.id,
        barbeiro_id=ag.barbeiro_id,
        estrelas=estrelas,
    )
    db.session.add(nova)

    # Recalcula a média do barbeiro com todas as avaliações
    barbeiro = db.session.get(Barbeiro, ag.barbeiro_id)
    todas = Avaliacao.query.filter_by(barbeiro_id=barbeiro.id).all()
    total_estrelas = sum(a.estrelas for a in todas) + estrelas
    barbeiro.nota = round(total_estrelas / (len(todas) + 1), 1)

    db.session.commit()
    flash(f"Obrigado pela avaliação! Você deu {estrelas} ⭐ para {barbeiro.nome}.", "sucesso")
    return redirect(url_for("meus_agendamentos"))

# ── Inicialização ──────────────────────────────────────────────
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
