import csv
import hashlib
import io
import json
import os
import re
import secrets
import smtplib
import sqlite3
import ssl
import threading
import unicodedata
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr
from functools import wraps
from urllib.parse import urlsplit

from dotenv import load_dotenv

from flask import (Flask, Response, abort, flash, g, redirect, render_template,
                   request, session, url_for)
from werkzeug.datastructures import MultiDict
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))   # lê as configurações do ficheiro .env
DB_PATH = os.path.join(BASE_DIR, "apoio_habitacao.db")

app = Flask(__name__)
# Em produção define a variável de ambiente SECRET_KEY com um valor longo e aleatório.
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "chave-de-desenvolvimento-mudar")
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TOKEN_VALIDADE_MINUTOS = 60
TOKEN_VERIFICACAO_HORAS = 24
SITUACOES_HABITACIONAIS = (
    ("arrendamento", "Arrendamento"),
    ("arrendamento_quarto", "Arrendamento de quarto"),
    ("credito", "Casa própria com crédito à habitação"),
    ("proprietario", "Casa própria sem crédito"),
    ("familia", "Vivo com familiares ou outras pessoas"),
    ("temporario", "Alojamento temporário"),
    ("sem_abrigo", "Sem alojamento estável"),
)
PRESTACOES_SOCIAIS = (
    ("rsi", "Rendimento Social de Inserção (RSI)"),
    ("abono", "Abono de família"),
    ("desemprego", "Subsídio de desemprego"),
    ("pensao", "Pensão"),
    ("psi", "Prestação Social para a Inclusão (PSI)"),
    ("csi", "Complemento Solidário para Idosos (CSI)"),
    ("outro", "Outra prestação social"),
)
REGIOES = (
    ("continente", "Portugal continental"),
    ("madeira", "Região Autónoma da Madeira"),
    ("acores", "Região Autónoma dos Açores"),
)
APOIOS_PROCURADOS = (
    ("arrendamento", "Arrendar habitação"),
    ("arrendamento_opcao_compra", "Arrendamento com opção de compra"),
    ("aquisicao", "Adquirir habitação"),
    ("construcao", "Construir habitação"),
    ("credito", "Apoio relacionado com crédito à habitação"),
    ("habitacao_indigna", "Resolver condições habitacionais indignas"),
)
TIPOLOGIAS = ("T0", "T1", "T2", "T3", "T4")
RELACOES_AGREGADO = (
    ("conjuge", "Cônjuge ou parceiro/a"),
    ("filho", "Filho/a"),
    ("pai_mae", "Pai ou mãe"),
    ("irmao", "Irmão ou irmã"),
    ("outro", "Outro familiar ou pessoa"),
)
ESTADOS_CANDIDATURA = {
    "submetida": "Submetida",
    "em_analise": "Em análise",
    "aprovada": "Aprovada",
    "rejeitada": "Rejeitada",
    "cancelada": "Cancelada",
}
TRANSICOES_CANDIDATURA = {
    "submetida": ("em_analise", "aprovada", "rejeitada", "cancelada"),
    "em_analise": ("aprovada", "rejeitada", "cancelada"),
    "aprovada": (),
    "rejeitada": (),
    "cancelada": (),
}


