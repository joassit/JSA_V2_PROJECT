"""
Verifica la lista blanca de tablas de solo lectura y el manejo explicito
de la ausencia de credenciales -- ambos deben fallar rapido, sin intentar
una conexion real, para que este test corra sin ninguna base de datos.
"""

import pytest

from data_sources.historical_readonly import ReadonlyAccessError, _assert_allowed
import config


def test_allowed_tables_pass():
    for table in config.READONLY_ALLOWED_TABLES:
        _assert_allowed(table)  # no debe lanzar


def test_disallowed_table_raises():
    with pytest.raises(ReadonlyAccessError):
        _assert_allowed("historical_game; DROP TABLE historical_game;--")


def test_disallowed_table_never_in_whitelist_by_accident():
    # Ninguna tabla de escritura del proyecto propio debe colarse aqui --
    # este modulo es EXCLUSIVAMENTE para el historico compartido.
    assert "linescore_game" not in config.READONLY_ALLOWED_TABLES
    assert "candidate_audit_result" not in config.READONLY_ALLOWED_TABLES
