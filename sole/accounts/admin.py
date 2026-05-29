from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display   = ("email", "first_name", "last_name", "is_active", "is_staff", "date_joined")
    list_filter    = ("is_active", "is_staff")
    search_fields  = ("email", "first_name", "last_name")
    ordering       = ("-date_joined",)
    readonly_fields = ("date_joined",)

    fieldsets = (
        (None,           {"fields": ("email",)}),
        ("Personal info",{"fields": ("first_name", "last_name")}),
        ("Permissions",  {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates",        {"fields": ("date_joined",)}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields":  ("email", "first_name", "last_name", "is_staff", "is_active"),
        }),
    )

    # No password fields needed
    filter_horizontal = ("groups", "user_permissions")
