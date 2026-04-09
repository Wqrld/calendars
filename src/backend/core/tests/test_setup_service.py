"""Tests for SetupService — focused on org resolution policy.

The strict policy: if ``OIDC_USERINFO_ORGANIZATION_CLAIM`` is set, the
mailbox MUST carry that claim on its mail domain (no fallback). If the
setting is empty, fall back to the mailbox's email domain.
"""

from django.test import override_settings

import pytest

from core import factories
from core.models import Organization
from core.services.setup_service import (
    SetupServiceError,
    _resolve_mailbox_org_id,
)

# ---------------------------------------------------------------------------
# Strict mode: OIDC_USERINFO_ORGANIZATION_CLAIM is set
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(OIDC_USERINFO_ORGANIZATION_CLAIM="siret")
def test_resolve_mailbox_org_with_claim_present():
    """Claim configured AND present on mail domain → uses claim value."""
    mailbox = {
        "email": "contact@ministry.gouv.fr",
        "maildomain_custom_attributes": {"siret": "13002526500013"},
    }

    org_id = _resolve_mailbox_org_id(mailbox)

    org = Organization.objects.get(id=org_id)
    assert org.external_id == "13002526500013"
    assert org.name == "Organization 13002526500013"


@pytest.mark.django_db
@override_settings(OIDC_USERINFO_ORGANIZATION_CLAIM="siret")
def test_resolve_mailbox_org_with_claim_missing_raises():
    """Claim configured but absent from mail domain → strict failure.

    No fallback to email domain — opting into the claim is opting into
    strict org identity.
    """
    mailbox = {
        "email": "contact@sardinepq.fr",
        "maildomain_custom_attributes": {},
    }

    with pytest.raises(SetupServiceError) as exc_info:
        _resolve_mailbox_org_id(mailbox)

    assert "siret" in str(exc_info.value)
    assert "sardinepq.fr" in str(exc_info.value)
    # And we did NOT create an Organization for the email domain.
    assert not Organization.objects.filter(external_id="sardinepq.fr").exists()


@pytest.mark.django_db
@override_settings(OIDC_USERINFO_ORGANIZATION_CLAIM="siret")
def test_resolve_mailbox_org_with_claim_empty_string_raises():
    """An empty-string claim value is the same as missing."""
    mailbox = {
        "email": "contact@sardinepq.fr",
        "maildomain_custom_attributes": {"siret": ""},
    }

    with pytest.raises(SetupServiceError):
        _resolve_mailbox_org_id(mailbox)


@pytest.mark.django_db
@override_settings(OIDC_USERINFO_ORGANIZATION_CLAIM="siret")
def test_resolve_mailbox_org_with_no_custom_attributes_key_raises():
    """Missing ``maildomain_custom_attributes`` entirely → strict failure."""
    mailbox = {"email": "contact@sardinepq.fr"}

    with pytest.raises(SetupServiceError):
        _resolve_mailbox_org_id(mailbox)


# ---------------------------------------------------------------------------
# Fallback mode: OIDC_USERINFO_ORGANIZATION_CLAIM is empty
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(OIDC_USERINFO_ORGANIZATION_CLAIM="")
def test_resolve_mailbox_org_falls_back_to_email_domain():
    """No claim configured → mailbox's email domain becomes the org id."""
    mailbox = {
        "email": "contact@sardinepq.fr",
        "maildomain_custom_attributes": {},
    }

    org_id = _resolve_mailbox_org_id(mailbox)

    org = Organization.objects.get(id=org_id)
    assert org.external_id == "sardinepq.fr"


@pytest.mark.django_db
@override_settings(OIDC_USERINFO_ORGANIZATION_CLAIM="")
def test_resolve_mailbox_org_fallback_ignores_claim_attributes():
    """When claim is unset, custom attributes are not consulted at all."""
    mailbox = {
        "email": "contact@sardinepq.fr",
        # Even if siret happens to be there, it's irrelevant when the
        # setting is empty — we go straight to email domain.
        "maildomain_custom_attributes": {"siret": "13002526500013"},
    }

    org_id = _resolve_mailbox_org_id(mailbox)

    org = Organization.objects.get(id=org_id)
    assert org.external_id == "sardinepq.fr"


@pytest.mark.django_db
@override_settings(OIDC_USERINFO_ORGANIZATION_CLAIM="")
def test_resolve_mailbox_org_fallback_without_email_raises():
    """No claim configured AND no usable email → failure."""
    mailbox = {"email": "", "maildomain_custom_attributes": {}}

    with pytest.raises(SetupServiceError):
        _resolve_mailbox_org_id(mailbox)


@pytest.mark.django_db
@override_settings(OIDC_USERINFO_ORGANIZATION_CLAIM="")
def test_resolve_mailbox_org_fallback_with_malformed_email_raises():
    """Email without an @ cannot yield a domain → failure."""
    mailbox = {"email": "not-an-email", "maildomain_custom_attributes": {}}

    with pytest.raises(SetupServiceError):
        _resolve_mailbox_org_id(mailbox)


# ---------------------------------------------------------------------------
# Organization reuse / auto-creation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(OIDC_USERINFO_ORGANIZATION_CLAIM="siret")
def test_resolve_mailbox_org_reuses_existing_organization():
    """Existing Organization rows are reused, not duplicated."""
    existing = factories.OrganizationFactory(
        external_id="13002526500013", name="Ministere X"
    )
    mailbox = {
        "email": "contact@ministry.gouv.fr",
        "maildomain_custom_attributes": {"siret": "13002526500013"},
    }

    org_id = _resolve_mailbox_org_id(mailbox)

    assert org_id == str(existing.id)
    # The existing name must NOT be overwritten by the placeholder.
    existing.refresh_from_db()
    assert existing.name == "Ministere X"
    assert Organization.objects.filter(external_id="13002526500013").count() == 1


@pytest.mark.django_db
@override_settings(OIDC_USERINFO_ORGANIZATION_CLAIM="")
def test_resolve_mailbox_org_fallback_reuses_existing_organization():
    """Same reuse contract applies in email-domain fallback mode."""
    existing = factories.OrganizationFactory(
        external_id="sardinepq.fr", name="Sardine PQ"
    )
    mailbox = {
        "email": "contact@sardinepq.fr",
        "maildomain_custom_attributes": {},
    }

    org_id = _resolve_mailbox_org_id(mailbox)

    assert org_id == str(existing.id)
    existing.refresh_from_db()
    assert existing.name == "Sardine PQ"
