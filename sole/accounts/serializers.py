from rest_framework import serializers


class EmailLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()


class VerifyOTPSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp   = serializers.CharField(min_length=6, max_length=6)

class RegisterSerializer(serializers.Serializer):
    email      = serializers.EmailField()
    first_name = serializers.CharField(max_length=30, required=False, allow_blank=True)
    last_name  = serializers.CharField(max_length=30, required=False, allow_blank=True)