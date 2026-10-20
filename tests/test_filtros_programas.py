import unittest

from app import filtrar_programas


class FiltrarProgramasTests(unittest.TestCase):
    def setUp(self):
        self.programas = [
            {
                "id": 1,
                "criterios_json": (
                    '{"regioes":["madeira"],"rendimento_max":1500,'
                    '"rendimento_anual_min":12000,'
                    '"rendimento_anual_max":24000}'
                ),
            },
            {
                "id": 2,
                "criterios_json": '{"regioes":["acores"]}',
            },
            {"id": 3, "criterios_json": "{}"},
            {
                "id": 4,
                "criterios_json": (
                    '{"regioes":["madeira"],"rendimento_max":1500,'
                    '"rendimento_anual_min":12000,'
                    '"rendimento_anual_max":24000}'
                ),
            },
        ]

    def test_filtra_por_regiao(self):
        resultado = filtrar_programas(self.programas, regiao="madeira")

        self.assertEqual([1, 3, 4], [programa["id"] for programa in resultado])

    def test_limite_mensal_e_anual_inclusivos(self):
        resultado = filtrar_programas(
            self.programas,
            rendimento_mensal=1500,
            rendimento_anual=12000,
        )

        self.assertEqual([1, 2, 3, 4], [programa["id"] for programa in resultado])

    def test_combina_regiao_e_rendimentos(self):
        resultado = filtrar_programas(
            [self.programas[0], self.programas[1], self.programas[3]],
            regiao="madeira",
            rendimento_mensal=1500,
            rendimento_anual=20000,
        )

        self.assertEqual([1, 4], [programa["id"] for programa in resultado])

    def test_rendimento_anual_fora_do_intervalo(self):
        resultado = filtrar_programas(
            [self.programas[0]], rendimento_anual=24001
        )

        self.assertEqual([], resultado)

    def test_sem_resultados(self):
        resultado = filtrar_programas(
            self.programas[:2],
            regiao="continente",
        )

        self.assertEqual([], resultado)


if __name__ == "__main__":
    unittest.main()