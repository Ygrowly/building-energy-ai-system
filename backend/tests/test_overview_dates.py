from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api import routes_data


def _query_result(*, scalar=None, fetchone=None, fetchall=None) -> MagicMock:
    result = MagicMock()
    result.scalar.return_value = scalar
    result.fetchone.return_value = fetchone
    result.fetchall.return_value = [] if fetchall is None else fetchall
    return result


async def _passthrough_cache(_cache_key, _ttl_seconds, compute):
    return await compute()


@pytest.mark.asyncio
async def test_get_overview_uses_database_day_boundaries():
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        side_effect=[
            _query_result(scalar=date(2026, 7, 1)),
            _query_result(
                fetchall=[
                    (
                        "Fox_education_Louie",
                        "Education",
                        1000.0,
                        120.0,
                        12.0,
                        26.5,
                        80.0,
                    )
                ]
            ),
            _query_result(fetchone=(26.5, 55.0)),
            _query_result(
                fetchall=[
                    (
                        "Fox_education_Louie",
                        "Education",
                        1.5,
                        10.0,
                        26.5,
                    )
                ]
            ),
            _query_result(fetchall=[("Fox_education_Louie",)]),
            _query_result(fetchall=[("Education", 100.0, 10.0, 60.0)]),
            _query_result(fetchall=[]),
        ]
    )

    with patch("app.api.routes_data.get_or_compute_json", new=_passthrough_cache):
        payload = await routes_data.get_overview(query_date=None, db=mock_db)

    assert payload["data_date"] == "2026-07-01"
    assert payload["kpis"]["total_electricity_kwh"] == 120.0
    assert payload["kpis_change"]["total_electricity_pct"] == 20.0
    assert len(payload["buildings"]) == 1

    execute_calls = mock_db.execute.await_args_list
    daily_params = execute_calls[1].args[1]
    yesterday_params = execute_calls[5].args[1]

    assert daily_params == {"target_day": date(2026, 7, 1)}
    assert yesterday_params == {"target_day": date(2026, 6, 30)}


@pytest.mark.asyncio
async def test_latest_energy_data_date_is_clamped_to_current_date():
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(
        return_value=_query_result(scalar=date(2026, 4, 21))
    )

    latest_day = await routes_data._get_latest_energy_data_date(mock_db)

    assert latest_day == date(2026, 4, 21)
    sql = str(mock_db.execute.await_args.args[0])
    assert "LEAST" in sql
    assert "CURRENT_DATE" in sql
