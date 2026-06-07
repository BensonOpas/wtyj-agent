import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from agents.social import social_agent


def test_customer_media_selection_matches_product_metadata(monkeypatch):
    monkeypatch.setenv("PUBLIC_API_BASE_URL", "https://api.unboks.org")
    monkeypatch.setattr(
        social_agent.config_loader,
        "get_raw",
        lambda: {"tenant_slug": "wibrandt", "business": {"name": "Wibrandt"}},
    )
    monkeypatch.setattr(
        social_agent.state_registry,
        "get_photos",
        lambda limit=200: [
            {
                "id": 4,
                "filename": "wibrandt-tosca-twist-ang5.jpg",
                "original_filename": "tosca.jpg",
                "tags": [
                    "The Tosca Twist - 5 ANG - Swedish Toscakaka-inspired bake.",
                    "The Tosca Twist",
                    "almond",
                ],
                "service_key": "knowledge:info_update:wibrandt-tosca-twist",
                "source": "knowledge_media",
                "source_id": "wibrandt-tosca-twist",
            },
            {
                "id": 6,
                "filename": "wibrandt-cinnamon-twist-ang5.jpg",
                "original_filename": "cinnamon.jpg",
                "tags": [
                    "The Cinnamon Twist - 5 ANG - buttery and flaky.",
                    "The Cinnamon Twist",
                    "cinnamon",
                ],
                "service_key": "knowledge:info_update:wibrandt-cinnamon-twist",
                "source": "knowledge_media",
                "source_id": "wibrandt-cinnamon-twist",
            },
        ],
    )

    selected = social_agent._select_customer_media(
        "Can you send info about the cinnamon twist?",
        "The Cinnamon Twist is 5 ANG.",
        {},
        {},
    )

    assert selected is not None
    assert selected["id"] == "6"
    assert selected["url"].endswith(
        "/api/wibrandt/dashboard/api/public/media/wibrandt-cinnamon-twist-ang5.jpg"
    )


def test_customer_media_selection_does_not_attach_for_unrelated_message(monkeypatch):
    monkeypatch.setattr(
        social_agent.config_loader,
        "get_raw",
        lambda: {"tenant_slug": "wibrandt"},
    )
    monkeypatch.setattr(
        social_agent.state_registry,
        "get_photos",
        lambda limit=200: [
            {
                "id": 6,
                "filename": "wibrandt-cinnamon-twist-ang5.jpg",
                "tags": ["The Cinnamon Twist - 5 ANG"],
                "service_key": "knowledge:info_update:wibrandt-cinnamon-twist",
                "source_id": "wibrandt-cinnamon-twist",
            }
        ],
    )

    assert social_agent._select_customer_media(
        "Thanks, that is all.",
        "You are welcome.",
        {},
        {},
    ) is None


def test_customer_media_selection_uses_recent_product_context(monkeypatch):
    monkeypatch.setenv("PUBLIC_API_BASE_URL", "https://api.unboks.org")
    monkeypatch.setattr(
        social_agent.config_loader,
        "get_raw",
        lambda: {"tenant_slug": "wibrandt", "business": {"name": "Wibrandt"}},
    )
    monkeypatch.setattr(
        social_agent.state_registry,
        "get_photos",
        lambda limit=200: [
            {
                "id": 6,
                "filename": "wibrandt-cinnamon-twist-ang5.jpg",
                "original_filename": "cinnamon.jpg",
                "tags": [
                    "The Cinnamon Twist - 5 ANG - buttery and flaky.",
                    "The Cinnamon Twist",
                    "cinnamon",
                    "cardamom",
                ],
                "service_key": "knowledge:info_update:wibrandt-cinnamon-twist",
                "source": "knowledge_media",
                "source_id": "wibrandt-cinnamon-twist",
            },
        ],
    )

    selected = social_agent._select_customer_media(
        "Yes pls",
        "The Cinnamon Cardamom Twist is soft and buttery.",
        {},
        {},
        history=[
            {"role": "user", "text": "How does the Cinnamon Cardamom Twist look?"},
            {"role": "assistant", "text": "It is one of our Swedish-inspired bakes."},
        ],
    )

    assert selected is not None
    assert selected["id"] == "6"


def test_customer_media_selection_strips_instagram_fallback_when_image_attached():
    reply = (
        "Here is our White Chocolate Pecan Cookie.\n\n"
        "You can also find more photos on our Instagram: "
        "https://www.instagram.com/wibrandtbakehouse"
    )

    assert social_agent._strip_media_fallback_links(reply) == (
        "Here is our White Chocolate Pecan Cookie."
    )


def test_customer_media_selection_current_product_beats_old_history(monkeypatch):
    monkeypatch.setenv("PUBLIC_API_BASE_URL", "https://api.unboks.org")
    monkeypatch.setattr(
        social_agent.config_loader,
        "get_raw",
        lambda: {"tenant_slug": "wibrandt", "business": {"name": "Wibrandt"}},
    )
    monkeypatch.setattr(
        social_agent.state_registry,
        "get_photos",
        lambda limit=200: [
            {
                "id": 3,
                "filename": "wibrandt-white-chocolate-pecan-cookie-ang6.jpg",
                "original_filename": "cookie.jpg",
                "tags": [
                    "White Chocolate Pecan Cookie - 6 ANG - white chocolate chunks.",
                    "White Chocolate Pecan Cookie",
                    "cookie",
                    "white chocolate",
                    "pecan",
                ],
                "service_key": "knowledge:info_update:wibrandt-white-chocolate-pecan-cookie",
                "source": "knowledge_media",
                "source_id": "wibrandt-white-chocolate-pecan-cookie",
            },
            {
                "id": 6,
                "filename": "wibrandt-cinnamon-twist-ang5.jpg",
                "original_filename": "cinnamon.jpg",
                "tags": [
                    "The Cinnamon Twist - 5 ANG - buttery and flaky.",
                    "The Cinnamon Twist",
                    "cinnamon",
                    "cardamom",
                ],
                "service_key": "knowledge:info_update:wibrandt-cinnamon-twist",
                "source": "knowledge_media",
                "source_id": "wibrandt-cinnamon-twist",
            },
        ],
    )

    selected = social_agent._select_customer_media(
        "and cinamon? do u have it?",
        "Yeah, we do. The Cinnamon Cardamom Twist is our cinnamon pastry.",
        {},
        {},
        history=[
            {"role": "user", "text": "Tell me about the White Chocolate Pecan Cookie"},
            {"role": "assistant", "text": "The White Chocolate Pecan Cookie is a big cookie with white chocolate and pecans."},
        ],
    )

    assert selected is not None
    assert selected["id"] == "6"
