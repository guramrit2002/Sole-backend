from django.core.mail import send_mail
from django.conf import settings

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User, OTP
from .serializers import EmailLoginSerializer, VerifyOTPSerializer



class EmailLoginView(APIView):
    """
    POST /api/auth/login/
    Body: { "email": "user@example.com" }

    404  → no user found
    200  → OTP sent to email
    """

    def post(self, request):
        serializer = EmailLoginSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        email = serializer.validated_data["email"]

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"detail": "no user found"}, status=status.HTTP_404_NOT_FOUND)

        # Invalidate any previous unused OTPs for this user
        OTP.objects.filter(user=user, is_used=False).delete()

        otp = OTP.objects.create(user=user, code=OTP.generate_code())

        send_mail(
            subject="Your Sole OTP",
            message=f"Your OTP is: {otp.code}\n\nValid for {OTP.EXPIRY_MINUTES} minutes.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )

        return Response(
            {"detail": f"OTP sent to {email}"},
            status=status.HTTP_200_OK,
        )


class VerifyOTPView(APIView):
    """
    POST /api/auth/verify/
    Body: { "email": "user@example.com", "otp": "123456" }

    400 → invalid / expired OTP
    200 → JWT access + refresh tokens
    """

    def post(self, request):
        serializer = VerifyOTPSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        email = serializer.validated_data["email"]
        code  = serializer.validated_data["otp"]

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"detail": "no user found"}, status=status.HTTP_404_NOT_FOUND)

        otp = OTP.objects.filter(user=user, code=code, is_used=False).first()

        if not otp:
            return Response({"detail": "invalid OTP"}, status=status.HTTP_400_BAD_REQUEST)

        if otp.is_expired:
            return Response({"detail": "OTP has expired"}, status=status.HTTP_400_BAD_REQUEST)

        otp.is_used = True
        otp.save()

        refresh = RefreshToken.for_user(user)

        return Response(
            {
                "access":  str(refresh.access_token),
                "refresh": str(refresh),
                "user": {
                    "id":         user.id,
                    "email":      user.email,
                    "first_name": user.first_name,
                    "last_name":  user.last_name,
                },
            },
            status=status.HTTP_200_OK,
        )

class RegisterView(APIView):
    """
    POST /api/auth/register/
    Body: { "email": "user@example.com" }

    201 → user created, OTP sent
    400 → email already registered
    """

    def post(self, request):
        email = (request.data.get("email") or "").strip().lower()
        if not email:
            return Response({"detail": "email is required"}, status=status.HTTP_400_BAD_REQUEST)

        if User.objects.filter(email=email).exists():
            return Response({"detail": "an account with this email already exists"}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.create_user(email=email)

        OTP.objects.filter(user=user, is_used=False).delete()
        otp = OTP.objects.create(user=user, code=OTP.generate_code())

        send_mail(
            subject="Your Sole OTP",
            message=f"Your OTP is: {otp.code}\n\nValid for {OTP.EXPIRY_MINUTES} minutes.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )

        return Response({"detail": f"account created, OTP sent to {email}"}, status=status.HTTP_201_CREATED)
