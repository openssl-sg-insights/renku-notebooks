import base64
import json
import re
from abc import ABC, abstractmethod
from functools import lru_cache
from typing import Optional

import escapism
import jwt
from flask import current_app
from gitlab import Gitlab
from gitlab.exceptions import GitlabListError
from gitlab.v4.objects.projects import Project
from kubernetes import client

from ...config import config
from .storage import AutosaveBranch
from ...errors.programming import ConfigurationError


class User(ABC):
    @abstractmethod
    def get_autosaves(self, *args, **kwargs):
        pass

    def setup_k8s(self):
        self._k8s_client, self._k8s_namespace = config.k8s.client, config.k8s.namespace
        self._k8s_api_instance = client.CustomObjectsApi(client.ApiClient())

    @property
    def jss(self):
        """Get a list of k8s jupyterserver objects for all the active servers of a user."""
        label_selector = (
            config.session_get_endpoint_annotations.renku_annotation_prefix
            + f"safe-username={self.safe_username}"
        )
        jss = self._k8s_api_instance.list_namespaced_custom_object(
            group=config.amalthea.group,
            version=config.amalthea.version,
            namespace=self._k8s_namespace,
            plural=config.amalthea.plural,
            label_selector=label_selector,
        )
        return jss["items"]

    @lru_cache(maxsize=8)
    def get_renku_project(self, namespace_project) -> Optional[Project]:
        """Retrieve the GitLab project."""
        try:
            return self.gitlab_client.projects.get("{0}".format(namespace_project))
        except Exception as e:
            current_app.logger.warning(
                f"Cannot get project: {namespace_project} for user: {self.username}, error: {e}"
            )


class AnonymousUser(User):
    auth_header = "Renku-Auth-Anon-Id"

    def __init__(self, headers):
        if not config.anonymous_sessions_enabled:
            raise ConfigurationError(message="Anonymous sessions are not enabled.")
        self.authenticated = (
            self.auth_header in headers.keys()
            and headers[self.auth_header] != ""
            # The anonymous id must start with an alphanumeric character
            and re.match(r"^[a-zA-Z0-9]", headers[self.auth_header]) is not None
        )
        if not self.authenticated:
            return
        self.git_url = config.git.url
        self.gitlab_client = Gitlab(self.git_url, api_version=4, per_page=50)
        self.username = headers[self.auth_header]
        self.safe_username = escapism.escape(self.username, escape_char="-").lower()
        self.full_name = None
        self.email = None
        self.oidc_issuer = None
        self.git_token = None
        self.id = headers[self.auth_header]
        self.setup_k8s()

    def get_autosaves(self, *args, **kwargs):
        return []

    def __str__(self):
        return f"<Anonymous user id:{self.username[:5]}****>"


class RegisteredUser(User):
    auth_headers = [
        "Renku-Auth-Access-Token",
        "Renku-Auth-Id-Token",
        "Renku-Auth-Git-Credentials",
    ]

    def __init__(self, headers):
        self.authenticated = all(
            [header in headers.keys() for header in self.auth_headers]
        )
        if not self.authenticated:
            return
        parsed_id_token = self.parse_jwt_from_headers(headers)
        self.email = parsed_id_token["email"]
        self.full_name = parsed_id_token["name"]
        self.username = parsed_id_token["preferred_username"]
        self.safe_username = escapism.escape(self.username, escape_char="-").lower()
        self.oidc_issuer = parsed_id_token["iss"]
        self.id = parsed_id_token["sub"]

        (
            self.git_url,
            self.git_auth_header,
            self.git_token,
        ) = self.git_creds_from_headers(headers)
        self.gitlab_client = Gitlab(
            self.git_url,
            api_version=4,
            oauth_token=self.git_token,
            per_page=50,
        )
        self.setup_k8s()

    @property
    def gitlab_user(self):
        if not getattr(self.gitlab_client, "user", None):
            self.gitlab_client.auth()
        return self.gitlab_client.user

    @staticmethod
    def parse_jwt_from_headers(headers):
        # No need to verify the signature because this is already done by the gateway
        return jwt.decode(
            headers["Renku-Auth-Id-Token"], options={"verify_signature": False}
        )

    @staticmethod
    def git_creds_from_headers(headers):
        parsed_dict = json.loads(
            base64.decodebytes(headers["Renku-Auth-Git-Credentials"].encode())
        )
        git_url, git_credentials = next(iter(parsed_dict.items()))
        token_match = re.match(
            r"^[^\s]+\ ([^\s]+)$", git_credentials["AuthorizationHeader"]
        )
        git_token = token_match.group(1) if token_match is not None else None
        return git_url, git_credentials["AuthorizationHeader"], git_token

    def get_autosaves(self, namespace_project=None):
        """Get a list of autosaves for all projects for the user"""
        gl_project = (
            self.get_renku_project(namespace_project)
            if namespace_project is not None
            else None
        )
        projects = []
        autosaves = []
        # add any autosave branches, regardless of wheter pvcs are supported or not
        if namespace_project is None:  # get autosave branches from all projects
            projects = self.gitlab_client.projects.list(iterator=True)
        elif gl_project:
            projects.append(gl_project)
        for project in projects:
            try:
                branches = project.branches.list(
                    search="^renku/autosave/", iterator=True
                )
            except GitlabListError:
                branches = []
            for branch in branches:
                autosave = AutosaveBranch.from_name(
                    self, namespace_project, branch.name
                )
                if autosave is not None:
                    autosaves.append(autosave)
                else:
                    current_app.logger.warning(
                        f"Autosave branch {branch.name} for "
                        f"project {namespace_project} cannot be instantiated."
                    )
        return autosaves

    def __str__(self):
        return (
            f"<Registered user username:{self.username} name: "
            f"{self.full_name} email: {self.email}>"
        )
