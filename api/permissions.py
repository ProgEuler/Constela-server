from rest_framework import permissions

class IsMember(permissions.BasePermission):
    """
    Allows access only to standard members.
    """
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == 'member'

class IsSupportAgent(permissions.BasePermission):
    """
    Allows access to Support, Admin, and Super Admin roles.
    """
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        return request.user.role in ['support', 'admin', 'superadmin']

class IsModerator(permissions.BasePermission):
    """
    Allows access to Moderator, Admin, and Super Admin roles.
    """
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        return request.user.role in ['moderator', 'admin', 'superadmin']

class IsAdminUser(permissions.BasePermission):
    """
    Allows access to Admin and Super Admin roles.
    """
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        return request.user.role in ['admin', 'superadmin']

class IsSuperAdmin(permissions.BasePermission):
    """
    Allows access strictly to Super Admin roles.
    """
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        return request.user.role == 'superadmin'

