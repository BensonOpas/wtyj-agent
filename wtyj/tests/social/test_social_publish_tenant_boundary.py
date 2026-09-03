"""Public posting must not turn a shared provider key into tenant authority."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agents.social import scheduler, social_publisher
from shared import config_loader, state_registry


def _account(account_id, platform, active=True):
    return SimpleNamespace(
        field_id=account_id, platform=platform, isActive=active, username="owned"
    )


@pytest.fixture
def publication(monkeypatch):
    config = {
        "slug": "mermaid",
        "channel_account_allowlist": {
            "mode": "strict", "zernio_accounts": ["owned"]
        },
        "social_content": {"platforms": ["instagram", "facebook", "twitter"]},
    }
    monkeypatch.setenv("TENANT_ACCOUNT_ALLOWLIST_REQUIRED", "true")
    monkeypatch.setenv("TENANT_ID", "mermaid")
    monkeypatch.setattr(config_loader, "get_raw", lambda: config)
    client = MagicMock()
    client.accounts.list.return_value = SimpleNamespace(
        accounts=[_account("owned", "instagram")]
    )
    client.posts.create.return_value = SimpleNamespace(
        post=SimpleNamespace(field_id="post-owned", platforms=[])
    )
    monkeypatch.setattr(social_publisher, "_get_client", lambda: client)
    return config, client


def _publish(platform, account_id="owned"):
    if platform == "instagram":
        return social_publisher.publish_to_instagram("caption", "https://media", account_id)
    if platform == "facebook":
        return social_publisher.publish_to_facebook("caption", "https://media", account_id)
    return social_publisher.publish_to_platform(platform, "caption", "https://media", account_id)


@pytest.mark.parametrize("platform", ["instagram", "facebook", "twitter"])
def test_every_publisher_rejects_foreign_account_before_provider_read_or_write(publication, platform):
    _, client = publication
    client.accounts.list.return_value.accounts = [_account("foreign", platform)]
    assert _publish(platform, "foreign") is None
    client.accounts.list.assert_not_called()
    client.posts.create.assert_not_called()


@pytest.mark.parametrize("platform", ["instagram", "facebook", "twitter"])
@pytest.mark.parametrize("kind", ["no_opt_in", "wrong_platform", "inactive", "missing_account"])
def test_strict_publish_requires_platform_opt_in_and_exact_active_account(publication, platform, kind):
    config, client = publication
    client.accounts.list.return_value.accounts = [_account("owned", platform)]
    if kind == "no_opt_in":
        config.pop("social_content")
    elif kind == "wrong_platform":
        client.accounts.list.return_value.accounts = [_account("owned", "whatsapp")]
    elif kind == "inactive":
        client.accounts.list.return_value.accounts = [_account("owned", platform, False)]
    else:
        client.accounts.list.return_value.accounts = []
    assert _publish(platform) is None
    client.posts.create.assert_not_called()


@pytest.mark.parametrize("platform", ["instagram", "facebook", "twitter"])
def test_strict_owned_publication_reaches_exact_provider_target(publication, platform):
    _, client = publication
    client.accounts.list.return_value.accounts = [_account("owned", platform)]
    assert _publish(platform) == {"post_id": "post-owned", "post_url": ""}
    client.posts.create.assert_called_once()
    assert client.posts.create.call_args.kwargs["platforms"] == [
        {"platform": platform, "accountId": "owned"}
    ]


@pytest.mark.parametrize("platform", ["instagram", "facebook", "twitter"])
@pytest.mark.parametrize("change", ["reassigned", "platform_revoked", "unavailable"])
def test_publish_rechecks_after_provider_account_lookup(publication, platform, change):
    config, client = publication

    def lookup():
        if change == "reassigned":
            config["channel_account_allowlist"]["zernio_accounts"] = ["new-owner"]
        elif change == "platform_revoked":
            config["social_content"]["platforms"] = []
        else:
            config.clear()
        return SimpleNamespace(accounts=[_account("owned", platform)])

    client.accounts.list.side_effect = lookup
    assert _publish(platform) is None
    client.posts.create.assert_not_called()


@pytest.mark.parametrize("invalid", [{}, {"slug": "other"}, {"channel_account_allowlist": None}])
def test_unknown_required_config_cannot_enable_publish_or_delete(publication, invalid):
    config, client = publication
    config.clear()
    config.update(invalid)
    assert _publish("instagram") is None
    assert social_publisher.delete_post("arbitrary-post-id") is False
    assert social_publisher.get_available_platforms() == []
    client.posts.create.assert_not_called()
    client.posts.delete.assert_not_called()


def test_config_exception_fails_closed(publication, monkeypatch):
    _, client = publication
    monkeypatch.setattr(config_loader, "get_raw", MagicMock(side_effect=OSError("unavailable")))
    assert _publish("instagram") is None
    assert social_publisher.get_account_id("instagram") == ""
    assert social_publisher.delete_post("arbitrary-post-id") is False
    client.posts.create.assert_not_called()
    client.posts.delete.assert_not_called()


def test_discovery_skips_foreign_first_and_filters_available_platforms(publication):
    config, client = publication
    config["channel_account_allowlist"]["zernio_accounts"] = ["owned-ig", "owned-fb", "owned-wa"]
    config["social_content"]["platforms"] = ["instagram"]
    client.accounts.list.return_value.accounts = [
        _account("foreign-ig", "instagram"), _account("foreign-twitter", "twitter"),
        _account("owned-ig", "instagram"), _account("owned-fb", "facebook"),
        _account("owned-wa", "whatsapp"),
    ]
    assert social_publisher.get_instagram_account_id() == "owned-ig"
    assert social_publisher.get_facebook_account_id() == ""
    assert social_publisher.get_account_id("instagram") == "owned-ig"
    assert social_publisher.get_account_id("twitter") == ""
    assert social_publisher.get_available_platforms() == ["instagram"]


def test_strict_whatsapp_discovery_does_not_require_public_post_opt_in(publication):
    config, client = publication
    config.pop("social_content")
    client.accounts.list.return_value.accounts = [
        _account("foreign", "whatsapp"), _account("owned", "whatsapp")
    ]
    assert social_publisher.get_account_id("whatsapp") == "owned"
    assert social_publisher.get_available_platforms() == []
    assert _publish("whatsapp") is None
    client.posts.create.assert_not_called()


@pytest.mark.parametrize("lookup", [
    social_publisher.get_instagram_account_id,
    lambda: social_publisher.get_account_id("instagram"),
    social_publisher.get_available_platforms,
])
def test_discovery_rechecks_ownership_after_provider_io(publication, lookup):
    config, client = publication

    def accounts():
        config["channel_account_allowlist"]["zernio_accounts"] = ["new-owner"]
        return SimpleNamespace(accounts=[_account("owned", "instagram")])

    client.accounts.list.side_effect = accounts
    assert not lookup()


@pytest.mark.parametrize("platforms", [[], ["instagram"], ["facebook"], ["instagram", "twitter"]])
@pytest.mark.parametrize("dry_run", [False, True])
def test_mermaid_scheduler_refuses_unprovisioned_draft_before_any_side_effect(
    publication, monkeypatch, platforms, dry_run
):
    config, client = publication
    config.pop("social_content")
    resolve = MagicMock()
    upload = MagicMock()
    status = MagicMock()
    monkeypatch.setattr(scheduler, "_resolve_image", resolve)
    monkeypatch.setattr(social_publisher, "upload_media", upload)
    monkeypatch.setattr(state_registry, "is_dry_run", lambda: dry_run)
    monkeypatch.setattr(state_registry, "update_draft_status", status)
    result = scheduler.execute_publish({"id": 1, "platforms": platforms})
    assert result["ok"] is False
    resolve.assert_not_called()
    upload.assert_not_called()
    status.assert_not_called()
    client.posts.create.assert_not_called()


@pytest.mark.parametrize("change_during", ["resolve", "upload"])
def test_scheduler_rechecks_platform_and_account_after_slow_work(publication, monkeypatch, change_during):
    config, client = publication
    monkeypatch.setattr(state_registry, "is_dry_run", lambda: False)
    status = MagicMock()
    monkeypatch.setattr(state_registry, "update_draft_status", status)

    def resolve(_):
        if change_during == "resolve":
            config["social_content"]["platforms"] = []
        return "/test/photo.jpg"

    def upload(_):
        if change_during == "upload":
            config["channel_account_allowlist"]["zernio_accounts"] = ["new-owner"]
        return "https://media"

    monkeypatch.setattr(scheduler, "_resolve_image", resolve)
    upload_mock = MagicMock(side_effect=upload)
    monkeypatch.setattr(social_publisher, "upload_media", upload_mock)
    # Deliberately stale discovery must not bypass the final provider guard.
    monkeypatch.setattr(social_publisher, "get_instagram_account_id", lambda: "owned")
    assert scheduler.execute_publish({"id": 1, "platforms": ["instagram"]})["ok"] is False
    if change_during == "resolve":
        upload_mock.assert_not_called()
    client.posts.create.assert_not_called()
    status.assert_not_called()


@pytest.mark.parametrize("mode", ["strict", "unavailable"])
def test_strict_delete_never_trusts_an_unbound_post_id(publication, mode):
    config, client = publication
    if mode == "unavailable":
        config.clear()
    assert social_publisher.delete_post("foreign-post") is False
    client.posts.delete.assert_not_called()


@pytest.mark.parametrize("mode", ["legacy", "permissive"])
def test_legacy_and_permissive_generic_publish_and_delete_remain_compatible(publication, monkeypatch, mode):
    config, client = publication
    monkeypatch.delenv("TENANT_ACCOUNT_ALLOWLIST_REQUIRED")
    config.pop("social_content")
    if mode == "legacy":
        config.pop("channel_account_allowlist")
    else:
        config["channel_account_allowlist"]["mode"] = "permissive"
    assert _publish("linkedin", "legacy-account")["post_id"] == "post-owned"
    client.accounts.list.assert_not_called()
    assert social_publisher.delete_post("legacy-post") is True
    client.posts.delete.assert_called_once_with("legacy-post")