# ---------------------------------------------------------------- Base de dados

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def fechar_db(_erro):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Cria as tabelas (se ainda não existirem)."""
    with sqlite3.connect(DB_PATH) as db:
        with open(os.path.join(BASE_DIR, "schema.sql"), encoding="utf-8") as f:
            db.executescript(f.read())
        # Migração: bases de dados antigas não têm a coluna email_verificado.
        # Os utilizadores que já existem ficam como verificados (DEFAULT 1).
        colunas = [linha[1] for linha in db.execute("PRAGMA table_info(utilizadores)")]
        if "email_verificado" not in colunas:
            db.execute(
                "ALTER TABLE utilizadores "
                "ADD COLUMN email_verificado INTEGER NOT NULL DEFAULT 1"
            )
        if "ativo" not in colunas:
            db.execute(
                "ALTER TABLE utilizadores "
                "ADD COLUMN ativo INTEGER NOT NULL DEFAULT 1"
            )
        colunas_programas = [
            linha[1] for linha in db.execute("PRAGMA table_info(programas)")
        ]
        if "criterios_json" not in colunas_programas:
            db.execute(
                "ALTER TABLE programas ADD COLUMN criterios_json "
                "TEXT NOT NULL DEFAULT '{}'"
            )
        if "criterios_configurados" not in colunas_programas:
            db.execute(
                "ALTER TABLE programas ADD COLUMN criterios_configurados "
                "INTEGER NOT NULL DEFAULT 0"
            )
        if "url_candidatura" not in colunas_programas:
            db.execute("ALTER TABLE programas ADD COLUMN url_candidatura TEXT")
        colunas_perfil = [
            linha[1] for linha in db.execute("PRAGMA table_info(perfis_habitacionais)")
        ]
        colunas_novas_perfil = {
            "regiao": "TEXT",
            "freguesia": "TEXT",
            "idade_candidato": "INTEGER",
            "idade_parceiro": "INTEGER",
            "rendimento_anual": "INTEGER",
            "data_contrato": "TEXT",
            "habitacao_permanente": "INTEGER",
            "propriedade_regiao": "TEXT",
            "carencia_financeira": "INTEGER",
            "condicoes_indignas": "INTEGER",
            "residencia_legal": "INTEGER",
            "apoios_json": "TEXT NOT NULL DEFAULT '[]'",
            "tipologia": "TEXT",
            "preco_imovel": "INTEGER",
            "lote_disponivel": "INTEGER",
            "projeto_construcao": "INTEGER",
            "negociacao_banco_recente": "INTEGER",
        }
        for nome_coluna, tipo_coluna in colunas_novas_perfil.items():
            if nome_coluna not in colunas_perfil:
                db.execute(
                    f"ALTER TABLE perfis_habitacionais "
                    f"ADD COLUMN {nome_coluna} {tipo_coluna}"
                )
        historico_sql = db.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' "
            "AND name = 'historico_alteracoes'"
        ).fetchone()[0]
        colunas_historico = {
            linha[1]
            for linha in db.execute("PRAGMA table_info(historico_alteracoes)")
        }
        if (
            "detalhes" not in colunas_historico
            or "'utilizador.atualizado'" not in historico_sql
        ):
            db.execute(
                "ALTER TABLE historico_alteracoes "
                "RENAME TO historico_alteracoes_antigo"
            )
            db.execute(
                "CREATE TABLE historico_alteracoes ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "tipo TEXT NOT NULL CHECK (tipo IN ("
                "'utilizador.criado', 'utilizador.email_verificado', "
                "'utilizador.palavra_passe_alterada', 'utilizador.atualizado', "
                "'utilizador.ativado', 'utilizador.desativado', "
                "'utilizador.eliminado', 'perfil.criado', 'perfil.atualizado', "
                "'membro.criado', 'membro.atualizado', 'membro.eliminado', "
                "'programa.criado', 'programa.atualizado')), "
                "entidade TEXT NOT NULL CHECK (entidade IN "
                "('utilizador', 'perfil', 'membro', 'programa')), "
                "entidade_id INTEGER NOT NULL CHECK (entidade_id > 0), "
                "responsavel_id INTEGER NOT NULL CHECK (responsavel_id > 0), "
                "responsavel_nome TEXT NOT NULL, "
                "responsavel_email TEXT NOT NULL, "
                "detalhes TEXT NOT NULL DEFAULT '', "
                "criado_em TEXT NOT NULL DEFAULT (datetime('now')))"
            )
            detalhes_expr = (
                "detalhes" if "detalhes" in colunas_historico else "''"
            )
            db.execute(
                "INSERT INTO historico_alteracoes "
                "(id, tipo, entidade, entidade_id, responsavel_id, "
                "responsavel_nome, responsavel_email, detalhes, criado_em) "
                "SELECT id, tipo, entidade, entidade_id, responsavel_id, "
                f"responsavel_nome, responsavel_email, {detalhes_expr}, criado_em "
                "FROM historico_alteracoes_antigo"
            )
            db.execute("DROP TABLE historico_alteracoes_antigo")
            db.execute(
                "CREATE INDEX idx_historico_criado_em "
                "ON historico_alteracoes(criado_em DESC)"
            )
            db.execute(
                "CREATE INDEX idx_historico_tipo_criado_em "
                "ON historico_alteracoes(tipo, criado_em DESC)"
            )
        with open(
            os.path.join(BASE_DIR, "programas_iniciais.sql"), encoding="utf-8"
        ) as f:
            db.executescript(f.read())


init_db()


# ---------------------------------------------------------------- Segurança

def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def proteger_csrf():
    if request.method == "POST":
        esperado = session.get("_csrf", "").encode()
        recebido = request.form.get("_csrf", "").encode()
        if not esperado or not secrets.compare_digest(esperado, recebido):
            abort(400)


@app.after_request
def cabecalhos_seguranca(resposta):
    # Impede que o link de recuperação (com o token) seja enviado a terceiros
    # (por exemplo ao Google Fonts) através do cabeçalho Referer.
    resposta.headers["Referrer-Policy"] = "no-referrer"
    return resposta


@app.before_request
def carregar_utilizador():
    g.user = None
    user_id = session.get("user_id")
    if user_id is not None:
        g.user = get_db().execute(
            "SELECT id, nome, apelido, email, papel, ativo "
            "FROM utilizadores WHERE id = ?",
            (user_id,),
        ).fetchone()
        if g.user is None or not g.user["ativo"]:
            session.clear()
            g.user = None


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if g.user is None:
            flash("Inicie sessão para aceder a esta página.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapper


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if g.user["papel"] != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapper


TIPOS_HISTORICO = {
    "utilizador.criado": "Conta criada",
    "utilizador.email_verificado": "Email confirmado",
    "utilizador.palavra_passe_alterada": "Palavra-passe alterada",
    "utilizador.atualizado": "Conta atualizada",
    "utilizador.ativado": "Conta ativada",
    "utilizador.desativado": "Conta desativada",
    "utilizador.eliminado": "Conta eliminada",
    "perfil.criado": "Perfil criado",
    "perfil.atualizado": "Perfil atualizado",
    "membro.criado": "Membro do agregado adicionado",
    "membro.atualizado": "Membro do agregado atualizado",
    "membro.eliminado": "Membro do agregado removido",
    "programa.criado": "Programa criado",
    "programa.atualizado": "Programa atualizado",
}


def registar_alteracao(responsavel_id, tipo, entidade, entidade_id, detalhes=""):
    responsavel = get_db().execute(
        "SELECT nome, apelido, email FROM utilizadores WHERE id = ?",
        (responsavel_id,),
    ).fetchone()
    if responsavel is None:
        raise ValueError("O responsável pelo evento não existe.")
    get_db().execute(
        "INSERT INTO historico_alteracoes "
        "(tipo, entidade, entidade_id, responsavel_id, responsavel_nome, "
        "responsavel_email, detalhes) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (tipo, entidade, entidade_id, responsavel_id,
         f"{responsavel['nome']} {responsavel['apelido']}", responsavel["email"],
         detalhes),
    )


def area_do_utilizador(user):
    return url_for("admin" if user["papel"] == "admin" else "cliente")


def normalizar_texto(valor):
    sem_acentos = unicodedata.normalize("NFD", valor.casefold())
    return "".join(caractere for caractere in sem_acentos
                   if unicodedata.category(caractere) != "Mn").strip()


def criterios_do_formulario(form):
    erros = []

    def inteiro_opcional(nome, etiqueta, minimo=0, maximo=10000000):
        valor = form.get(nome, "").strip()
        if not valor:
            return None
        try:
            numero = int(valor)
        except ValueError:
            erros.append(f"{etiqueta}: indique um número inteiro válido.")
            return None
        if not minimo <= numero <= maximo:
            erros.append(f"{etiqueta}: indique um valor entre {minimo} e {maximo}.")
            return None
        return numero

    concelhos_texto = form.get("concelhos", "").strip()
    if len(concelhos_texto) > 1000:
        erros.append("A lista de concelhos não pode exceder 1000 caracteres.")
    concelhos = [item.strip() for item in concelhos_texto.split(",") if item.strip()]
    situacoes = form.getlist("situacoes")
    prestacoes = form.getlist("prestacoes")
    situacoes_validas = {valor for valor, _ in SITUACOES_HABITACIONAIS}
    prestacoes_validas = {valor for valor, _ in PRESTACOES_SOCIAIS}

    if any(valor not in situacoes_validas for valor in situacoes):
        erros.append("Selecione apenas situações habitacionais válidas.")
    if any(valor not in prestacoes_validas for valor in prestacoes):
        erros.append("Selecione apenas prestações sociais válidas.")

    rendimento_max = inteiro_opcional(
        "rendimento_max", "Rendimento máximo mensal"
    )
    agregado_min = inteiro_opcional(
        "agregado_min", "Número mínimo de pessoas no agregado", 1, 30
    )
    agregado_max = inteiro_opcional(
        "agregado_max", "Número máximo de pessoas no agregado", 1, 30
    )
    encargo_max = inteiro_opcional(
        "encargo_max", "Encargo máximo mensal com habitação"
    )
    idade_min = inteiro_opcional("idade_min", "Idade mínima", 16, 120)
    idade_max = inteiro_opcional("idade_max", "Idade máxima", 16, 120)
    rendimento_anual_min = inteiro_opcional(
        "rendimento_anual_min", "Rendimento bruto anual mínimo", 0, 100000000
    )
    rendimento_anual_max = inteiro_opcional(
        "rendimento_anual_max", "Rendimento bruto anual máximo", 0, 100000000
    )
    if agregado_min is not None and agregado_max is not None and agregado_min > agregado_max:
        erros.append("O número mínimo de pessoas não pode exceder o máximo.")
    if idade_min is not None and idade_max is not None and idade_min > idade_max:
        erros.append("A idade mínima não pode exceder a máxima.")
    if (rendimento_anual_min is not None and rendimento_anual_max is not None
            and rendimento_anual_min > rendimento_anual_max):
        erros.append("O rendimento anual mínimo não pode exceder o máximo.")

    regioes = form.getlist("regioes")
    regioes_validas = {valor for valor, _ in REGIOES}
    if any(valor not in regioes_validas for valor in regioes):
        erros.append("Selecione apenas regiões válidas.")
    freguesias_texto = form.get("freguesias", "").strip()
    if len(freguesias_texto) > 1000:
        erros.append("A lista de freguesias não pode exceder 1000 caracteres.")
    freguesias = [item.strip() for item in freguesias_texto.split(",") if item.strip()]
    data_contrato_ate = form.get("data_contrato_ate", "").strip() or None
    if data_contrato_ate:
        try:
            datetime.strptime(data_contrato_ate, "%Y-%m-%d")
        except ValueError:
            erros.append("Indique uma data limite de contrato válida.")

    encargo_max_por_pessoas = {}
    for chave, numero in (("1", 1), ("2", 2), ("3", 3), ("4", 4)):
        limite = inteiro_opcional(
            f"encargo_max_pessoas_{chave}",
            f"Encargo máximo para agregado de {numero if numero < 4 else '4 ou mais'} pessoas",
        )
        if limite is not None:
            encargo_max_por_pessoas[chave] = limite

    preco_max_por_tipologia = {}
    for tipologia in TIPOLOGIAS:
        limite = inteiro_opcional(
            f"preco_max_{tipologia.lower()}", f"Preço máximo para {tipologia}"
        )
        if limite is not None:
            preco_max_por_tipologia[tipologia] = limite

    apoios = form.getlist("apoios")
    apoios_validos = {valor for valor, _ in APOIOS_PROCURADOS}
    if any(valor not in apoios_validos for valor in apoios):
        erros.append("Selecione apenas tipos de apoio válidos.")
    tipologias = form.getlist("tipologias")
    if any(valor not in TIPOLOGIAS for valor in tipologias):
        erros.append("Selecione apenas tipologias válidas.")

    criterios = {
        "concelhos": concelhos,
        "regioes": regioes,
        "freguesias": freguesias,
        "situacoes": situacoes,
        "rendimento_max": rendimento_max,
        "rendimento_anual_min": rendimento_anual_min,
        "rendimento_anual_max": rendimento_anual_max,
        "requer_confirmacao_limites_rendimento": not bool(
            form.get("limites_rendimento_confirmados")
        ),
        "idade_min": idade_min,
        "idade_max": idade_max,
        "casal_aceita_36": bool(form.get("casal_aceita_36")),
        "data_contrato_ate": data_contrato_ate,
        "agregado_min": agregado_min,
        "agregado_max": agregado_max,
        "encargo_max": encargo_max,
        "encargo_max_por_pessoas": encargo_max_por_pessoas,
        "preco_imovel_max_por_tipologia": preco_max_por_tipologia,
        "criancas": bool(form.get("exige_criancas")),
        "monoparental": bool(form.get("exige_monoparental")),
        "dependente": bool(form.get("exige_dependente")),
        "habitacao_permanente": bool(form.get("exige_habitacao_permanente")),
        "propriedade_regiao": (
            "nao" if form.get("exige_sem_propriedade_regiao") else None
        ),
        "carencia_financeira": bool(form.get("exige_carencia_financeira")),
        "condicoes_indignas": bool(form.get("exige_condicoes_indignas")),
        "residencia_legal": bool(form.get("exige_residencia_legal")),
        "lote_disponivel": bool(form.get("exige_lote_disponivel")),
        "projeto_construcao": bool(form.get("exige_projeto_construcao")),
        "negociacao_banco_recente": bool(
            form.get("exige_negociacao_banco_recente")
        ),
        "apoios": apoios,
        "tipologias": tipologias,
        "prestacoes": prestacoes,
    }
    return criterios, erros


def validar_url_candidatura(valor):
    if not valor:
        return None, None
    if len(valor) > 2000:
        return None, "O link de candidatura não pode exceder 2000 caracteres."
    try:
        partes_url = urlsplit(valor)
        if partes_url.scheme in ("http", "https") and partes_url.hostname:
            return valor, None
    except ValueError:
        pass
    return None, "O link de candidatura deve ser um endereço http:// ou https:// válido."


def transicao_candidatura_valida(estado_atual, novo_estado):
    return novo_estado in TRANSICOES_CANDIDATURA.get(estado_atual, ())


def analisar_csv_programas(conteudo):
    """Valida CSV UTF-8 com as colunas nome, entidade, descricao e url_candidatura."""
    erros = []
    try:
        leitor = csv.DictReader(io.StringIO(conteudo, newline=""))
        campos_obrigatorios = {"nome", "entidade", "descricao"}
        campos = leitor.fieldnames or []
        if len(campos) != len(set(campos)):
            return [], ["O CSV contém nomes de colunas repetidos."]
        if not campos_obrigatorios.issubset(campos):
            return [], [
                "O CSV deve incluir as colunas nome, entidade e descricao."
            ]
        if set(campos) - campos_obrigatorios - {"url_candidatura"}:
            return [], ["O CSV contém colunas não suportadas."]

        programas = []
        for numero_linha, linha in enumerate(leitor, start=2):
            if None in linha:
                erros.append(f"Linha {numero_linha}: número de colunas inválido.")
                continue
            nome = (linha.get("nome") or "").strip()
            entidade = (linha.get("entidade") or "").strip()
            descricao = (linha.get("descricao") or "").strip()
            url, erro_url = validar_url_candidatura(
                (linha.get("url_candidatura") or "").strip()
            )
            if not nome or len(nome) > 120:
                erros.append(
                    f"Linha {numero_linha}: nome obrigatório (máximo 120 caracteres)."
                )
            if not entidade or len(entidade) > 120:
                erros.append(
                    f"Linha {numero_linha}: entidade obrigatória (máximo 120 caracteres)."
                )
            if not descricao or len(descricao) > 2000:
                erros.append(
                    f"Linha {numero_linha}: descrição obrigatória (máximo 2000 caracteres)."
                )
            if erro_url:
                erros.append(f"Linha {numero_linha}: {erro_url}")
            if nome and entidade and descricao and not erro_url:
                programas.append({
                    "nome": nome,
                    "entidade": entidade,
                    "descricao": descricao,
                    "url_candidatura": url,
                })
            if numero_linha - 1 > 100:
                return [], ["O CSV não pode conter mais de 100 programas."]
        if not programas and not erros:
            erros.append("O CSV não contém programas para importar.")
        return programas, erros
    except csv.Error:
        return [], ["Não foi possível interpretar o ficheiro CSV."]


def resumo_criterios_programa(criterios):
    resumo = []

    def adicionar_intervalo(chave_min, chave_max, etiqueta, sufixo=""):
        minimo = criterios.get(chave_min)
        maximo = criterios.get(chave_max)
        if minimo is not None and maximo is not None:
            resumo.append(
                f"{etiqueta}: entre {formatar_valor(minimo)} e "
                f"{formatar_valor(maximo)}{sufixo}."
            )
        elif minimo is not None:
            resumo.append(f"{etiqueta}: a partir de {formatar_valor(minimo)}{sufixo}.")
        elif maximo is not None:
            resumo.append(f"{etiqueta}: até {formatar_valor(maximo)}{sufixo}.")

    def formatar_valor(valor):
        return f"{valor:,}".replace(",", " ")

    for chave, etiqueta in (
        ("regioes", "Regiões"),
        ("concelhos", "Concelhos"),
        ("freguesias", "Freguesias"),
    ):
        valores = criterios.get(chave, [])
        if chave == "regioes":
            nomes_regioes = dict(REGIOES)
            valores = [nomes_regioes.get(valor, valor) for valor in valores]
        if valores:
            resumo.append(f"{etiqueta}: {', '.join(valores)}.")
    situacoes = [
        dict(SITUACOES_HABITACIONAIS).get(valor, valor)
        for valor in criterios.get("situacoes", [])
    ]
    if situacoes:
        resumo.append(f"Situação habitacional: {', '.join(situacoes)}.")

    adicionar_intervalo("rendimento_anual_min", "rendimento_anual_max",
                        "Rendimento bruto anual do agregado", " €")
    if criterios.get("rendimento_max") is not None:
        resumo.append(
            "Rendimento líquido mensal do agregado: até "
            f"{formatar_valor(criterios['rendimento_max'])} €."
        )
    adicionar_intervalo("idade_min", "idade_max", "Idade", " anos")
    if criterios.get("casal_aceita_36"):
        resumo.append("Em candidatura de casal, um dos candidatos pode ter 36 anos.")
    if criterios.get("data_contrato_ate"):
        resumo.append(
            f"Data limite do contrato: {criterios['data_contrato_ate']}."
        )
    adicionar_intervalo("agregado_min", "agregado_max", "Pessoas no agregado")
    if criterios.get("encargo_max") is not None:
        resumo.append(
            "Renda/prestação mensal: até "
            f"{formatar_valor(criterios['encargo_max'])} €."
        )

    limites_encargo = criterios.get("encargo_max_por_pessoas", {})
    if limites_encargo:
        limites = [
            f"{'4 ou mais' if pessoas == '4' else pessoas} pessoa(s): "
            f"{formatar_valor(valor)} €"
            for pessoas, valor in sorted(limites_encargo.items())
        ]
        resumo.append(f"Renda máxima por dimensão do agregado: {'; '.join(limites)}.")
    limites_preco = criterios.get("preco_imovel_max_por_tipologia", {})
    if limites_preco:
        limites = [
            f"{tipologia}: {formatar_valor(valor)} €"
            for tipologia, valor in sorted(limites_preco.items())
        ]
        resumo.append(f"Preço máximo do imóvel: {'; '.join(limites)}.")

    apoios = [
        dict(APOIOS_PROCURADOS).get(valor, valor)
        for valor in criterios.get("apoios", [])
    ]
    if apoios:
        resumo.append(f"Tipos de apoio: {', '.join(apoios)}.")
    if criterios.get("tipologias"):
        resumo.append(f"Tipologias: {', '.join(criterios['tipologias'])}.")
    if criterios.get("criancas"):
        resumo.append("Exige crianças no agregado.")
    if criterios.get("monoparental"):
        resumo.append("Exige agregado familiar monoparental.")
    if criterios.get("dependente"):
        resumo.append("Exige pessoa com deficiência ou dependente no agregado.")
    for chave, etiqueta in (
        ("habitacao_permanente", "Habitação própria e permanente"),
        ("carencia_financeira", "Carência financeira"),
        ("condicoes_indignas", "Condições habitacionais indignas"),
        ("residencia_legal", "Nacionalidade portuguesa ou residência legal"),
        ("lote_disponivel", "Lote disponível para construção"),
        ("projeto_construcao", "Projeto de construção"),
        ("negociacao_banco_recente", "Negociação com o banco nos últimos 6 meses"),
    ):
        if criterios.get(chave):
            resumo.append(f"Exige: {etiqueta.lower()}.")
    if criterios.get("propriedade_regiao") == "nao":
        resumo.append("Não pode possuir outro imóvel na região.")
    if criterios.get("prestacoes"):
        prestacoes = [
            dict(PRESTACOES_SOCIAIS).get(valor, valor)
            for valor in criterios["prestacoes"]
        ]
        resumo.append(f"Prestações sociais elegíveis: {', '.join(prestacoes)}.")
    if criterios.get("requer_confirmacao_limites_rendimento"):
        resumo.append(
            "Os limites de rendimento ainda não estão confirmados; "
            "consulte a entidade responsável."
        )
    return resumo


def avaliar_compatibilidade_programa(criterios, respostas):
    if criterios.get("requer_confirmacao_limites_rendimento"):
        return None
    dados_em_falta = set()
    concelhos = [normalizar_texto(item) for item in criterios.get("concelhos", [])]
    if concelhos and normalizar_texto(respostas["concelho"]) not in concelhos:
        return None
    regioes = criterios.get("regioes", [])
    if regioes and respostas["regiao"] not in regioes:
        return None
    freguesias = [
        normalizar_texto(item) for item in criterios.get("freguesias", [])
    ]
    if freguesias and normalizar_texto(respostas["freguesia"]) not in freguesias:
        return None
    if criterios.get("situacoes") and respostas["situacao"] not in criterios["situacoes"]:
        return None
    if (criterios.get("rendimento_max") is not None
            and respostas["rendimento"] > criterios["rendimento_max"]):
        return None
    for chave, resposta_chave in (
        ("rendimento_anual_min", "rendimento_anual"),
        ("rendimento_anual_max", "rendimento_anual"),
    ):
        if criterios.get(chave) is not None:
            valor = respostas[resposta_chave]
            if valor is None:
                dados_em_falta.add("rendimento anual do agregado")
                continue
            if chave.endswith("_min") and valor < criterios[chave]:
                return None
            if chave.endswith("_max") and valor > criterios[chave]:
                return None
    limite_idade_min = criterios.get("idade_min")
    limite_idade_max = criterios.get("idade_max")
    if limite_idade_min is not None or limite_idade_max is not None:
        if respostas["idade_candidato"] is None:
            dados_em_falta.add("idade do candidato")
        else:
            idades = [respostas["idade_candidato"]]
            if respostas["idade_parceiro"] is not None:
                idades.append(respostas["idade_parceiro"])
            if limite_idade_min is not None and any(
                idade < limite_idade_min for idade in idades
            ):
                return None
            if limite_idade_max is not None:
                maior_idade_permitida = 36 if criterios.get("casal_aceita_36") else limite_idade_max
                if any(idade > maior_idade_permitida for idade in idades):
                    return None
                if 36 in idades and (
                    not criterios.get("casal_aceita_36")
                    or idades.count(36) > 1
                    or any(idade > 35 for idade in idades if idade != 36)
                ):
                    return None
                if 36 in idades and len(idades) < 2:
                    dados_em_falta.add("idade do cônjuge/parceiro")
    if criterios.get("casal_aceita_36"):
        if respostas["idade_candidato"] is None:
            dados_em_falta.add("idade do candidato")
        else:
            idades = [respostas["idade_candidato"]]
            if respostas["idade_parceiro"] is not None:
                idades.append(respostas["idade_parceiro"])
            if any(idade > 36 or idade < 18 for idade in idades):
                return None
            if idades.count(36) > 1:
                return None
            if 36 in idades and len(idades) < 2:
                dados_em_falta.add("idade do cônjuge/parceiro")
    if criterios.get("data_contrato_ate"):
        if not respostas["data_contrato"]:
            dados_em_falta.add("data de início do contrato")
        elif respostas["data_contrato"] > criterios["data_contrato_ate"]:
            return None
    if (criterios.get("agregado_min") is not None
            and respostas["pessoas"] < criterios["agregado_min"]):
        return None
    if (criterios.get("agregado_max") is not None
            and respostas["pessoas"] > criterios["agregado_max"]):
        return None
    if (criterios.get("encargo_max") is not None
            and respostas["encargo"] > criterios["encargo_max"]):
        return None
    limites_encargo = criterios.get("encargo_max_por_pessoas", {})
    if limites_encargo:
        if respostas["encargo"] is None or respostas["pessoas"] is None:
            if respostas["encargo"] is None:
                dados_em_falta.add("encargo mensal")
            if respostas["pessoas"] is None:
                dados_em_falta.add("dimensão do agregado")
        else:
            chave_pessoas = str(min(respostas["pessoas"], 4))
            limite = limites_encargo.get(chave_pessoas)
            if limite is not None and respostas["encargo"] > limite:
                return None
    limites_preco = criterios.get("preco_imovel_max_por_tipologia", {})
    if limites_preco:
        if not respostas["tipologia"]:
            dados_em_falta.add("tipologia da habitação")
        elif respostas["preco_imovel"] is None:
            dados_em_falta.add("preço do imóvel")
        else:
            limite = limites_preco.get(respostas["tipologia"])
            if limite is None or respostas["preco_imovel"] > limite:
                return None
    if criterios.get("criancas") and not respostas["criancas"]:
        return None
    if criterios.get("monoparental") and not respostas["monoparental"]:
        return None
    if criterios.get("dependente") and not respostas["dependente"]:
        return None
    for chave, resposta_chave in (
        ("habitacao_permanente", "habitacao_permanente"),
        ("carencia_financeira", "carencia_financeira"),
        ("condicoes_indignas", "condicoes_indignas"),
        ("residencia_legal", "residencia_legal"),
        ("lote_disponivel", "lote_disponivel"),
        ("projeto_construcao", "projeto_construcao"),
        ("negociacao_banco_recente", "negociacao_banco_recente"),
    ):
        if criterios.get(chave):
            if respostas[resposta_chave] is None:
                dados_em_falta.add({
                    "habitacao_permanente": "habitação própria e permanente",
                    "carencia_financeira": "situação de carência financeira",
                    "condicoes_indignas": "condições da habitação",
                    "residencia_legal": "residência legal em Portugal",
                    "lote_disponivel": "disponibilidade de lote",
                    "projeto_construcao": "existência de projeto de construção",
                    "negociacao_banco_recente": "negociação recente com o banco",
                }[chave])
            elif respostas[resposta_chave] != 1:
                return None
    if criterios.get("propriedade_regiao") is not None:
        if respostas["propriedade_regiao"] is None:
            dados_em_falta.add("existência de outro imóvel na região")
        elif respostas["propriedade_regiao"] != criterios["propriedade_regiao"]:
            return None
    apoios_exigidos = criterios.get("apoios", [])
    if (apoios_exigidos and respostas["apoios"]
            and not set(apoios_exigidos).intersection(respostas["apoios"])):
        return None
    tipologias_exigidas = criterios.get("tipologias", [])
    if tipologias_exigidas:
        if not respostas["tipologia"]:
            dados_em_falta.add("tipologia da habitação")
        elif respostas["tipologia"] not in tipologias_exigidas:
            return None
    prestacoes_exigidas = criterios.get("prestacoes", [])
    if prestacoes_exigidas and not set(prestacoes_exigidas).intersection(respostas["prestacoes"]):
        return None
    return sorted(dados_em_falta)


def obter_perfil_habitacional(utilizador_id):
    perfil = get_db().execute(
        "SELECT concelho, situacao, rendimento, encargo, pessoas, criancas, "
        "monoparental, dependente, prestacoes_json, regiao, freguesia, "
        "idade_candidato, idade_parceiro, rendimento_anual, data_contrato, "
        "habitacao_permanente, propriedade_regiao, carencia_financeira, "
        "condicoes_indignas, residencia_legal, apoios_json, tipologia, "
        "preco_imovel, lote_disponivel, projeto_construcao, negociacao_banco_recente "
        "FROM perfis_habitacionais WHERE utilizador_id = ?",
        (utilizador_id,),
    ).fetchone()
    if perfil is None:
        return None
    dados = dict(perfil)
    dados["prestacoes"] = json.loads(dados.pop("prestacoes_json"))
    dados["apoios"] = json.loads(dados.pop("apoios_json"))
    return dados


def formulario_do_perfil(perfil):
    if perfil is None:
        return MultiDict()
    valores = {
        "concelho": perfil["concelho"],
        "situacao": perfil["situacao"],
        "rendimento": str(perfil["rendimento"]),
        "encargo": str(perfil["encargo"]),
        "pessoas": str(perfil["pessoas"]),
        "criancas": "on" if perfil["criancas"] else "",
        "monoparental": "on" if perfil["monoparental"] else "",
        "dependente": "on" if perfil["dependente"] else "",
        "prestacoes": perfil["prestacoes"],
        "regiao": perfil["regiao"] or "",
        "freguesia": perfil["freguesia"] or "",
        "idade_candidato": str(perfil["idade_candidato"] or ""),
        "idade_parceiro": str(perfil["idade_parceiro"] or ""),
        "rendimento_anual": str(perfil["rendimento_anual"] or ""),
        "data_contrato": perfil["data_contrato"] or "",
        "habitacao_permanente": valor_formulario_bool(perfil["habitacao_permanente"]),
        "propriedade_regiao": perfil["propriedade_regiao"] or "",
        "carencia_financeira": valor_formulario_bool(perfil["carencia_financeira"]),
        "condicoes_indignas": valor_formulario_bool(perfil["condicoes_indignas"]),
        "residencia_legal": valor_formulario_bool(perfil["residencia_legal"]),
        "apoios": perfil["apoios"],
        "tipologia": perfil["tipologia"] or "",
        "preco_imovel": str(perfil["preco_imovel"] or ""),
        "lote_disponivel": valor_formulario_bool(perfil["lote_disponivel"]),
        "projeto_construcao": valor_formulario_bool(perfil["projeto_construcao"]),
        "negociacao_banco_recente": valor_formulario_bool(
            perfil["negociacao_banco_recente"]
        ),
    }
    return MultiDict(valores)


def valor_formulario_bool(valor):
    if valor is None:
        return ""
    return "sim" if valor else "nao"


def respostas_do_perfil(perfil):
    return {
        "concelho": perfil["concelho"],
        "situacao": perfil["situacao"],
        "rendimento": perfil["rendimento"],
        "encargo": perfil["encargo"],
        "pessoas": perfil["pessoas"],
        "criancas": bool(perfil["criancas"]),
        "monoparental": bool(perfil["monoparental"]),
        "dependente": bool(perfil["dependente"]),
        "prestacoes": perfil["prestacoes"],
        "regiao": perfil["regiao"],
        "freguesia": perfil["freguesia"] or "",
        "idade_candidato": perfil["idade_candidato"],
        "idade_parceiro": perfil["idade_parceiro"],
        "rendimento_anual": perfil["rendimento_anual"],
        "data_contrato": perfil["data_contrato"],
        "habitacao_permanente": perfil["habitacao_permanente"],
        "propriedade_regiao": perfil["propriedade_regiao"],
        "carencia_financeira": perfil["carencia_financeira"],
        "condicoes_indignas": perfil["condicoes_indignas"],
        "residencia_legal": perfil["residencia_legal"],
        "apoios": perfil["apoios"],
        "tipologia": perfil["tipologia"],
        "preco_imovel": perfil["preco_imovel"],
        "lote_disponivel": perfil["lote_disponivel"],
        "projeto_construcao": perfil["projeto_construcao"],
        "negociacao_banco_recente": perfil["negociacao_banco_recente"],
    }


def membros_do_agregado(utilizador_id):
    return get_db().execute(
        "SELECT id, nome, relacao, idade, rendimento_mensal "
        "FROM membros_agregado WHERE utilizador_id = ? ORDER BY id",
        (utilizador_id,),
    ).fetchall()


def validar_membro_agregado(form):
    nome = form.get("nome", "").strip()
    relacao = form.get("relacao", "")
    idade_texto = form.get("idade", "").strip()
    rendimento_texto = form.get("rendimento_mensal", "").strip()
    erros = []
    if not nome:
        erros.append("Indique o nome do membro do agregado.")
    elif len(nome) > 100:
        erros.append("O nome não pode exceder 100 caracteres.")
    if relacao not in dict(RELACOES_AGREGADO):
        erros.append("Selecione uma relação válida com o candidato.")

    idade = None
    if idade_texto:
        try:
            idade = int(idade_texto)
            if not 0 <= idade <= 120:
                raise ValueError
        except ValueError:
            erros.append("A idade deve estar entre 0 e 120 anos.")

    rendimento = None
    if rendimento_texto:
        try:
            rendimento = int(rendimento_texto)
            if not 0 <= rendimento <= 10_000_000:
                raise ValueError
        except ValueError:
            erros.append("O rendimento deve estar entre 0 e 10 000 000 euros.")

    return {
        "nome": nome,
        "relacao": relacao,
        "idade": idade,
        "rendimento_mensal": rendimento,
    }, erros


def sincronizar_pessoas_agregado(utilizador_id, membros_antes):
    db = get_db()
    perfil = db.execute(
        "SELECT pessoas FROM perfis_habitacionais WHERE utilizador_id = ?",
        (utilizador_id,),
    ).fetchone()
    if perfil is None:
        return
    membros = db.execute(
        "SELECT relacao, idade FROM membros_agregado "
        "WHERE utilizador_id = ? ORDER BY id",
        (utilizador_id,),
    ).fetchall()
    membros_agora = len(membros)
    esperado_antes = membros_antes + 1
    pessoas = (
        membros_agora + 1
        if perfil["pessoas"] <= esperado_antes
        else perfil["pessoas"]
    )
    criancas = int(any(
        membro["relacao"] == "filho"
        or (membro["idade"] is not None and membro["idade"] < 18)
        for membro in membros
    ))
    idade_parceiro = next(
        (
            membro["idade"] for membro in membros
            if membro["relacao"] == "conjuge" and membro["idade"] is not None
        ),
        None,
    )
    db.execute(
        "UPDATE perfis_habitacionais SET pessoas = ?, criancas = ?, "
        "idade_parceiro = ?, atualizado_em = datetime('now') "
        "WHERE utilizador_id = ?",
        (pessoas, criancas, idade_parceiro, utilizador_id),
    )


def obter_programas_compativeis(respostas):
    db = get_db()
    programas_configurados = db.execute(
        "SELECT id, nome, entidade, descricao, criterios_json "
        "FROM programas WHERE criterios_configurados = 1 "
        "ORDER BY criado_em DESC, id DESC"
    ).fetchall()
    correspondencias = []
    for programa in programas_configurados:
        dados_em_falta = avaliar_compatibilidade_programa(
            json.loads(programa["criterios_json"]), respostas
        )
        if dados_em_falta is not None:
            resultado = dict(programa)
            resultado["dados_em_falta"] = dados_em_falta
            correspondencias.append(resultado)
    return correspondencias, bool(programas_configurados)


def validar_perfil_habitacional(form):
    concelho = form.get("concelho", "").strip()
    situacao = form.get("situacao", "")
    regiao = form.get("regiao", "")
    freguesia = form.get("freguesia", "").strip()
    erros = []
    if not concelho:
        erros.append("Indique o seu concelho.")
    elif len(concelho) > 100:
        erros.append("O concelho não pode exceder 100 caracteres.")
    if situacao not in {valor for valor, _ in SITUACOES_HABITACIONAIS}:
        erros.append("Selecione a sua situação habitacional.")
    if regiao not in {valor for valor, _ in REGIOES}:
        erros.append("Selecione a região onde vive.")
    if len(freguesia) > 100:
        erros.append("A freguesia não pode exceder 100 caracteres.")

    def inteiro_obrigatorio(nome, etiqueta, minimo, maximo):
        valor = form.get(nome, "").strip()
        try:
            numero = int(valor)
        except ValueError:
            erros.append(f"{etiqueta}: indique um número inteiro válido.")
            return 0
        if not minimo <= numero <= maximo:
            erros.append(f"{etiqueta}: indique um valor entre {minimo} e {maximo}.")
            return 0
        return numero

    def inteiro_opcional(nome, etiqueta, minimo, maximo):
        valor = form.get(nome, "").strip()
        if not valor:
            return None
        return inteiro_obrigatorio(nome, etiqueta, minimo, maximo)

    def booleano_opcional(nome, etiqueta):
        valor = form.get(nome, "")
        if valor not in ("", "sim", "nao"):
            erros.append(f"Indique se {etiqueta}.")
            return None
        return None if not valor else int(valor == "sim")

    rendimento = inteiro_obrigatorio(
        "rendimento", "Rendimento mensal líquido do agregado", 0, 10000000
    )
    encargo = inteiro_obrigatorio(
        "encargo", "Encargo mensal com habitação", 0, 10000000
    )
    pessoas = inteiro_obrigatorio("pessoas", "Pessoas no agregado", 1, 30)
    idade_candidato = inteiro_opcional(
        "idade_candidato", "Idade do candidato", 16, 120
    )
    idade_parceiro = inteiro_opcional(
        "idade_parceiro", "Idade do cônjuge ou parceiro", 16, 120
    )
    rendimento_anual = inteiro_opcional(
        "rendimento_anual", "Rendimento bruto anual do agregado", 0, 100000000
    )
    preco_imovel = inteiro_opcional(
        "preco_imovel", "Preço do imóvel a adquirir", 0, 100000000
    )
    data_contrato = form.get("data_contrato", "").strip() or None
    if data_contrato:
        try:
            datetime.strptime(data_contrato, "%Y-%m-%d")
        except ValueError:
            erros.append("Indique uma data de contrato válida.")

    prestacoes = form.getlist("prestacoes")
    prestacoes_validas = {valor for valor, _ in PRESTACOES_SOCIAIS}
    if any(valor not in prestacoes_validas for valor in prestacoes):
        erros.append("Selecione apenas prestações sociais válidas.")
    apoios = form.getlist("apoios")
    apoios_validos = {valor for valor, _ in APOIOS_PROCURADOS}
    if any(valor not in apoios_validos for valor in apoios):
        erros.append("Selecione apenas tipos de apoio válidos.")
    tipologia = form.get("tipologia", "").strip() or None
    if tipologia is not None and tipologia not in TIPOLOGIAS:
        erros.append("Selecione uma tipologia habitacional válida.")

    propriedade_regiao = form.get("propriedade_regiao", "")
    if propriedade_regiao not in ("", "sim", "nao"):
        erros.append("Indique uma resposta válida sobre propriedade imobiliária.")

    perfil = {
        "concelho": concelho,
        "situacao": situacao,
        "rendimento": rendimento,
        "encargo": encargo,
        "pessoas": pessoas,
        "criancas": bool(form.get("criancas")),
        "monoparental": bool(form.get("monoparental")),
        "dependente": bool(form.get("dependente")),
        "prestacoes": prestacoes,
        "regiao": regiao,
        "freguesia": freguesia,
        "idade_candidato": idade_candidato,
        "idade_parceiro": idade_parceiro,
        "rendimento_anual": rendimento_anual,
        "data_contrato": data_contrato,
        "habitacao_permanente": booleano_opcional(
            "habitacao_permanente", "é habitação própria e permanente"
        ),
        "propriedade_regiao": propriedade_regiao or None,
        "carencia_financeira": booleano_opcional(
            "carencia_financeira", "se encontra em carência financeira"
        ),
        "condicoes_indignas": booleano_opcional(
            "condicoes_indignas", "a habitação tem condições indignas"
        ),
        "residencia_legal": booleano_opcional(
            "residencia_legal", "tem nacionalidade portuguesa ou residência legal"
        ),
        "apoios": apoios,
        "tipologia": tipologia,
        "preco_imovel": preco_imovel,
        "lote_disponivel": booleano_opcional(
            "lote_disponivel", "tem lote disponível para construção"
        ),
        "projeto_construcao": booleano_opcional(
            "projeto_construcao", "tem um projeto de construção"
        ),
        "negociacao_banco_recente": booleano_opcional(
            "negociacao_banco_recente", "negociou o crédito com o banco nos últimos seis meses"
        ),
    }
    return perfil, erros


def guardar_perfil_habitacional(utilizador_id, perfil):
    db = get_db()
    membros = db.execute(
        "SELECT relacao, idade FROM membros_agregado "
        "WHERE utilizador_id = ? ORDER BY id",
        (utilizador_id,),
    ).fetchall()
    total_membros = len(membros)
    perfil["pessoas"] = max(perfil["pessoas"], total_membros + 1)
    if membros:
        perfil["criancas"] = any(
            membro["relacao"] == "filho"
            or (membro["idade"] is not None and membro["idade"] < 18)
            for membro in membros
        )
        perfil["idade_parceiro"] = next(
            (
                membro["idade"] for membro in membros
                if membro["relacao"] == "conjuge" and membro["idade"] is not None
            ),
            None,
        )
    perfil_existente = db.execute(
        "SELECT 1 FROM perfis_habitacionais WHERE utilizador_id = ?",
        (utilizador_id,),
    ).fetchone()
    db.execute(
        "INSERT INTO perfis_habitacionais "
        "(utilizador_id, concelho, situacao, rendimento, encargo, pessoas, "
        "criancas, monoparental, dependente, prestacoes_json, regiao, freguesia, "
        "idade_candidato, idade_parceiro, rendimento_anual, data_contrato, "
        "habitacao_permanente, propriedade_regiao, carencia_financeira, "
        "condicoes_indignas, residencia_legal, apoios_json, tipologia, preco_imovel, "
        "lote_disponivel, projeto_construcao, negociacao_banco_recente, atualizado_em) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now')) "
        "ON CONFLICT(utilizador_id) DO UPDATE SET "
        "concelho = excluded.concelho, situacao = excluded.situacao, "
        "rendimento = excluded.rendimento, encargo = excluded.encargo, "
        "pessoas = excluded.pessoas, criancas = excluded.criancas, "
        "monoparental = excluded.monoparental, dependente = excluded.dependente, "
        "prestacoes_json = excluded.prestacoes_json, regiao = excluded.regiao, "
        "freguesia = excluded.freguesia, idade_candidato = excluded.idade_candidato, "
        "idade_parceiro = excluded.idade_parceiro, "
        "rendimento_anual = excluded.rendimento_anual, "
        "data_contrato = excluded.data_contrato, "
        "habitacao_permanente = excluded.habitacao_permanente, "
        "propriedade_regiao = excluded.propriedade_regiao, "
        "carencia_financeira = excluded.carencia_financeira, "
        "condicoes_indignas = excluded.condicoes_indignas, "
        "residencia_legal = excluded.residencia_legal, apoios_json = excluded.apoios_json, "
        "tipologia = excluded.tipologia, preco_imovel = excluded.preco_imovel, "
        "lote_disponivel = excluded.lote_disponivel, "
        "projeto_construcao = excluded.projeto_construcao, "
        "negociacao_banco_recente = excluded.negociacao_banco_recente, "
        "atualizado_em = datetime('now')",
        (
            utilizador_id, perfil["concelho"], perfil["situacao"],
            perfil["rendimento"], perfil["encargo"], perfil["pessoas"],
            int(perfil["criancas"]), int(perfil["monoparental"]),
            int(perfil["dependente"]),
            json.dumps(perfil["prestacoes"], ensure_ascii=False),
            perfil["regiao"], perfil["freguesia"], perfil["idade_candidato"],
            perfil["idade_parceiro"], perfil["rendimento_anual"],
            perfil["data_contrato"], perfil["habitacao_permanente"],
            perfil["propriedade_regiao"], perfil["carencia_financeira"],
            perfil["condicoes_indignas"], perfil["residencia_legal"],
            json.dumps(perfil["apoios"], ensure_ascii=False), perfil["tipologia"],
            perfil["preco_imovel"], perfil["lote_disponivel"],
            perfil["projeto_construcao"], perfil["negociacao_banco_recente"],
        ),
    )
    registar_alteracao(
        utilizador_id,
        "perfil.atualizado" if perfil_existente else "perfil.criado",
        "perfil",
        utilizador_id,
        "Dados do perfil habitacional guardados.",
    )
    db.commit()


# ---------------------------------------------------------------- Email (SMTP)

def enviar_email(destino, assunto, corpo):
    """Envia um email por SMTP, usando as variáveis de ambiente / ficheiro .env.

    Se SMTP_HOST não estiver definido, escreve o email no terminal (modo de
    desenvolvimento), para se poder testar sem configurar nada.
    """
    host = os.environ.get("SMTP_HOST")
    if not host:
        print("\n[SMTP não configurado] Email que seria enviado para", destino)
        print("Assunto:", assunto)
        print(corpo)
        print("-" * 60, flush=True)
        return

    porta = int(os.environ.get("SMTP_PORT", "587"))
    seguranca = os.environ.get("SMTP_SECURITY", "starttls").lower()   # starttls | ssl | none
    utilizador = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    remetente = os.environ.get("SMTP_FROM") or utilizador or "noreply@localhost"

    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"] = formataddr(("Apoio à Habitação", remetente))
    msg["To"] = destino
    msg.set_content(corpo)

    contexto = ssl.create_default_context()
    try:
        if seguranca == "ssl":
            servidor = smtplib.SMTP_SSL(host, porta, timeout=20, context=contexto)
        else:
            servidor = smtplib.SMTP(host, porta, timeout=20)
        with servidor:
            if seguranca == "starttls":
                servidor.starttls(context=contexto)
            if utilizador:
                servidor.login(utilizador, password)
            servidor.send_message(msg)
    except Exception as erro:
        app.logger.error("Falha ao enviar email para %s: %s", destino, erro)


def enviar_email_em_segundo_plano(destino, assunto, corpo):
    # Numa thread, para o pedido responder sempre ao mesmo ritmo, exista ou
    # não a conta (assim ninguém descobre emails registados pelo tempo de resposta).
    threading.Thread(target=enviar_email, args=(destino, assunto, corpo), daemon=True).start()


# ---------------------------------------------------------------- Rotas

def filtrar_programas(programas, regiao=None, rendimento_mensal=None,
                      rendimento_anual=None):
    filtrados = []
    for programa in programas:
        try:
            criterios = json.loads(programa["criterios_json"] or "{}")
        except (TypeError, ValueError):
            criterios = {}

        regioes = criterios.get("regioes") or []
        if regiao and regioes and regiao not in regioes:
            continue

        rendimento_max = criterios.get("rendimento_max")
        if (rendimento_mensal is not None and rendimento_max is not None
                and rendimento_mensal > rendimento_max):
            continue

        rendimento_anual_min = criterios.get("rendimento_anual_min")
        rendimento_anual_max = criterios.get("rendimento_anual_max")
        if (rendimento_anual is not None
                and rendimento_anual_min is not None
                and rendimento_anual < rendimento_anual_min):
            continue
        if (rendimento_anual is not None
                and rendimento_anual_max is not None
                and rendimento_anual > rendimento_anual_max):
            continue

        filtrados.append(programa)
    return filtrados


@app.route("/")
def index():
    regiao = request.args.get("regiao", "")
    erros_filtro = []
    if regiao and regiao not in {valor for valor, _ in REGIOES}:
        erros_filtro.append("Selecione uma região válida.")
        regiao = ""

    def obter_rendimento(nome, maximo, etiqueta):
        valor = request.args.get(nome, "").strip()
        if not valor:
            return None, ""
        try:
            numero = int(valor)
        except ValueError:
            erros_filtro.append(f"{etiqueta}: indique um valor inteiro válido.")
            return None, valor
        if not 0 <= numero <= maximo:
            erros_filtro.append(f"{etiqueta}: indique um valor entre 0 e {maximo} €.")
            return None, valor
        return numero, valor

    rendimento_mensal, rendimento_mensal_form = obter_rendimento(
        "rendimento_mensal", 10000000, "Rendimento líquido mensal"
    )
    rendimento_anual, rendimento_anual_form = obter_rendimento(
        "rendimento_anual", 100000000, "Rendimento bruto anual"
    )
    programas = get_db().execute(
        "SELECT id, nome, entidade, descricao, criterios_json "
        "FROM programas ORDER BY criado_em DESC, id DESC"
    ).fetchall()
    programas = filtrar_programas(
        programas, regiao, rendimento_mensal, rendimento_anual
    )
    return render_template(
        "index.html",
        programas=programas,
        regiao=regiao,
        rendimento_mensal=rendimento_mensal_form,
        rendimento_anual=rendimento_anual_form,
        erros_filtro=erros_filtro,
        filtros_aplicados=bool(
            regiao or rendimento_mensal_form or rendimento_anual_form
        ),
        regioes=REGIOES,
    )


@app.route("/programas/<int:programa_id>")
def detalhe_programa(programa_id):
    db = get_db()
    programa = db.execute(
        "SELECT id, nome, entidade, descricao, criterios_json, "
        "criterios_configurados, url_candidatura "
        "FROM programas WHERE id = ?",
        (programa_id,),
    ).fetchone()
    if programa is None:
        abort(404)
    db.execute(
        "INSERT INTO visualizacoes_programas (programa_id) VALUES (?)",
        (programa_id,),
    )
    db.commit()
    feedback = db.execute(
        "SELECT f.avaliacao, f.comentario, f.criado_em "
        "FROM feedback_programas f WHERE f.programa_id = ? "
        "ORDER BY f.atualizado_em DESC, f.id DESC LIMIT 20",
        (programa_id,),
    ).fetchall()
    resumo_feedback = db.execute(
        "SELECT COUNT(*) AS total, AVG(avaliacao) AS media "
        "FROM feedback_programas WHERE programa_id = ?",
        (programa_id,),
    ).fetchone()
    minha_avaliacao = None
    if g.user and g.user["papel"] == "cliente":
        minha_avaliacao = db.execute(
            "SELECT avaliacao, comentario FROM feedback_programas "
            "WHERE programa_id = ? AND utilizador_id = ?",
            (programa_id, g.user["id"]),
        ).fetchone()
    candidatura_existente = None
    if g.user and g.user["papel"] == "cliente":
        candidatura_existente = db.execute(
            "SELECT id, estado FROM candidaturas "
            "WHERE programa_id = ? AND utilizador_id = ?",
            (programa_id, g.user["id"]),
        ).fetchone()
    return render_template(
        "programa.html",
        programa=programa,
        criterios=resumo_criterios_programa(
            json.loads(programa["criterios_json"])
        ),
        feedback=feedback,
        resumo_feedback=resumo_feedback,
        minha_avaliacao=minha_avaliacao,
        candidatura_existente=candidatura_existente,
        estados_candidatura=ESTADOS_CANDIDATURA,
    )


@app.route("/simulador")
@login_required
def simulador():
    if g.user["papel"] != "cliente":
        return redirect(url_for("admin"))

    perfil = obter_perfil_habitacional(g.user["id"])
    if perfil is None:
        flash("Preencha o seu perfil antes de procurar programas.", "error")
        return redirect(url_for("cliente"))

    programas, criterios_disponiveis = obter_programas_compativeis(
        respostas_do_perfil(perfil)
    )
    return render_template(
        "simulador.html",
        programas=programas,
        criterios_disponiveis=criterios_disponiveis,
    )


@app.route("/programas/<int:programa_id>/feedback", methods=["POST"])
@login_required
def avaliar_programa(programa_id):
    if g.user["papel"] != "cliente":
        return redirect(url_for("admin"))
    db = get_db()
    if db.execute(
        "SELECT id FROM programas WHERE id = ?", (programa_id,)
    ).fetchone() is None:
        abort(404)
    try:
        avaliacao = int(request.form.get("avaliacao", ""))
    except ValueError:
        avaliacao = 0
    comentario = request.form.get("comentario", "").strip()
    if not 1 <= avaliacao <= 5:
        flash("Selecione uma avaliação entre 1 e 5.", "error")
    elif len(comentario) > 1000:
        flash("O comentário não pode exceder 1000 caracteres.", "error")
    else:
        db.execute(
            "INSERT INTO feedback_programas "
            "(utilizador_id, programa_id, avaliacao, comentario) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(utilizador_id, programa_id) "
            "DO UPDATE SET avaliacao = excluded.avaliacao, "
            "comentario = excluded.comentario, atualizado_em = datetime('now')",
            (g.user["id"], programa_id, avaliacao, comentario),
        )
        db.commit()
        flash("A sua avaliação foi guardada.", "ok")
    return redirect(url_for("detalhe_programa", programa_id=programa_id))


@app.route("/registar", methods=["GET", "POST"])
def registar():
    if g.user:
        return redirect(area_do_utilizador(g.user))

    if request.method == "POST":
        nome = request.form.get("name", "").strip()
        apelido = request.form.get("apelido", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        erros = []
        if not nome:
            erros.append("Indique o seu nome.")
        if not apelido:
            erros.append("Indique o seu apelido.")
        if len(email) > 254 or not EMAIL_RE.match(email):
            erros.append("Indique um email válido.")
        if len(password) < 8:
            erros.append("A palavra-passe deve ter pelo menos 8 caracteres.")

        if not erros:
            db = get_db()
            try:
                # Consulta parametrizada (?) -> protege contra SQL injection
                cursor = db.execute(
                    "INSERT INTO utilizadores "
                    "(nome, apelido, email, password_hash, papel, email_verificado) "
                    "VALUES (?, ?, ?, ?, 'cliente', 0)",
                    (nome, apelido, email, generate_password_hash(password)),
                )
                registar_alteracao(
                    cursor.lastrowid, "utilizador.criado", "utilizador",
                    cursor.lastrowid, "Conta criada; email pendente de confirmação.",
                )
                db.commit()
            except sqlite3.IntegrityError:
                existente = db.execute(
                    "SELECT email_verificado FROM utilizadores WHERE email = ?", (email,)
                ).fetchone()
                if existente and not existente["email_verificado"]:
                    flash("Já existe uma conta com este email que ainda não foi "
                          "confirmada. Pode pedir um novo link de confirmação abaixo.", "error")
                    return redirect(url_for("reenviar_verificacao", email=email))
                erros.append("Já existe uma conta com este email.")
            else:
                enviar_verificacao(db, cursor.lastrowid, nome, email)
                flash("Conta criada. Enviámos um email para confirmar o seu endereço: "
                      "abra o link que lá está para poder entrar. Verifique também o spam.", "ok")
                return redirect(url_for("login"))

        for erro in erros:
            flash(erro, "error")
        return render_template("registar.html", form=request.form)

    return render_template("registar.html", form={})


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(area_do_utilizador(g.user))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = get_db().execute(
            "SELECT * FROM utilizadores WHERE email = ?", (email,)
        ).fetchone()

        if user and user["ativo"] and check_password_hash(
            user["password_hash"], password
        ):
            if not user["email_verificado"]:
                flash("Confirme o seu email antes de entrar. Se não recebeu o "
                      "link, pode pedir um novo abaixo.", "error")
                return redirect(url_for("reenviar_verificacao", email=email))
            session.clear()                      # evita session fixation
            session["user_id"] = user["id"]
            session.permanent = bool(request.form.get("remember"))
            return redirect(area_do_utilizador(user))

        # Mensagem genérica: não revela se o email existe
        flash("Email ou palavra-passe incorretos.", "error")
        return render_template("login.html", form=request.form)

    return render_template("login.html", form={})


def _hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _token_valido(token):
    return get_db().execute(
        "SELECT id, utilizador_id FROM tokens_recuperacao "
        "WHERE token_hash = ? AND expira_em > datetime('now')",
        (_hash_token(token),),
    ).fetchone()


@app.route("/recuperar", methods=["GET", "POST"])
def recuperar():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if not EMAIL_RE.match(email):
            flash("Indique um email válido.", "error")
            return render_template("recuperar.html", form=request.form)

        db = get_db()
        db.execute("DELETE FROM tokens_recuperacao WHERE expira_em <= datetime('now')")
        user = db.execute(
            "SELECT id, nome FROM utilizadores WHERE email = ?", (email,)
        ).fetchone()

        if user:
            # Máximo de 1 pedido por minuto por conta (evita spam de emails)
            recente = db.execute(
                "SELECT 1 FROM tokens_recuperacao "
                "WHERE utilizador_id = ? AND criado_em > datetime('now', '-60 seconds')",
                (user["id"],),
            ).fetchone()
            if not recente:
                token = secrets.token_urlsafe(32)
                db.execute("DELETE FROM tokens_recuperacao WHERE utilizador_id = ?", (user["id"],))
                db.execute(
                    "INSERT INTO tokens_recuperacao (utilizador_id, token_hash, expira_em) "
                    "VALUES (?, ?, datetime('now', ?))",
                    (user["id"], _hash_token(token), f"+{TOKEN_VALIDADE_MINUTOS} minutes"),
                )
                db.commit()

                base = os.environ.get("BASE_URL", "http://127.0.0.1:5000").rstrip("/")
                link = base + url_for("redefinir", token=token)
                corpo = (
                    f"Olá, {user['nome']}.\n\n"
                    "Recebemos um pedido para redefinir a palavra-passe da sua conta "
                    "no Apoio à Habitação.\n\n"
                    f"Para criar uma nova palavra-passe, abra este link "
                    f"(válido durante {TOKEN_VALIDADE_MINUTOS} minutos):\n\n{link}\n\n"
                    "Se não fez este pedido, ignore este email: a sua palavra-passe "
                    "não será alterada.\n"
                )
                enviar_email_em_segundo_plano(email, "Redefinir palavra-passe", corpo)
        db.commit()

        # Mesma resposta exista ou não a conta: não revela quais emails estão registados
        flash("Se existir uma conta com esse email, enviámos um link para "
              "redefinir a palavra-passe. Verifique também o spam.", "ok")
        return redirect(url_for("login"))

    return render_template("recuperar.html", form={})


@app.route("/redefinir/<token>", methods=["GET", "POST"])
def redefinir(token):
    registo = _token_valido(token)
    if registo is None:
        flash("Este link é inválido ou expirou. Peça um novo.", "error")
        return redirect(url_for("recuperar"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirmar = request.form.get("confirmar", "")

        erros = []
        if len(password) < 8:
            erros.append("A palavra-passe deve ter pelo menos 8 caracteres.")
        elif password != confirmar:
            erros.append("As palavras-passe não coincidem.")

        if not erros:
            db = get_db()
            db.execute(
                "UPDATE utilizadores SET password_hash = ?, email_verificado = 1 WHERE id = ?",
                (generate_password_hash(password), registo["utilizador_id"]),
            )
            registar_alteracao(
                registo["utilizador_id"], "utilizador.palavra_passe_alterada",
                "utilizador", registo["utilizador_id"],
                "Palavra-passe redefinida; o valor não é registado.",
            )
            # O link só pode ser usado uma vez
            db.execute("DELETE FROM tokens_recuperacao WHERE utilizador_id = ?",
                       (registo["utilizador_id"],))
            db.commit()
            session.clear()
            flash("Palavra-passe alterada. Já pode entrar.", "ok")
            return redirect(url_for("login"))

        for erro in erros:
            flash(erro, "error")

    return render_template("redefinir.html", token=token)


def enviar_verificacao(db, user_id, nome, email):
    """Cria um token de confirmação e envia o email. Não faz nada se houve
    um pedido nos últimos 60 segundos (evita spam de emails)."""
    recente = db.execute(
        "SELECT 1 FROM tokens_verificacao "
        "WHERE utilizador_id = ? AND criado_em > datetime('now', '-60 seconds')",
        (user_id,),
    ).fetchone()
    if recente:
        return

    token = secrets.token_urlsafe(32)
    db.execute("DELETE FROM tokens_verificacao WHERE utilizador_id = ?", (user_id,))
    db.execute(
        "INSERT INTO tokens_verificacao (utilizador_id, token_hash, expira_em) "
        "VALUES (?, ?, datetime('now', ?))",
        (user_id, _hash_token(token), f"+{TOKEN_VERIFICACAO_HORAS} hours"),
    )
    db.commit()

    base = os.environ.get("BASE_URL", "http://127.0.0.1:5000").rstrip("/")
    link = base + url_for("verificar", token=token)
    corpo = (
        f"Olá, {nome}.\n\n"
        "Obrigado por se registar no Apoio à Habitação. Para confirmar que este "
        "email é seu e ativar a conta, abra este link "
        f"(válido durante {TOKEN_VERIFICACAO_HORAS} horas):\n\n{link}\n\n"
        "Se não foi você que criou esta conta, ignore este email.\n"
    )
    enviar_email_em_segundo_plano(email, "Confirme o seu email", corpo)


@app.route("/verificar/<token>")
def verificar(token):
    db = get_db()
    registo = db.execute(
        "SELECT utilizador_id FROM tokens_verificacao "
        "WHERE token_hash = ? AND expira_em > datetime('now')",
        (_hash_token(token),),
    ).fetchone()

    if registo is None:
        flash("Este link de confirmação é inválido ou expirou. Peça um novo.", "error")
        return redirect(url_for("reenviar_verificacao"))

    db.execute("UPDATE utilizadores SET email_verificado = 1 WHERE id = ?",
               (registo["utilizador_id"],))
    registar_alteracao(
        registo["utilizador_id"], "utilizador.email_verificado", "utilizador",
        registo["utilizador_id"],
        "Endereço de email confirmado.",
    )
    db.execute("DELETE FROM tokens_verificacao WHERE utilizador_id = ?",
               (registo["utilizador_id"],))
    db.commit()
    flash("Email confirmado. Já pode entrar.", "ok")
    return redirect(url_for("login"))


@app.route("/reenviar-verificacao", methods=["GET", "POST"])
def reenviar_verificacao():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if not EMAIL_RE.match(email):
            flash("Indique um email válido.", "error")
            return render_template("reenviar_verificacao.html", form=request.form)

        db = get_db()
        db.execute("DELETE FROM tokens_verificacao WHERE expira_em <= datetime('now')")
        user = db.execute(
            "SELECT id, nome FROM utilizadores WHERE email = ? AND email_verificado = 0",
            (email,),
        ).fetchone()
        if user:
            enviar_verificacao(db, user["id"], user["nome"], email)
        db.commit()

        # Mesma resposta exista ou não a conta
        flash("Se existir uma conta por confirmar com esse email, enviámos um "
              "novo link. Verifique também o spam.", "ok")
        return redirect(url_for("login"))

    return render_template("reenviar_verificacao.html",
                           form={"email": request.args.get("email", "")})


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/agregado/membros/novo", methods=["GET", "POST"])
@login_required
def novo_membro_agregado():
    if g.user["papel"] != "cliente":
        return redirect(url_for("admin"))
    db = get_db()
    perfil = db.execute(
        "SELECT 1 FROM perfis_habitacionais WHERE utilizador_id = ?",
        (g.user["id"],),
    ).fetchone()
    if perfil is None:
        flash("Preencha primeiro o seu perfil habitacional.", "error")
        return redirect(url_for("cliente", editar=1))
    if request.method == "POST":
        membro, erros = validar_membro_agregado(request.form)
        if erros:
            for erro in erros:
                flash(erro, "error")
            return render_template(
                "membro_agregado.html",
                membro=membro,
                relacoes=RELACOES_AGREGADO,
                editar=False,
            )
        total_antes = db.execute(
            "SELECT COUNT(*) FROM membros_agregado WHERE utilizador_id = ?",
            (g.user["id"],),
        ).fetchone()[0]
        if total_antes >= 29:
            flash("O agregado não pode exceder 30 pessoas, incluindo o candidato.", "error")
            return redirect(url_for("cliente"))
        cursor = db.execute(
            "INSERT INTO membros_agregado "
            "(utilizador_id, nome, relacao, idade, rendimento_mensal) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                g.user["id"],
                membro["nome"],
                membro["relacao"],
                membro["idade"],
                membro["rendimento_mensal"],
            ),
        )
        sincronizar_pessoas_agregado(g.user["id"], total_antes)
        registar_alteracao(
            g.user["id"], "membro.criado", "membro", cursor.lastrowid,
            "Membro adicionado ao agregado.",
        )
        db.commit()
        flash("Membro do agregado adicionado.", "ok")
        return redirect(url_for("cliente"))
    return render_template(
        "membro_agregado.html",
        membro={},
        relacoes=RELACOES_AGREGADO,
        editar=False,
    )


@app.route("/agregado/membros/<int:membro_id>/editar", methods=["GET", "POST"])
@login_required
def editar_membro_agregado(membro_id):
    if g.user["papel"] != "cliente":
        return redirect(url_for("admin"))
    db = get_db()
    membro = db.execute(
        "SELECT id, nome, relacao, idade, rendimento_mensal "
        "FROM membros_agregado WHERE id = ? AND utilizador_id = ?",
        (membro_id, g.user["id"]),
    ).fetchone()
    if membro is None:
        abort(404)
    membro = dict(membro)
    if request.method == "POST":
        valores, erros = validar_membro_agregado(request.form)
        if erros:
            for erro in erros:
                flash(erro, "error")
            return render_template(
                "membro_agregado.html",
                membro=valores,
                relacoes=RELACOES_AGREGADO,
                editar=True,
                membro_id=membro_id,
            )
        total_antes = db.execute(
            "SELECT COUNT(*) FROM membros_agregado WHERE utilizador_id = ?",
            (g.user["id"],),
        ).fetchone()[0]
        db.execute(
            "UPDATE membros_agregado SET nome = ?, relacao = ?, idade = ?, "
            "rendimento_mensal = ?, atualizado_em = datetime('now') "
            "WHERE id = ? AND utilizador_id = ?",
            (
                valores["nome"],
                valores["relacao"],
                valores["idade"],
                valores["rendimento_mensal"],
                membro_id,
                g.user["id"],
            ),
        )
        sincronizar_pessoas_agregado(g.user["id"], total_antes)
        registar_alteracao(
            g.user["id"], "membro.atualizado", "membro", membro_id,
            "Dados do membro atualizados.",
        )
        db.commit()
        flash("Dados do membro do agregado atualizados.", "ok")
        return redirect(url_for("cliente"))
    return render_template(
        "membro_agregado.html",
        membro=membro,
        relacoes=RELACOES_AGREGADO,
        editar=True,
        membro_id=membro_id,
    )


@app.route("/agregado/membros/<int:membro_id>/remover", methods=["POST"])
@login_required
def remover_membro_agregado(membro_id):
    if g.user["papel"] != "cliente":
        return redirect(url_for("admin"))
    db = get_db()
    total_antes = db.execute(
        "SELECT COUNT(*) FROM membros_agregado WHERE utilizador_id = ?",
        (g.user["id"],),
    ).fetchone()[0]
    cursor = db.execute(
        "DELETE FROM membros_agregado WHERE id = ? AND utilizador_id = ?",
        (membro_id, g.user["id"]),
    )
    if cursor.rowcount == 0:
        abort(404)
    sincronizar_pessoas_agregado(g.user["id"], total_antes)
    registar_alteracao(
        g.user["id"], "membro.eliminado", "membro", membro_id,
        "Membro removido do agregado.",
    )
    db.commit()
    flash("Membro removido do agregado.", "ok")
    return redirect(url_for("cliente"))


def candidaturas_do_utilizador(utilizador_id):
    db = get_db()
    candidaturas = db.execute(
        "SELECT c.id, c.estado, c.criada_em, c.atualizada_em, "
        "p.id AS programa_id, p.nome AS programa_nome "
        "FROM candidaturas c JOIN programas p ON p.id = c.programa_id "
        "WHERE c.utilizador_id = ? ORDER BY c.atualizada_em DESC, c.id DESC",
        (utilizador_id,),
    ).fetchall()
    if not candidaturas:
        return []
    historico = db.execute(
        "SELECT historico_candidaturas.candidatura_id, "
        "historico_candidaturas.estado, historico_candidaturas.criado_em "
        "FROM historico_candidaturas JOIN candidaturas "
        "ON candidaturas.id = historico_candidaturas.candidatura_id "
        "WHERE candidaturas.utilizador_id = ? ORDER BY historico_candidaturas.criado_em, "
        "historico_candidaturas.id",
        (utilizador_id,),
    ).fetchall()
    historico_por_candidatura = {}
    for evento in historico:
        historico_por_candidatura.setdefault(evento["candidatura_id"], []).append(
            evento
        )
    resultado = []
    for candidatura in candidaturas:
        item = dict(candidatura)
        item["historico"] = historico_por_candidatura.get(candidatura["id"], [])
        item["transicoes"] = [
            (estado, ESTADOS_CANDIDATURA[estado])
            for estado in TRANSICOES_CANDIDATURA[candidatura["estado"]]
        ]
        resultado.append(item)
    return resultado


@app.route("/cliente", methods=["GET", "POST"])
@login_required
def cliente():
    if g.user["papel"] == "admin":
        return redirect(url_for("admin"))

    if request.method == "POST":
        perfil_enviado, erros = validar_perfil_habitacional(request.form)
        if erros:
            for erro in erros:
                flash(erro, "error")
            perfil_atual = obter_perfil_habitacional(g.user["id"])
            membros = membros_do_agregado(g.user["id"])
            return render_template(
                "cliente.html",
                perfil=perfil_atual,
                form=request.form,
                editar_perfil=True,
                situacoes=dict(SITUACOES_HABITACIONAIS),
                prestacoes_sociais=PRESTACOES_SOCIAIS,
                regioes=dict(REGIOES),
                apoios_procurados=APOIOS_PROCURADOS,
                tipologias=TIPOLOGIAS,
                prestacoes_perfil=[],
                apoios_perfil=[],
                candidaturas=candidaturas_do_utilizador(g.user["id"]),
                membros_agregado=membros,
                idade_parceiro_gerida=any(
                    membro["relacao"] == "conjuge" for membro in membros
                ),
                relacoes_agregado=dict(RELACOES_AGREGADO),
                estados_candidatura=ESTADOS_CANDIDATURA,
                perfil_completo=bool(perfil_atual and perfil_atual["regiao"]),
            )
        guardar_perfil_habitacional(g.user["id"], perfil_enviado)
        flash("Perfil atualizado com sucesso.", "ok")
        return redirect(url_for("cliente"))

    perfil = obter_perfil_habitacional(g.user["id"])
    membros = membros_do_agregado(g.user["id"])
    perfil_completo = perfil is not None and bool(perfil["regiao"])
    editar_perfil = not perfil_completo or request.args.get("editar") == "1"
    return render_template(
        "cliente.html",
        perfil=perfil,
        form=formulario_do_perfil(perfil),
        editar_perfil=editar_perfil,
        perfil_completo=perfil_completo,
        situacoes=dict(SITUACOES_HABITACIONAIS),
        prestacoes_sociais=PRESTACOES_SOCIAIS,
        regioes=dict(REGIOES),
        apoios_procurados=APOIOS_PROCURADOS,
        tipologias=TIPOLOGIAS,
        prestacoes_perfil=(
            [etiqueta for valor, etiqueta in PRESTACOES_SOCIAIS
             if valor in perfil["prestacoes"]]
            if perfil else []
        ),
        apoios_perfil=(
            [etiqueta for valor, etiqueta in APOIOS_PROCURADOS
             if valor in perfil["apoios"]]
            if perfil else []
        ),
        candidaturas=candidaturas_do_utilizador(g.user["id"]),
        membros_agregado=membros,
        idade_parceiro_gerida=any(
            membro["relacao"] == "conjuge" for membro in membros
        ),
        relacoes_agregado=dict(RELACOES_AGREGADO),
        estados_candidatura=ESTADOS_CANDIDATURA,
    )


@app.route("/candidaturas", methods=["POST"])
@login_required
def registar_candidatura():
    if g.user["papel"] != "cliente":
        return redirect(url_for("admin"))
    try:
        programa_id = int(request.form.get("programa_id", ""))
    except ValueError:
        abort(400)
    db = get_db()
    programa = db.execute(
        "SELECT id FROM programas WHERE id = ?", (programa_id,)
    ).fetchone()
    if programa is None:
        abort(404)
    ja_existe = db.execute(
        "SELECT id FROM candidaturas WHERE utilizador_id = ? AND programa_id = ?",
        (g.user["id"], programa_id),
    ).fetchone()
    if ja_existe:
        flash("Já acompanha uma candidatura a este programa.", "error")
        return redirect(url_for("detalhe_programa", programa_id=programa_id))
    cursor = db.execute(
        "INSERT INTO candidaturas (utilizador_id, programa_id, estado) "
        "VALUES (?, ?, 'submetida')",
        (g.user["id"], programa_id),
    )
    candidatura_id = cursor.lastrowid
    db.execute(
        "INSERT INTO historico_candidaturas (candidatura_id, estado) "
        "VALUES (?, 'submetida')",
        (candidatura_id,),
    )
    db.commit()
    flash("Candidatura registada para acompanhamento.", "ok")
    return redirect(url_for("cliente"))


@app.route("/candidaturas/<int:candidatura_id>/estado", methods=["POST"])
@login_required
def atualizar_estado_candidatura(candidatura_id):
    if g.user["papel"] != "cliente":
        return redirect(url_for("admin"))
    novo_estado = request.form.get("estado", "")
    if novo_estado not in ESTADOS_CANDIDATURA:
        abort(400)
    db = get_db()
    candidatura = db.execute(
        "SELECT id, estado FROM candidaturas "
        "WHERE id = ? AND utilizador_id = ?",
        (candidatura_id, g.user["id"]),
    ).fetchone()
    if candidatura is None:
        abort(404)
    if not transicao_candidatura_valida(candidatura["estado"], novo_estado):
        flash("Essa alteração de estado não é permitida.", "error")
        return redirect(url_for("cliente"))
    db.execute(
        "UPDATE candidaturas SET estado = ?, atualizada_em = datetime('now') "
        "WHERE id = ?",
        (novo_estado, candidatura_id),
    )
    db.execute(
        "INSERT INTO historico_candidaturas (candidatura_id, estado) VALUES (?, ?)",
        (candidatura_id, novo_estado),
    )
    db.commit()
    flash("Estado da candidatura atualizado.", "ok")
    return redirect(url_for("cliente"))


@app.route("/admin")
@admin_required
def admin():
    db = get_db()
    utilizadores = db.execute(
        "SELECT id, nome, apelido, email, papel, ativo, email_verificado, criado_em "
        "FROM utilizadores ORDER BY criado_em DESC, id DESC"
    ).fetchall()
    programas = db.execute(
        "SELECT id, nome, entidade, criado_em, criterios_configurados, "
        "url_candidatura "
        "FROM programas ORDER BY criado_em DESC, id DESC"
    ).fetchall()
    estatisticas = {
        "utilizadores": db.execute(
            "SELECT COUNT(*) FROM utilizadores WHERE papel = 'cliente'"
        ).fetchone()[0],
        "perfis": db.execute(
            "SELECT COUNT(*) FROM perfis_habitacionais"
        ).fetchone()[0],
        "programas": db.execute(
            "SELECT COUNT(*) FROM programas"
        ).fetchone()[0],
        "candidaturas": db.execute(
            "SELECT COUNT(*) FROM candidaturas"
        ).fetchone()[0],
        "consultas": db.execute(
            "SELECT COUNT(*) FROM visualizacoes_programas"
        ).fetchone()[0],
    }
    candidaturas_por_estado = db.execute(
        "SELECT estado, COUNT(*) AS total FROM candidaturas GROUP BY estado"
    ).fetchall()
    programas_procurados = db.execute(
        "SELECT p.id, p.nome, COUNT(v.id) AS consultas "
        "FROM programas p LEFT JOIN visualizacoes_programas v "
        "ON v.programa_id = p.id GROUP BY p.id HAVING COUNT(v.id) > 0 "
        "ORDER BY consultas DESC, p.nome LIMIT 5"
    ).fetchall()
    return render_template(
        "admin.html",
        utilizadores=utilizadores,
        programas=programas,
        estatisticas=estatisticas,
        candidaturas_por_estado=candidaturas_por_estado,
        estados_candidatura=ESTADOS_CANDIDATURA,
        programas_procurados=programas_procurados,
        data_inicio=request.args.get("data_inicio", ""),
        data_fim=request.args.get("data_fim", ""),
    )


@app.route("/admin/relatorio.csv")
@admin_required
def relatorio_agregado():
    data_inicio = request.args.get("data_inicio", "").strip()
    data_fim = request.args.get("data_fim", "").strip()
    for valor in (data_inicio, data_fim):
        if valor:
            try:
                datetime.strptime(valor, "%Y-%m-%d")
            except ValueError:
                abort(400)
    if data_inicio and data_fim and data_inicio > data_fim:
        abort(400)

    filtros = []
    parametros = []
    if data_inicio:
        filtros.append("date({coluna}) >= date(?)")
        parametros.append(data_inicio)
    if data_fim:
        filtros.append("date({coluna}) <= date(?)")
        parametros.append(data_fim)

    db = get_db()

    def contar_tabela(tabela, coluna_data, condicao="", argumentos=()):
        clausulas = [
            filtro.format(coluna=coluna_data) for filtro in filtros
        ]
        if condicao:
            clausulas.append(condicao)
        consulta = f"SELECT COUNT(*) FROM {tabela}"
        if clausulas:
            consulta += " WHERE " + " AND ".join(clausulas)
        return db.execute(consulta, (*parametros, *argumentos)).fetchone()[0]

    linhas = [
        ("Contas de cliente criadas", "Total",
         contar_tabela("utilizadores", "criado_em", "papel = 'cliente'")),
        ("Candidaturas registadas", "Total",
         contar_tabela("candidaturas", "criada_em")),
        ("Consultas de programas", "Total",
         contar_tabela("visualizacoes_programas", "criado_em")),
        ("Avaliações submetidas", "Total",
         contar_tabela("feedback_programas", "criado_em")),
    ]
    for tipo, etiqueta in (
        ("perfil.criado", "Perfis criados"),
        ("perfil.atualizado", "Perfis atualizados"),
        ("programa.criado", "Programas criados"),
        ("programa.atualizado", "Programas atualizados"),
    ):
        linhas.append(
            (etiqueta, "Total", contar_tabela(
                "historico_alteracoes", "criado_em", "tipo = ?", (tipo,)
            ))
        )

    clausulas_estado = [
        filtro.format(coluna="criado_em") for filtro in filtros
    ]
    consulta_estados = (
        "SELECT estado, COUNT(*) AS total FROM historico_candidaturas"
    )
    if clausulas_estado:
        consulta_estados += " WHERE " + " AND ".join(clausulas_estado)
    consulta_estados += " GROUP BY estado ORDER BY estado"
    for linha in db.execute(consulta_estados, parametros).fetchall():
        linhas.append(
            (
                "Estados registados no histórico de candidaturas",
                ESTADOS_CANDIDATURA[linha["estado"]],
                linha["total"],
            )
        )

    clausulas_consulta = [
        filtro.format(coluna="v.criado_em") for filtro in filtros
    ]
    consulta_programas = (
        "SELECT p.nome, COUNT(v.id) AS total FROM visualizacoes_programas v "
        "JOIN programas p ON p.id = v.programa_id"
    )
    if clausulas_consulta:
        consulta_programas += " WHERE " + " AND ".join(clausulas_consulta)
    consulta_programas += (
        " GROUP BY p.id, p.nome ORDER BY total DESC, p.nome LIMIT 5"
    )
    for linha in db.execute(consulta_programas, parametros).fetchall():
        linhas.append(("Programa mais consultado", linha["nome"], linha["total"]))

    conteudo = io.StringIO(newline="")
    escritor = csv.writer(conteudo, delimiter=";")
    escritor.writerow(["Indicador agregado", "Categoria", "Total"])
    for linha in linhas:
        campos = []
        for campo in linha:
            valor = str(campo)
            if valor.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
                valor = "'" + valor
            campos.append(valor)
        escritor.writerow(campos)
    resposta = Response(
        "\ufeff" + conteudo.getvalue(),
        content_type="text/csv; charset=utf-8",
    )
    resposta.headers["Content-Disposition"] = (
        "attachment; filename=relatorio-agregado.csv"
    )
    return resposta


@app.route("/admin/utilizadores/<int:utilizador_id>/editar", methods=["GET", "POST"])
@admin_required
def editar_utilizador(utilizador_id):
    db = get_db()
    utilizador = db.execute(
        "SELECT id, nome, apelido, email, papel, email_verificado "
        "FROM utilizadores "
        "WHERE id = ? AND papel = 'cliente'",
        (utilizador_id,),
    ).fetchone()
    if utilizador is None:
        abort(404)
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        apelido = request.form.get("apelido", "").strip()
        email = request.form.get("email", "").strip().lower()
        erros = []
        if not nome or len(nome) > 100:
            erros.append("O nome é obrigatório e não pode exceder 100 caracteres.")
        if not apelido or len(apelido) > 100:
            erros.append("O apelido é obrigatório e não pode exceder 100 caracteres.")
        if len(email) > 254 or not EMAIL_RE.match(email):
            erros.append("Indique um email válido.")
        email_alterado = email != utilizador["email"]
        if erros:
            for erro in erros:
                flash(erro, "error")
            return render_template(
                "utilizador_editar.html",
                utilizador={
                    "id": utilizador_id,
                    "nome": nome,
                    "apelido": apelido,
                    "email": email,
                },
            )
        try:
            db.execute(
                "UPDATE utilizadores SET nome = ?, apelido = ?, email = ?, "
                "email_verificado = ? "
                "WHERE id = ? AND papel = 'cliente'",
                (
                    nome,
                    apelido,
                    email,
                    0 if email_alterado else utilizador["email_verificado"],
                    utilizador_id,
                ),
            )
        except sqlite3.IntegrityError:
            flash("Já existe uma conta com esse email.", "error")
            return render_template(
                "utilizador_editar.html",
                utilizador={
                    "id": utilizador_id,
                    "nome": nome,
                    "apelido": apelido,
                    "email": email,
                },
            )
        registar_alteracao(
            g.user["id"], "utilizador.atualizado", "utilizador", utilizador_id,
            "Dados de conta atualizados por um administrador.",
        )
        if email_alterado:
            db.execute(
                "DELETE FROM tokens_verificacao WHERE utilizador_id = ?",
                (utilizador_id,),
            )
        db.commit()
        if email_alterado:
            enviar_verificacao(db, utilizador_id, nome, email)
            flash(
                "Conta atualizada. O novo endereço de email tem de ser confirmado.",
                "ok",
            )
            return redirect(url_for("admin"))
        flash("Conta atualizada.", "ok")
        return redirect(url_for("admin"))
    return render_template("utilizador_editar.html", utilizador=utilizador)


@app.route("/admin/utilizadores/<int:utilizador_id>/estado", methods=["POST"])
@admin_required
def alternar_estado_utilizador(utilizador_id):
    db = get_db()
    utilizador = db.execute(
        "SELECT id, ativo FROM utilizadores "
        "WHERE id = ? AND papel = 'cliente'",
        (utilizador_id,),
    ).fetchone()
    if utilizador is None:
        abort(404)
    novo_estado = 0 if utilizador["ativo"] else 1
    db.execute(
        "UPDATE utilizadores SET ativo = ? WHERE id = ? AND papel = 'cliente'",
        (novo_estado, utilizador_id),
    )
    tipo = "utilizador.ativado" if novo_estado else "utilizador.desativado"
    registar_alteracao(
        g.user["id"], tipo, "utilizador", utilizador_id,
        "Conta ativada por um administrador."
        if novo_estado else "Conta desativada por um administrador.",
    )
    db.commit()
    flash(
        "Conta ativada." if novo_estado else "Conta desativada; o utilizador "
        "deixará de conseguir iniciar sessão.",
        "ok",
    )
    return redirect(url_for("admin"))


@app.route("/admin/utilizadores/<int:utilizador_id>/eliminar", methods=["POST"])
@admin_required
def eliminar_utilizador(utilizador_id):
    db = get_db()
    utilizador = db.execute(
        "SELECT id FROM utilizadores "
        "WHERE id = ? AND papel = 'cliente'",
        (utilizador_id,),
    ).fetchone()
    if utilizador is None:
        abort(404)
    registar_alteracao(
        g.user["id"], "utilizador.eliminado", "utilizador", utilizador_id,
        "Conta eliminada por um administrador; dados associados removidos.",
    )
    db.execute(
        "DELETE FROM utilizadores WHERE id = ? AND papel = 'cliente'",
        (utilizador_id,),
    )
    db.commit()
    flash("Conta eliminada e dados associados removidos.", "ok")
    return redirect(url_for("admin"))


@app.route("/admin/programas/modelo-csv")
@admin_required
def modelo_csv_programas():
    conteudo = "nome,entidade,descricao,url_candidatura\n"
    resposta = Response(conteudo, content_type="text/csv; charset=utf-8")
    resposta.headers["Content-Disposition"] = (
        "attachment; filename=modelo-programas.csv"
    )
    return resposta


@app.route("/admin/programas/importar", methods=["POST"])
@admin_required
def importar_programas_csv():
    ficheiro = request.files.get("ficheiro_csv")
    if ficheiro is None or not ficheiro.filename:
        flash("Selecione um ficheiro CSV para importar.", "error")
        return redirect(url_for("admin"))
    conteudo_bytes = ficheiro.stream.read(2 * 1024 * 1024 + 1)
    if len(conteudo_bytes) > 2 * 1024 * 1024:
        flash("O ficheiro CSV não pode exceder 2 MB.", "error")
        return redirect(url_for("admin"))
    try:
        conteudo = conteudo_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        flash("O ficheiro CSV deve estar codificado em UTF-8.", "error")
        return redirect(url_for("admin"))
    programas_importados, erros = analisar_csv_programas(conteudo)
    if erros:
        for erro in erros:
            flash(erro, "error")
        return redirect(url_for("admin"))
    db = get_db()
    for programa in programas_importados:
        cursor = db.execute(
            "INSERT INTO programas "
            "(nome, entidade, descricao, criterios_json, criterios_configurados, "
            "url_candidatura) VALUES (?, ?, ?, '{}', 0, ?)",
            (
                programa["nome"],
                programa["entidade"],
                programa["descricao"],
                programa["url_candidatura"],
            ),
        )
        registar_alteracao(
            g.user["id"], "programa.criado", "programa", cursor.lastrowid,
            "Programa importado via CSV.",
        )
    db.commit()
    flash(
        f"{len(programas_importados)} programa(s) importado(s). "
        "Reveja e configure os critérios antes de ativar a correspondência automática.",
        "ok",
    )
    return redirect(url_for("admin"))


@app.route("/admin/historico")
@admin_required
def historico():
    data_inicio = request.args.get("data_inicio", "").strip()
    data_fim = request.args.get("data_fim", "").strip()
    tipo = request.args.get("tipo", "").strip()
    filtros = []
    parametros = []

    for valor, operador in ((data_inicio, ">="), (data_fim, "<=")):
        if valor:
            try:
                datetime.strptime(valor, "%Y-%m-%d")
            except ValueError:
                abort(400)
            filtros.append(f"date(h.criado_em) {operador} date(?)")
            parametros.append(valor)
    if data_inicio and data_fim and data_inicio > data_fim:
        abort(400)
    if tipo:
        if tipo not in TIPOS_HISTORICO:
            abort(400)
        filtros.append("h.tipo = ?")
        parametros.append(tipo)

    sql = (
        "SELECT h.id, h.tipo, h.entidade, h.entidade_id, h.responsavel_id, "
        "h.responsavel_nome, h.responsavel_email, h.detalhes, h.criado_em "
        "FROM historico_alteracoes h"
    )
    if filtros:
        sql += " WHERE " + " AND ".join(filtros)
    sql += " ORDER BY h.criado_em DESC, h.id DESC LIMIT 500"
    eventos = get_db().execute(sql, parametros).fetchall()
    return render_template(
        "historico.html",
        eventos=eventos,
        tipos=TIPOS_HISTORICO,
        data_inicio=data_inicio,
        data_fim=data_fim,
        tipo=tipo,
        tipos_rotulo=TIPOS_HISTORICO,
    )


@app.route("/admin/programas/novo", methods=["GET", "POST"])
@admin_required
def novo_programa():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        entidade = request.form.get("entidade", "").strip()
        descricao = request.form.get("descricao", "").strip()
        url_candidatura = request.form.get("url_candidatura", "").strip()
        criterios, erros = criterios_do_formulario(request.form)

        if not nome:
            erros.append("Indique o nome do programa.")
        elif len(nome) > 120:
            erros.append("O nome não pode ter mais de 120 caracteres.")
        if not entidade:
            erros.append("Indique a entidade responsável.")
        elif len(entidade) > 120:
            erros.append("A entidade não pode ter mais de 120 caracteres.")
        if not descricao:
            erros.append("Escreva uma descrição.")
        elif len(descricao) > 2000:
            erros.append("A descrição não pode ter mais de 2000 caracteres.")
        url_candidatura, erro_url = validar_url_candidatura(url_candidatura)
        if erro_url:
            erros.append(erro_url)

        if not erros:
            db = get_db()
            db.execute(
                "INSERT INTO programas "
                "(nome, entidade, descricao, criterios_json, criterios_configurados, "
                "url_candidatura) VALUES (?, ?, ?, ?, ?, ?)",
                (nome, entidade, descricao, json.dumps(criterios, ensure_ascii=False),
                 int(bool(request.form.get("criterios_configurados"))), url_candidatura),
            )
            programa_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            registar_alteracao(
                g.user["id"], "programa.criado", "programa", programa_id,
                "Programa criado manualmente.",
            )
            db.commit()
            flash("Programa adicionado com sucesso.", "ok")
            return redirect(url_for("admin"))

        for erro in erros:
            flash(erro, "error")
        return render_template(
            "novo_programa.html",
            form=request.form,
            criterios=criterios,
            situacoes=SITUACOES_HABITACIONAIS,
            prestacoes=PRESTACOES_SOCIAIS,
            regioes=dict(REGIOES),
            apoios_procurados=APOIOS_PROCURADOS,
            tipologias=TIPOLOGIAS,
            criterios_configurados=bool(request.form.get("criterios_configurados")),
            editar=False,
        )

    return render_template(
        "novo_programa.html",
        form={},
        criterios={},
        situacoes=SITUACOES_HABITACIONAIS,
        prestacoes=PRESTACOES_SOCIAIS,
        regioes=dict(REGIOES),
        apoios_procurados=APOIOS_PROCURADOS,
        tipologias=TIPOLOGIAS,
        criterios_configurados=False,
        editar=False,
    )


@app.route("/admin/programas/<int:programa_id>/editar", methods=["GET", "POST"])
@admin_required
def editar_programa(programa_id):
    db = get_db()
    programa = db.execute(
        "SELECT id, nome, entidade, descricao, criterios_json, "
        "criterios_configurados, url_candidatura "
        "FROM programas WHERE id = ?",
        (programa_id,),
    ).fetchone()
    if programa is None:
        abort(404)

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        entidade = request.form.get("entidade", "").strip()
        descricao = request.form.get("descricao", "").strip()
        url_candidatura = request.form.get("url_candidatura", "").strip()
        criterios_originais = json.loads(programa["criterios_json"])
        criterios, erros = criterios_do_formulario(request.form)
        if (
            criterios_originais.get("requer_confirmacao_limites_rendimento")
            and request.form.get("limites_rendimento_confirmados")
            and (
                criterios["rendimento_anual_min"] is None
                or criterios["rendimento_anual_max"] is None
            )
        ):
            erros.append(
                "Indique os limites anuais mínimo e máximo antes de confirmar "
                "os critérios de rendimento."
            )
        limites_renda_originais = criterios_originais.get(
            "encargo_max_por_pessoas", {}
        )
        if (
            limites_renda_originais
            and request.form.get("criterios_configurados")
            and criterios["encargo_max_por_pessoas"].keys()
            != limites_renda_originais.keys()
        ):
            erros.append(
                "Mantenha os limites de renda para todas as dimensões do agregado "
                "ou desative a correspondência automática."
            )

        if not nome:
            erros.append("Indique o nome do programa.")
        elif len(nome) > 120:
            erros.append("O nome não pode ter mais de 120 caracteres.")
        if not entidade:
            erros.append("Indique a entidade responsável.")
        elif len(entidade) > 120:
            erros.append("A entidade não pode ter mais de 120 caracteres.")
        if not descricao:
            erros.append("Escreva uma descrição.")
        elif len(descricao) > 2000:
            erros.append("A descrição não pode ter mais de 2000 caracteres.")
        url_candidatura, erro_url = validar_url_candidatura(url_candidatura)
        if erro_url:
            erros.append(erro_url)

        if not erros:
            db.execute(
                "UPDATE programas SET nome = ?, entidade = ?, descricao = ?, "
                "criterios_json = ?, criterios_configurados = ?, "
                "url_candidatura = ? WHERE id = ?",
                (nome, entidade, descricao, json.dumps(criterios, ensure_ascii=False),
                 int(bool(request.form.get("criterios_configurados"))),
                 url_candidatura, programa_id),
            )
            registar_alteracao(
                g.user["id"], "programa.atualizado", "programa", programa_id,
                "Dados do programa e critérios atualizados.",
            )
            db.commit()
            flash("Programa atualizado com sucesso.", "ok")
            return redirect(url_for("admin"))

        for erro in erros:
            flash(erro, "error")
        dados_programa = request.form
        criterios_configurados = bool(request.form.get("criterios_configurados"))
    else:
        dados_programa = dict(programa)
        criterios = json.loads(programa["criterios_json"])
        criterios_configurados = bool(programa["criterios_configurados"])

    return render_template(
        "novo_programa.html",
        form=dados_programa,
        criterios=criterios,
        situacoes=SITUACOES_HABITACIONAIS,
        prestacoes=PRESTACOES_SOCIAIS,
        regioes=dict(REGIOES),
        apoios_procurados=APOIOS_PROCURADOS,
        tipologias=TIPOLOGIAS,
        criterios_configurados=criterios_configurados,
        editar=True,
        programa_id=programa_id,
    )


@app.errorhandler(403)
def proibido(_e):
    return render_template("erro.html", titulo="Acesso negado",
                           mensagem="Não tem permissão para ver esta página."), 403


@app.errorhandler(400)
def pedido_invalido(_e):
    return render_template("erro.html", titulo="Pedido inválido",
                           mensagem="A sessão expirou. Volte atrás e tente de novo."), 400


if __name__ == "__main__":
    # debug=True só para desenvolvimento
    app.run(debug=True)
