import os
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token

from core.models import Tenant, UserProfile
from ingestion.models import (
    PlantLookup,
    SAPIngestionBatch, RawSAPRecord,
    UtilityIngestionBatch, RawUtilityRecord,
    TravelIngestionBatch, RawTravelRecord,
    NormalizedEmissionRecord,
)

# ── Tenant / User definitions ───────────────────────────────
# Both tenants start completely clean and empty (no pre-seeded ingestion data).
# Both are configured with the standard plants to support live SAP OData triggers.
TENANTS = [
    {
        'name': 'Acme Industries',
        'slug': 'acme',
        'user': 'analyst',
        'password': 'breathe2026',
        'plants': [
            ('1010', 'IN01', 'Mumbai Factory', 'IN', 'Maharashtra'),
            ('2030', 'IN01', 'Delhi Warehouse', 'IN', 'Delhi'),
            ('3050', 'IN01', 'Chennai Plant', 'IN', 'Tamil Nadu'),
        ],
    },
    {
        'name': 'Beta Corp',
        'slug': 'beta',
        'user': 'reviewer',
        'password': 'breathe2026',
        'plants': [
            ('1010', 'IN01', 'Mumbai Factory', 'IN', 'Maharashtra'),
            ('2030', 'IN01', 'Delhi Warehouse', 'IN', 'Delhi'),
            ('3050', 'IN01', 'Chennai Plant', 'IN', 'Tamil Nadu'),
        ],
    },
]


class Command(BaseCommand):
    help = 'Seeds the database with Acme and Beta Corp tenants, users, and plant lookups'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear all ingestion batches, raw records, and normalized records before seeding (dev only)',
        )

    def handle(self, *args, **options):
        self.stdout.write("Starting database seeding...")

        if options['clear']:
            self.stdout.write("Wiping existing ingestion batches, raw records, and normalized records...")
            NormalizedEmissionRecord.objects.all().delete()
            RawSAPRecord.objects.all().delete()
            RawUtilityRecord.objects.all().delete()
            RawTravelRecord.objects.all().delete()
            SAPIngestionBatch.objects.all().delete()
            UtilityIngestionBatch.objects.all().delete()
            TravelIngestionBatch.objects.all().delete()
            
            # Also clean up old tenants that are no longer part of our 2-tenant setup
            stale_slugs = ['gamma', 'delta']
            stale_users = ['gamma_user', 'delta_user']
            Tenant.objects.filter(slug__in=stale_slugs).delete()
            User.objects.filter(username__in=stale_users).delete()
            
            self.stdout.write(self.style.SUCCESS("Wipe complete."))

        for t_def in TENANTS:
            # ── Create tenant ────────────────────────────────────
            tenant, created = Tenant.objects.get_or_create(
                slug=t_def['slug'],
                defaults={'name': t_def['name']}
            )
            verb = 'Created' if created else 'Exists'
            self.stdout.write(self.style.SUCCESS(f"{verb} Tenant: {tenant}"))

            # ── Create user ──────────────────────────────────────
            user, user_created = User.objects.get_or_create(username=t_def['user'])
            if user_created:
                user.set_password(t_def['password'])
                user.is_staff = True
                user.save()
                self.stdout.write(self.style.SUCCESS(
                    f"Created User: {t_def['user']} / {t_def['password']}"
                ))
            else:
                self.stdout.write(f"User '{t_def['user']}' already exists")

            # ── Create user profile (links user → tenant) ────────
            profile, profile_created = UserProfile.objects.get_or_create(
                user=user,
                defaults={'tenant': tenant}
            )
            if profile_created:
                self.stdout.write(self.style.SUCCESS(f"Created UserProfile: {profile}"))
            else:
                if profile.tenant != tenant:
                    profile.tenant = tenant
                    profile.save()
                    self.stdout.write(self.style.SUCCESS("Updated UserProfile tenant"))

            # ── Create auth token ────────────────────────────────
            token, _ = Token.objects.get_or_create(user=user)
            self.stdout.write(f"  Auth Token ({t_def['user']}): {token.key}")

            # ── Create plant lookups ─────────────────────────────
            for p_code, c_code, p_name, country, region in t_def.get('plants', []):
                pl, pl_created = PlantLookup.objects.get_or_create(
                    tenant=tenant,
                    plant_code=p_code,
                    company_code=c_code,
                    defaults={
                        'plant_name': p_name,
                        'country': country,
                        'region': region,
                    }
                )
                if pl_created:
                    self.stdout.write(f"  Created PlantLookup: {p_code} -> {p_name}")

        self.stdout.write(self.style.SUCCESS("\nDatabase seeding completed successfully!"))
        self.stdout.write(self.style.SUCCESS(
            f"Created exactly {len(TENANTS)} tenants with isolated user accounts and seeded plants."
        ))
        self.stdout.write(self.style.SUCCESS("All tenants start with a 100% clean and pristine state."))
