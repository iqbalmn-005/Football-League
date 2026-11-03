from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User
from django.db.models import Q


class PhoneOrUsernameBackend(ModelBackend):
    """
    Authenticates against settings.AUTH_USER_MODEL by username, email, or phone number.
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get('phone') or kwargs.get('email')
        if not username or not password:
            return None

        # Clean string
        login_input = str(username).strip()

        try:
            # Match username, email, or profile.phone
            user = User.objects.filter(
                Q(username__iexact=login_input) |
                Q(email__iexact=login_input) |
                Q(profile__phone__iexact=login_input)
            ).distinct().first()

            if user and user.check_password(password):
                return user
        except Exception:
            return None
        return None

