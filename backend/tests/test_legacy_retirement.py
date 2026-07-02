import pytest

pytestmark = pytest.mark.asyncio


async def test_articles_api_is_retired(client, eng_auth):
    res = await client.get("/api/v1/articles", headers=eng_auth)
    assert res.status_code == 404


async def test_catalog_parts_survive(client, eng_auth):
    res = await client.get("/api/v1/catalog-parts", headers=eng_auth)
    assert res.status_code == 200


async def test_catalog_part_import_location():
    from app.models.catalog import CatalogPart  # new canonical home
    from app.models import CatalogPart as reexported
    assert CatalogPart is reexported


async def test_legacy_models_gone():
    import app.models as m
    for name in ("Article", "ArticleRevision", "ArticleDocument", "BOM",
                 "BOMItem", "WorkflowInstance", "WorkflowTemplate",
                 "WorkflowStep", "WorkflowTask"):
        assert not hasattr(m, name), f"{name} should be retired"
