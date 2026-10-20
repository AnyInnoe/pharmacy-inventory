from django.shortcuts import render

# Create your views here.
import json

from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .models import AuditEvent, BranchMembership


def _user_data(user):
    memberships = (
        BranchMembership.objects.filter(
            user=user,
            is_active=True,
            branch__is_active=True,
        )
        .select_related("branch")
        .order_by("branch__name")
    )

    return {
        "id": user.id,
        "username": user.username,
        "firstName": user.first_name,
        "lastName": user.last_name,
        "isSuperuser": user.is_superuser,
        "memberships": [
            {
                "branchId": membership.branch_id,
                "branchName": membership.branch.name,
                "branchCode": membership.branch.code,
                "role": membership.role,
            }
            for membership in memberships
        ],
    }


def _record_auth_event(request, user, action):
    AuditEvent.objects.create(
        actor=user,
        action=action,
        entity_type="user",
        entity_id=str(user.pk),
        ip_address=request.META.get("REMOTE_ADDR"),
    )


@ensure_csrf_cookie
@require_GET
def csrf_token(request):
    return JsonResponse({"csrfToken": get_token(request)})


@require_POST
def login_view(request):
    try:
        data = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"detail": "Request must contain valid JSON."}, status=400)

    if not isinstance(data, dict):
        return JsonResponse({"detail": "Request must contain a JSON object."}, status=400)

    username = data.get("username", "")
    password = data.get("password", "")

    if not isinstance(username, str) or not isinstance(password, str):
        return JsonResponse({"detail": "Username and password are required."}, status=400)

    user = authenticate(request, username=username.strip(), password=password)

    if user is None:
        return JsonResponse({"detail": "Invalid username or password."}, status=401)

    login(request, user)
    _record_auth_event(request, user, AuditEvent.Action.LOGIN)

    return JsonResponse({"user": _user_data(user)})


@require_POST
def logout_view(request):
    if request.user.is_authenticated:
        _record_auth_event(request, request.user, AuditEvent.Action.LOGOUT)
        logout(request)

    return JsonResponse({"detail": "Logged out."})


@require_GET
def current_user(request):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required."}, status=401)

    return JsonResponse({"user": _user_data(request.user)})