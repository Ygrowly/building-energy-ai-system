"""
MCP 工具：building_kpi_forecast_6h_12h / building_kpi_forecast_from_features
=============================================================================
薄封装层，将 MCP 入参转发给 forecast_service。
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.mcp_schemas import (
    ForecastFromFeaturesInput,
    ForecastFromFeaturesOutput,
    ForecastKPIInput,
    ForecastKPIOutput,
    MCPError,
)


async def building_kpi_forecast(
    inp: ForecastKPIInput,
    session: AsyncSession,
) -> ForecastKPIOutput | MCPError:
    from app.services.forecast_service import forecast_building_kpi

    return await forecast_building_kpi(
        building_id=inp.building_id,
        session=session,
        as_of=inp.as_of,
        include_expected_comparison=inp.include_expected_comparison,
    )


def building_kpi_forecast_debug(
    inp: ForecastFromFeaturesInput,
) -> ForecastFromFeaturesOutput | MCPError:
    from app.services.forecast_service import forecast_from_raw_features

    return forecast_from_raw_features(features=inp.features)
