import sys

from git_services.init import errors
from git_services.init.cloner import GitCloner
from git_services.init.config import config_from_env
from git_services.cli.sentry import setup_sentry

# NOTE: register exception handler
sys.excepthook = errors.handle_exception

if __name__ == "__main__":
    config = config_from_env()
    setup_sentry(config.sentry)
    git_cloner = GitCloner(
        config.git_url,
        config.repository_url,
        config.user,
        config.lfs_auto_fetch,
        config.mount_path,
    )
    git_cloner.run(
        config.git_autosave, config.branch, config.commit_sha, config.s3_mount
    )
