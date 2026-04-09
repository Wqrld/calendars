"""Management user to create a superuser."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from core.models import Organization

UserModel = get_user_model()


class Command(BaseCommand):
    """Management command to create a superuser from an email and password."""

    help = "Create a superuser with an email and a password"

    def add_arguments(self, parser):
        """Define required arguments "email" and "password"."""
        parser.add_argument(
            "--email",
            help=("Email for the user."),
        )
        parser.add_argument(
            "--password",
            help="Password for the user.",
        )

    def handle(self, *args, **options):
        """
        Given an email and a password, create a superuser or upgrade the existing
        user to superuser status.
        """
        email = options.get("email")
        if not email or "@" not in email:
            raise CommandError("A valid --email is required.")

        try:
            user = UserModel.objects.get(admin_email=email)
        except UserModel.DoesNotExist:
            external_id = email.split("@")[-1]
            organization, _ = Organization.objects.get_or_create(
                external_id=external_id,
                defaults={"name": external_id},
            )
            user = UserModel(admin_email=email, organization=organization)
            message = "Superuser created successfully."
        else:
            if user.is_superuser and user.is_staff:
                message = "Superuser already exists."
            else:
                message = "User already existed and was upgraded to superuser."

        user.is_superuser = True
        user.is_staff = True
        user.set_password(options["password"])
        user.save()

        self.stdout.write(self.style.SUCCESS(message))
