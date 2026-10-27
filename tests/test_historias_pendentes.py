import io
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import app as aplicacao


class HistoriasPendentesTests(unittest.TestCase):
    def setUp(self):
        self.diretorio = tempfile.TemporaryDirectory()
        self.db_original = aplicacao.DB_PATH
        aplicacao.DB_PATH = os.path.join(self.diretorio.name, "teste.db")
        aplicacao.app.config.update(TESTING=True)
        aplicacao.init_db()
        with sqlite3.connect(aplicacao.DB_PATH) as db:
            db.execute(
                "INSERT INTO utilizadores "
                "(id, nome, apelido, email, password_hash, papel) "
                "VALUES (1, 'Ana', 'Costa', 'ana@example.pt', 'x', 'cliente')"
            )
            db.execute(
                "INSERT INTO utilizadores "
                "(id, nome, apelido, email, password_hash, papel) "
                "VALUES (2, 'Admin', 'Teste', 'admin@example.pt', 'x', 'admin')"
            )
            cursor = db.execute(
                "INSERT INTO programas (nome, entidade, descricao) "
                "VALUES ('Apoio Teste', 'Entidade', 'Descrição')"
            )
            self.programa_id = cursor.lastrowid
        self.total_programas_inicial = self.ler_db(
            "SELECT COUNT(*) FROM programas"
        )[0][0]
        self.cliente = aplicacao.app.test_client()

    def tearDown(self):
        aplicacao.DB_PATH = self.db_original
        self.diretorio.cleanup()

    def autenticar(self, utilizador_id):
        with self.cliente.session_transaction() as sessao:
            sessao["user_id"] = utilizador_id
            sessao["_csrf"] = "token-teste"

    def ler_db(self, consulta, parametros=()):
        with sqlite3.connect(aplicacao.DB_PATH) as db:
            return db.execute(consulta, parametros).fetchall()

    def criar_perfil(self, utilizador_id=1, pessoas=1):
        with sqlite3.connect(aplicacao.DB_PATH) as db:
            db.execute(
                "INSERT INTO perfis_habitacionais "
                "(utilizador_id, concelho, situacao, rendimento, encargo, pessoas) "
                "VALUES (?, 'Lisboa', 'arrendamento', 1000, 400, ?)",
                (utilizador_id, pessoas),
            )

    def test_transicoes_de_estado_validas_e_invalidas(self):
        self.assertTrue(
            aplicacao.transicao_candidatura_valida("submetida", "em_analise")
        )
        self.assertTrue(
            aplicacao.transicao_candidatura_valida("em_analise", "aprovada")
        )
        self.assertTrue(
            aplicacao.transicao_candidatura_valida("submetida", "aprovada")
        )
        self.assertTrue(
            aplicacao.transicao_candidatura_valida("submetida", "rejeitada")
        )
        self.assertFalse(
            aplicacao.transicao_candidatura_valida("aprovada", "rejeitada")
        )

    def test_regista_candidatura_e_persiste_historico_dos_estados(self):
        self.autenticar(1)
        resposta = self.cliente.post(
            "/candidaturas",
            data={"_csrf": "token-teste", "programa_id": str(self.programa_id)},
        )
        self.assertEqual(302, resposta.status_code)
        candidatura_id = self.ler_db(
            "SELECT id FROM candidaturas WHERE utilizador_id = 1"
        )[0][0]
        self.assertEqual(
            [("submetida",)],
            self.ler_db(
                "SELECT estado FROM historico_candidaturas "
                "WHERE candidatura_id = ?",
                (candidatura_id,),
            ),
        )
        resposta = self.cliente.get("/cliente")
        self.assertIn(b'value="aprovada">Aprovada', resposta.data)
        self.assertIn(b'value="rejeitada">Rejeitada', resposta.data)

        resposta = self.cliente.post(
            f"/candidaturas/{candidatura_id}/estado",
            data={"_csrf": "token-teste", "estado": "em_analise"},
        )
        self.assertEqual(302, resposta.status_code)
        self.assertEqual(
            [("submetida",), ("em_analise",)],
            self.ler_db(
                "SELECT estado FROM historico_candidaturas "
                "WHERE candidatura_id = ? ORDER BY id",
                (candidatura_id,),
            ),
        )
        resposta = self.cliente.get("/cliente")
        self.assertEqual(200, resposta.status_code)
        self.assertIn(b'value="aprovada">Aprovada', resposta.data)
        self.assertIn(b'value="rejeitada">Rejeitada', resposta.data)
        self.assertIn(b'value="cancelada">Cancelada', resposta.data)

        resposta = self.cliente.post(
            f"/candidaturas/{candidatura_id}/estado",
            data={"_csrf": "token-teste", "estado": "aprovada"},
        )
        self.assertEqual(302, resposta.status_code)
        self.assertEqual(
            "aprovada",
            self.ler_db(
                "SELECT estado FROM candidaturas WHERE id = ?", (candidatura_id,)
            )[0][0],
        )
        resposta = self.cliente.get("/cliente")
        self.assertEqual(200, resposta.status_code)
        self.assertIn("Histórico de estados".encode(), resposta.data)

    def test_decisao_pode_ser_registada_sem_estado_intermedio(self):
        self.autenticar(1)
        self.cliente.post(
            "/candidaturas",
            data={"_csrf": "token-teste", "programa_id": str(self.programa_id)},
        )

        resposta = self.cliente.post(
            "/candidaturas/1/estado",
            data={"_csrf": "token-teste", "estado": "rejeitada"},
        )

        self.assertEqual(302, resposta.status_code)
        self.assertEqual(
            [("submetida",), ("rejeitada",)],
            self.ler_db(
                "SELECT estado FROM historico_candidaturas "
                "WHERE candidatura_id = 1 ORDER BY id"
            ),
        )

    def test_estado_invalido_nao_altera_candidatura(self):
        self.autenticar(1)
        self.cliente.post(
            "/candidaturas",
            data={"_csrf": "token-teste", "programa_id": str(self.programa_id)},
        )
        self.cliente.post(
            "/candidaturas/1/estado",
            data={"_csrf": "token-teste", "estado": "submetida"},
        )
        self.assertEqual(
            "submetida",
            self.ler_db("SELECT estado FROM candidaturas WHERE id = 1")[0][0],
        )
        self.assertEqual(
            [("submetida",)],
            self.ler_db("SELECT estado FROM historico_candidaturas WHERE candidatura_id = 1"),
        )

    def test_importacao_csv_validada_e_indicadores_de_consulta(self):
        self.autenticar(2)
        csv_ficheiro = io.BytesIO(
            "nome,entidade,descricao,url_candidatura\n"
            "Apoio CSV,Serviço,Descrição,https://example.pt/apoio\n".encode()
        )
        resposta = self.cliente.post(
            "/admin/programas/importar",
            data={"_csrf": "token-teste", "ficheiro_csv": (csv_ficheiro, "programas.csv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(302, resposta.status_code)
        self.assertEqual(
            self.total_programas_inicial + 1,
            self.ler_db("SELECT COUNT(*) FROM programas")[0][0],
        )
        self.assertEqual(
            0,
            self.ler_db(
                "SELECT criterios_configurados FROM programas WHERE nome = 'Apoio CSV'"
            )[0][0],
        )

        self.cliente.get(f"/programas/{self.programa_id}")
        resposta = self.cliente.get("/admin")
        self.assertEqual(200, resposta.status_code)
        self.assertIn(b"Programas mais consultados", resposta.data)
        self.assertEqual(1, self.ler_db("SELECT COUNT(*) FROM visualizacoes_programas")[0][0])

    def test_csv_com_url_invalido_nao_importa_lote(self):
        self.autenticar(2)
        csv_ficheiro = io.BytesIO(
            "nome,entidade,descricao,url_candidatura\n"
            "Apoio CSV,Serviço,Descrição,javascript:alert(1)\n".encode()
        )
        self.cliente.post(
            "/admin/programas/importar",
            data={"_csrf": "token-teste", "ficheiro_csv": (csv_ficheiro, "programas.csv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(
            self.total_programas_inicial,
            self.ler_db("SELECT COUNT(*) FROM programas")[0][0],
        )

    def test_avaliacao_de_programa_fica_guardada_e_visivel(self):
        self.autenticar(1)
        resposta = self.cliente.post(
            f"/programas/{self.programa_id}/feedback",
            data={
                "_csrf": "token-teste",
                "avaliacao": "5",
                "comentario": "Informação clara.",
            },
        )
        self.assertEqual(302, resposta.status_code)
        resposta = self.cliente.get(f"/programas/{self.programa_id}")
        self.assertEqual(200, resposta.status_code)
        self.assertIn("Informação clara.".encode(), resposta.data)
        self.assertIn(b"5.0 / 5", resposta.data)

    def test_cliente_gera_membros_do_agregado_e_sincroniza_total(self):
        self.autenticar(1)
        self.criar_perfil()

        resposta = self.cliente.post(
            "/agregado/membros/novo",
            data={
                "_csrf": "token-teste",
                "nome": "Joana Costa",
                "relacao": "filho",
                "idade": "8",
                "rendimento_mensal": "",
            },
        )

        self.assertEqual(302, resposta.status_code)
        membro_id = self.ler_db(
            "SELECT id FROM membros_agregado WHERE utilizador_id = 1"
        )[0][0]
        self.assertEqual(
            2,
            self.ler_db(
                "SELECT pessoas FROM perfis_habitacionais WHERE utilizador_id = 1"
            )[0][0],
        )
        resposta = self.cliente.get("/cliente")
        self.assertIn("Joana Costa".encode(), resposta.data)
        self.assertIn("Filho/a".encode(), resposta.data)
        self.assertEqual(
            200,
            self.cliente.get(
                f"/agregado/membros/{membro_id}/editar"
            ).status_code,
        )

        resposta = self.cliente.post(
            f"/agregado/membros/{membro_id}/editar",
            data={
                "_csrf": "token-teste",
                "nome": "Joana Costa",
                "relacao": "filho",
                "idade": "9",
                "rendimento_mensal": "50",
            },
        )
        self.assertEqual(302, resposta.status_code)
        self.assertEqual(
            (9, 50),
            self.ler_db(
                "SELECT idade, rendimento_mensal FROM membros_agregado WHERE id = ?",
                (membro_id,),
            )[0],
        )
        self.assertEqual(
            (2, 1, None),
            self.ler_db(
                "SELECT pessoas, criancas, idade_parceiro "
                "FROM perfis_habitacionais WHERE utilizador_id = 1"
            )[0],
        )

        self.cliente.post(
            "/agregado/membros/novo",
            data={
                "_csrf": "token-teste",
                "nome": "Paulo Costa",
                "relacao": "conjuge",
                "idade": "45",
                "rendimento_mensal": "1200",
            },
        )
        parceiro_id = self.ler_db(
            "SELECT id FROM membros_agregado WHERE relacao = 'conjuge'"
        )[0][0]
        self.assertEqual(
            (3, 1, 45),
            self.ler_db(
                "SELECT pessoas, criancas, idade_parceiro "
                "FROM perfis_habitacionais WHERE utilizador_id = 1"
            )[0],
        )
        self.cliente.post(
            f"/agregado/membros/{parceiro_id}/remover",
            data={"_csrf": "token-teste"},
        )
        self.assertEqual(
            (2, 1, None),
            self.ler_db(
                "SELECT pessoas, criancas, idade_parceiro "
                "FROM perfis_habitacionais WHERE utilizador_id = 1"
            )[0],
        )

        resposta = self.cliente.post(
            f"/agregado/membros/{membro_id}/remover",
            data={"_csrf": "token-teste"},
        )
        self.assertEqual(302, resposta.status_code)
        self.assertEqual([], self.ler_db("SELECT id FROM membros_agregado"))
        self.assertEqual(
            1,
            self.ler_db(
                "SELECT pessoas FROM perfis_habitacionais WHERE utilizador_id = 1"
            )[0][0],
        )
        self.assertEqual(
            (0, None),
            self.ler_db(
                "SELECT criancas, idade_parceiro FROM perfis_habitacionais "
                "WHERE utilizador_id = 1"
            )[0],
        )
        self.assertEqual(
            [
                ("membro.criado",),
                ("membro.atualizado",),
                ("membro.criado",),
                ("membro.eliminado",),
                ("membro.eliminado",),
            ],
            self.ler_db(
                "SELECT tipo FROM historico_alteracoes "
                "WHERE entidade = 'membro' ORDER BY id"
            ),
        )

    def test_membro_nao_pode_ser_alterado_por_outro_cliente(self):
        self.autenticar(1)
        self.criar_perfil()
        self.cliente.post(
            "/agregado/membros/novo",
            data={
                "_csrf": "token-teste",
                "nome": "Joana",
                "relacao": "filho",
                "idade": "8",
            },
        )
        with sqlite3.connect(aplicacao.DB_PATH) as db:
            db.execute(
                "INSERT INTO utilizadores "
                "(id, nome, apelido, email, password_hash, papel) "
                "VALUES (3, 'Rui', 'Silva', 'rui@example.pt', 'x', 'cliente')"
            )
        self.autenticar(3)

        resposta = self.cliente.post(
            "/agregado/membros/1/remover",
            data={"_csrf": "token-teste"},
        )

        self.assertEqual(404, resposta.status_code)
        self.assertEqual(1, self.ler_db("SELECT COUNT(*) FROM membros_agregado")[0][0])

    def test_admin_edita_desativa_e_elimina_conta_de_cliente(self):
        self.autenticar(2)
        self.criar_perfil()
        self.assertEqual(
            200,
            self.cliente.get("/admin/utilizadores/1/editar").status_code,
        )

        with patch.object(aplicacao, "enviar_verificacao") as enviar_verificacao:
            resposta = self.cliente.post(
                "/admin/utilizadores/1/editar",
                data={
                    "_csrf": "token-teste",
                    "nome": "Ana Maria",
                    "apelido": "Costa",
                    "email": "ana.maria@example.pt",
                },
            )
        enviar_verificacao.assert_called_once()
        self.assertEqual(302, resposta.status_code)
        self.assertEqual(
            ("Ana Maria", "ana.maria@example.pt", 0),
            self.ler_db(
                "SELECT nome, email, email_verificado FROM utilizadores WHERE id = 1"
            )[0],
        )

        self.autenticar(1)
        cliente_separado = aplicacao.app.test_client()
        with cliente_separado.session_transaction() as sessao:
            sessao["user_id"] = 1
            sessao["_csrf"] = "token-cliente"
        self.autenticar(2)
        resposta = self.cliente.post(
            "/admin/utilizadores/1/estado",
            data={"_csrf": "token-teste"},
        )
        self.assertEqual(302, resposta.status_code)
        self.assertEqual(0, self.ler_db("SELECT ativo FROM utilizadores WHERE id = 1")[0][0])
        self.assertEqual(302, cliente_separado.get("/cliente").status_code)

        resposta = self.cliente.post(
            "/admin/utilizadores/1/eliminar",
            data={"_csrf": "token-teste"},
        )
        self.assertEqual(302, resposta.status_code)
        self.assertEqual([], self.ler_db("SELECT id FROM utilizadores WHERE id = 1"))
        self.assertEqual(
            [],
            self.ler_db(
                "SELECT utilizador_id FROM perfis_habitacionais WHERE utilizador_id = 1"
            ),
        )
        self.assertEqual(
            [
                ("utilizador.atualizado",),
                ("utilizador.desativado",),
                ("utilizador.eliminado",),
            ],
            self.ler_db(
                "SELECT tipo FROM historico_alteracoes "
                "WHERE entidade_id = 1 ORDER BY id"
            ),
        )

    def test_admin_nao_pode_editar_ou_eliminar_outra_conta_admin(self):
        self.autenticar(2)

        resposta = self.cliente.get("/admin/utilizadores/2/editar")
        self.assertEqual(404, resposta.status_code)
        resposta = self.cliente.post(
            "/admin/utilizadores/2/eliminar",
            data={"_csrf": "token-teste"},
        )
        self.assertEqual(404, resposta.status_code)
        self.assertEqual(1, self.ler_db("SELECT COUNT(*) FROM utilizadores WHERE id = 2")[0][0])

    def test_admin_pode_reativar_conta_desativada(self):
        self.autenticar(2)
        self.cliente.post(
            "/admin/utilizadores/1/estado",
            data={"_csrf": "token-teste"},
        )
        resposta = self.cliente.post(
            "/admin/utilizadores/1/estado",
            data={"_csrf": "token-teste"},
        )

        self.assertEqual(302, resposta.status_code)
        self.assertEqual(1, self.ler_db("SELECT ativo FROM utilizadores WHERE id = 1")[0][0])
        self.assertEqual(
            [("utilizador.desativado",), ("utilizador.ativado",)],
            self.ler_db(
                "SELECT tipo FROM historico_alteracoes "
                "WHERE entidade_id = 1 ORDER BY id"
            ),
        )

    def test_historico_administrativo_e_relatorio_csv(self):
        self.autenticar(2)
        self.cliente.post(
            "/admin/utilizadores/1/editar",
            data={
                "_csrf": "token-teste",
                "nome": "Ana Nova",
                "apelido": "Costa",
                "email": "ana@example.pt",
            },
        )
        resposta = self.cliente.get("/admin/historico")
        self.assertEqual(200, resposta.status_code)
        self.assertIn("Conta atualizada".encode(), resposta.data)
        self.assertIn("Dados de conta atualizados por um administrador.".encode(), resposta.data)

        with sqlite3.connect(aplicacao.DB_PATH) as db:
            db.execute(
                "INSERT INTO visualizacoes_programas (programa_id) VALUES (?)",
                (self.programa_id,),
            )
            cursor = db.execute(
                "INSERT INTO programas (nome, entidade, descricao) "
                "VALUES ('=2+2', 'Entidade', 'Teste de CSV')"
            )
            db.execute(
                "INSERT INTO visualizacoes_programas (programa_id, criado_em) "
                "VALUES (?, '2020-01-02 12:00:00')",
                (cursor.lastrowid,),
            )
        resposta = self.cliente.get("/admin/relatorio.csv")
        self.assertEqual(200, resposta.status_code)
        self.assertIn("text/csv", resposta.content_type)
        self.assertIn("Consultas de programas;Total;2".encode(), resposta.data)
        self.assertIn("'=2+2".encode(), resposta.data)
        self.assertNotIn("ana@example.pt".encode(), resposta.data)
        resposta = self.cliente.get(
            "/admin/relatorio.csv?data_inicio=2020-01-02&data_fim=2020-01-02"
        )
        self.assertIn("Consultas de programas;Total;1".encode(), resposta.data)
        self.assertIn("Programa mais consultado;'=2+2;1".encode(), resposta.data)
        self.assertEqual(
            400,
            self.cliente.get(
                "/admin/relatorio.csv?data_inicio=2026-10-28&data_fim=2026-10-27"
            ).status_code,
        )

    def test_migracao_preserva_historico_antigo_e_admite_novos_eventos(self):
        caminho_original = aplicacao.DB_PATH
        caminho_legado = os.path.join(self.diretorio.name, "legado.db")
        aplicacao.DB_PATH = caminho_legado
        try:
            with sqlite3.connect(caminho_legado) as db:
                db.execute(
                    "CREATE TABLE historico_alteracoes ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "tipo TEXT NOT NULL CHECK (tipo IN ("
                    "'utilizador.criado', 'utilizador.email_verificado', "
                    "'utilizador.palavra_passe_alterada', 'perfil.criado', "
                    "'perfil.atualizado', 'programa.criado', 'programa.atualizado')), "
                    "entidade TEXT NOT NULL CHECK (entidade IN "
                    "('utilizador', 'perfil', 'programa')), "
                    "entidade_id INTEGER NOT NULL CHECK (entidade_id > 0), "
                    "responsavel_id INTEGER NOT NULL CHECK (responsavel_id > 0), "
                    "responsavel_nome TEXT NOT NULL, responsavel_email TEXT NOT NULL, "
                    "criado_em TEXT NOT NULL DEFAULT (datetime('now')))"
                )
                db.execute(
                    "INSERT INTO historico_alteracoes "
                    "(tipo, entidade, entidade_id, responsavel_id, "
                    "responsavel_nome, responsavel_email) "
                    "VALUES ('utilizador.criado', 'utilizador', 1, 1, 'Ana', "
                    "'ana@example.pt')"
                )
            aplicacao.init_db()
            with sqlite3.connect(caminho_legado) as db:
                self.assertEqual(
                    [("utilizador.criado", "",)],
                    db.execute(
                        "SELECT tipo, detalhes FROM historico_alteracoes"
                    ).fetchall(),
                )
                db.execute(
                    "INSERT INTO historico_alteracoes "
                    "(tipo, entidade, entidade_id, responsavel_id, "
                    "responsavel_nome, responsavel_email, detalhes) "
                    "VALUES ('membro.criado', 'membro', 1, 1, 'Ana', "
                    "'ana@example.pt', 'Membro adicionado.')"
                )
        finally:
            aplicacao.DB_PATH = caminho_original


if __name__ == "__main__":
    unittest.main()
