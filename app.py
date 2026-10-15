import hashlib
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

from flask import (Flask, abort, flash, g, redirect, render_template,
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
            "SELECT id, nome, apelido, email, papel FROM utilizadores WHERE id = ?",
            (user_id,),
        ).fetchone()
        if g.user is None:          # utilizador apagado entretanto
            session.clear()


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

@app.route("/")
def index():
    programas = get_db().execute(
        "SELECT id, nome, entidade, descricao "
        "FROM programas ORDER BY criado_em DESC, id DESC"
    ).fetchall()
    return render_template("index.html", programas=programas)


@app.route("/programas/<int:programa_id>")
def detalhe_programa(programa_id):
    programa = get_db().execute(
        "SELECT id, nome, entidade, descricao, criterios_json, "
        "criterios_configurados, url_candidatura "
        "FROM programas WHERE id = ?",
        (programa_id,),
    ).fetchone()
    if programa is None:
        abort(404)
    return render_template(
        "programa.html",
        programa=programa,
        criterios=resumo_criterios_programa(
            json.loads(programa["criterios_json"])
        ),
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
        if not EMAIL_RE.match(email):
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

        if user and check_password_hash(user["password_hash"], password):
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
                perfil_completo=bool(perfil_atual and perfil_atual["regiao"]),
            )
        guardar_perfil_habitacional(g.user["id"], perfil_enviado)
        flash("Perfil atualizado com sucesso.", "ok")
        return redirect(url_for("cliente"))

    perfil = obter_perfil_habitacional(g.user["id"])
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
    )


@app.route("/admin")
@admin_required
def admin():
    db = get_db()
    utilizadores = db.execute(
        "SELECT id, nome, apelido, email, papel, email_verificado, criado_em "
        "FROM utilizadores ORDER BY criado_em DESC, id DESC"
    ).fetchall()
    programas = db.execute(
        "SELECT id, nome, entidade, criado_em, criterios_configurados, "
        "url_candidatura "
        "FROM programas ORDER BY criado_em DESC, id DESC"
    ).fetchall()
    return render_template("admin.html", utilizadores=utilizadores, programas=programas)


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
