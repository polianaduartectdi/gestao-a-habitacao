# Proposta de Tema

Projeto 1 - Unidade Curricular: Aplicações Informáticas

Data: 24 de setembro de 2026

Para: Professor Rui Humberto Pereira

## Grupo: Poliana Duarte, Débora Oliveira e Beatriz Pinto

## Tema Proposto:

Sistema de Organização e Apoio à Decisão sobre Programas de Apoio à Habitação

## 1. Descrição

Existem atualmente em Portugal vários programas de apoio à habitação em vigor em simultâneo (ex.: Porta 65 Jovem, Programa de Arrendamento Acessível, Garantia Pública para Compra de Habitação, 1.º Direito, Mais Habitação, Habitação a Custos Acessíveis, Alojamento Urgente e Temporário) cada um com critérios de elegibilidade, entidade responsável e forma de candidatura próprios, divulgados de forma dispersa. Não existe atualmente um local único onde um cidadão possa, com base no seu perfil, identificar a que apoios tem acesso.

A aplicação a desenvolver é um sistema web que organiza de forma estruturada a informação sobre os programas de apoio à habitação existentes e cruza essa informação com o perfil de cada cidadão, devolvendo uma recomendação personalizada dos apoios a que este é potencialmente elegível, e permitindo o acompanhamento do estado das candidaturas submetidas.

Para além do cruzamento automático com o perfil, o cidadão pode ainda consultar e pesquisar livremente todos os programas disponíveis. A aplicação tem dois tipos de utilizador: o cidadão, que regista o seu perfil, pesquisa programas e consulta recomendações, e o administrador, responsável por manter atualizada a informação sobre os programas e os respetivos critérios de elegibilidade, bem como pela gestão das contas de utilizador.

O desenvolvimento seguirá uma metodologia ágil (Scrum), organizada em três sprints, com apoio de Inteligência Artificial no processo de implementação (Vibe Coding). A linguagem de desenvolvimento (Python) será confirmada em função da arquitetura final da solução.

## 2. Requisitos

### 2.1 Requisitos Não Funcionais

Usabilidade - interface simples e acessível, com linguagem clara, adequada a cidadãos com diferentes níveis de literacia digital.

Segurança e Privacidade - conformidade com o RGPD no tratamento de dados pessoais, através de: consentimento explícito do cidadão no momento do registo; minimização dos dados recolhidos ao estritamente necessário para avaliar a elegibilidade; encriptação dos dados sensíveis em repouso e em trânsito; definição de um prazo de conservação dos dados, com eliminação ou anonimização automática após esse período; e autenticação e controlo de acesso à área de gestão.

Desempenho - o cruzamento entre o perfil do cidadão e os critérios dos programas deve devolver resultado em poucos segundos.

Disponibilidade - aplicação acessível através de um navegador web comum, sem necessidade de instalação.

Compatibilidade / Responsividade - interface adaptável a computador, tablet e telemóvel.

Manutenibilidade - atualização dos critérios dos programas pelo administrador sem necessidade de alterações ao código-fonte.

### 2.2 Requisitos Funcionais

#### Registo e Gestão do Perfil do Cidadão

**Descrição**

Permite ao cidadão criar, consultar e atualizar o seu perfil, com os dados necessários à avaliação de elegibilidade: idade, rendimento, composição do agregado familiar, situação habitacional e região.

**User Story**

Como cidadão, quero registar o meu perfil, para que o sistema possa identificar os apoios à habitação a que tenho direito.

**Definition of Done (DoD) e Testes**

- O perfil pode ser criado, editado e eliminado pelo cidadão.
- Os dados obrigatórios são validados antes de guardar (ex.: idade numérica, rendimento ≥ 0).
- Os dados são armazenados de forma segura, cumprindo os requisitos de segurança e privacidade definidos.
- Testes unitários às regras de validação de campos.
- Teste de integração à criação/atualização do perfil na base de dados.
- Teste manual de usabilidade do formulário com um utilizador não técnico.

**Casos de Uso**

**Ator:** Cidadão

**Pré-condições:** O cidadão tem acesso à aplicação.

**Fluxo Principal:**

- O cidadão acede ao formulário de perfil.
- Preenche idade, rendimento, composição do agregado, situação habitacional e região.
- Submete o formulário.
- O sistema valida os dados.
- O sistema guarda o perfil.

**Fluxo Alternativo:**

- Se os dados forem inválidos, o sistema apresenta uma mensagem de erro e solicita a correção dos campos assinalados.

**Pós-condições:** O perfil fica guardado e disponível para ser cruzado com os critérios dos programas de apoio.

**BPMN**

