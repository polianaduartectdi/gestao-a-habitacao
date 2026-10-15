INSERT INTO programas (nome, entidade, descricao, criterios_json, criterios_configurados)
SELECT
    'Porta 65-Jovem',
    'IHRU',
    'Apoio ao arrendamento jovem, de âmbito nacional. Segundo os critérios fornecidos, destina-se a candidatos entre os 18 e os 35 anos; numa candidatura em casal, um dos membros pode ter 36 anos. Não se aplica ao arrendamento de quartos. Confirme as condições em vigor junto do IHRU.',
    '{"situacoes":["arrendamento"],"idade_min":18,"idade_max":35,"casal_aceita_36":true,"apoios":["arrendamento"]}',
    1
WHERE NOT EXISTS (SELECT 1 FROM programas WHERE nome = 'Porta 65-Jovem');

INSERT INTO programas (nome, entidade, descricao, criterios_json, criterios_configurados)
SELECT
    'Apoio Extraordinário à Renda',
    'Estado Português',
    'Apoio à renda da habitação permanente. Os critérios fornecidos indicam contrato de arrendamento ou subarrendamento celebrado até 15 de março de 2023 e rendimento anual do agregado até 43.090 €. O apoio indicado é até 200 €/mês nas condições antigas e limitado a dois terços da renda. Confirme a vigência e os valores atuais junto da entidade responsável.',
    '{"situacoes":["arrendamento","arrendamento_quarto"],"apoios":["arrendamento"],"rendimento_anual_max":43090,"data_contrato_ate":"2023-03-15","habitacao_permanente":true}',
    1
WHERE NOT EXISTS (SELECT 1 FROM programas WHERE nome = 'Apoio Extraordinário à Renda');

INSERT INTO programas (nome, entidade, descricao, criterios_json, criterios_configurados)
SELECT
    '1.º Direito',
    'IHRU e municípios',
    'Programa de âmbito nacional, executado pelos municípios, para pessoas ou agregados em situação de carência financeira e a viver em condições habitacionais indignas. Inclui cidadãos estrangeiros com residência legal. A avaliação final é feita pelo município.',
    '{"condicoes_indignas":true,"carencia_financeira":true,"residencia_legal":true}',
    1
WHERE NOT EXISTS (SELECT 1 FROM programas WHERE nome = '1.º Direito');

INSERT INTO programas (nome, entidade, descricao, criterios_json, criterios_configurados)
SELECT
    'PRAHABITAR – Arrendamento',
    'Região Autónoma da Madeira',
    'Apoio ao arrendamento na Região Autónoma da Madeira para quem não possui propriedade imobiliária na Região. Os dados fornecidos indicam rendimento anual bruto corrigido entre o RSI e 70 vezes o IAS e renda máxima mensal de 850 € (1 pessoa), 950 € (2), 1.100 € (3) e 1.250 € (4 ou mais). Os valores exatos de rendimento não foram indicados; a correspondência automática fica suspensa até serem confirmados.',
    '{"regioes":["madeira"],"situacoes":["arrendamento"],"propriedade_regiao":"nao","apoios":["arrendamento"],"encargo_max_por_pessoas":{"1":850,"2":950,"3":1100,"4":1250},"requer_confirmacao_limites_rendimento":true}',
    0
WHERE NOT EXISTS (SELECT 1 FROM programas WHERE nome = 'PRAHABITAR – Arrendamento');

INSERT INTO programas (nome, entidade, descricao, criterios_json, criterios_configurados)
SELECT
    'PRAHABITAR – Aquisição',
    'Região Autónoma da Madeira',
    'Apoio à aquisição de habitação própria e permanente na Região Autónoma da Madeira. Os dados fornecidos indicam preços máximos de 180.000 € (T0), 250.000 € (T1), 300.000 € (T2) e 350.000 € (T3 ou superior), com apoio de 10% do preço até 15.000 €, podendo chegar a 20.000 €. Confirme os limites atuais junto da entidade responsável.',
    '{"regioes":["madeira"],"apoios":["aquisicao"],"habitacao_permanente":true,"preco_imovel_max_por_tipologia":{"T0":180000,"T1":250000,"T2":300000,"T3":350000,"T4":350000}}',
    1
WHERE NOT EXISTS (SELECT 1 FROM programas WHERE nome = 'PRAHABITAR – Aquisição');

INSERT INTO programas (nome, entidade, descricao, criterios_json, criterios_configurados)
SELECT
    'REEQUILIBRAR',
    'Região Autónoma da Madeira',
    'Apoio a agregados com crédito à habitação própria e permanente na Região Autónoma da Madeira. Os critérios fornecidos indicam necessidade de comprovar negociação com o banco nos seis meses anteriores e comparticipação máxima de 200 €/mês, a fundo perdido. Confirme as condições em vigor junto da entidade responsável.',
    '{"regioes":["madeira"],"situacoes":["credito"],"apoios":["credito"],"habitacao_permanente":true,"negociacao_banco_recente":true}',
    1
WHERE NOT EXISTS (SELECT 1 FROM programas WHERE nome = 'REEQUILIBRAR');

