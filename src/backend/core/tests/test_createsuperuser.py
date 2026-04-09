"""Tests for the custom ``createsuperuser`` management command."""

from io import StringIO

from django.core.management import call_command

import pytest

from core import factories
from core.models import Organization, User


@pytest.mark.django_db
def test_createsuperuser_creates_user_and_organization():
    """The command should create both the user and an org from the email domain."""
    call_command(
        "createsuperuser",
        email="root@example.com",
        password="hunter2",
        stdout=StringIO(),
    )

    user = User.objects.get(admin_email="root@example.com")
    assert user.is_superuser is True
    assert user.is_staff is True
    assert user.check_password("hunter2") is True
    assert user.organization is not None
    assert user.organization.external_id == "example.com"


@pytest.mark.django_db
def test_createsuperuser_reuses_existing_organization():
    """When the org already exists, the command should reuse it."""
    org = factories.OrganizationFactory(external_id="example.com", name="Example")

    call_command(
        "createsuperuser",
        email="root@example.com",
        password="hunter2",
        stdout=StringIO(),
    )

    user = User.objects.get(admin_email="root@example.com")
    assert user.organization_id == org.id
    assert Organization.objects.filter(external_id="example.com").count() == 1


@pytest.mark.django_db
def test_createsuperuser_upgrades_existing_user():
    """An existing non-superuser should be upgraded in place."""
    org = factories.OrganizationFactory(external_id="example.com")
    existing = factories.UserFactory(
        admin_email="root@example.com",
        organization=org,
        is_superuser=False,
        is_staff=False,
    )

    call_command(
        "createsuperuser",
        email="root@example.com",
        password="hunter2",
        stdout=StringIO(),
    )

    existing.refresh_from_db()
    assert existing.is_superuser is True
    assert existing.is_staff is True
    assert existing.check_password("hunter2") is True
    assert existing.organization_id == org.id
