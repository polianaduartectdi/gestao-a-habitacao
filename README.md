# Apoio à Habitação

Site com registo, login (cliente e administrador), programas de apoio e
verificação de email, recuperação de palavra-passe, em Python (Flask) + SQLite.

## Como correr

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate
# Mac/Linux: source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env       # (Windows: copy .env.example .env) e preencher
python criar_admin.py      # cria o administrador (pede email e palavra-passe)
python app.py              # abre http://127.0.0.1:5000
```

A base de dados (`apoio_habitacao.db`) é criada automaticamente ao arrancar.

## Configurar o envio de email (Gmail)

1. Na conta Google, ativa a **verificação em dois passos**.
2. Vai a https://myaccount.google.com/apppasswords e cria uma
   **palavra-passe de aplicação** (16 letras).
3. No `.env`, preenche `SMTP_USER` (o teu Gmail) e `SMTP_PASSWORD` (a palavra-passe de aplicação).
4. Reinicia o `python app.py`.

Qualquer outro fornecedor SMTP serve: basta mudar `SMTP_HOST`, `SMTP_PORT`
e `SMTP_SECURITY` (`starttls`, `ssl` ou `none`).

Se `SMTP_HOST` não estiver definido, o email é escrito no terminal em vez de
enviado (útil para testar).

## Estrutura

| Ficheiro | Função |
|---|---|
| `app.py` | rotas, sessões, ligação à BD, envio de email |
| `schema.sql` | tabelas: utilizadores, programas, perfis habitacionais e tokens de recuperação/verificação |
| `programas_iniciais.sql` | catálogo inicial de programas e critérios transcritos da lista fornecida |
| `criar_admin.py` | cria uma conta de administrador |
| `.env` | configurações e segredos (não partilhar) |
| `templates/` | páginas HTML (Jinja) |
| `static/` | CSS, JS e logótipo |

## Rotas

- `/` programas · `/registar` · `/login` · `/logout` (POST)
- `/verificar/<token>` confirmar email · `/reenviar-verificacao` pedir novo link de confirmação
- `/recuperar` pedir link · `/redefinir/<token>` definir nova palavra-passe
- `/simulador` consulta automática de programas compatíveis com o perfil guardado, apenas para clientes autenticados
- `/programas/<id>` página pública com descrição, critérios e link oficial de cada programa
- `/cliente` perfil editável e área pessoal, só para utilizadores autenticados
- `/admin` e `/admin/programas/novo` só para administradores; critérios de programas em `/admin/programas/<id>/editar`

Os programas só aparecem nos resultados do simulador depois de a administração
assinalar os critérios como revistos. A aplicação inicializa o catálogo a partir
de `programas_iniciais.sql`, sem duplicar programas já existentes. Os requisitos
sem valores suficientes para uma comparação automática ficam desativados até
serem confirmados e completados pela administração.

O perfil de cliente guarda localização (região, concelho e freguesia), situação
habitacional, rendimentos mensal e anual, idade, contrato, agregado, necessidades
habitacionais, tipologia, imóvel e prestações sociais. O simulador compara os
dados relevantes para cada programa. Se faltarem respostas opcionais necessárias
para confirmar um critério, o programa pode aparecer como potencialmente compatível
com a indicação dos dados em falta; respostas preenchidas que contrariem os
critérios excluem o programa. Os dados do perfil podem ser consultados e alterados
pelo próprio cliente autenticado. Os resultados são indicativos e não confirmam a
elegibilidade oficial.

Cada programa tem uma página própria. Na administração, edite o programa e
preencha o campo «Link oficial para informações ou candidatura» com o endereço
da entidade responsável. Os links oficiais fornecidos para o catálogo inicial
são aplicados automaticamente a cada arranque, incluindo às bases de dados
existentes.