INSERT INTO programas (nome, entidade, descricao, criterios_json, criterios_configurados)
SELECT
    'Arrendamento com Opção de Compra (Santa Clara)',
    'Região Autónoma dos Açores — Ponta Delgada',
    'Programa localizado na freguesia de Santa Clara, concelho de Ponta Delgada, para arrendamento com opção de compra de habitação própria e permanente. Os dados fornecidos indicam 18 unidades T3 e 4 unidades T4. A disponibilidade deve ser confirmada junto da entidade responsável.',
    '{"regioes":["acores"],"concelhos":["Ponta Delgada"],"freguesias":["Santa Clara"],"apoios":["arrendamento_opcao_compra"],"tipologias":["T3","T4"],"habitacao_permanente":true}',
    1
WHERE NOT EXISTS (SELECT 1 FROM programas WHERE nome = 'Arrendamento com Opção de Compra (Santa Clara)');

INSERT INTO programas (nome, entidade, descricao, criterios_json, criterios_configurados)
SELECT
    'Arrendamento com Opção de Compra (São Brás)',
    'Região Autónoma dos Açores — Praia da Vitória',
    'Programa localizado na freguesia de São Brás, concelho de Praia da Vitória, para arrendamento com opção de compra. Os dados fornecidos indicam 8 unidades T2, 4 unidades T3 e 1 unidade T4. A disponibilidade deve ser confirmada junto da entidade responsável.',
    '{"regioes":["acores"],"concelhos":["Praia da Vitória"],"freguesias":["São Brás"],"apoios":["arrendamento_opcao_compra"],"tipologias":["T2","T3","T4"]}',
    1
WHERE NOT EXISTS (SELECT 1 FROM programas WHERE nome = 'Arrendamento com Opção de Compra (São Brás)');

INSERT INTO programas (nome, entidade, descricao, criterios_json, criterios_configurados)
SELECT
    'Apoio à Autoconstrução',
    'Região Autónoma dos Açores',
    'Apoio à construção de habitação própria e permanente em lote privado ou cedido pela Região. Os dados fornecidos indicam apoio máximo de 75.000 €, definido em função da composição e rendimento do agregado e da tipologia do imóvel. Confirme os limites e requisitos atuais junto da entidade responsável.',
    '{"regioes":["acores"],"apoios":["construcao"],"habitacao_permanente":true,"lote_disponivel":true}',
    1
WHERE NOT EXISTS (SELECT 1 FROM programas WHERE nome = 'Apoio à Autoconstrução');

INSERT INTO programas (nome, entidade, descricao, criterios_json, criterios_configurados)
SELECT
    'Apoio à Aquisição de Projetos',
    'Região Autónoma dos Açores',
    'Apoio à aquisição de projetos para construção de habitação própria e permanente. Os dados fornecidos indicam apoio a fundo perdido até 5.000 €, cumulável com o apoio à autoconstrução. Confirme os requisitos atuais junto da entidade responsável.',
    '{"regioes":["acores"],"apoios":["construcao"],"habitacao_permanente":true,"projeto_construcao":true}',
    1
WHERE NOT EXISTS (SELECT 1 FROM programas WHERE nome = 'Apoio à Aquisição de Projetos');

UPDATE programas
SET url_candidatura = 'https://portal.azores.gov.pt/web/drh/aquisi%C3%A7%C3%A3o-de-habita%C3%A7%C3%A3o-pr%C3%B3pria'
WHERE nome = 'Apoio à Aquisição de Projetos'
  AND (url_candidatura IS NULL OR url_candidatura = '');

UPDATE programas
SET url_candidatura = 'https://www.portaldahabitacao.pt/porta-65-jovem'
WHERE nome = 'Porta 65-Jovem'
  AND (url_candidatura IS NULL OR url_candidatura = '');

UPDATE programas
SET url_candidatura = 'https://www.portaldahabitacao.pt/web/guest/apextrrendalandingpage1'
WHERE nome = 'Apoio Extraordinário à Renda'
  AND (url_candidatura IS NULL OR url_candidatura = '');

UPDATE programas
SET url_candidatura = 'https://www.ihm.pt/pt/prahabitar-programa-de-apoio-a-aquisicao-e-ao-arrendamento-de-habitacao'
WHERE nome IN ('PRAHABITAR – Arrendamento', 'PRAHABITAR – Aquisição')
  AND (url_candidatura IS NULL OR url_candidatura = '');

UPDATE programas
SET url_candidatura = 'https://www.ihm.pt/pt/os-nossos-apoios/reequilibrar-programa-de-apoio-as-familias-com-credito-a-habitacao'
WHERE nome = 'REEQUILIBRAR'
  AND (url_candidatura IS NULL OR url_candidatura = '');

UPDATE programas
SET url_candidatura = 'https://portal.azores.gov.pt/web/drh/concursos-habitacao-arrendamento-opcao-compra'
WHERE nome IN (
    'Arrendamento com Opção de Compra (Santa Clara)',
    'Arrendamento com Opção de Compra (São Brás)'
)
  AND (url_candidatura IS NULL OR url_candidatura = '');

UPDATE programas
SET url_candidatura = 'https://portal.azores.gov.pt/web/drh/constru%C3%A7%C3%A3o-amplia%C3%A7%C3%A3o-de-habita%C3%A7%C3%A3o-pr%C3%B3pria'
WHERE nome = 'Apoio à Autoconstrução'
  AND (url_candidatura IS NULL OR url_candidatura = '');

UPDATE programas
SET url_candidatura = 'https://portovivosru.pt/areas-atuacao/1o-direito'
WHERE nome = '1.º Direito'
  AND (url_candidatura IS NULL OR url_candidatura = '');