Cidadão: preenche/atualiza o perfil. Sistema: valida os dados, cruza com os critérios dos programas e gera a lista de recomendações.

#### Consulta, Pesquisa e Filtragem de Programas

**Descrição**

Permite ao cidadão consultar a lista completa de programas de apoio à habitação disponíveis, pesquisar por palavra-chave e aplicar filtros (ex.: tipo de apoio, entidade responsável, região), independentemente do perfil registado, e consultar os detalhes e critérios de cada programa.

**User Story**

Como cidadão, quero pesquisar e filtrar os programas de apoio disponíveis, para que possa explorar todas as opções existentes mesmo antes de preencher o meu perfil.

**Definition of Done (DoD) e Testes**

- O cidadão consegue listar todos os programas ativos.
- O cidadão consegue pesquisar por palavra-chave e aplicar pelo menos um filtro (ex.: região, tipo de apoio).
- O cidadão consegue consultar a página de detalhe de cada programa, com os respetivos critérios.
- Teste unitário à lógica de pesquisa e filtragem (ex.: o filtro devolve apenas os programas correspondentes).
- Teste de integração à listagem de programas a partir da base de dados.
- Teste manual de usabilidade da pesquisa e dos filtros.

**Casos de Uso**

**Ator:** Cidadão

**Pré-condições:** O cidadão tem acesso à aplicação (não necessita de ter o perfil preenchido).

**Fluxo Principal:**

- O cidadão acede à lista de programas.
- Introduz uma palavra-chave ou seleciona filtros.
- O sistema devolve os programas correspondentes.
- O cidadão seleciona um programa para consultar os detalhes e critérios.

**Fluxo Alternativo:**

- Se nenhum programa corresponder à pesquisa, o sistema informa o cidadão e sugere ajustar os filtros.

**Pós-condições:** O cidadão fica a conhecer os programas existentes e os respetivos critérios, independentemente do cruzamento automático com o perfil.

**BPMN**

Cidadão: pesquisa/filtra os programas. Sistema: devolve a lista filtrada. Se houver resultados, o cidadão consulta os detalhes do programa; se não houver, ajusta a pesquisa e tenta novamente.

#### Cruzamento e Recomendação de Programas

**Descrição**

Cruza automaticamente o perfil do cidadão com os critérios de elegibilidade de todos os programas ativos e devolve a lista dos programas a que o cidadão é potencialmente elegível.

**User Story**

Como cidadão, quero receber uma lista dos programas de apoio a que sou elegível com base no meu perfil, para que não tenha de pesquisar manualmente em várias fontes dispersas.

**Definition of Done (DoD) e Testes**

- Dado um perfil e um conjunto de programas, o sistema devolve todos os programas cujos critérios são cumpridos e nenhum programa cujos critérios não sejam cumpridos.
- Cada recomendação inclui a indicação de como e onde formalizar a candidatura.
- Testes unitários ao motor de correspondência, incluindo casos-limite (ex.: perfil no limite exato de idade ou rendimento).
- Teste de integração ponta a ponta (perfil → resultado apresentado).
- Teste de regressão ao adicionar um novo programa, confirmando que não quebra recomendações existentes.

**Casos de Uso**

**Ator:** Cidadão

**Pré-condições:** O cidadão já preencheu o seu perfil.

**Fluxo Principal:**

- O cidadão solicita as recomendações.
- O sistema cruza o perfil com os critérios de todos os programas ativos.
- O sistema apresenta a lista de programas elegíveis, com indicação de como formalizar cada candidatura.

**Fluxo Alternativo:**

- Se não existirem programas elegíveis, o sistema informa o cidadão e sugere rever os dados do perfil.

**Pós-condições:** O cidadão fica a conhecer os apoios a que pode aceder.

**BPMN**

Cidadão: consulta as recomendações e decide se quer candidatar-se. Se sim, regista a candidatura e passa a acompanhar o seu estado; se não, o processo termina.

#### Gestão dos Programas de Apoio à Habitação

**Descrição**

Permite ao administrador registar, editar e remover programas de apoio à habitação e os respetivos critérios de elegibilidade, mantendo a informação utilizada pelo motor de recomendação sempre atualizada.

**User Story**

Como administrador, quero registar e manter atualizados os programas de apoio e os seus critérios de elegibilidade, para que as recomendações apresentadas aos cidadãos estejam sempre corretas.

**Definition of Done (DoD) e Testes**

- O administrador consegue criar, editar e remover programas e respetivos critérios.
- As alterações são refletidas imediatamente nas recomendações e na pesquisa seguintes.
- Apenas utilizadores autenticados com permissões de administração acedem a esta área.
- Testes unitários às regras de validação dos critérios de cada programa.
- Teste de integração ao CRUD de programas.
- Teste manual que confirma que uma alteração a um critério afeta corretamente as recomendações seguintes.

