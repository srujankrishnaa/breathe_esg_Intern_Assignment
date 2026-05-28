from django.db import models
from django.contrib.auth.models import User


class Tenant(models.Model):
    """
    Multi-tenancy model — data is isolated per client company.
    Every data-bearing model has a FK to Tenant.
    """
    name = models.CharField(max_length=255, help_text="Company name (e.g. 'Acme Industries')")
    slug = models.SlugField(unique=True, help_text="URL-safe identifier (e.g. 'acme')")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']


class UserProfile(models.Model):
    """
    Extends Django's auth.User with tenant association.
    Links each user to exactly one tenant for data isolation.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='users')

    def __str__(self):
        return f"{self.user.username} @ {self.tenant.name}"

    class Meta:
        verbose_name = 'User Profile'
        verbose_name_plural = 'User Profiles'
