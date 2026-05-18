from fastapi import APIRouter, Request


router = APIRouter(tags=["health"])


@router.get("/api/health")
async def health(request: Request) -> dict:
    container = request.app.state.container
    mcp_client = container.mcp_client
    mcp_status = "configured" if mcp_client is not None else "disconnected"
    return {
        "status": "ok",
       "mcp_connection": mcp_status,
        "version": container.settings.api_version,
        "environment": container.settings.environment,
        "upstream": {
            "pubchem_rest_base_url": container.settings.pubchem_rest_base_url,
            "pubchem_view_base_url": container.settings.pubchem_view_base_url,
        },
        "cache_backend": "memory",
        "rate_limit_strategy": "in-process-sliding-window",
        "planned_components": ["autocomplete", "bundle", "jobs", "redis", "pug-view"],
    }

