CREATE TABLE IF NOT EXISTS utilizadores (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    nome          TEXT NOT NULL,
    apelido       TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    papel         TEXT NOT NULL DEFAULT 'cliente'
                  CHECK (papel IN ('cliente', 'admin')),
    -- 1 por defeito: contas criadas por script (admin) e contas antigas contam como verificadas.
    -- O registo de clientes define explicitamente 0 até confirmarem o email.
    email_verificado INTEGER NOT NULL DEFAULT 1,
    criado_em     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS programas (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    nome       TEXT NOT NULL,
    entidade   TEXT NOT NULL,
    descricao  TEXT NOT NULL,
    criterios_json TEXT NOT NULL DEFAULT '{}',
    criterios_configurados INTEGER NOT NULL DEFAULT 0,
    url_candidatura TEXT,
    criado_em  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS perfis_habitacionais (
    utilizador_id INTEGER PRIMARY KEY REFERENCES utilizadores(id) ON DELETE CASCADE,
    concelho      TEXT NOT NULL,
    situacao      TEXT NOT NULL,
    rendimento    INTEGER NOT NULL,
    encargo       INTEGER NOT NULL,
    pessoas       INTEGER NOT NULL,
    criancas      INTEGER NOT NULL DEFAULT 0,
    monoparental  INTEGER NOT NULL DEFAULT 0,
    dependente    INTEGER NOT NULL DEFAULT 0,
    prestacoes_json TEXT NOT NULL DEFAULT '[]',
    regiao        TEXT,
    freguesia     TEXT,
    idade_candidato INTEGER,
    idade_parceiro INTEGER,
    rendimento_anual INTEGER,
    data_contrato TEXT,
    habitacao_permanente INTEGER,
    propriedade_regiao TEXT,
    carencia_financeira INTEGER,
    condicoes_indignas INTEGER,
    residencia_legal INTEGER,
    apoios_json TEXT NOT NULL DEFAULT '[]',
    tipologia TEXT,
    preco_imovel INTEGER,
    lote_disponivel INTEGER,
    projeto_construcao INTEGER,
    negociacao_banco_recente INTEGER,
    atualizado_em TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tokens_recuperacao (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    utilizador_id INTEGER NOT NULL REFERENCES utilizadores(id) ON DELETE CASCADE,
    token_hash    TEXT NOT NULL UNIQUE,
    expira_em     TEXT NOT NULL,
    criado_em     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tokens_verificacao (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    utilizador_id INTEGER NOT NULL REFERENCES utilizadores(id) ON DELETE CASCADE,
    token_hash    TEXT NOT NULL UNIQUE,
    expira_em     TEXT NOT NULL,
    criado_em     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS historico_alteracoes (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo             TEXT NOT NULL CHECK (tipo IN (
                         'utilizador.criado', 'utilizador.email_verificado',
                         'utilizador.palavra_passe_alterada',
                         'perfil.criado', 'perfil.atualizado',
                         'programa.criado', 'programa.atualizado'
                     )),
    entidade         TEXT NOT NULL CHECK (entidade IN ('utilizador', 'perfil', 'programa')),
    entidade_id      INTEGER NOT NULL CHECK (entidade_id > 0),
    responsavel_id   INTEGER NOT NULL CHECK (responsavel_id > 0),
    responsavel_nome TEXT NOT NULL,
    responsavel_email TEXT NOT NULL,
    criado_em        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_historico_criado_em
    ON historico_alteracoes(criado_em DESC);
CREATE INDEX IF NOT EXISTS idx_historico_tipo_criado_em
    ON historico_alteracoes(tipo, criado_em DESC);
