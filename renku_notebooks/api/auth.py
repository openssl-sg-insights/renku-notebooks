# -*- coding: utf-8 -*-
#
# Copyright 2019 - Swiss Data Science Center (SDSC)
# A partnership between École Polytechnique Fédérale de Lausanne (EPFL) and
# Eidgenössische Technische Hochschule Zürich (ETHZ).
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Authentication functions for the notebooks service."""

from functools import wraps

from flask import Blueprint, request

from ..config import config
from .classes.user import RegisteredUser, AnonymousUser
from ..errors.user import AuthenticationError

bp = Blueprint("auth_bp", __name__, url_prefix=config.service_prefix)


def authenticated(f):
    """Decorator for checking authentication status of the user given the headers."""

    @wraps(f)
    def decorated(*args, **kwargs):
        user = RegisteredUser(request.headers)
        if config.anonymous_sessions_enabled and not user.authenticated:
            user = AnonymousUser(request.headers)
        if user.authenticated:
            # the user is logged in
            return f(user, *args, **kwargs)
        else:
            # the user is not logged in
            raise AuthenticationError(
                detail="The required authentication headers "
                f"{RegisteredUser.auth_headers} are missing. "
                "If anonymous user sessions are supported then the header "
                f"{AnonymousUser.auth_header} can also be used.",
            )

    return decorated
