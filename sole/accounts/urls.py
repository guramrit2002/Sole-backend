from django.urls import path
from .views import EmailLoginView, RegisterView, VerifyOTPView

urlpatterns = [
    path("login/",    EmailLoginView.as_view(), name="login"),
    path("verify/",   VerifyOTPView.as_view(),  name="verify-otp"),
    path("register/", RegisterView.as_view(),   name="register"),
]
