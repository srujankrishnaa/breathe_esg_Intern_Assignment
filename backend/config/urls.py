from django.contrib import admin
from django.urls import path, include
from rest_framework.authtoken.views import obtain_auth_token
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.models import UserProfile


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def current_user_info(request):
    """
    GET /api/auth/me/
    Returns the authenticated user's username and tenant name.
    Used by the frontend to display tenant context in the UI.
    """
    try:
        profile = UserProfile.objects.select_related('tenant').get(user=request.user)
        tenant_name = profile.tenant.name
    except UserProfile.DoesNotExist:
        tenant_name = 'No tenant assigned'

    return Response({
        'username': request.user.username,
        'tenant_name': tenant_name,
    })


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/login/', obtain_auth_token, name='api_token_auth'),
    path('api/auth/me/', current_user_info, name='current-user-info'),
    path('api/', include('ingestion.urls')),
]
