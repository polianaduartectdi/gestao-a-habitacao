import io
import os
import sqlite3
import tempfile
import unittest

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

    def test_transicoes_de_estado_validas_e_invalidas(self):
        self.assertTrue(
            aplicacao.transicao_candidatura_valida("submetida", "em_analise")
        )
        self.assertTrue(
            aplicacao.transicao_candidatura_valida("em_analise", "aprovada")
        )
        self.assertFalse(
            aplicacao.transicao_candidatura_valida("submetida", "aprovada")
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

    def test_estado_invalido_nao_altera_candidatura(self):
        self.autenticar(1)
        self.cliente.post(
            "/candidaturas",
            data={"_csrf": "token-teste", "programa_id": str(self.programa_id)},
        )
        self.cliente.post(
            "/candidaturas/1/estado",
            data={"_csrf": "token-teste", "estado": "aprovada"},
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


if __name__ == "__main__":
    unittest.main()