**Casos de Uso**

**Ator:** Administrador

**Pré-condições:** O administrador está autenticado com permissões de administração.

**Fluxo Principal:**

- O administrador acede à área de gestão de programas.
- Cria um novo programa ou seleciona um programa existente.
- Define ou edita os critérios de elegibilidade.
- Guarda as alterações.

**Fluxo Alternativo:**

- O administrador remove um programa descontinuado, que deixa de ser considerado nas recomendações e na pesquisa futuras.

**Pós-condições:** A lista de programas e critérios fica atualizada e disponível para o motor de recomendação e para a pesquisa.

**BPMN**

Administrador: acede à gestão de programas e decide se cria/edita critérios ou remove um programa descontinuado. Sistema: valida e guarda as alterações e atualiza o motor de recomendação.

#### Gestão de Utilizadores

**Descrição**

Permite ao administrador consultar, criar, editar e remover contas de utilizador, incluindo a atribuição de permissões de acesso (cidadão ou administrador).

**User Story**

Como administrador, quero gerir as contas de utilizador da aplicação, para que o acesso à área de gestão seja controlado e os dados dos cidadãos sejam mantidos corretamente.

**Definition of Done (DoD) e Testes**

- O administrador consegue listar, criar, editar e remover/desativar utilizadores.
- As permissões de acesso são atribuídas corretamente a cada conta.
- Ações de gestão de utilizadores ficam registadas para efeitos de auditoria.
- Teste unitário às regras de atribuição de permissões.
- Teste de integração ao CRUD de utilizadores.
- Teste manual de tentativa de acesso à área de gestão por um utilizador sem permissões, que deve ser bloqueado.

**Casos de Uso**

**Ator:** Administrador

**Pré-condições:** O administrador está autenticado com permissões de administração.

**Fluxo Principal:**

- O administrador acede à área de gestão de utilizadores.
- Consulta a lista de utilizadores.
- Cria, edita ou remove um utilizador e define as suas permissões.
- Guarda as alterações.

**Fluxo Alternativo:**

- O administrador desativa, em vez de remover, uma conta, mantendo o histórico associado.

**Pós-condições:** A lista de utilizadores e respetivas permissões fica atualizada.

**BPMN**

Administrador: acede à gestão de utilizadores e decide se cria/edita ou remove/desativa um utilizador. Sistema: valida e guarda as alterações.

#### Gestão de Consentimento e Direitos do Titular dos Dados (RGPD)

**Descrição**

Permite ao cidadão exercer os seus direitos enquanto titular dos dados pessoais, nos termos do RGPD: consultar os dados que o sistema tem sobre si, corrigir dados incorretos, solicitar a eliminação da conta e dos dados associados, exportar os seus dados num formato legível e retirar o consentimento dado previamente ao registo.

**User Story**

Como cidadão, quero controlar os meus dados pessoais dentro da aplicação, para que possa exercer os meus direitos de privacidade sem depender de pedidos manuais ao administrador.

**Definition of Done (DoD) e Testes**

- O cidadão consegue consultar, num único local, todos os dados pessoais que a aplicação guarda sobre si.
- O cidadão consegue corrigir os seus dados diretamente ou solicitar a respetiva correção.
- O cidadão consegue solicitar a eliminação da conta e dos dados associados, com confirmação explícita antes de a ação ser executada.
- O cidadão consegue exportar os seus dados num formato estruturado e legível (ex.: PDF ou JSON).
- O consentimento dado no registo fica registado com data e finalidade, e pode ser retirado pelo cidadão a qualquer momento.
- Teste de integração ao processo de eliminação de conta, confirmando que os dados deixam de estar acessíveis.
- Teste manual do fluxo de consulta e retirada de consentimento por um utilizador não técnico.

**Casos de Uso**

**Ator:** Cidadão

**Pré-condições:** O cidadão está autenticado na aplicação.

**Fluxo Principal:**

- O cidadão acede à área “Os Meus Dados e Privacidade”.
- Consulta os dados pessoais e o histórico de consentimento associados à sua conta.
- Solicita a correção de um dado, a exportação dos dados ou a eliminação da conta.
- O sistema confirma a ação com o cidadão antes de a executar.
- O sistema regista o pedido e executa a ação solicitada.

**Fluxo Alternativo:**

- Se o cidadão pedir a eliminação da conta, o sistema solicita uma confirmação explícita adicional antes de apagar de forma irreversível os dados.

**Pós-condições:** Os dados do cidadão ficam atualizados, exportados ou eliminados conforme o solicitado, e a ação fica registada para efeitos de auditoria.

