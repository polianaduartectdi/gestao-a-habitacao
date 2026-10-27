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
| `schema.sql` | tabelas: utilizadores, programas, perfis, tokens, candidaturas, histórico de estados, consultas agregadas e avaliações |
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
- `/agregado/membros/novo` e `/agregado/membros/<id>/editar` gerir os restantes membros do agregado
- `/candidaturas` (POST) registar uma candidatura submetida; estado e histórico na área `/cliente`
- `/admin` só para administradores, com indicadores agregados, gestão de contas de clientes e programas
- `/admin/utilizadores/<id>/editar`, `/estado` e `/eliminar` editar, ativar/desativar ou eliminar contas de clientes
- `/admin/relatorio.csv` descarregar indicadores agregados com filtros por período
- `/admin/historico` consultar eventos administrativos, filtrados por data e tipo
- `/admin/programas/novo` e `/admin/programas/<id>/editar` gerir programas e critérios
- `/admin/programas/importar` importar programas em CSV; `/admin/programas/modelo-csv` descarregar o modelo
- `/programas/<id>/feedback` (POST) guardar ou atualizar uma avaliação de cidadão autenticado

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

Na área pessoal, cada cidadão pode registar os restantes membros do agregado,
com relação, idade e rendimento mensal próprio opcional. O total de pessoas no
perfil não fica abaixo do número de membros registados mais o candidato; a
existência de crianças e a idade do cônjuge/parceiro são atualizadas a partir
dos membros registados. O rendimento total do agregado continua a ser indicado
no perfil e não é calculado automaticamente a partir dos rendimentos individuais.

Cada programa tem uma página própria. Na administração, edite o programa e
preencha o campo «Link oficial para informações ou candidatura» com o endereço
da entidade responsável. Os links oficiais fornecidos para o catálogo inicial
são aplicados automaticamente a cada arranque, incluindo às bases de dados
existentes.

Os cidadãos podem registar na área pessoal uma candidatura que já submeteram
oficialmente à entidade responsável (a aplicação não submete candidaturas em
nome do cidadão) e acompanhar os estados «Submetida», «Em análise», «Aprovada»,
«Rejeitada» ou «Cancelada». As transições são limitadas: «Submetida» pode passar
a «Em análise», «Aprovada», «Rejeitada» ou «Cancelada»; «Em análise» pode passar
a «Aprovada», «Rejeitada» ou «Cancelada». Os estados finais não podem ser
alterados.

Na página de cada programa, os cidadãos autenticados podem avaliar a qualidade
da informação e consultar as avaliações publicadas, sem exposição do nome do
autor. A administração vê apenas indicadores agregados, incluindo programas
mais consultados, contagens de perfis e candidaturas, sem atividade individual.

Os administradores podem editar os dados de conta dos clientes, desativar ou
reativar o acesso e eliminar contas. A eliminação remove também os dados pessoais
associados. O histórico administrativo regista ações e responsáveis, mas não
copia palavras-passe nem valores pessoais alterados. O relatório CSV contém
contagens agregadas, estados de candidaturas e programas mais consultados, com
filtros de data; não inclui nomes ou emails de cidadãos.

Para importar programas, use o modelo CSV disponibilizado na administração.
O ficheiro deve ser UTF-8, ter as colunas `nome`, `entidade` e `descricao`, e
pode incluir `url_candidatura`. São aceites até 100 linhas e 2 MB; o lote é
rejeitado integralmente se alguma linha tiver erros. Os programas importados
ficam com critérios por rever e devem ser editados antes de ativar a
correspondência automática.
