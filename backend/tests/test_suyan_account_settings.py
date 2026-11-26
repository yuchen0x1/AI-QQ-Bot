"""Official account API-menu settings: schema constraints and JSON round trips."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Account


def official_account_payload(**overrides: object) -> dict[str, object]:
    return {
        "name": "菜单配置测试账号",
        "protocol": "qq_official",
        "app_id": "suyan-menu-settings-test",
        "app_secret": "unit-test-secret",
        **overrides,
    }


async def create_account(client, admin_headers: dict[str, str], **overrides: object) -> dict:
    response = await client.post(
        "/api/accounts",
        headers=admin_headers,
        json=official_account_payload(**overrides),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def delete_account(client, admin_headers: dict[str, str], account_id: int) -> None:
    response = await client.delete(f"/api/accounts/{account_id}", headers=admin_headers)
    assert response.status_code == 200, response.text


async def test_create_defaults_are_stored_and_serialized(client, admin_headers, db):
    account = await create_account(client, admin_headers)
    try:
        expected = {
            "official_api_menu_enabled": True,
            "official_menu_markdown_mode": "plain",
            "official_menu_template_id": "",
            "official_menu_template_key": "content",
        }
        assert {key: account[key] for key in expected} == expected

        listing = await client.get("/api/accounts", headers=admin_headers)
        assert listing.status_code == 200, listing.text
        listed = next(item for item in listing.json() if item["id"] == account["id"])
        assert {key: listed[key] for key in expected} == expected

        stored = await db.scalar(select(Account).where(Account.id == account["id"]))
        assert stored is not None
        assert {key: stored.features[key] for key in expected} == expected

        stored.features = {key: value for key, value in stored.features.items() if key not in expected}
        await db.commit()
        legacy_listing = await client.get("/api/accounts", headers=admin_headers)
        assert legacy_listing.status_code == 200, legacy_listing.text
        legacy_account = next(item for item in legacy_listing.json() if item["id"] == account["id"])
        assert {key: legacy_account[key] for key in expected} == expected
        await db.refresh(stored, attribute_names=["features"])
        assert not expected.keys() & stored.features.keys()
    finally:
        await delete_account(client, admin_headers, account["id"])


async def test_custom_template_settings_round_trip_and_preserve_other_features(client, admin_headers, db):
    account = await create_account(
        client,
        admin_headers,
        official_api_menu_enabled=True,
        official_menu_markdown_mode="template",
        official_menu_template_id="  open-platform-menu-template  ",
        official_menu_template_key="  body_text_2  ",
    )
    account_id = account["id"]
    try:
        assert account["official_menu_markdown_mode"] == "template"
        assert account["official_menu_template_id"] == "open-platform-menu-template"
        assert account["official_menu_template_key"] == "body_text_2"

        stored = await db.scalar(select(Account).where(Account.id == account_id))
        assert stored is not None
        features = dict(stored.features)
        features["unrelated_existing_feature"] = "preserve me"
        stored.features = features
        await db.commit()

        updated = await client.put(
            f"/api/accounts/{account_id}",
            headers=admin_headers,
            json={
                "official_api_menu_enabled": False,
                "official_menu_template_id": "  updated-menu-template  ",
                "official_menu_template_key": "  menu_body3  ",
            },
        )
        assert updated.status_code == 200, updated.text
        expected = {
            "official_api_menu_enabled": False,
            "official_menu_markdown_mode": "template",
            "official_menu_template_id": "updated-menu-template",
            "official_menu_template_key": "menu_body3",
        }
        body = updated.json()
        assert {key: body[key] for key in expected} == expected

        stored = await db.scalar(select(Account).where(Account.id == account_id))
        assert stored is not None
        await db.refresh(stored, attribute_names=["features"])
        assert stored.features["unrelated_existing_feature"] == "preserve me"
        assert {key: stored.features[key] for key in expected} == expected

        listing = await client.get("/api/accounts", headers=admin_headers)
        assert listing.status_code == 200, listing.text
        listed = next(item for item in listing.json() if item["id"] == account_id)
        assert {key: listed[key] for key in expected} == expected
    finally:
        await delete_account(client, admin_headers, account_id)


@pytest.mark.parametrize(
    "menu_fields",
    [
        {"official_menu_markdown_mode": "markdown"},
        {"official_menu_markdown_mode": "template"},
        {"official_menu_markdown_mode": "template", "official_menu_template_id": "  "},
        {"official_menu_template_id": "x" * 129},
        {"official_menu_template_key": ""},
        {"official_menu_template_key": "   "},
        {"official_menu_template_key": "2content"},
        {"official_menu_template_key": "menu-content"},
        {"official_menu_template_key": "k" * 65},
        {"official_api_menu_enabled": None},
        {"official_menu_template_key": None},
    ],
)
async def test_create_rejects_invalid_menu_settings(client, admin_headers, menu_fields):
    response = await client.post(
        "/api/accounts",
        headers=admin_headers,
        json=official_account_payload(**menu_fields),
    )
    assert response.status_code == 422, response.text


async def test_partial_updates_validate_merged_template_settings(client, admin_headers):
    account = await create_account(client, admin_headers)
    account_id = account["id"]
    try:
        missing_id = await client.put(
            f"/api/accounts/{account_id}",
            headers=admin_headers,
            json={"official_menu_markdown_mode": "template"},
        )
        assert missing_id.status_code == 422, missing_id.text

        invalid_key = await client.put(
            f"/api/accounts/{account_id}",
            headers=admin_headers,
            json={"official_menu_template_key": "invalid-key"},
        )
        assert invalid_key.status_code == 422, invalid_key.text

        too_long_id = await client.put(
            f"/api/accounts/{account_id}",
            headers=admin_headers,
            json={"official_menu_template_id": "x" * 129},
        )
        assert too_long_id.status_code == 422, too_long_id.text

        configured = await client.put(
            f"/api/accounts/{account_id}",
            headers=admin_headers,
            json={
                "official_menu_markdown_mode": "template",
                "official_menu_template_id": "  configured-template  ",
                "official_menu_template_key": "  menu_body  ",
            },
        )
        assert configured.status_code == 200, configured.text
        configured_body = configured.json()
        assert configured_body["official_menu_markdown_mode"] == "template"
        assert configured_body["official_menu_template_id"] == "configured-template"
        assert configured_body["official_menu_template_key"] == "menu_body"

        clear_id = await client.put(
            f"/api/accounts/{account_id}",
            headers=admin_headers,
            json={"official_menu_template_id": "   "},
        )
        assert clear_id.status_code == 422, clear_id.text

        toggle_only = await client.put(
            f"/api/accounts/{account_id}",
            headers=admin_headers,
            json={"official_api_menu_enabled": False},
        )
        assert toggle_only.status_code == 200, toggle_only.text
        toggle_body = toggle_only.json()
        assert toggle_body["official_api_menu_enabled"] is False
        assert toggle_body["official_menu_markdown_mode"] == "template"
        assert toggle_body["official_menu_template_id"] == "configured-template"
        assert toggle_body["official_menu_template_key"] == "menu_body"

        clear_in_native_mode = await client.put(
            f"/api/accounts/{account_id}",
            headers=admin_headers,
            json={
                "official_menu_markdown_mode": "native",
                "official_menu_template_id": "",
            },
        )
        assert clear_in_native_mode.status_code == 200, clear_in_native_mode.text
        assert clear_in_native_mode.json()["official_menu_template_id"] == ""
    finally:
        await delete_account(client, admin_headers, account_id)