**BPMN**

Cidadão: consulta os seus dados e escolhe corrigir, exportar ou eliminar a conta. Sistema: confirma a ação com o cidadão, executa o pedido e regista a alteração para efeitos de auditoria.

#### Acompanhamento de Candidaturas

**Descrição**

Permite ao cidadão registar que submeteu candidatura a um programa recomendado e acompanhar a evolução do respetivo estado.

**User Story**

Como cidadão, quero registar e acompanhar o estado das candidaturas que submeti, para que saiba em que ponto está cada pedido.

**Definition of Done (DoD) e Testes**

- O cidadão consegue marcar uma candidatura como submetida e consultar o seu histórico de estados.
- Os estados possíveis (ex.: Submetida, Em Análise, Aprovada, Rejeitada) estão bem definidos e as transições são válidas.
- Testes unitários às transições de estado válidas e inválidas.
- Teste de integração à persistência do estado da candidatura.
- Teste manual ao fluxo completo de acompanhamento, do registo à atualização final.

**Casos de Uso**

**Ator:** Cidadão

**Pré-condições:** O cidadão recebeu a recomendação de pelo menos um programa.

**Fluxo Principal:**

- O cidadão regista que submeteu candidatura a um programa.
- O sistema cria um registo de acompanhamento com o estado inicial "Submetida".
- O cidadão atualiza o estado conforme a evolução (ex.: "Em Análise", "Aprovada", "Rejeitada").
- O sistema mantém o histórico de estados.

**Fluxo Alternativo:**

- O cidadão cancela o acompanhamento de uma candidatura que já não pretende seguir.

**Pós-condições:** O cidadão tem uma visão atualizada do estado de todas as suas candidaturas.

**BPMN**

Cidadão: regista a candidatura submetida a um programa e vai atualizando o estado (Submetida → Em Análise → Aprovada/Rejeitada) até ao fim do processo.

## 3. Product Backlog

O backlog organiza os requisitos funcionais já definidos como itens de trabalho (user stories), com prioridade, estimativa relativa (story points) e distribuição pelos três sprints da metodologia Scrum adotada no projeto.

| ID | Requisito Funcional / User Story | Prioridade | Pontos | Sprint |
|---|---|---|---|---|
| US01 | Gestão dos Programas de Apoio à Habitação — Como administrador, quero registar e manter atualizados os programas de apoio e os seus critérios de elegibilidade, para que as recomendações apresentadas aos cidadãos estejam sempre corretas. | Alta | 8 | Sprint 1 |
| US02 | Registo e Gestão do Perfil do Cidadão — Como cidadão, quero registar o meu perfil, para que o sistema possa identificar os apoios à habitação a que tenho direito. | Alta | 5 | Sprint 1 |
| US03 | Gestão de Utilizadores — Como administrador, quero gerir as contas de utilizador da aplicação, para que o acesso à área de gestão seja controlado e os dados dos cidadãos sejam mantidos corretamente. | Média | 5 | Sprint 1 |
| US04 | Consulta, Pesquisa e Filtragem de Programas — Como cidadão, quero pesquisar e filtrar os programas de apoio disponíveis, para que possa explorar todas as opções existentes mesmo antes de preencher o meu perfil. | Alta | 5 | Sprint 2 |
| US05 | Cruzamento e Recomendação de Programas — Como cidadão, quero receber uma lista dos programas de apoio a que sou elegível com base no meu perfil, para que não tenha de pesquisar manualmente em várias fontes dispersas. | Alta | 8 | Sprint 2 |
| US06 | Gestão de Consentimento e Direitos do Titular dos Dados (RGPD) — Como cidadão, quero controlar os meus dados pessoais dentro da aplicação, para que possa exercer os meus direitos de privacidade sem depender de pedidos manuais ao administrador. | Média | 5 | Sprint 2 |
| US07 | Acompanhamento de Candidaturas — Como cidadão, quero registar e acompanhar o estado das candidaturas que submeti, para que saiba em que ponto está cada pedido. | Média | 3 | Sprint 3 |

Estimativa total: 39 pontos. A ordem dos sprints segue as dependências entre funcionalidades: primeiro a base de dados de programas, perfis e contas (Sprint 1), depois a pesquisa e o motor de recomendação, incluindo os direitos do titular dos dados (Sprint 2), e por fim o acompanhamento de candidaturas e os ajustes finais (Sprint 3).

## Próximos Passos

Aguardamos a aprovação do tema e da composição do grupo. Este documento serve de base ao levantamento de requisitos, casos de uso, diagramas BPMN e backlog a entregar na 1.ª fase do Projeto 1 (8 de outubro).

